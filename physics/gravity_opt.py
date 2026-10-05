"""
高性能引力计算模块
在原有基础上增加GPU加速支持
"""
import numpy as np
from typing import List
from .body import Body
from .gravity import GravitySolver
from .constants import G, SOFTENING

# 尝试导入CuPy（GPU加速）
CUPY_AVAILABLE = False
try:
    import cupy as cp
    CUPY_AVAILABLE = True
    print("[GravityOpt] CuPy available - GPU acceleration enabled")
except Exception:
    pass  # 静默失败

class GravitySolverOpt(GravitySolver):
    """
    引力求解器（支持GPU加速）
    """
    def __init__(self, softening: float = SOFTENING, use_gpu: bool = True):
        super().__init__(softening=softening)
        self.use_gpu = use_gpu and CUPY_AVAILABLE
        
    def _compute_accelerations_impl(self, bodies: List[Body]) -> np.ndarray:
        """加速度计算的实现"""
        n = len(bodies)
        if n == 0:
            return np.zeros((0, 2), dtype=np.float64)
        
        # 根据配置选择GPU或CPU
        if self.use_gpu:
            return self._compute_gpu(bodies)
        else:
            return super()._compute_accelerations_impl(bodies)
    
    def _compute_gpu(self, bodies: List[Body]) -> np.ndarray:
        """GPU加速实现"""
        n = len(bodies)
        
        # 提取位置和质量
        positions = np.array([b.position for b in bodies], dtype=np.float64)
        masses = np.array([b.mass for b in bodies], dtype=np.float64)
        
        # 转换到GPU
        positions_cp = cp.asarray(positions)
        masses_cp = cp.asarray(masses)
        soft_cp = cp.float64(self.softening)
        
        # GPU计算（与原版逻辑相同）
        diff = positions_cp[cp.newaxis, :, :] - positions_cp[:, cp.newaxis, :]
        dist_sq = cp.sum(diff ** 2, axis=2) + soft_cp ** 2
        cp.fill_diagonal(dist_sq, 1.0)
        inv_dist_cube = 1.0 / cp.power(dist_sq, 1.5)
        cp.fill_diagonal(inv_dist_cube, 0.0)
        weights = masses_cp[cp.newaxis, :] * inv_dist_cube
        accelerations_cp = G * cp.sum(weights[:, :, cp.newaxis] * diff, axis=1)
        
        # 转回CPU
        return cp.asnumpy(accelerations_cp)
    
    def _compute_cpu(self, bodies: List[Body]) -> np.ndarray:
        """Compatibility wrapper sharing the canonical CPU solver."""
        return super()._compute_accelerations_impl(bodies)
