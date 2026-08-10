"""
天体数据类模块

定义 Body 类，表示模拟中的单个天体
"""

import numpy as np
from typing import Tuple, Optional


class Body:
    """
    天体类
    
    属性:
        name: 天体名称
        mass: 质量
        radius: 半径
        position: 位置 (x, y)
        velocity: 速度 (vx, vy)
        color: 颜色 (R, G, B) 归一化到 0-1
    """
    
    def __init__(
        self,
        name: str = "",
        mass: float = 1.0,
        radius: float = 1.0,
        position: Tuple[float, float] = (0.0, 0.0),
        velocity: Tuple[float, float] = (0.0, 0.0),
        color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    ):
        """
        初始化天体
        
        Args:
            name: 天体名称
            mass: 质量（必须 > 0）
            radius: 半径（必须 > 0）
            position: 初始位置 (x, y)
            velocity: 初始速度 (vx, vy)
            color: RGB 颜色，归一化到 0-1
        """
        self.name = name
        self.mass = max(mass, 1e-10)  # 防止零质量
        self.radius = max(radius, 1e-10)  # 防止零半径
        self.position = np.array(position, dtype=np.float64)
        self.velocity = np.array(velocity, dtype=np.float64)
        self.color = np.array(color, dtype=np.float32)
        
        # 轨迹历史（用于渲染）
        self.trail: list = []
    
    def kinetic_energy(self) -> float:
        """
        计算天体的动能
        
        Returns:
            动能 = 0.5 * m * v²
        """
        v_squared = np.sum(self.velocity ** 2)
        return 0.5 * self.mass * v_squared
    
    def momentum(self) -> np.ndarray:
        """
        计算天体的动量
        
        Returns:
            动量向量 (px, py) = m * (vx, vy)
        """
        return self.mass * self.velocity
    
    def distance_to(self, other: 'Body') -> float:
        """
        计算到另一个天体的距离
        
        Args:
            other: 另一个天体
            
        Returns:
            欧几里得距离
        """
        return np.linalg.norm(self.position - other.position)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"Body(name='{self.name}', mass={self.mass:.2f}, pos={self.position})"
