# 渲染与运行速度优化验证

## 实测结果

在本机 Windows 上使用同一套 `benchmark_render_pipeline.py`，窗口 1400×900，
太阳系九体（基准移除 Moon），开启性能覆盖层、关闭逐帧日志和 GPU 强制同步。
原版本使用独立临时副本，优化版本使用当前工作区；每档预热 2 秒、计时 4 秒，
调用计数另测 2 秒，一轮采样。FPS 来自实际 `paintGL` 次数 / 测量时间。

| 倍率 | 原版本实际 FPS | 优化后实际 FPS | 原版本 paintGL / 次 | 优化后 paintGL / 次 |
| --- | ---: | ---: | ---: | ---: |
| 1× | 62.40 | 61.53 | 4.465 ms | 2.950 ms |
| 5× | 45.48 | 62.58 | 4.841 ms | 2.790 ms |
| 10× | 29.78 | 62.00 | 4.881 ms | 2.751 ms |

16 ms 渲染定时器对应约 62.5 Hz；1× 已达到刷新目标，改善主要体现在耗时和高倍率。
这些是当前机器和场景的测量值，不能代表任意天体数量或硬件。
原统计帧按 30 Hz 物理 tick 划分，新统计帧按实际绘制划分，因此旧、新 CSV 的
`period`、`physics_ms` 等“每统计帧”列不能直接比较；表中只比较同口径的
实际绘制频率与单次 `paintGL` 耗时。

原始数据：[优化前](logs/render_optimization_before.csv)、
[优化后](logs/render_optimization_after.csv)、
[同口径摘要](logs/render_optimization_comparison.csv)。

## 原因与修改

- FPS 显示原本统计物理定时器，无法反映真实渲染速度。现在由实际 `paintGL` 驱动统计，暂停物理后仍统计渲染。
- 天体逐顶点提交跨 Python/OpenGL 边界，每九体有约 630 次顶点/颜色调用。
  [BodyRenderer](ui/body_renderer.py) 改为批量三角形提交，保留原来的圆形几何、透明度和选中光环绘制顺序。
- 两个渲染器共同使用 [ColoredVertexBuffer](ui/gl_buffers.py)，复用 VBO 创建、释放、上传与数组绘制。
  [坐标转换](ui/render_coordinates.py) 调用现有 Camera，并被两个顶点构建器共用。
- 轨迹在物理更新之间复用已上传缓冲；相机、视口、颜色、采样上限、天体或轨迹变化时重新生成。
  默认无 revision 的独立渲染器调用仍重新构建，以支持任意可变输入。
  超长历史先采样再转数组；原默认历史上限 1000，超长历史不是默认场景主要瓶颈。
- 主循环使用精确定时器；日志默认关闭，`PERF_LOG=1` 可开启，文件改为每秒刷新一次、退出时关闭。
- 场景加载原本绕过引擎的优化积分器构造分支，导致 RK4 实现类型发生变化，场景往返测试失败。
  引擎与场景加载现在共用 IntegratorFactory。
- 原有两份 RK4 算法合并到 [RK4Integrator](physics/integrator.py)，`RK4IntegratorOpt` 直接继承复用。
  每阶段的中间状态改为 NumPy 批量运算，移除逐天体小数组计算和冗余拷贝。
  四阶段 RK4、固定 dt、float64、归一化单位与 G=1 均保留。
- `GravitySolverOpt` 继承并复用现有 CPU 引力、计时与统计函数，保留 GPU 加速度分支。
- GL 资源在所属上下文销毁前释放；GPU 查询按需创建，修复 NumPy 查询 ID 数组清理时的布尔判断错误。
- 修正阶段计时累计值被误当作单帧值，以及超限轨迹测试/基准被 `maxlen=1000` 意外截断的问题。

## 验证

- 141 项物理、碰撞、渲染、缓存、相机与性能统计针对性测试通过；另有 7 项场景往返/扫描测试通过。
- 与原版本太阳系连续 1000 步对照：每 100 步采样的轨迹、最终位置/速度、总能量与动量完全一致。
- 新增双星圆轨道四阶收敛、恒加速度解析解、四次引力求值、float64 和两种求解器轨迹一致性检查。
- 使用真实 GL framebuffer 检查相机平移前后天体颜色；截图确认轨迹、圆形和选中光环。
  [验证截图](logs/render_optimization_smoke.png)。
- Python 编译检查与 `git diff --check` 通过。

复测性能：

```powershell
python benchmark_render_pipeline.py --speeds 1,5,10 --rounds 1 --warmup 2 --duration 4 --count-duration 2
```

运行针对性回归：

```powershell
python -m unittest test_rk4_batch test_physics_units test_collision test_render_profiling test_body_renderer test_trail_builder test_trail_draw_batch test_camera_scale -q
python -m unittest test_scene_manager -q
```

GPU/CuPy 分支没有在此次 CPU 基准中做性能验证。
