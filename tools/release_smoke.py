"""Exercise the actual frozen Qt/OpenGL application and write a JSON report."""

import json
from pathlib import Path
import sys
import traceback

from PyQt6.QtCore import QTimer
import OpenGL.GL as gl

from app_metadata import VERSION
from app_paths import data_directory


def schedule_smoke_test(app, window, report_path):
    report_path = Path(report_path).resolve()

    def verify():
        report = {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False))}
        exit_code = 1
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            view = window.sim_widget
            view.pause()
            scenes = window.scene_manager.scan_scenes()
            assert scenes, 'Bundled scene gallery is empty'
            for scene in scenes:
                window._load_scene_from_path(scene['path'])
                assert window.engine.bodies, f"Empty scene: {scene['path']}"
            window._load_scene_from_path(window.scene_manager.scenes_directory / 'solar_system.json')
            view.pause()
            assert view.isValid(), 'OpenGL widget has no valid context'
            frame = view.grabFramebuffer()
            assert not frame.isNull(), 'OpenGL framebuffer is empty'
            frame.save(str(report_path.with_suffix('.png')))
            view.makeCurrent()
            report['opengl_version'] = gl.glGetString(gl.GL_VERSION).decode()
            assert gl.glGetError() == gl.GL_NO_ERROR, 'OpenGL error after rendering'
            view.doneCurrent()
            saved = report_path.parent / 'smoke-scene.json'
            window.scene_manager.export_scene(window.engine, window.camera, saved, name='Release smoke')
            body_count = len(window.engine.bodies)
            window.scene_manager.import_scene(saved, window.engine, window.camera)
            assert len(window.engine.bodies) == body_count
            report.update(ok=True, scene_count=len(scenes), body_count=body_count,
                          data_directory=str(data_directory()),
                          scenes_directory=str(window.scene_manager.scenes_directory))
            exit_code = 0
        except Exception:
            report.update(ok=False, error=traceback.format_exc())
        finally:
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            window.performance_logger.close()
            window.close()
            app.exit(exit_code)

    QTimer.singleShot(1500, verify)
