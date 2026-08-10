"""
物理引擎主循环模块

协调引力计算、积分、碰撞检测等步骤
管理世界状态和时间推进
"""

import numpy as np
from typing import List, Optional
from .body import Body
from .gravity import GravitySolver
from .collision import CollisionHandler
from .integrator import VelocityVerletIntegrator, RK4Integrator, IntegratorFactory
from .constants import G, SOFTENING, DEFAULT_DT, MAX_TRAJECTORY_LENGTH


class PhysicsEngine:
    """
    物理引擎
    
    管理整个模拟的生命周期：
    1. 引力计算
    2. 数值积分（更新位置和速度）
    3. 碰撞检测与融合
    4. 轨迹记录
    5. 统计量计算（质心、能量等）
    """
    
    def __init__(
        self,
        integrator_type: str = 'verlet',
        softening: float = SOFTENING,
        dt: float = DEFAULT_DT,
        time_scale: float = 1.0
    ):
        """
        初始化物理引擎
        
        Args:
            integrator_type: 积分器类型 ('verlet' 或 'rk4')
            softening: 软化因子
            dt: 基础时间步长
            time_scale: 时间倍率（1.0 = 正常速度）
        """
        # 物理组件
        self.gravity_solver = GravitySolver(softening=softening)
        self.collision_handler = CollisionHandler()
        self.integrator = IntegratorFactory.create(integrator_type, self.gravity_solver)
        
        # 世界状态
        self.bodies: List[Body] = []
        self.simulation_time: float = 0.0  # 模拟时间
        
        # 全局轨迹历史（所有天体的轨迹点）
        self.trajectory_history: List[np.ndarray] = []
        
        # 时间控制
        self.dt = dt
        self.time_scale = time_scale
        
        # Velocity Verlet 需要的上一步加速度缓存
        self._cached_accelerations: Optional[np.ndarray] = None
    
    def add_body(self, body: Body) -> None:
        """
        添加天体到模拟中
        
        Args:
            body: 要添加的天体
        """
        self.bodies.append(body)
        # 添加天体后，加速度缓存失效
        self._cached_accelerations = None
    
    def remove_body(self, index: int) -> Body:
        """
        移除指定索引的天体
        
        Args:
            index: 天体索引
            
        Returns:
            被移除的天体
        """
        body = self.bodies.pop(index)
        self._cached_accelerations = None
        return body
    
    def clear(self) -> None:
        """清空所有天体和轨迹"""
        self.bodies.clear()
        self.trajectory_history.clear()
        self.simulation_time = 0.0
        self._cached_accelerations = None
    
    def step(self) -> None:
        """
        执行一步物理模拟
        
        包含：
        1. 根据 time_scale 确定子步数
        2. 对每个子步执行：积分 -> 碰撞 -> 轨迹记录
        """
        # 计算每帧需要执行的物理子步数
        updates_per_frame = int(self.time_scale)
        fractional_part = self.time_scale - updates_per_frame
        
        # 执行整数部分
        for _ in range(updates_per_frame):
            self._single_step()
        
        # 小数部分用概率补偿
        if np.random.random() < fractional_part:
            self._single_step()
    
    def _single_step(self) -> None:
        """
        执行单个物理时间步
        
        顺序：积分 -> 碰撞处理 -> 轨迹记录 -> 时间推进
        """
        if len(self.bodies) == 0:
            return
        
        # 1. 数值积分（更新位置和速度）
        if isinstance(self.integrator, VelocityVerletIntegrator):
            self._cached_accelerations = self.integrator.step(
                self.bodies, self.dt, self._cached_accelerations
            )
        else:
            self.integrator.step(self.bodies, self.dt)
        
        # 2. 碰撞检测与融合
        self.bodies = self.collision_handler.resolve_collisions(self.bodies)
        # 碰撞后加速度缓存失效
        self._cached_accelerations = None
        
        # 3. 记录轨迹
        self._record_trajectories()
        
        # 4. 推进模拟时间
        self.simulation_time += self.dt
    
    def _record_trajectories(self) -> None:
        """
        记录当前帧的轨迹数据
        
        - 每个天体的个体轨迹（trail）
        - 全局轨迹历史（trajectory_history）
        """
        for body in self.bodies:
            # 记录个体轨迹
            body.trail.append(body.position.copy())
            # 限制轨迹长度
            if len(body.trail) > MAX_TRAJECTORY_LENGTH:
                body.trail = body.trail[-MAX_TRAJECTORY_LENGTH:]
            
            # 记录到全局轨迹
            self.trajectory_history.append(body.position.copy())
        
        # 限制全局轨迹长度
        if len(self.trajectory_history) > MAX_TRAJECTORY_LENGTH:
            self.trajectory_history = self.trajectory_history[-MAX_TRAJECTORY_LENGTH:]
    
    def center_of_mass(self) -> np.ndarray:
        """
        计算系统质心位置
        
        R_cm = sum(m_i * r_i) / sum(m_i)
        
        Returns:
            质心坐标 (x, y)
        """
        if not self.bodies:
            return np.zeros(2, dtype=np.float64)
        
        total_mass = sum(b.mass for b in self.bodies)
        weighted_pos = sum(b.mass * b.position for b in self.bodies)
        
        return weighted_pos / total_mass
    
    def total_momentum(self) -> np.ndarray:
        """
        计算系统总动量
        
        P = sum(m_i * v_i)
        
        Returns:
            总动量向量 (px, py)
        """
        if not self.bodies:
            return np.zeros(2, dtype=np.float64)
        
        return sum(b.momentum() for b in self.bodies)
    
    def kinetic_energy(self) -> float:
        """
        计算系统总动能
        
        KE = sum(0.5 * m_i * v_i^2)
        
        Returns:
            总动能
        """
        return sum(b.kinetic_energy() for b in self.bodies)
    
    def potential_energy(self) -> float:
        """
        计算系统总势能
        
        PE = -G * sum(m_i * m_j / r_ij)  (i < j)
        
        Returns:
            总势能（负值）
        """
        return self.gravity_solver.potential_energy(self.bodies)
    
    def total_energy(self) -> float:
        """
        计算系统总能量
        
        E = KE + PE
        
        Returns:
            总能量
        """
        return self.kinetic_energy() + self.potential_energy()
    
    def total_mass(self) -> float:
        """
        计算系统总质量
        
        Returns:
            总质量
        """
        return sum(b.mass for b in self.bodies)
    
    def body_count(self) -> int:
        """
        获取当前天体数量
        
        Returns:
            天体数量
        """
        return len(self.bodies)
    # ============================================================
    # 只读查询接口（供 UI / Formatter 使用，不修改物理状态）
    # ============================================================

    def get_body_state(self, index: int) -> dict:
        """
        获取指定天体的状态快照（只读）

        Args:
            index: 天体索引

        Returns:
            包含 name, mass, position, velocity, physical_radius, render_radius 的字典
            所有数值均为模拟单位
        """
        body = self.bodies[index]
        return {
            'name': body.name,
            'mass': body.mass,
            'position': body.position.copy(),
            'velocity': body.velocity.copy(),
            'physical_radius': body.physical_radius,
            'render_radius': body.render_radius,
            'color': body.color.copy(),
        }

    def body_acceleration(self, index: int) -> np.ndarray:
        """
        计算指定天体当前受到的引力加速度（只读）

        不修改物理状态，仅计算当前时刻的加速度。

        Args:
            index: 天体索引

        Returns:
            加速度向量 (ax, ay)（模拟单位）
        """
        if len(self.bodies) <= 1:
            return np.zeros(2, dtype=np.float64)
        return self.gravity_solver.compute_acceleration_single(self.bodies, index)

    def body_net_force(self, index: int) -> np.ndarray:
        """
        计算指定天体当前受到的净引力（只读）

        F = m * a

        Args:
            index: 天体索引

        Returns:
            力向量 (Fx, Fy)（模拟单位）
        """
        body = self.bodies[index]
        return body.mass * self.body_acceleration(index)

    def body_distances(self, index: int) -> np.ndarray:
        """
        计算指定天体到所有其他天体的距离（只读）

        Args:
            index: 天体索引

        Returns:
            距离数组，长度为 N-1（排除自身）
        """
        body = self.bodies[index]
        distances = []
        for j, other in enumerate(self.bodies):
            if j != index:
                distances.append(body.distance_to(other))
        return np.array(distances, dtype=np.float64)

    def body_kinetic_energy(self, index: int) -> float:
        """
        计算指定天体的动能（只读）

        Args:
            index: 天体索引

        Returns:
            动能（模拟单位）
        """
        return self.bodies[index].kinetic_energy()

    def get_all_body_states(self) -> list:
        """
        获取所有天体的状态快照列表（只读）

        Returns:
            状态字典列表
        """
        return [self.get_body_state(i) for i in range(len(self.bodies))]

    def snapshot(self) -> dict:
        """
        获取当前模拟状态的完整快照（只读）

        用于模式切换前后验证物理状态一致性。

        Returns:
            包含所有物理状态的字典
        """
        return {
            'simulation_time': self.simulation_time,
            'dt': self.dt,
            'time_scale': self.time_scale,
            'body_count': len(self.bodies),
            'bodies': [
                {
                    'name': b.name,
                    'mass': b.mass,
                    'position': b.position.copy(),
                    'velocity': b.velocity.copy(),
                    'physical_radius': b.physical_radius,
                    'render_radius': b.render_radius,
                }
                for b in self.bodies
            ],
        }

