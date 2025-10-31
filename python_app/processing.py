"""Utilities for converting CEUS DICOM clips into time–intensity curves (TICs).

The functions in this module are framework agnostic so they can be reused by
Dash callbacks, command-line scripts, or tests. They cover loading DICOM data,
optional cropping, flash detection heuristics, ROI masking, and TIC
construction.
"""

from __future__ import annotations

import base64
import dataclasses
import io
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pydicom
from pydicom.pixel_data_handlers.util import apply_modality_lut
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, savgol_filter
from skimage.draw import polygon2mask


@dataclasses.dataclass
class DicomVideo:
    """Representation of a CEUS clip loaded from a DICOM file."""

    frames: np.ndarray  # shape: (n_frames, height, width)
    time: np.ndarray  # seconds, shape: (n_frames,)
    metadata: Dict[str, str]

    def as_uint8(self) -> np.ndarray:
        """Return a uint8 rendering of the frames suitable for display."""

        if self.frames.dtype == np.uint8:
            return self.frames

        # Normalize per video to preserve contrast.
        frame_min = float(self.frames.min())
        frame_max = float(self.frames.max())
        if math.isclose(frame_min, frame_max):
            return np.zeros_like(self.frames, dtype=np.uint8)

        scaled = (self.frames - frame_min) / (frame_max - frame_min)
        return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)


def _extract_time_vector(dataset: pydicom.Dataset, frames: np.ndarray) -> np.ndarray:
    """Infer frame timestamps in seconds."""

    n_frames = frames.shape[0]

    if "FrameTimeVector" in dataset:
        vector = np.asarray(dataset.FrameTimeVector, dtype=float) / 1000.0
        if vector.shape[0] == n_frames:
            return vector
    if "FrameTime" in dataset:
        frame_time = float(dataset.FrameTime) / 1000.0
        return np.arange(n_frames, dtype=float) * frame_time
    if "CineRate" in dataset:
        rate = float(dataset.CineRate)
        if rate > 0:
            return np.arange(n_frames, dtype=float) / rate

    # As a last resort, fall back to unit spacing and let callers know.
    return np.arange(n_frames, dtype=float)


def load_dicom_from_bytes(data: bytes) -> DicomVideo:
    """Load a CEUS multi-frame DICOM payload.

    Parameters
    ----------
    data:
        Raw DICOM file contents.
    """

    buffer = io.BytesIO(data)
    dataset = pydicom.dcmread(buffer, force=True)

    if not hasattr(dataset, "PixelData"):
        raise ValueError("Provided DICOM does not contain pixel data")

    frames = dataset.pixel_array
    frames = apply_modality_lut(frames, dataset).astype(np.float32)

    if frames.ndim == 4:
        # Handle color images by converting to grayscale via luminance.
        frames = 0.2126 * frames[..., 0] + 0.7152 * frames[..., 1] + 0.0722 * frames[..., 2]

    if frames.ndim != 3:
        raise ValueError(f"Unexpected frame array shape {frames.shape}")

    time_vector = _extract_time_vector(dataset, frames)

    metadata = {
        "PatientID": getattr(dataset, "PatientID", ""),
        "StudyDescription": getattr(dataset, "StudyDescription", ""),
        "SeriesDescription": getattr(dataset, "SeriesDescription", ""),
        "Manufacturer": getattr(dataset, "Manufacturer", ""),
    }

    return DicomVideo(frames=frames, time=time_vector, metadata=metadata)


def crop_frames(frames: np.ndarray, crop_box: Tuple[int, int, int, int]) -> np.ndarray:
    """Crop frames given a pixel-space bounding box (x0, y0, x1, y1)."""

    x0, y0, x1, y1 = crop_box
    x0 = max(int(x0), 0)
    y0 = max(int(y0), 0)
    x1 = min(int(x1), frames.shape[2])
    y1 = min(int(y1), frames.shape[1])
    if x0 >= x1 or y0 >= y1:
        raise ValueError("Invalid crop box")
    return frames[:, y0:y1, x0:x1]


def make_preset_crop(height: int, width: int, preset: str) -> Tuple[int, int, int, int]:
    """Return a crop box for known presets."""

    preset = preset.lower()
    if preset == "center":
        margin_y = int(height * 0.1)
        margin_x = int(width * 0.1)
        return (margin_x, margin_y, width - margin_x, height - margin_y)
    if preset == "ceus-only":
        # Example: assume CEUS is on left half of the screen.
        return (0, 0, width // 2, height)
    if preset == "bmode-only":
        return (width // 2, 0, width, height)

    raise ValueError(f"Unknown preset '{preset}'")


def frames_to_data_url(frame: np.ndarray) -> str:
    """Convert a single frame (2D array) into a base64 PNG data URI."""

    import PIL.Image

    array = frame.astype(np.float32)
    array -= array.min()
    if array.max() > 0:
        array /= array.max()
    array = (array * 255).astype(np.uint8)
    image = PIL.Image.fromarray(array)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def ndarray_to_base64(array: np.ndarray) -> str:
    """Serialize an ndarray into a base64-encoded npy payload."""

    buffer = io.BytesIO()
    np.save(buffer, array)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return encoded


def base64_to_ndarray(payload: str) -> np.ndarray:
    buffer = io.BytesIO(base64.b64decode(payload.encode("ascii")))
    return np.load(buffer, allow_pickle=False)


def compute_intensity_trace(frames: np.ndarray, percentile: float = 95.0) -> np.ndarray:
    """Aggregate per-frame intensity to a 1D trace."""

    if frames.size == 0:
        return np.array([])
    if percentile == 50.0:
        return np.median(frames.reshape(frames.shape[0], -1), axis=1)
    flat = frames.reshape(frames.shape[0], -1)
    return np.percentile(flat, percentile, axis=1)


def detect_flash_indices(intensity: np.ndarray, distance: int = 5, prominence: float = 5.0) -> List[int]:
    """Return candidate flash indices based on the derivative of the intensity trace."""

    if intensity.size == 0:
        return []

    diff = np.diff(intensity, prepend=intensity[0])
    smooth = savgol_filter(diff, window_length=min(len(diff) // 2 * 2 + 1, 11), polyorder=2)
    peaks, _ = find_peaks(np.abs(smooth), distance=distance, prominence=prominence)
    return peaks.tolist()


def mask_from_polygon(points: Sequence[Dict[str, float]], shape: Tuple[int, int]) -> np.ndarray:
    """Create a boolean mask from polygon points."""

    if not points:
        raise ValueError("Polygon has no points")
    rows = [point["y"] for point in points]
    cols = [point["x"] for point in points]
    mask = polygon2mask(shape, np.column_stack([rows, cols]))
    return mask


def compute_tic_dataframe(
    frames: np.ndarray,
    time: np.ndarray,
    roi_masks: Dict[str, np.ndarray],
    smoothing_window: int = 5,
) -> pd.DataFrame:
    """Compute raw and filtered TICs for each ROI."""

    if not roi_masks:
        raise ValueError("No ROI masks supplied")

    data: Dict[str, np.ndarray] = {"time": time.astype(float)}

    for key, mask in roi_masks.items():
        if mask.shape != frames.shape[1:]:
            raise ValueError(f"Mask for {key} has incorrect shape {mask.shape}")

        mask_indices = np.where(mask)
        if len(mask_indices[0]) == 0:
            raise ValueError(f"Mask for {key} is empty")

        raw = frames[:, mask] if mask.dtype == bool else frames[:, mask.astype(bool)]
        raw_mean = raw.mean(axis=1)
        data[key] = raw_mean

        # Median filter for noise suppression, then small Savitzky-Golay smoothing.
        filtered = median_filter(raw_mean, size=max(1, smoothing_window))
        if len(raw_mean) >= 7:
            filtered = savgol_filter(filtered, window_length=min(len(raw_mean) // 2 * 2 + 1, 11), polyorder=2)
        data[f"{key}_filt"] = filtered

    df = pd.DataFrame(data)
    column_order = ["time"]
    for roi in roi_masks.keys():
        column_order.extend([roi, f"{roi}_filt"])
    return df[column_order]


def export_tic_csv(df: pd.DataFrame, path: str) -> None:
    """Persist TIC data to disk."""

    df.to_csv(path, index=False)


def time_axis_summary(time: np.ndarray) -> Dict[str, float]:
    """Provide diagnostic stats for the time axis."""

    if time.size == 0:
        return {"frames": 0, "duration": 0.0, "frame_interval": 0.0}
    return {
        "frames": int(time.size),
        "duration": float(time.max() - time.min()),
        "frame_interval": float(np.median(np.diff(time))) if time.size > 1 else 0.0,
    }
