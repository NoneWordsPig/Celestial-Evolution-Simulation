import os, sys
os.environ['PERF_LOG'] = '0'
os.environ['GL_GPU_PROFILING'] = 'none'
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from ui.profiler import ProfilingApplication
from benchmark_render_pipeline import _spin, _install_frame_counters, _restore_frame_counters

app = ProfilingApplication(sys.argv)
app.setStyle('Fusion')
frame_counts, originals = _install_frame_counters()
window = MainWindow()
window.resize(1400, 900)
window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
window.show()
_spin(window, app, 3.0)
print('paintgl:', frame_counts['paintgl'], 'update_calls:', frame_counts['update_calls'])
print('bodies:', len(window.engine.bodies))
print('trail mode:', window.sim_widget.old_trail_renderer)
window.close()
_restore_frame_counters(originals)
app.quit()
