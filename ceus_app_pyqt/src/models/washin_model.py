"""
Wash-in model fitting module
Fits A*(1 - exp(-B*t)) to wash-in phase
"""
import numpy as np
from scipy.optimize import curve_fit
from typing import Tuple, Optional


def washin_model(t: np.ndarray, A: float, B: float) -> np.ndarray:
    """
    Wash-in model: A*(1 - exp(-B*t))
    
    Args:
        t: Time array
        A: Plateau parameter
        B: Rate parameter
        
    Returns:
        Predicted values
    """
    return A * (1.0 - np.exp(-B * t))


def fit_washin(
    time: np.ndarray,
    dvi: np.ndarray,
    t_max: float = 5.0,
    A_start: Optional[float] = None,
    B_start: float = 0.5,
    bounds: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
    maxfev: int = 20000
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], np.ndarray, np.ndarray]:
    """
    Fit wash-in model to dVI curve
    
    Args:
        time: Time array (seconds)
        dvi: Delta VI array
        t_max: Maximum time to fit (seconds)
        A_start: Initial guess for A (auto if None)
        B_start: Initial guess for B
        bounds: ((A_min, B_min), (A_max, B_max))
        maxfev: Maximum function evaluations
        
    Returns:
        Tuple of (params, pcov, t_fit, y_fit)
        - params: [A, B] or None if fit failed
        - pcov: Parameter covariance matrix or None
        - t_fit: Time array used for fitting
        - y_fit: dVI values used for fitting
    """
    # Select fitting window (0 to t_max seconds)
    mask_fit = time <= t_max
    t_fit = time[mask_fit]
    y_fit = dvi[mask_fit]
    
    if len(t_fit) < 3:
        return None, None, t_fit, y_fit
    
    # Auto-determine A_start if not provided
    if A_start is None:
        A_start = max(1e-6, float(np.nanmax(y_fit)))
    
    # Default bounds
    if bounds is None:
        bounds = ([0.0, 0.1], [np.inf, 5.0])
    
    # Fit
    try:
        params, pcov = curve_fit(
            washin_model, 
            t_fit, 
            y_fit,
            p0=[A_start, B_start],
            bounds=bounds,
            maxfev=maxfev
        )
        return params, pcov, t_fit, y_fit
    except Exception as e:
        print(f"Wash-in fit failed: {e}")
        return None, None, t_fit, y_fit
