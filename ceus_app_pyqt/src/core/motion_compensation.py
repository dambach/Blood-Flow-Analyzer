"""
Motion compensation module
Phase-correlation based registration for CEUS stacks
"""
import numpy as np
from typing import Tuple
from skimage.registration import phase_cross_correlation
from scipy.ndimage import shift as ndi_shift
from src.utils.converters import to_gray


def _compute_reference(
    register_stack: np.ndarray,
    skip_first: int = 3,
    ref_window: int = 10
) -> Tuple[np.ndarray, str]:
    """
    Build robust reference by median of K frames following initial skip
    
    Args:
        register_stack: Stack to register (T, H, W) or (T, H, W, 3)
        skip_first: Number of initial frames to skip
        ref_window: Number of frames to median
        
    Returns:
        Tuple of (ref_gray, ref_info)
    """
    T = register_stack.shape[0]
    start = min(max(0, skip_first), max(0, T - 1))
    end = min(T, start + max(1, ref_window))
    
    ref_gray = np.median(
        np.stack([to_gray(register_stack[i]) for i in range(start, end)], axis=0),
        axis=0
    )
    
    return ref_gray, f"median[{start}:{end}]"


def _estimate_shifts(
    register_stack: np.ndarray,
    ref_gray: np.ndarray,
    upsample: int = 20
) -> np.ndarray:
    """
    Estimate shifts (dy, dx) between each frame and reference (subpixel)
    
    Args:
        register_stack: Stack to register
        ref_gray: Reference grayscale image
        upsample: Upsampling factor for subpixel precision
        
    Returns:
        Shifts array (T, 2) with (dy, dx) per frame
    """
    T = register_stack.shape[0]
    shifts = np.zeros((T, 2), dtype=np.float32)
    
    for t in range(T):
        img_gray = to_gray(register_stack[t])
        shift, _, _ = phase_cross_correlation(
            ref_gray, img_gray, 
            upsample_factor=upsample
        )
        shifts[t] = (float(shift[0]), float(shift[1]))
    
    return shifts


def _apply_shifts(
    target_stack: np.ndarray,
    shifts: np.ndarray,
    pad_mode: str = 'nearest',
    order: int = 1
) -> np.ndarray:
    """
    Apply shifts (dy, dx) to each frame of target stack
    
    Args:
        target_stack: Stack to transform
        shifts: Shifts array (T, 2)
        pad_mode: Padding mode for shift
        order: Interpolation order
        
    Returns:
        Transformed stack
    """
    T = target_stack.shape[0]
    out = np.empty_like(target_stack)
    
    for t in range(T):
        dy, dx = float(shifts[t, 0]), float(shifts[t, 1])
        
        if target_stack.ndim == 4 and target_stack.shape[-1] == 3:
            # RGB: apply shift per channel
            out[t] = np.stack(
                [ndi_shift(target_stack[t, ..., c], shift=(dy, dx), 
                          order=order, mode=pad_mode)
                 for c in range(3)],
                axis=-1
            )
        else:
            # Grayscale
            out[t] = ndi_shift(target_stack[t], shift=(dy, dx), 
                             order=order, mode=pad_mode)
    
    return out


def motion_compensate(
    ceus_stack: np.ndarray,
    bmode_stack: np.ndarray = None,
    skip_first: int = 3,
    ref_window: int = 10,
    upsample: int = 20
) -> Tuple[np.ndarray, np.ndarray, str]:
    """
    Motion compensate CEUS stack (optionally use B-mode for registration)
    
    Args:
        ceus_stack: CEUS stack to correct
        bmode_stack: Optional B-mode stack for registration (if compatible)
        skip_first: Frames to skip for reference computation
        ref_window: Number of frames to median for reference
        upsample: Upsampling factor for subpixel precision
        
    Returns:
        Tuple of (ceus_corrected, shifts, source_info)
    """
    # Determine which stack to use for shift estimation
    register_stack = ceus_stack
    target_stack = ceus_stack
    used_bmode = False
    
    if bmode_stack is not None and len(bmode_stack) > 0:
        # Harmonize length and spatial size
        T = min(len(bmode_stack), len(ceus_stack))
        bm = bmode_stack[:T]
        tg = ceus_stack[:T]
        
        if bm.ndim >= 3 and tg.ndim >= 3 and bm.shape[1:3] == tg.shape[1:3]:
            register_stack = bm
            target_stack = tg
            used_bmode = True
    
    # Compute robust reference
    ref_gray, ref_info = _compute_reference(register_stack, skip_first, ref_window)
    
    # Estimate shifts on register_stack
    shifts = _estimate_shifts(register_stack, ref_gray=ref_gray, upsample=upsample)
    
    # Apply shifts on target_stack (CEUS)
    ceus_corrected = _apply_shifts(target_stack, shifts, pad_mode='nearest', order=1)
    
    source_info = "B-mode" if used_bmode else "CEUS"
    
    return ceus_corrected, shifts, source_info
