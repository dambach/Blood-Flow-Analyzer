"""Simple disk-backed cache for large NumPy arrays used by the Dash app."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

import numpy as np


CACHE_ROOT = Path(tempfile.gettempdir()) / "blood_flow_analyzer_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _path_for(identifier: str) -> Path:
    return CACHE_ROOT / f"{identifier}.npy"


def save_array(array: np.ndarray) -> str:
    identifier = uuid.uuid4().hex
    path = _path_for(identifier)
    np.save(path, array, allow_pickle=False)
    return identifier


def load_array(identifier: str) -> np.ndarray:
    path = _path_for(identifier)
    if not path.exists():
        raise FileNotFoundError(f"Cached array {identifier} not found")
    return np.load(path, allow_pickle=False)


def delete_array(identifier: str) -> None:
    path = _path_for(identifier)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def clear_cache(prefix: str = "") -> None:
    for file in CACHE_ROOT.glob(f"{prefix}*.npy"):
        try:
            file.unlink()
        except FileNotFoundError:
            continue

