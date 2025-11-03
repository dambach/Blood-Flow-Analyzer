"""
Automated test script for CEUS Analyzer
Loads data/00010230 with LOGIC crop preset automatically
"""

import sys
import time
from pathlib import Path
import numpy as np

# Import the app
from napari_ceus_app import CEUSAnalyzer

def test_auto_load():
    """Test automatic loading with LOGIC preset"""
    print("\n" + "="*70)
    print("AUTOMATED TEST: Load data/00010230 with LOGIC crop")
    print("="*70 + "\n")
    
    # Create app
    app = CEUSAnalyzer()
    
    # Set LOGIC preset
    app.crop_preset = "LOGIC"
    
    # Load DICOM
    dicom_path = Path("data/00010230")
    
    print(f"Loading: {dicom_path}")
    print(f"Crop preset: {app.crop_preset}")
    
    try:
        app.load_and_process(dicom_path)
        
        # Wait for processing
        time.sleep(2)
        
        # Check results
        print("\n--- Test Results ---")
        print(f"✓ DICOM loaded: {app.dicom_path is not None}")
        print(f"✓ Frames loaded: {app.all_frames_loaded}")
        print(f"✓ Frames shape: {app.frames_cropped.shape if app.frames_cropped is not None else 'None'}")
        print(f"✓ FPS: {app.fps}")
        print(f"✓ YCbCr format: {app.is_ycbcr}")
        
        if app.frames_cropped is not None:
            print(f"\n✅ SUCCESS: {app.frames_cropped.shape[0]} frames loaded and cropped with LOGIC preset")
            print(f"   Cropped dimensions: {app.frames_cropped.shape[1]}x{app.frames_cropped.shape[2]} pixels")
        else:
            print("\n❌ FAILED: Frames not loaded")
            return False
        
        # Run the viewer
        print("\n🎬 Launching viewer... (close window to exit)")
        app.run()
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_auto_load()
    sys.exit(0 if success else 1)
