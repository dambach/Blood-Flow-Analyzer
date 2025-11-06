"""
TIC metrics computation module
"""
import numpy as np
from typing import Dict, Optional
from scipy.ndimage import median_filter


def r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Compute R² (coefficient of determination)
    
    Args:
        y_true: True values
        y_pred: Predicted values
        
    Returns:
        R² score
    """
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2)) + 1e-12
    return 1.0 - ss_res / ss_tot


def compute_metrics(
    time: np.ndarray,
    dvi: np.ndarray,
    dvi_filt: np.ndarray,
    params: Optional[np.ndarray],
    t_fit: np.ndarray,
    y_fit: np.ndarray,
    washin_model_func
) -> Dict[str, float]:
    """
    Compute all TIC metrics
    
    Args:
        time: Full time array
        dvi: Raw dVI
        dvi_filt: Filtered dVI
        params: Fit parameters [A, B] or None
        t_fit: Time array used for fitting
        y_fit: dVI values used for fitting
        washin_model_func: Wash-in model function
        
    Returns:
        Dictionary of metrics
    """
    # Predicted curve
    if params is not None:
        y_pred = washin_model_func(t_fit, *params)
        R2 = r2_score(y_fit, y_pred)
        AUC_pred = float(np.trapz(y_pred, t_fit))
        A, B = params
    else:
        y_pred = np.zeros_like(t_fit)
        R2 = np.nan
        AUC_pred = np.nan
        A, B = np.nan, np.nan
    
    # AUC (filtered)
    AUC_filt = float(np.trapz(y_fit, t_fit))
    
    # Peak values
    peak_dVI = float(np.nanmax(dvi))
    peak_dVI_filt = float(np.nanmax(dvi_filt))
    
    # Mean values
    mean_dVI = float(np.nanmean(dvi))
    mean_dVI_filt = float(np.nanmean(dvi_filt))
    
    # Max slope (from filtered dVI)
    dt = np.maximum(1e-6, np.diff(time))
    dv = np.diff(dvi_filt)
    max_slope = float(np.nanmax(dv / dt)) if len(dv) > 0 else np.nan
    
    return {
        'A': float(A),
        'B': float(B),
        'A*B': float(A * B) if params is not None else np.nan,
        'R2': R2,
        'AUC_dVI_filt': AUC_filt,
        'AUC_dVI_pred': AUC_pred,
        'Peak_dVI': peak_dVI,
        'Peak_dVI_filt': peak_dVI_filt,
        'Mean_dVI': mean_dVI,
        'Mean_dVI_filt': mean_dVI_filt,
        'Max_slope_dVI_filt': max_slope,
    }


def apply_median_filter(dvi: np.ndarray, fps: float, window_s: float = 0.5) -> np.ndarray:
    """
    Apply median filter to dVI curve
    
    Args:
        dvi: Raw dVI
        fps: Frames per second
        window_s: Window size in seconds
        
    Returns:
        Filtered dVI
    """
    window_size = max(3, int(window_s * fps))
    if window_size % 2 == 0:
        window_size += 1  # Force odd for median_filter
    
    return median_filter(dvi, size=window_size, mode='nearest')
