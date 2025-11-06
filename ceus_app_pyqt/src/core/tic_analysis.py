"""
Time-Intensity Curve (TIC) extraction module
"""
import numpy as np
from typing import Tuple
from src.utils.converters import to_gray
from src.utils.validators import validate_roi


def extract_tic_from_roi(
    stack: np.ndarray,
    roi: Tuple[int, int, int, int],
    fps: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extract TIC from ROI
    
    Args:
        stack: Image stack (T, H, W) or (T, H, W, 3)
        roi: ROI coordinates (x0, y0, x1, y1)
        fps: Frames per second
        
    Returns:
        Tuple of (time, vi, dvi)
        - time: Time axis in seconds
        - vi: Video intensity (mean in ROI)
        - dvi: Delta VI (VI - baseline)
    """
    # Validate ROI
    is_valid, clipped_roi = validate_roi(roi, stack.shape[1:3])
    if not is_valid:
        raise ValueError(f"Invalid ROI: {roi}")
    
    x0, y0, x1, y1 = clipped_roi
    
    # Convert to grayscale if needed
    if stack.ndim == 4 and stack.shape[-1] == 3:
        stack_gray = np.stack([to_gray(f) for f in stack], axis=0)
    else:
        stack_gray = stack.astype(np.float32)
    
    # Extract VI series in ROI
    T = stack_gray.shape[0]
    roi_series = stack_gray[:, y0:y1+1, x0:x1+1].reshape(T, -1).mean(axis=1)
    
    # Time axis (seconds)
    time = np.arange(T, dtype=np.float32) / fps
    
    # dVI = VI - baseline (first frame)
    baseline = float(roi_series[0])
    dvi = roi_series - baseline
    
    return time, roi_series, dvi
