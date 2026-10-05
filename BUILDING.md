# Windows release build

The Windows x64 release is a single GUI executable with Python, NumPy, PyQt6,
PyOpenGL and the built-in JSON scenes bundled. Optional CuPy is excluded.
It uses the system OpenGL graphics driver.

From a Windows x64 Python 3.13 environment, run:

```powershell
python -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm CelestialEvolutionSimulation.spec
```

The output is `dist/CelestialEvolutionSimulation-0.1-windows-x64.exe`.
Version metadata is shared with the app through `app_metadata.py`.
Build output and environments are ignored by Git.

Validate the actual executable, including OpenGL, all bundled scenes and scene
export/import. The optional diagnostic flag writes a JSON report and screenshot,
then exits with status 0 on success:

```powershell
dist\CelestialEvolutionSimulation-0.1-windows-x64.exe --smoke-test build\release-smoke\report.json
Get-Content build\release-smoke\report.json
Get-FileHash dist\CelestialEvolutionSimulation-0.1-windows-x64.exe -Algorithm SHA256
```

Frozen builds seed built-in scenes in
`%LOCALAPPDATA%\Celestial Evolution Simulation\scenes` without replacing
existing files. Saved scenes persist across launches; optional logs use the
neighboring `logs` directory. Source runs continue to use repository paths.
