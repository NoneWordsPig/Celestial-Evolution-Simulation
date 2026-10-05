"""Numerical validation of the shared, batched float64 RK4 implementation."""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from physics.body import Body
from physics.gravity import GravitySolver
from physics.gravity_opt import GravitySolverOpt
from physics.integrator import RK4Integrator, IntegratorFactory
from physics.integrator_opt import RK4IntegratorOpt


class TestRK4Batch(unittest.TestCase):
    def test_constant_acceleration_is_exact_and_uses_four_stages(self):
        acceleration = np.array([[1.5, -2.0], [-0.5, 0.25]], dtype=np.float64)
        solver = SimpleNamespace(compute_accelerations=mock.Mock(return_value=acceleration))
        bodies = [Body(position=(2, 3), velocity=(-1, 4)),
                  Body(position=(-5, 1), velocity=(2, -3))]
        positions = np.array([b.position for b in bodies])
        velocities = np.array([b.velocity for b in bodies])
        old_positions = [b.position for b in bodies]
        dt = 0.125
        RK4Integrator(solver).step(bodies, dt)
        np.testing.assert_allclose([b.position for b in bodies],
                                   positions + velocities * dt + 0.5 * acceleration * dt**2,
                                   rtol=0, atol=1e-15)
        np.testing.assert_allclose([b.velocity for b in bodies], velocities + acceleration * dt,
                                   rtol=0, atol=1e-15)
        self.assertEqual(solver.compute_accelerations.call_count, 4)
        np.testing.assert_array_equal(old_positions, positions)
        for body in bodies:
            self.assertEqual(body.position.dtype, np.float64)
            self.assertEqual(body.velocity.dtype, np.float64)
        self.assertFalse(np.shares_memory(bodies[0].position, bodies[1].position))

    def test_circular_binary_has_fourth_order_convergence(self):
        for solver in (GravitySolver(softening=0), GravitySolverOpt(softening=0, use_gpu=False)):
            errors = []
            for dt in (0.05, 0.025):
                bodies = [Body(mass=0.5, position=(-0.5, 0), velocity=(0, -0.5)),
                          Body(mass=0.5, position=(0.5, 0), velocity=(0, 0.5))]
                integrator = IntegratorFactory.create('rk4', solver)
                for _ in range(round(1 / dt)):
                    integrator.step(bodies, dt)
                expected = np.array([0.5 * np.cos(1.0), 0.5 * np.sin(1.0)])
                errors.append(np.linalg.norm(bodies[1].position - expected))
                energy = sum(b.kinetic_energy() for b in bodies) + solver.potential_energy(bodies)
                self.assertLess(abs(energy + 0.125), 1e-7)
                np.testing.assert_allclose(sum(b.momentum() for b in bodies), 0, atol=1e-15)
            self.assertGreater(errors[0] / errors[1], 12)
            self.assertLess(errors[0] / errors[1], 20)

    def test_empty_scene_skips_force_evaluation(self):
        solver = SimpleNamespace(compute_accelerations=mock.Mock())
        RK4Integrator(solver).step([], 0.001)
        solver.compute_accelerations.assert_not_called()

    def test_optimized_and_standard_solvers_follow_same_trajectory(self):
        rng = np.random.default_rng(42)
        initial = [(float(rng.uniform(0.01, 1)), rng.uniform(-2, 2, 2), rng.uniform(-0.5, 0.5, 2))
                   for _ in range(9)]
        results = []
        for solver in (GravitySolver(), GravitySolverOpt(use_gpu=False)):
            bodies = [Body(mass=m, position=p, velocity=v) for m, p, v in initial]
            integrator = IntegratorFactory.create('rk4', solver)
            for _ in range(300):
                integrator.step(bodies, 0.001)
            results.append(np.array([[*b.position, *b.velocity] for b in bodies]))
        np.testing.assert_array_equal(*results)


if __name__ == '__main__':
    unittest.main()
