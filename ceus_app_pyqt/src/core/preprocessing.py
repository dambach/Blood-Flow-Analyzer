"""
CEUS preprocessing module
Improves SNR through filtering, normalization, and background subtraction
"""
import numpy as np
from typing import Optional
from scipy.ndimage import median_filter, gaussian_filter, gaussian_filter1d
from src.utils.converters import to_gray


def preprocess_ceus(
    stack: np.ndarray,
    use_log: bool = True,
    p_lo: float = 1,
    p_hi: float = 99,
    spatial: Optional[str] = 'median',    # 'median'|'gaussian'|None
    temporal: Optional[str] = 'gaussian',  # 'gaussian'|'mean'|None
    t_win: int = 3,
    baseline_frames: int = 5
) -> np.ndarray:
    """
    Preprocess CEUS stack to improve SNR
    
    Args:
        stack: Input stack (T, H, W) or (T, H, W, 3)
        use_log: Apply log-compression
        p_lo, p_hi: Percentiles for normalization
        spatial: Spatial filter ('median', 'gaussian', or None)
        temporal: Temporal filter ('gaussian', 'mean', or None)
        t_win: Temporal window size
        baseline_frames: Number of frames for baseline subtraction
        
    Returns:
        Preprocessed stack (T, H, W) as float32
    """
    assert stack.ndim in (3, 4), "stack expected (T,H,W) or (T,H,W,3)"
    
    X = stack.astype(np.float32)
    
    # Convert to grayscale if RGB
    if X.ndim == 4 and X.shape[-1] == 3:
        X = np.stack([to_gray(X[t]) for t in range(X.shape[0])], axis=0)
    
    # Normalization by global percentiles
    p1, p99 = np.percentile(X, [p_lo, p_hi])
    p1 = float(p1)
    p99 = float(p99 if p99 > p1 else p1 + 1e-3)
    X = np.clip((X - p1) / (p99 - p1), 0, 1)
    
    # Log-compression (homomorphic)
    if use_log:
        alpha = 20.0
        X = np.log1p(alpha * X) / np.log1p(alpha)
    
    # Spatial smoothing
    if spatial == 'median':
        X = median_filter(X, size=(1, 3, 3))
    elif spatial == 'gaussian':
        X = gaussian_filter(X, sigma=(0, 0.6, 0.6))
    
    # Background subtraction (baseline = median of N first frames)
    if baseline_frames is None:
        baseline_frames = 0
    if baseline_frames <= 0:
        N = 0
    else:
        N = min(int(baseline_frames), max(1, X.shape[0] // 10))
    if N > 0:
        baseline = np.median(X[:N], axis=0, keepdims=True)
        X = np.maximum(X - baseline, 0)
    
    # Temporal filter
    if temporal == 'gaussian' and X.shape[0] > 1:
        sig = max(0.5, (t_win - 1) / 2.0)
        X = gaussian_filter1d(X, sigma=sig, axis=0, mode='nearest')
    elif temporal == 'mean' and X.shape[0] > 1:
        k = max(1, int(t_win))
        k = k if k % 2 == 1 else k + 1
        pad = k // 2
        kernel = np.ones((k, 1, 1), dtype=np.float32) / k
        X_pad = np.pad(X, ((pad, pad), (0, 0), (0, 0)), mode='edge')
        # Naive 1D convolution along time
        Y = np.empty_like(X)
        for t in range(X.shape[0]):
            Y[t] = np.sum(X_pad[t:t+k] * kernel, axis=0)
        X = Y
    
    return X
