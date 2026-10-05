"""Frozen releases must keep saved scenes outside one-file extraction folders."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app_paths
from app_metadata import APP_NAME


class TestAppPaths(unittest.TestCase):
    def test_source_paths_use_repository(self):
        with mock.patch.object(app_paths.sys, 'frozen', False, create=True):
            self.assertEqual(app_paths.data_directory(), Path(app_paths.__file__).resolve().parent)
            self.assertEqual(app_paths.scene_directory(), app_paths.data_directory() / 'scenes')

    def test_frozen_scenes_are_persistent_and_existing_files_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'bundle'
            (bundle / 'scenes').mkdir(parents=True)
            (bundle / 'scenes' / 'demo.json').write_text('{"name":"built-in"}', encoding='utf-8')
            with mock.patch.object(app_paths.sys, 'frozen', True, create=True), \
                    mock.patch.object(app_paths, 'resource_directory', return_value=bundle), \
                    mock.patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'profile')}):
                scenes = app_paths.scene_directory()
                self.assertEqual(scenes, root / 'profile' / APP_NAME / 'scenes')
                self.assertEqual((scenes / 'demo.json').read_text(), '{"name":"built-in"}')
                (scenes / 'demo.json').write_text('{"name":"edited"}', encoding='utf-8')
                (scenes / 'custom.json').write_text('{}', encoding='utf-8')
                self.assertEqual(app_paths.scene_directory(), scenes)
                self.assertEqual((scenes / 'demo.json').read_text(), '{"name":"edited"}')
                self.assertTrue((scenes / 'custom.json').is_file())


if __name__ == '__main__':
    unittest.main()
