"""
Input validation functions
"""
import numpy as np
from typing import Tuple, Optional


def validate_roi(roi: Tuple[int, int, int, int], 
                 image_shape: Tuple[int, int]) -> Tuple[bool, Optional[Tuple[int, int, int, int]]]:
    """
    Validate and clip ROI coordinates to image bounds
    
    Args:
        roi: (x0, y0, x1, y1) coordinates
        image_shape: (height, width) of image
        
    Returns:
        Tuple of (is_valid, clipped_roi or None)
    """
    x0, y0, x1, y1 = roi
    H, W = image_shape
    
    # Clip to bounds
    x0_clipped = max(0, min(x0, W - 1))
    y0_clipped = max(0, min(y0, H - 1))
    x1_clipped = max(0, min(x1, W - 1))
    y1_clipped = max(0, min(y1, H - 1))
    
    # Check if valid after clipping (need at least 5x5 pixels)
    width = x1_clipped - x0_clipped + 1
    height = y1_clipped - y0_clipped + 1
    
    if width < 5 or height < 5:
        return False, None
    
    return True, (x0_clipped, y0_clipped, x1_clipped, y1_clipped)


def validate_stack(stack: np.ndarray) -> Tuple[bool, str]:
    """
    Validate image stack format
    
    Args:
        stack: Image stack array
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if stack is None:
        return False, "Stack is None"
    
    if not isinstance(stack, np.ndarray):
        return False, "Stack must be numpy array"
    
    if stack.ndim not in (3, 4):
        return False, f"Stack must be 3D or 4D, got {stack.ndim}D"
    
    if stack.shape[0] < 2:
        return False, f"Stack must have at least 2 frames, got {stack.shape[0]}"
    
    if stack.ndim == 4 and stack.shape[-1] != 3:
        return False, f"RGB stack must have 3 channels, got {stack.shape[-1]}"
    
    return True, ""
