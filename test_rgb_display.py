"""
Test script to understand RGB data format in DICOM and how to display it in Napari
"""

import napari
import numpy as np
import pydicom
from pathlib import Path

def test_dicom_rgb():
    """Test loading and displaying DICOM RGB data"""
    
    # Load DICOM
    dicom_path = Path("data/dicom_file")
    print(f"Loading DICOM from: {dicom_path}")
    
    ds = pydicom.dcmread(str(dicom_path), force=True)
    pixel_array = ds.pixel_array
    
    print(f"\n=== DICOM Pixel Array Info ===")
    print(f"Shape: {pixel_array.shape}")
    print(f"Dtype: {pixel_array.dtype}")
    print(f"Min value: {pixel_array.min()}")
    print(f"Max value: {pixel_array.max()}")
    print(f"Mean value: {pixel_array.mean():.2f}")
    
    # Extract first frame
    if pixel_array.ndim == 4:
        first_frame = pixel_array[0, :, :, :]
        print(f"\n=== First Frame Info ===")
        print(f"Shape: {first_frame.shape}")
        print(f"Dtype: {first_frame.dtype}")
        print(f"Min: {first_frame.min()}, Max: {first_frame.max()}")
        
        # Check each channel
        if first_frame.shape[-1] == 3:
            print(f"\nChannel 0 (R): min={first_frame[:,:,0].min()}, max={first_frame[:,:,0].max()}, mean={first_frame[:,:,0].mean():.2f}")
            print(f"Channel 1 (G): min={first_frame[:,:,1].min()}, max={first_frame[:,:,1].max()}, mean={first_frame[:,:,1].mean():.2f}")
            print(f"Channel 2 (B): min={first_frame[:,:,2].min()}, max={first_frame[:,:,2].max()}, mean={first_frame[:,:,2].mean():.2f}")
    else:
        first_frame = pixel_array[0] if pixel_array.ndim == 3 else pixel_array
        print(f"\n=== First Frame Info ===")
        print(f"Shape: {first_frame.shape}")
        print(f"Dtype: {first_frame.dtype}")
        print(f"Min: {first_frame.min()}, Max: {first_frame.max()}")
    
    # Create viewer
    viewer = napari.Viewer(title="DICOM RGB Test")
    
    # Test 1: Display as-is
    print("\n=== Test 1: Display as-is ===")
    if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
        viewer.add_image(
            first_frame,
            name="1. As-is (RGB)",
            rgb=True
        )
    
    # Test 2: Convert to uint8 if needed
    print("\n=== Test 2: Convert to uint8 ===")
    if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
        if first_frame.max() > 1.0:
            frame_uint8 = first_frame.astype(np.uint8)
            print(f"Converted to uint8: min={frame_uint8.min()}, max={frame_uint8.max()}")
            viewer.add_image(
                frame_uint8,
                name="2. uint8 (RGB)",
                rgb=True
            )
        else:
            print("Already in 0-1 range, skipping")
    
    # Test 3: Normalize to 0-255 then uint8
    print("\n=== Test 3: Normalize to 0-255 ===")
    if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
        frame_norm = (first_frame - first_frame.min()) / (first_frame.max() - first_frame.min() + 1e-8)
        frame_norm = (frame_norm * 255).astype(np.uint8)
        print(f"Normalized: min={frame_norm.min()}, max={frame_norm.max()}")
        viewer.add_image(
            frame_norm,
            name="3. Normalized 0-255 (RGB)",
            rgb=True
        )
    
    # Test 4: Grayscale conversion
    print("\n=== Test 4: Grayscale ===")
    if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
        # RGB to grayscale: 0.299*R + 0.587*G + 0.114*B
        gray = 0.299 * first_frame[:,:,0] + 0.587 * first_frame[:,:,1] + 0.114 * first_frame[:,:,2]
        print(f"Grayscale: min={gray.min()}, max={gray.max()}")
        viewer.add_image(
            gray,
            name="4. Grayscale (inferno)",
            colormap="inferno"
        )
    
    # Test 5: Display each channel separately
    print("\n=== Test 5: Individual channels ===")
    if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
        viewer.add_image(
            first_frame[:,:,0],
            name="5a. Red channel",
            colormap="red"
        )
        viewer.add_image(
            first_frame[:,:,1],
            name="5b. Green channel",
            colormap="green"
        )
        viewer.add_image(
            first_frame[:,:,2],
            name="5c. Blue channel",
            colormap="blue"
        )
    
    print("\n=== Opening Napari viewer ===")
    print("Compare the different display methods to see which looks correct!")
    napari.run()

if __name__ == "__main__":
    test_dicom_rgb()
