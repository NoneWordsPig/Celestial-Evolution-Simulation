"""
Physics 物理引擎模块

提供天体引力模拟的核心物理计算功能

主要组件：
- Body: 天体数据类
- GravitySolver: 万有引力计算
- CollisionHandler: 碰撞检测与融合
- VelocityVerletIntegrator / RK4Integrator: 数值积分器
- PhysicsEngine: 物理引擎主循环
"""

from .body import Body
from .gravity import GravitySolver
from .collision import CollisionHandler
from .integrator import VelocityVerletIntegrator, RK4Integrator, IntegratorFactory
from .engine import PhysicsEngine
from .constants import G, SOFTENING, DEFAULT_DT, MAX_TRAJECTORY_LENGTH

__all__ = [
    'Body',
    'GravitySolver',
    'CollisionHandler',
    'VelocityVerletIntegrator',
    'RK4Integrator',
    'IntegratorFactory',
    'PhysicsEngine',
    'G',
    'SOFTENING',
    'DEFAULT_DT',
    'MAX_TRAJECTORY_LENGTH',
]
