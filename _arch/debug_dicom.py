"""Utility script to inspect CEUS DICOM clips outside the Dash UI.

Run with::

    python debug_dicom.py data/dicom_file --frame 0 --save first_frame.png

This will print summary statistics about the clip and optionally dump the
selected frame as a PNG to help diagnose display issues.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from python_app.processing import load_dicom_from_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a CEUS DICOM clip")
    parser.add_argument("dicom_path", type=Path, help="Path to the DICOM file")
    parser.add_argument(
        "--frame",
        type=int,
        default=0,
        help="Index of the frame to inspect/save (default: 0)",
    )
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="Optional path to save the selected frame as a PNG",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.dicom_path.open("rb") as handle:
        video = load_dicom_from_bytes(handle.read())

    frames = video.frames
    frame_index = int(np.clip(args.frame, 0, frames.shape[0] - 1))
    frame = frames[frame_index]

    print(f"Loaded {args.dicom_path}")
    print(f"Frames: {frames.shape[0]}, height: {frames.shape[1]}, width: {frames.shape[2]}")
    print(f"Time span: {video.time[0]:.3f}s → {video.time[-1]:.3f}s")
    print(
        "Frame statistics (raw): min={:.3f}, max={:.3f}, mean={:.3f}".format(
            float(frame.min()), float(frame.max()), float(frame.mean())
        )
    )

    uint8_frame = video.as_uint8()[frame_index]
    print(
        "Frame statistics (uint8): min={:.0f}, max={:.0f}, mean={:.1f}".format(
            float(uint8_frame.min()), float(uint8_frame.max()), float(uint8_frame.mean())
        )
    )

    if args.save:
        from PIL import Image

        Image.fromarray(uint8_frame).save(args.save)
        print(f"Saved frame {frame_index} to {args.save}")


if __name__ == "__main__":
    main()


