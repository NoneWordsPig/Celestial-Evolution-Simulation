# Architecture

PhysicsEngine 不得依赖 UI。

UnitSystem 不得依赖 PhysicsEngine。

SceneManager 不负责物理计算。

Renderer 不得修改 Simulation State。

Camera 只负责显示坐标转换。

UI 不直接执行物理计算。


# Numerical Rules

Physics Engine 内部统一使用 float64/double。

内部使用 normalized simulation units。

Physics Engine 中：

G = 1


Scientific Units：

kg
m
km
AU
M_sun
s
day
year

全部由 UnitSystem 转换。

Physics Engine 不直接处理 SI G。


# Modification Rules

修改代码前：

1. 确定受影响模块。
2. 只读取完成任务所需的文件。
3. 不要重写无关模块。
4. 不要修改未涉及的 Physics / UI / Renderer。
5. 完成后运行针对性测试。


# Testing Rules

优先运行 targeted tests。

不要为了一个小 UI 修改运行整个项目的所有测试。

如果修改 Physics：

必须进行数值验证。


# Important

当前 Physics Engine 使用 RK4。

不要自行替换积分器。

后续如果需要增加四阶辛几何积分，应作为独立 Integrator 实现，而不是直接删除 RK4。
