# Celestial Evolution Simulation · 天体引力模拟器

> An interactive N-body gravitational simulation desktop app built with **PyQt6 + OpenGL**, with a normalized-simulation-units physics engine (`G = 1`), collision merging, trajectories, center-of-mass reference frame, scene management, and built-in runtime profiling.

**English** | [简体中文](README.zh-CN.md)

![Python](https://img.shields.io/badge/Python-3.13-3776AB)
![GUI](https://img.shields.io/badge/GUI-PyQt6-41B883)
![Integrator](https://img.shields.io/badge/Integrator-RK4%20%2F%20Velocity%20Verlet-6366F1)

---

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [User Guide](#user-guide)
  - [Window Layout](#window-layout)
  - [Menus](#menus)
  - [Toolbar](#toolbar)
  - [Mouse and Keyboard](#mouse-and-keyboard)
  - [Add Body Dialog](#add-body-dialog)
  - [Status Bar](#status-bar)
  - [Performance Overlay](#performance-overlay)
- [Modes and Units](#modes-and-units)
- [Scenes](#scenes)
- [Physics Engine](#physics-engine)
- [Performance Profiling](#performance-profiling)
- [Configuration](#configuration)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [FAQ](#faq)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## Introduction

This project is a 2D N-body gravitational simulation. It runs a real-time
multi-body gravity solver, lets you add, delete, select and inspect bodies,
observes collision merging, and renders bodies with trails, a dynamic scale
bar, and a dark "space" theme. The application ships with several built-in
scenes, including the classic Figure-8 three-body orbit and a real-data solar
system model.

The physics core is deliberately decoupled from the UI: it works exclusively in
normalized simulation units (mass `MU`, distance `DU`, time `TU`, with the
gravitational constant `G = 1`), while a unit system converts to and from real
world units (`kg`, `m`, `km`, `AU`, `M_sun`, `s`, `day`, `year`) for display
and input in Scientific mode.

## Features

- Real-time N-body gravity simulation with a NumPy-vectorized O(N²) solver and
  gravitational softening.
- Two integrators: **RK4** (default) and **Velocity Verlet** (symplectic),
  selectable through scene files.
- Collision detection and physically consistent merging (mass, momentum and
  volume conservation).
- Per-body trajectory history with gradient rendering.
- Simulation / Scientific modes: compact simulation units, or real-world units
  with scientific notation, energy and momentum.
- Center-of-mass reference frame with smooth camera transitions and momentum
  correction.
- Scene system: load, save, import and export JSON scenes; built-in scene
  gallery (periodic three-body orbits + solar system).
- Camera with zoom-at-cursor, panning, fit-all and reset.
- Built-in per-frame profiler (physics / UI / render breakdown) and optional
  performance logging.
- Decoupled fixed-timestep physics (30 Hz) and rendering (60 Hz) loops.
- Dark modern UI, toast notifications, scientific-notation number input.

## Screenshots

<!--
Place screenshots in `docs/screenshots/` and reference them here, e.g.:
![Main window](docs/screenshots/main.png)
-->

Screenshots are not bundled yet. You can capture the running application and
drop it into `docs/screenshots/` to include it here.

## Installation

Requirements:

- Python **3.11+** (developed and tested on **3.13**)
- A display environment with OpenGL support (Windows desktop recommended)

Install dependencies:

```bash
pip install -r requirements.txt
```

The requirements are:

```text
numpy>=1.26
PyQt6>=6.6
PyOpenGL>=3.1
```

## Quick Start

Run from the repository root:

```bash
python main.py
```

The application starts with the Figure-8 three-body system loaded automatically.
You can load other scenes from the **Scene** menu.

## User Guide

### Window Layout

```
+--------------------------------------------------------------------------+
|  Menu Bar                                                                |
+--------------------------------------------------------------------------+
|  Toolbar (play / step / add / camera / reference frame / speed / mode)   |
+--------+----------------------------------------------+------------------+
| Body   |                                              | Inspector        |
| List   |            Simulation View (OpenGL)          | (name, mass,    |
| (left) |            bodies + trails + scale bar       | radius, motion, |
|        |            + perf overlay                    | kinetic energy, |
|        |                                              | momentum)       |
+--------+----------------------------------------------+------------------+
|  Status Bar: FPS · body count · simulation time · center of mass        |
+--------------------------------------------------------------------------+
```

- **Left panel — Body List**: all bodies, selectable; delete the selected body
  with the button or the `Delete` key.
- **Center — Simulation View**: the OpenGL rendering area.
- **Right panel — Inspector**: detailed information of the selected body.
- **Status bar**: FPS, body count, simulation time, and center of mass.

### Menus

| Menu | Action | Shortcut | Description |
| --- | --- | --- | --- |
| 文件 (File) | 添加天体 (Add Body) | `Ctrl+A` | Open the Add Body dialog. |
| 文件 (File) | 退出 (Quit) | `Ctrl+Q` | Close the application. |
| 视图 (View) | 重置摄像机 (Reset Camera) | — | Reset camera to its default center and zoom. |
| 视图 (View) | 适应所有天体 (Fit All Bodies) | — | Frame all bodies with 10% padding. |
| 视图 (View) | 显示/隐藏天体列表 (Toggle Body List) | — | Show/hide the left panel. |
| 视图 (View) | 显示/隐藏检查器 (Toggle Inspector) | — | Show/hide the right panel. |
| 视图 (View) | 显示性能分析 (Performance Overlay) | — | Toggle the profiler overlay in the simulation view (on by default). |
| 参考系 (Frame) | 跟随质心 (Follow Center of Mass) | — | Smoothly keep the center of mass in the middle of the view. |
| 参考系 (Frame) | 重置参考系 (Reset Reference Frame) | — | Animate the camera to the center of mass (0.8 s) and smoothly zero the total momentum (1.0 s). |
| 模式 (Mode) | 模拟模式 (Simulation Mode) | — | Compact display in MU / DU / TU. |
| 模式 (Mode) | 科学模式 (Scientific Mode) | — | Real-world units with scientific notation. |
| 场景 (Scene) | 加载场景 (Load Scene) | — | Pick a JSON scene file and apply it. |
| 场景 (Scene) | 保存场景 (Save Scene) | — | Save the current state to `scenes/<name>.json`. |
| 场景 (Scene) | 导入场景 (Import Scene) | — | Import a JSON scene from any path. |
| 场景 (Scene) | 导出场景 (Export Scene) | — | Export the current state to a chosen JSON file. |
| 场景 (Scene) | *dynamic list* | — | All valid JSON files in `scenes/` are listed at startup; click to load. |
| 帮助 (Help) | 关于 (About) | — | Show version and feature summary. |

### Toolbar

| Button | Action | Description |
| --- | --- | --- |
| ▶ / ⏸ | Play / Pause | Toggle simulation advance. |
| ⏭ | Step | Execute one simulation step. |
| ➕ 添加 | Add Body | Open the Add Body dialog. |
| 🎯 | Reset Camera | Same as 视图 → 重置摄像机. |
| 🔍 | Fit All | Same as 视图 → 适应所有天体. |
| ⚖️ | Reset Reference Frame | Same as 参考系 → 重置参考系. |
| 📍 | Follow Center of Mass | Toggle, same as 参考系 → 跟随质心. |
| 速度 slider | Evolution speed | Logarithmic slider, **0.1× – 20×** (`1×` = legacy 5× speed). |
| preset combo | Speed presets | Quick select 0.1 / 0.5 / 1 / 2 / 5 / 10 / 20 ×. |
| 🔬 / 🎮 | Toggle Mode | Switch between Simulation and Scientific modes. |

The speed slider uses a logarithmic scale (position 100 = 1×). Changing speed
never changes the numerical timestep: the engine always advances in fixed
`dt` sub-steps and only varies how many sub-steps run per second. If the speed
multiplier hits the per-frame sub-step cap (200), a toast
“倍率已达上限 / speed limit reached” is shown once — this is informational
only and changes nothing.

### Mouse and Keyboard

| Input | Action |
| --- | --- |
| Left click on a body | Select the body (also selects it in the list and inspector). |
| Left click on empty space | Deselect. |
| Middle-drag | Pan the camera. |
| Mouse wheel | Zoom in / out centered on the cursor (factor 1.1 / 0.9, clamped to 0.001–2000 px/DU). |
| `Delete` (body list focused) | Delete the selected body (with confirmation). |
| `Ctrl+A` | Add body. |
| `Ctrl+Q` | Quit. |

### Add Body Dialog

Opened via **文件 → 添加天体**, toolbar **➕ 添加**, or `Ctrl+A`.

- **名称 (Name)**: body name.
- **质量 (Mass)**: in `MU` (Simulation mode) or `kg` / `M_sun` with a unit
  combo (Scientific mode).
- **半径 (Radius)**: in `DU` or `m` / `km` / `AU` (default `km` in Scientific
  mode). This is the physical radius used for collision detection.
- **位置 X / Y (Position)**: in `DU` or `m` / `km` / `AU` (default `AU`).
- **速度 (Velocity)** — two input modes, switchable at any time:
  - **X/Y**: Cartesian velocity components `vx`, `vy`.
  - **V/θ**: polar velocity — speed and direction angle in degrees.
  - Units: `DU/TU` or `m/s`, `km/s`, `AU/T0` (default `km/s` in Scientific
    mode). Switching between X/Y and V/θ converts the current values.
- **颜色 (Color)**: pick a display color (default blue).

All number fields accept scientific notation, e.g. `1e-6`, `3.003e-6`,
`1.989e30`; the display is normalized to about 15 significant digits on
finishing the edit. In Scientific mode, values are converted to normalized
simulation units before entering the physics engine.

### Status Bar

The status bar shows, from left to right:

- **FPS**: measured frame rate.
- **天体 (Bodies)**: current body count.
- **时间 (Time)**: simulation time — `TU` in Simulation mode, days/years in
  Scientific mode when a real-unit mapping exists.
- **质心 (Center of Mass)**: current center of mass `(x, y)`.

### Performance Overlay

The top-left overlay of the simulation view shows a live per-frame breakdown
(toggle with **视图 → 显示性能分析**, on by default, refreshed about 10 times
per second):

- Metrics: **FPS**, average / p95 / peak frame period, plus a sparkline of
  recent frame periods (average drawn as a dashed line).
- A table of the 9 stages (see [Performance Profiling](#performance-profiling))
  with time in ms, share of the frame period, and a ratio bar.
- A second metrics row: engine time, body count, sub-steps per frame, and
  collision merges.

## Modes and Units

The physics engine itself is mode-agnostic — **Mode only affects display and
input**. Switching modes never changes the simulation state.

| Mode | Display | Best for |
| --- | --- | --- |
| 模拟模式 (Simulation) | Compact simulation units `MU`, `DU`, `TU`, `DU/TU` | Exploring orbits, tweaking parameters, visual demos. |
| 科学模式 (Scientific) | Real units with scientific notation (e.g. `1.989 × 10³⁰ kg`), plus kinetic energy in J and momentum in kg·m/s | Solar-system-scale work, physics analysis. |

### Simulation units

The engine uses normalized units in which `G = 1`:

| Quantity | Unit | Notes |
| --- | --- | --- |
| Mass | `MU` | `1 MU = 1` |
| Distance | `DU` | `1 DU = 1` |
| Time | `TU` | Derived: `TU = sqrt(DU³ / (G·MU)) = 1` |
| Velocity | `DU/TU` | Derived: `VU = DU / TU = sqrt(G·MU/DU) = 1` |

### Scientific normalization

`physics/unit_system.py` defines a scientific normalization with:

- `L0 = 1 AU ≈ 1.495978707 × 10¹¹ m`
- `M0 = 1 M_sun ≈ 1.98892 × 10³⁰ kg`
- `T0 = sqrt(L0³ / (G_SI·M0))`, so that `G_sim = 1`

Useful identities (verified by tests): **1 year ≈ 2π TU**, Earth's orbital
velocity ≈ **1 VU ≈ 29.78 km/s**.

### Real-world mapping

`UnitConverter.solar_system()` maps the solar-system scale:

- `1 DU = 1 AU`
- `1 MU = 1 M_sun`
- Derived: `1 TU ≈ 0.112 year ≈ 41 days`, `1 VU ≈ 29.8 km/s`

Supported real units: `kg`, `m`, `km`, `AU`, `M_sun`, `s`, `day`, `year`,
`m/s`, `km/s`, `AU/T0`, `m/s²`, `km/s²` (case- and spacing-insensitive aliases
accepted, e.g. `msun`, `yr`). If no mapping exists, Scientific mode falls back
to simulation units and shows a hint “当前未设置现实世界单位映射”.

## Scenes

Scenes are plain JSON files. All valid JSON files in the `scenes/` directory
are auto-detected and listed in the **Scene** menu at startup.

### Built-in scenes

| File | Scene | Description |
| --- | --- | --- |
| `solar_system.json` | 太阳系全系 (Full Solar System) | Sun, 8 planets and the Moon with real masses/radii/orbital elements, normalized so `1 DU = 1 AU`, `1 MU = 1 M_sun`. |
| `figure8.json` | Figure-8 三体系统 | Classic stable Figure-8 periodic orbit (Chenciner & Montgomery, 2000), equal masses, period ≈ 6.326. |
| `lagrange.json` | 拉格朗日等边三角解 | Lagrange equilateral-triangle solution (1772), equal masses in uniform rotation. |
| `butterfly.json` | 蝴蝶轨道 Butterfly I | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |
| `bumblebee.json` | 大黄蜂轨道 Bumblebee | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |
| `dragonfly.json` | 蜻蜓轨道 Dragonfly | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |
| `goggles.json` | 护目镜轨道 Goggles | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |
| `moth.json` | 飞蛾轨道 Moth I | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |
| `yinyang.json` | 阴阳轨道 Yin-Yang I | Periodic three-body orbit (Šuvakov & Dmitrašinović, 2013). |

### Scene JSON format

```json
{
  "format_version": 1,
  "name": "Figure-8 三体系统",
  "description": "Classic Figure-8 stable periodic orbit",
  "units": { "length": "DU", "mass": "MU", "time": "TU", "velocity": "DU/TU" },
  "G": 1.0,
  "integrator": "rk4",
  "timestep": 0.0005,
  "time_scale": 1.0,
  "simulation_time": 0.0,
  "camera": { "center_x": 0.0, "center_y": 0.0, "zoom": 150.0,
              "viewport_width": 1400, "viewport_height": 900 },
  "bodies": [
    { "name": "Body 1", "mass": 1.0, "radius": 0.0001,
      "render_radius": 0.0001,
      "position": [-0.97000436, 0.24308753],
      "velocity": [0.4662036850, 0.4323657300],
      "color": [1.0, 0.3, 0.3] }
  ]
}
```

| Field | Type | Description |
| --- | --- | --- |
| `format_version` | int | Scene format version (`1`). |
| `name` / `description` | string | Display name and description. |
| `units` | object | Declared unit metadata (informational only). |
| `G` | number | Gravitational constant (always `1.0` in normalized units). |
| `integrator` | string | `rk4` or `verlet`; the engine rebuilds the integrator on load. |
| `timestep` | number | Fixed physics timestep in `TU`. |
| `time_scale` | number | Speed multiplier restored into the UI. |
| `simulation_time` | number | Simulated elapsed time in `TU`. |
| `camera` | object | Camera center, zoom and viewport size. |
| `bodies[]` | array | Body definitions: `name`, `mass`, `radius` (physical), `render_radius` (optional, defaults to `radius`), `position`, `velocity`, `color` (RGB 0–1). |

## Physics Engine

### Architecture rules

- `PhysicsEngine` never depends on the UI.
- `UnitSystem` never depends on `PhysicsEngine`.
- `SceneManager` only serializes/deserializes scenes — no physics.
- Renderer never modifies simulation state.
- `Camera` only performs coordinate transforms.
- The UI never computes physics itself.

### Numerical rules

- All internal physics uses **float64/double**.
- The engine works exclusively in **normalized simulation units** with
  `G = 1`; it never handles the SI gravitational constant.
- All real-world units (`kg`, `m`, `km`, `AU`, `M_sun`, `s`, `day`, `year`)
  are converted by the unit system.
- The default integrator is **RK4**; a **Velocity Verlet** (symplectic)
  integrator is also available. Do not remove RK4 — future higher-order
  symplectic integrators should be added as separate `Integrator` classes.

### Simulation loop

Each physics sub-step runs:

1. **Integrate** — gravity accelerations (O(N²), NumPy-vectorized, softening
   `ε = 1e-8 DU`), then RK4 or Velocity Verlet position/velocity update.
2. **Collision** — pairs with distance below
   `(physical_radius₁ + physical_radius₂) × 1.0` merge into one body,
   conserving mass, momentum and volume
   (`r_new = (r₁³ + r₂³)^(1/3)`); render radius is merged independently;
   color is mass-weighted.
3. **Trajectory** — append positions to per-body trails and global history
   (bounded `deque`, max 1000 points; rendering samples up to 1000 points).
4. **Advance time** by the fixed `dt`.

Timing model:

- Physics advances at **30 Hz** with a fixed timestep (`dt = 0.001 TU` by
  default) plus an accumulator for smooth motion.
- Rendering runs at **60 Hz**, decoupled from physics.
- Target advance rate = `BASE_SIMULATION_RATE × time_scale`
  (`BASE_SIMULATION_RATE = 5 × 60 × dt`, i.e. `0.3 TU/s` at default `dt`;
  `1×` equals the legacy 5× speed).
- A single frame executes at most `MAX_SUBSTEPS_PER_FRAME = 200` sub-steps;
  excess accumulation is discarded (prefer smoothness over catching up).

### Read-only query API

The engine exposes read-only state queries for the UI / formatters
(`get_body_state`, `get_all_body_states`, `body_acceleration`,
`body_net_force`, `body_distances`, `body_kinetic_energy`, `snapshot`, …)
plus aggregate quantities (`center_of_mass`, `total_momentum`,
`kinetic_energy`, `potential_energy`, `total_energy`, `total_mass`).

## Performance Profiling

`ui/profiler.py` instruments the running application without changing any
physics algorithm (runtime method wrapping). Statistics use a rolling window
of 60 frames.

| # | Stage | What it measures |
| --- | --- | --- |
| 1 | Force calculation | `GravitySolver.compute_accelerations` (RK4 k1–k4). |
| 2 | Integrator (RK4) update | Integrator bookkeeping excluding force calls. |
| 3 | Collision detection | Detection + merging. |
| 4 | Trail/history update | Trajectory recording. |
| 5 | Body state update | Engine residual (advance minus integrator/collision/trail). |
| 6 | Momentum calculation | Center-of-mass / total momentum queries. |
| 7 | Energy calculation | Kinetic / potential energy queries. |
| 8 | UI synchronization | Status bar, inspector and reference-frame timers. |
| 9 | Unaccounted time | Frame period minus stages 1–8 and render, split into: `a` Qt event processing, `b` sleep/frame limiter, `c` OS scheduling, `d` GPU synchronization (`glFinish`), `e` unknown/untracked. |
| — | Render | `paintGL` total (trails, bodies, overlay, GPU sync). |

## Configuration

| Environment variable | Default | Description |
| --- | --- | --- |
| `PERF_LOG` | `1` | Set to `0` to disable the per-frame performance log. |
| `PERF_LOG_PATH` | `<project>/logs/performance.log` | Where the per-frame log is written. |

The performance log writes one line per frame; every second it aggregates
mean / peak / 1-second-window statistics.

## Testing

Run the whole suite from the repository root:

```bash
python -m unittest discover -v
```

Run a single module:

```bash
python -m unittest test_physics_units -v
```

The suite currently contains **197 tests** covering units/conversion,
integrators, collisions, camera/scale, formatters, reference frames and
scene round-trips. All pass.

## Project Structure

```text
.
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── physics/                     # Physics engine package (no UI dependency)
│   ├── engine.py                #   PhysicsEngine main loop
│   ├── gravity.py               #   O(N²) gravity solver with softening
│   ├── integrator.py            #   RK4 + Velocity Verlet + factory
│   ├── collision.py             #   Collision detection and merging
│   ├── body.py                  #   Body data class
│   ├── constants.py             #   G=1, softening, dt, limits
│   ├── units.py                 #   UnitSystem / UnitConverter
│   ├── unit_system.py           #   Scientific normalization (AU, M_sun, T0)
│   ├── formatter.py             #   Simulation / Scientific formatters
│   ├── mode.py                  #   Mode enum (display layer only)
│   ├── scene_manager.py         #   JSON scene save/load/import/export
│   ├── camera.py                #   World <-> screen transforms
│   ├── scale_bar.py             #   Dynamic scale bar (1-2-5 series)
│   ├── reference_frame.py       #   Center-of-mass reference frame
│   └── transitions.py           #   Camera / momentum smooth transitions
├── ui/                          # PyQt6 desktop interface
│   ├── main_window.py           #   Main window, menus, toolbar, status bar
│   ├── simulation_widget.py     #   OpenGL simulation view + interactions
│   ├── body_list_widget.py      #   Left body list
│   ├── inspector_widget.py      #   Right inspector
│   ├── add_body_dialog.py       #   Add-body dialog (cartesian/polar velocity)
│   ├── scientific_number_input.py # Scientific-notation number input
│   ├── profiler.py              #   FrameProfiler + performance log
│   ├── styles.py                #   Dark theme
│   ├── toast.py                 #   Toast notifications
│   └── control_panel.py         #   Legacy control panel (not used by main window)
├── scenes/                      # JSON scenes (auto-scanned at startup)
├── logs/performance.log         # Per-frame performance log
└── test_*.py                    # unittest suite (197 tests)
```

> Note: `天体模拟器.html` in the working directory is a legacy single-file
> browser prototype; it is git-ignored and not part of the tracked project.

## FAQ

**Q: Why do I see “倍率已达上限 / speed limit reached”?**

The engine caps sub-steps at 200 per rendered frame to avoid freezing. Once
that cap is hit, raising the speed multiplier no longer makes the simulation
faster. Reduce the number of bodies or lower the speed multiplier.

**Q: Why does Scientific mode show “当前未设置现实世界单位映射”?**

No real-unit mapping is configured, so the display falls back to simulation
units. A mapping such as `UnitConverter.solar_system()` enables `AU`, `M_sun`,
`km/s` and days/years.

**Q: The simulation view is black or shows OpenGL errors.**

Make sure PyOpenGL is installed and the GPU driver supports OpenGL. On systems
without hardware OpenGL, try a software-rendering driver.

**Q: Which integrator is used?**

The main window uses RK4. Scenes declare their integrator (`rk4` or `verlet`),
and loading a scene rebuilds the engine integrator accordingly.

**Q: How do I add real solar-system bodies?**

Switch to Scientific mode, then add bodies using `M_sun` / `kg` for mass,
`AU` / `km` / `m` for position, and `km/s` for velocity.

## Contributing

Before modifying code, please follow the project rules in `AGENTS.md`:

- Only read the files required for the task and never rewrite unrelated
  modules (`Physics` / `UI` / `Renderer`).
- Keep the architecture constraints: physics has no UI dependency, unit
  system is standalone, scene management does no physics, renderer never
  mutates state, camera only transforms coordinates, UI never computes
  physics.
- Keep numerical rules: float64, normalized units, `G = 1`, no SI `G` inside
  the engine.
- Keep RK4; add new integrators as separate `Integrator` classes.
- Run targeted tests; any physics change requires numerical verification.

## Acknowledgments

- The Figure-8 orbit: A. Chenciner and R. Montgomery, *A remarkable periodic
  solution of the three-body problem in the case of equal masses*, Annals of
  Mathematics, 2000.
- The butterfly / bumblebee / dragonfly / goggles / moth / yin-yang periodic
  orbits: M. Šuvakov and V. Dmitrašinović, *Three-dimensional family
  of periodic orbits in the equal-mass Newtonian three-body problem*,
  arXiv:1303.0181, 2013.
- The equilateral-triangle solution: J.-L. Lagrange, 1772.

## License

No license file is currently included. Until a license is declared, all rights
are reserved by the author.
