"""
碰撞检测与处理模块

实现天体碰撞检测与融合
遵循质量守恒和动量守恒
"""

import numpy as np
from typing import List, Tuple
from .body import Body
from .constants import COLLISION_FACTOR, RADIUS_MERGE_EXPONENT


class CollisionHandler:
    """
    碰撞处理器
    
    检测天体之间的碰撞并执行融合
    """
    
    def __init__(self, collision_factor: float = COLLISION_FACTOR):
        """
        初始化碰撞处理器
        
        Args:
            collision_factor: 碰撞距离阈值系数
        """
        self.collision_factor = collision_factor
    
    def detect_collisions(self, bodies: List[Body]) -> List[Tuple[int, int]]:
        """
        检测所有碰撞对
        
        碰撞条件：两体距离 < (r1 + r2) * collision_factor
        
        Args:
            bodies: 天体列表
            
        Returns:
            碰撞对列表 [(i, j), ...]
        """
        collisions = []
        n = len(bodies)
        
        for i in range(n):
            for j in range(i + 1, n):
                dist = bodies[i].distance_to(bodies[j])
                threshold = (bodies[i].radius + bodies[j].radius) * self.collision_factor
                
                if dist < threshold:
                    collisions.append((i, j))
        
        return collisions
    
    def merge_bodies(self, body_a: Body, body_b: Body) -> Body:
        """
        融合两个天体
        
        守恒量：
        - 质量守恒：m_new = m_a + m_b
        - 动量守恒：m_new * v_new = m_a * v_a + m_b * v_b
        - 体积守恒：r_new = (r_a^3 + r_b^3)^(1/3)
        - 位置：质量加权平均（质心）
        
        Args:
            body_a: 第一个天体
            body_b: 第二个天体
            
        Returns:
            融合后的新天体
        """
        # 质量守恒
        new_mass = body_a.mass + body_b.mass
        
        # 动量守恒 -> 速度
        total_momentum = body_a.momentum() + body_b.momentum()
        new_velocity = total_momentum / new_mass
        
        # 体积守恒 -> 半径
        new_radius = (body_a.radius ** 3 + body_b.radius ** 3) ** RADIUS_MERGE_EXPONENT
        
        # 位置：质量加权平均（质心位置）
        new_position = (body_a.mass * body_a.position + body_b.mass * body_b.position) / new_mass
        
        # 颜色：质量加权平均
        new_color = (body_a.mass * body_a.color + body_b.mass * body_b.color) / new_mass
        
        # 名称：合并名称
        new_name = f"{body_a.name}+{body_b.name}" if body_a.name and body_b.name else body_a.name or body_b.name
        
        # 创建融合后的天体
        merged = Body(
            name=new_name,
            mass=new_mass,
            radius=new_radius,
            position=tuple(new_position),
            velocity=tuple(new_velocity),
            color=tuple(new_color)
        )
        
        # 合并轨迹历史
        merged.trail = body_a.trail + body_b.trail
        
        return merged
    
    def resolve_collisions(self, bodies: List[Body]) -> List[Body]:
        """
        处理所有碰撞，返回融合后的天体列表
        
        使用贪心策略：按碰撞对顺序依次融合
        注意：一次调用可能无法处理所有碰撞（级联碰撞需要多次调用）
        
        Args:
            bodies: 天体列表
            
        Returns:
            碰撞处理后的天体列表
        """
        collisions = self.detect_collisions(bodies)
        
        if not collisions:
            return bodies
        
        # 标记已被融合的天体
        merged_indices = set()
        new_bodies = []
        
        for i, j in collisions:
            # 如果两个天体都还没被融合
            if i not in merged_indices and j not in merged_indices:
                # 融合它们
                merged = self.merge_bodies(bodies[i], bodies[j])
                new_bodies.append(merged)
                merged_indices.add(i)
                merged_indices.add(j)
        
        # 添加未参与碰撞的天体
        for k, body in enumerate(bodies):
            if k not in merged_indices:
                new_bodies.append(body)
        
        return new_bodies
