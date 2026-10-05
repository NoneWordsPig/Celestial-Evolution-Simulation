"""Compatibility name for RK4 with an optimized gravity solver.

The four-stage algorithm lives in integrator.py; keep a single implementation.
"""

from .integrator import RK4Integrator


class RK4IntegratorOpt(RK4Integrator):
    """Reuse the canonical float64 RK4 implementation."""
