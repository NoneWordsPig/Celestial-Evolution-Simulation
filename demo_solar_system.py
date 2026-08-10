"""
太阳系全系演示

展示太阳与八大行星的真实 N 体引力模拟。

所有现实单位经独立 UnitSystem 归一化为 simulation units：
    1 DU = 1 AU
    1 MU = 1 M_sun
    1 TU = sqrt(AU^3 / (G_SI * M_sun)) ≈ 58.1 天
    1 VU = 1 AU/TU ≈ 29.78 km/s（接近地球公转速度）

初始条件：
- 太阳位于原点，初始静止
- 每颗行星位于近日点，速度取近日点速度
      r = a * (1 - e)
      v = sqrt(G * M * (1 + e) / r)    （G = 1，M = 1 + m）
- 质量、轨道半径、偏心率均使用真实观测数据
- 所有天体半径（含渲染半径）均为真实半径的归一化映射值（1 DU = 1 AU），
  不进行任何观感缩放

运行：
    python demo_solar_system.py

操作说明（与 Figure-8 演示一致）：
- 鼠标滚轮：缩放；鼠标中键拖拽：平移
- 工具栏：播放控制、适应全部、重置摄像机
- 跟随质心：默认开启，视图中心保持在系统质心
"""

import sys

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.styles import apply_global_style
from physics import Body
from physics.unit_system import UnitSystem


# ============================================================
# 行星真实数据
# (名称, 质量 kg, 半径 km, 半长轴 AU, 偏心率, 初始角度°, 颜色)
# ============================================================
PLANETS = [
    ("Mercury", 3.3011e23, 2439.7, 0.387098, 0.205630, 0.0, (0.65, 0.65, 0.68)),
    ("Venus", 4.8675e24, 6051.8, 0.723332, 0.006772, 35.0, (0.95, 0.80, 0.55)),
    ("Earth", 5.9724e24, 6371.0, 1.000000, 0.016710, 75.0, (0.30, 0.60, 1.00)),
    ("Mars", 6.4171e23, 3389.5, 1.523679, 0.093315, 120.0, (0.90, 0.45, 0.25)),
    ("Jupiter", 1.8982e27, 69911.0, 5.202603, 0.048386, 165.0, (0.85, 0.68, 0.48)),
    ("Saturn", 5.6834e26, 58232.0, 9.554910, 0.053862, 215.0, (0.92, 0.82, 0.55)),
    ("Uranus", 8.6813e25, 25362.0, 19.218446, 0.047258, 260.0, (0.55, 0.85, 0.90)),
    ("Neptune", 1.02409e26, 24622.0, 30.110387, 0.008590, 300.0, (0.30, 0.45, 0.95)),
]

# 太阳数据
SUN_MASS_KG = 1.98892e30
SUN_RADIUS_KM = 696340.0


def setup_solar_system(window, us: UnitSystem):
    """
    设置太阳系全系系统

    所有现实单位经 UnitSystem 转换为 normalized simulation units，
    Physics Engine 只接收 G=1 的归一化数值。
    """
    window.engine.clear()

    # 太阳（1 M_sun -> 1 MU）
    sun_radius = us.to_simulation(SUN_RADIUS_KM * 1000.0, "m")
    sun = Body(
        name="Sun",
        mass=us.to_simulation(SUN_MASS_KG, "kg"),
        physical_radius=sun_radius,
        render_radius=sun_radius,
        position=(0.0, 0.0),
        velocity=(0.0, 0.0),
        color=(1.0, 0.85, 0.25),
    )
    window.engine.add_body(sun)

    # 八大行星：近日点出发，近日点速度
    for name, mass_kg, radius_km, a_au, e, angle_deg, color in PLANETS:
        mass_mu = us.to_simulation(mass_kg, "kg")
        r_peri = us.to_simulation(a_au * (1.0 - e), "AU")
        # v_peri = sqrt(G * M * (1 + e) / r)，G = 1，M = 1 + m
        v_peri = np.sqrt((1.0 + mass_mu) * (1.0 + e) / r_peri)

        theta = np.radians(angle_deg)
        pos = (r_peri * np.cos(theta), r_peri * np.sin(theta))
        vel = (v_peri * -np.sin(theta), v_peri * np.cos(theta))

        # 真实半径映射值：render_radius = physical_radius（1 DU = 1 AU）
        real_radius = us.to_simulation(radius_km * 1000.0, "m")

        planet = Body(
            name=name,
            mass=mass_mu,
            physical_radius=real_radius,
            render_radius=real_radius,
            position=pos,
            velocity=vel,
            color=color,
        )
        window.engine.add_body(planet)

    # 视图：跟随质心，适应所有天体
    window.follow_com = True
    window.follow_com_btn.setChecked(True)
    window.follow_com_action.setChecked(True)
    window.camera.center_x = 0.0
    window.camera.center_y = 0.0
    window._on_fit_all_bodies()

    # 物理参数：RK4（引擎默认），小步长保证精度
    window.engine.dt = 0.001
    window.engine.time_scale = 20.0  # 20x 加速，内行星运动清晰可见

    # 延长轨迹显示长度（引擎最多记录 1000 点）
    window.sim_widget._max_trail_length = 1000

    window.body_list.refresh()

    print("太阳系全系系统已加载")
    print(f"归一化：1 DU = 1 AU，1 MU = 1 M_sun，1 TU ≈ {us.T0 / 86400.0:.1f} 天")
    print(f"标准速度：1 VU ≈ {us.V0 / 1000.0:.2f} km/s")
    print("行星初始条件（simulation units）：")
    for body in window.engine.bodies:
        print(
            f"  {body.name:<8} mass={body.mass:.6g} MU, "
            f"pos=({body.position[0]:.4f}, {body.position[1]:.4f}), "
            f"vel=({body.velocity[0]:.4f}, {body.velocity[1]:.4f})"
        )


def show_info(us: UnitSystem):
    """显示信息对话框"""
    msg = QMessageBox()
    msg.setWindowTitle("太阳系全系演示")
    msg.setText("<h2>太阳系全系演示</h2>")

    rows = "".join(
        f"<tr><td>{name}</td><td>{a:.3f} AU</td>"
        f"<td>{us.to_simulation(mass_kg, 'kg') * 1e6:.2f}×10⁻⁶ MU</td>"
        f"<td>{e:.4f}</td></tr>"
        for name, mass_kg, _r, a, e, _ang, _c in PLANETS
    )

    msg.setInformativeText(
        "<p>太阳 + 八大行星的真实 N 体引力模拟。</p>"
        "<p><b>归一化单位：</b></p>"
        "<ul>"
        f"<li>1 DU = 1 AU</li>"
        f"<li>1 MU = 1 M_sun</li>"
        f"<li>1 TU ≈ {us.T0 / 86400.0:.1f} 天（地球年 ≈ 2π TU）</li>"
        f"<li>1 VU ≈ {us.V0 / 1000.0:.2f} km/s（地球公转速度 ≈ 1 VU）</li>"
        "</ul>"
        "<p><b>行星数据：</b></p>"
        "<table border='1' cellspacing='0' cellpadding='4'>"
        "<tr><th>行星</th><th>半长轴</th><th>质量</th><th>偏心率</th></tr>"
        f"{rows}"
        "</table>"
        "<p><b>操作：</b>滚轮缩放 · 中键拖拽平移 · 工具栏播放控制 · "
        "跟随质心默认开启 · 默认 20x 时间加速（可在控制面板调整）</p>"
    )
    msg.setIcon(QMessageBox.Icon.Information)
    msg.exec()


def main():
    """主函数"""
    app = QApplication(sys.argv)

    app.setStyle('Fusion')
    apply_global_style(app)

    window = MainWindow()
    window.setWindowTitle("太阳系全系演示")
    window.resize(1400, 900)

    # 独立 UnitSystem：现实单位 -> normalized simulation units
    us = UnitSystem()
    setup_solar_system(window, us)
    show_info(us)

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
