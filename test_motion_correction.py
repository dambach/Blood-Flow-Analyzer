"""
Test Motion Correction for CEUS Analyzer
Loads data/00010230, applies LOGIC crop, then motion correction
"""

import sys
import time
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

# Import the app
from napari_ceus_app import CEUSAnalyzer

def test_motion_correction():
    """Test motion correction workflow"""
    print("\n" + "="*70)
    print("TEST: Motion Correction with LOGIC crop")
    print("="*70 + "\n")
    
    # Create app
    app = CEUSAnalyzer()
    
    # Step 1: Load DICOM with LOGIC preset
    app.crop_preset = "LOGIC"
    dicom_path = Path("data/00010230")
    
    print(f"Step 1: Loading {dicom_path} with LOGIC crop...")
    app.load_and_process(dicom_path)
    time.sleep(2)
    
    if app.frames_cropped is None:
        print("❌ Failed to load frames")
        return False
    
    print(f"✅ Loaded {app.frames_cropped.shape[0]} frames")
    print(f"   Shape: {app.frames_cropped.shape}")
    
    # Step 2: Apply motion correction
    print(f"\nStep 2: Applying motion correction...")
    print(f"   Reference frame: {app.flash_frame_idx}")
    
    # Store original frames for comparison
    frames_before = app.frames_cropped.copy()
    
    # Apply correction
    app.apply_motion_correction()
    time.sleep(2)
    
    frames_after = app.frames_cropped
    
    if frames_after is None:
        print("❌ Motion correction failed")
        return False
    
    print(f"✅ Motion correction complete")
    
    # Step 3: Verify motion correction worked
    print(f"\nStep 3: Verification...")
    
    # Check that frames changed
    if np.allclose(frames_before, frames_after):
        print("⚠️  Warning: Frames unchanged (may indicate no motion)")
    else:
        diff = np.abs(frames_before - frames_after).mean()
        print(f"✅ Frames modified (mean diff: {diff:.2f})")
    
    # Check for shift log file
    import glob
    shift_files = glob.glob("Motion_Shifts_*.csv")
    if shift_files:
        latest_shift = sorted(shift_files)[-1]
        print(f"✅ Shift log created: {latest_shift}")
        
        # Read and display statistics
        import pandas as pd
        df = pd.read_csv(latest_shift)
        print(f"\n📊 Motion Statistics:")
        print(f"   • Frames: {len(df)}")
        print(f"   • Max Y shift: {df['Shift_Y'].abs().max():.2f} px")
        print(f"   • Max X shift: {df['Shift_X'].abs().max():.2f} px")
        print(f"   • Mean Y shift: {df['Shift_Y'].abs().mean():.2f} px")
        print(f"   • Mean X shift: {df['Shift_X'].abs().mean():.2f} px")
        
        # Plot shifts
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6))
        ax1.plot(df['Frame'], df['Shift_Y'], 'b-', label='Y shift')
        ax1.set_ylabel('Y Shift (pixels)')
        ax1.set_title('Motion Correction Shifts')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        ax2.plot(df['Frame'], df['Shift_X'], 'r-', label='X shift')
        ax2.set_xlabel('Frame')
        ax2.set_ylabel('X Shift (pixels)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plot_file = f"Motion_Shifts_Plot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(plot_file, dpi=150)
        print(f"   • Plot saved: {plot_file}")
        plt.close()
    
    print(f"\n✅ SUCCESS: Motion correction test complete!")
    print(f"\n🎬 Launching viewer for visual inspection...")
    print(f"   (All ROIs should now be more stable across frames)")
    
    # Run the viewer
    app.run()
    
    return True

if __name__ == "__main__":
    success = test_motion_correction()
    sys.exit(0 if success else 1)
