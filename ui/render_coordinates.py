"""Render coordinate conversion shared by the body and trail builders."""

import numpy as np


def world_to_ndc(positions, camera):
    """Use Camera's world transform and produce float64 clip coordinates."""
    sx, sy = camera.world_to_screen(positions[:, 0], positions[:, 1])
    return np.column_stack((
        sx / camera.viewport_width * 2.0 - 1.0,
        1.0 - sy / camera.viewport_height * 2.0,
    ))
