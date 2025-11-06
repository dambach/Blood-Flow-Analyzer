"""
Flash and washout detection module
Detects microbubble destruction flash and true reperfusion start
"""
import numpy as np
from typing import Tuple


def detect_flash_ceus_refined(
    ceus_stack: np.ndarray,
    exclude_first_n: int = 5,
    search_window: int = 20
) -> Tuple[int, int, np.ndarray]:
    """
    Detect flash (microbubble destruction) and washout (darkest frame)
    
    Args:
        ceus_stack: CEUS video stack (T, H, W, C) or (T, H, W)
        exclude_first_n: Number of initial frames to exclude
        search_window: Search window after flash for washout detection
        
    Returns:
        Tuple of (flash_idx, washout_idx, intensities)
    """
    # Calculate mean intensity per frame
    if ceus_stack.ndim == 4:
        intensities = ceus_stack.mean(axis=(1, 2, 3))
    else:
        intensities = ceus_stack.mean(axis=(1, 2))
    
    T = len(intensities)
    start_frame = min(exclude_first_n, T // 10)
    
    # 1. Flash detection (maximum negative gradient)
    gradients = np.diff(intensities)
    flash_idx = start_frame + np.argmin(gradients[start_frame:])
    
    # 2. Washout detection (minimum intensity after flash)
    search_start = flash_idx
    search_end = min(T, flash_idx + search_window)
    washout_idx = search_start + np.argmin(intensities[search_start:search_end])
    
    return int(flash_idx), int(washout_idx), intensities
