"""
Test YCbCr to RGB conversion for DICOM
"""

import napari
import numpy as np
import pydicom
from pathlib import Path
from pydicom.pixel_data_handlers.util import apply_color_lut

def ycbcr_to_rgb(ycbcr):
    """
    Convert YCbCr (YBR_FULL_422) to RGB
    Y: luminance, Cb: blue-difference, Cr: red-difference
    """
    # Conversion matrix from YCbCr to RGB
    # Standard ITU-R BT.601 conversion
    y = ycbcr[:, :, 0].astype(float)
    cb = ycbcr[:, :, 1].astype(float)
    cr = ycbcr[:, :, 2].astype(float)
    
    # Convert to RGB
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    
    # Clip to valid range
    r = np.clip(r, 0, 255)
    g = np.clip(g, 0, 255)
    b = np.clip(b, 0, 255)
    
    # Stack into RGB image
    rgb = np.stack([r, g, b], axis=-1)
    
    return rgb.astype(np.uint8)

def test_ycbcr_conversion():
    """Test YCbCr to RGB conversion"""
    
    # Load DICOM
    dicom_path = Path("data/dicom_file")
    print(f"Loading DICOM from: {dicom_path}")
    
    # Method 1: Let pydicom handle it
    print("\n=== Method 1: Pydicom automatic conversion ===")
    ds = pydicom.dcmread(str(dicom_path), force=True)
    print(f"PhotometricInterpretation: {ds.PhotometricInterpretation}")
    
    # Try to convert automatically
    if ds.PhotometricInterpretation == "YBR_FULL_422" or ds.PhotometricInterpretation == "YBR_FULL":
        # Get pixel array (pydicom should auto-convert)
        pixel_array = ds.pixel_array
        print(f"Original shape: {pixel_array.shape}")
        print(f"Original dtype: {pixel_array.dtype}")
        print(f"Original range: [{pixel_array.min()}, {pixel_array.max()}]")
    
    # Method 2: Manual conversion
    print("\n=== Method 2: Manual YCbCr to RGB conversion ===")
    
    # Extract first frame
    if pixel_array.ndim == 4:
        first_frame_ycbcr = pixel_array[0, :, :, :]
    else:
        first_frame_ycbcr = pixel_array
    
    print(f"First frame shape: {first_frame_ycbcr.shape}")
    print(f"First frame Y channel range: [{first_frame_ycbcr[:,:,0].min()}, {first_frame_ycbcr[:,:,0].max()}]")
    print(f"First frame Cb channel range: [{first_frame_ycbcr[:,:,1].min()}, {first_frame_ycbcr[:,:,1].max()}]")
    print(f"First frame Cr channel range: [{first_frame_ycbcr[:,:,2].min()}, {first_frame_ycbcr[:,:,2].max()}]")
    
    # Convert to RGB
    first_frame_rgb = ycbcr_to_rgb(first_frame_ycbcr)
    print(f"After conversion - RGB shape: {first_frame_rgb.shape}")
    print(f"After conversion - RGB dtype: {first_frame_rgb.dtype}")
    print(f"After conversion - R range: [{first_frame_rgb[:,:,0].min()}, {first_frame_rgb[:,:,0].max()}]")
    print(f"After conversion - G range: [{first_frame_rgb[:,:,1].min()}, {first_frame_rgb[:,:,1].max()}]")
    print(f"After conversion - B range: [{first_frame_rgb[:,:,2].min()}, {first_frame_rgb[:,:,2].max()}]")
    
    # Create viewer
    viewer = napari.Viewer(title="YCbCr to RGB Conversion Test")
    
    # Display original YCbCr as if it were RGB (will look wrong - greenish)
    viewer.add_image(
        first_frame_ycbcr,
        name="1. Original YCbCr (displayed as RGB - WRONG)",
        rgb=True
    )
    
    # Display converted RGB (should look correct)
    viewer.add_image(
        first_frame_rgb,
        name="2. Converted to RGB (CORRECT)",
        rgb=True
    )
    
    # Display Y channel only (grayscale)
    viewer.add_image(
        first_frame_ycbcr[:, :, 0],
        name="3. Y channel only (luminance)",
        colormap="gray"
    )
    
    print("\n=== Opening Napari viewer ===")
    print("Image #2 'Converted to RGB' should show correct colors!")
    
    napari.run()

if __name__ == "__main__":
    test_ycbcr_conversion()
