"""Bundled resources and persistent data paths; no Qt or physics dependencies."""

import os
from pathlib import Path
import shutil
import sys

from app_metadata import APP_NAME


def resource_directory():
    return Path(__file__).resolve().parent


def data_directory():
    if not getattr(sys, 'frozen', False):
        return resource_directory()
    local_data = os.environ.get('LOCALAPPDATA')
    root = Path(local_data) if local_data else Path.home() / 'AppData' / 'Local'
    return root / APP_NAME


def scene_directory():
    """Seed bundled scenes once, preserving existing files and user scenes."""
    source = resource_directory() / 'scenes'
    if not getattr(sys, 'frozen', False):
        return source
    destination = data_directory() / 'scenes'
    destination.mkdir(parents=True, exist_ok=True)
    for scene in source.glob('*.json'):
        target = destination / scene.name
        if not target.exists():
            shutil.copyfile(scene, target)
    return destination
