"""
Color space and data type converters
"""
import numpy as np


def ycbcr_to_rgb(ycbcr: np.ndarray) -> np.ndarray:
    """
    Convert YCbCr (YBR) to RGB using BT.601 standard
    
    Args:
        ycbcr: Input array in YCbCr format (H, W, 3)
        
    Returns:
        RGB array (uint8)
    """
    y = ycbcr[:, :, 0].astype(float)
    cb = ycbcr[:, :, 1].astype(float)
    cr = ycbcr[:, :, 2].astype(float)
    
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    
    rgb = np.stack([
        np.clip(r, 0, 255),
        np.clip(g, 0, 255),
        np.clip(b, 0, 255)
    ], axis=-1)
    
    return rgb.astype(np.uint8)


def to_gray(img: np.ndarray) -> np.ndarray:
    """
    Convert RGB image to grayscale (luminance)
    
    Args:
        img: RGB image (H, W, 3) or grayscale (H, W)
        
    Returns:
        Grayscale image (H, W) as float32
    """
    if img.ndim == 3 and img.shape[-1] == 3:
        r, g, b = img[..., 0], img[..., 1], img[..., 2]
        return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)
    return img.astype(np.float32)
