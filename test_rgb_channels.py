"""
Test script to check RGB channel order in DICOM
"""

import napari
import numpy as np
import pydicom
from pathlib import Path

def test_channel_order():
    """Test different channel orders to find the correct one"""
    
    # Load DICOM
    dicom_path = Path("data/dicom_file")
    print(f"Loading DICOM from: {dicom_path}")
    
    ds = pydicom.dcmread(str(dicom_path), force=True)
    pixel_array = ds.pixel_array
    
    print(f"\n=== DICOM Info ===")
    print(f"Shape: {pixel_array.shape}")
    print(f"Dtype: {pixel_array.dtype}")
    print(f"Min: {pixel_array.min()}, Max: {pixel_array.max()}")
    
    # Check PhotometricInterpretation
    if hasattr(ds, 'PhotometricInterpretation'):
        print(f"PhotometricInterpretation: {ds.PhotometricInterpretation}")
    
    # Extract first frame
    if pixel_array.ndim == 4:
        first_frame = pixel_array[0, :, :, :]
    else:
        first_frame = pixel_array[0] if pixel_array.ndim == 3 else pixel_array
    
    print(f"\nFirst frame shape: {first_frame.shape}")
    print(f"First frame dtype: {first_frame.dtype}")
    
    if first_frame.ndim != 3 or first_frame.shape[-1] != 3:
        print("Not an RGB image!")
        return
    
    # Create viewer
    viewer = napari.Viewer(title="Channel Order Test")
    
    # Test different channel orders
    print("\n=== Testing different channel orders ===")
    
    # 1. RGB (original order)
    viewer.add_image(
        first_frame,
        name="1. RGB (original)",
        rgb=True
    )
    
    # 2. BGR (swap R and B)
    frame_bgr = first_frame[:, :, [2, 1, 0]]
    viewer.add_image(
        frame_bgr,
        name="2. BGR (swapped R<->B)",
        rgb=True
    )
    
    # 3. RBG (swap G and B)
    frame_rbg = first_frame[:, :, [0, 2, 1]]
    viewer.add_image(
        frame_rbg,
        name="3. RBG (swapped G<->B)",
        rgb=True
    )
    
    # 4. GRB (cyclic shift)
    frame_grb = first_frame[:, :, [1, 0, 2]]
    viewer.add_image(
        frame_grb,
        name="4. GRB (G,R,B order)",
        rgb=True
    )
    
    # 5. GBR (another cyclic shift)
    frame_gbr = first_frame[:, :, [1, 2, 0]]
    viewer.add_image(
        frame_gbr,
        name="5. GBR (G,B,R order)",
        rgb=True
    )
    
    # 6. BRG (another swap)
    frame_brg = first_frame[:, :, [2, 0, 1]]
    viewer.add_image(
        frame_brg,
        name="6. BRG (B,R,G order)",
        rgb=True
    )
    
    # Also test with normalization
    print("\n=== Testing with normalization ===")
    
    # Normalize to 0-255
    first_norm = (first_frame - first_frame.min()) / (first_frame.max() - first_frame.min() + 1e-8)
    first_norm = (first_norm * 255).astype(np.uint8)
    
    viewer.add_image(
        first_norm,
        name="7. RGB normalized (0-255)",
        rgb=True
    )
    
    frame_bgr_norm = first_norm[:, :, [2, 1, 0]]
    viewer.add_image(
        frame_bgr_norm,
        name="8. BGR normalized (0-255)",
        rgb=True
    )
    
    print("\n=== Opening Napari viewer ===")
    print("Look for the image that shows correct colors (not all green/cyan)!")
    print("The image should show ultrasound with proper color representation.")
    
    napari.run()

if __name__ == "__main__":
    test_channel_order()
