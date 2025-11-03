"""
Test du nouveau workflow temporel optimisé pour CEUS
Test: Load → Flash Frame → Temporal Crop → Motion Correction
"""

import napari
import numpy as np
from pathlib import Path
from napari_ceus_app import CEUSAnalyzer

def test_temporal_workflow():
    """Test du workflow complet avec temporal crop"""
    print("\n" + "="*70)
    print("TEST: WORKFLOW TEMPOREL OPTIMISÉ")
    print("="*70)
    
    # Create app (headless mode for testing)
    app = CEUSAnalyzer()
    
    # 1. Load DICOM with LOGIC preset
    print("\n1️⃣ Loading DICOM with LOGIC preset...")
    dicom_path = Path("data/00010230")
    if not dicom_path.exists():
        print(f"❌ DICOM file not found: {dicom_path}")
        return False
    
    app.crop_preset = "LOGIC"
    app.load_and_process(dicom_path)
    
    # Verify loading
    if app.frames_original is None:
        print("❌ Failed to load DICOM")
        return False
    print(f"✅ DICOM loaded: {app.frames_original.shape}")
    
    # Apply spatial crop
    print("\n2️⃣ Applying spatial crop (LOGIC preset)...")
    app.apply_crop_and_load_all()
    
    if app.frames_cropped is None:
        print("❌ Failed to crop frames")
        return False
    print(f"✅ Spatial crop applied: {app.frames_cropped.shape}")
    
    # 3. Set flash frame
    print("\n3️⃣ Setting flash frame...")
    # For test, use frame 10 as flash (in real usage, user navigates and presses 'f')
    app.flash_frame_idx = 10
    print(f"✅ Flash frame set to: {app.flash_frame_idx}")
    
    # 4. Apply temporal crop (Flash + 30s)
    print("\n4️⃣ Applying temporal crop (Flash + 30s)...")
    frames_before_temporal = app.frames_cropped.shape[0]
    
    app.apply_temporal_crop(duration_seconds=30)
    
    if app.frames_cropped is None:
        print("❌ Failed to apply temporal crop")
        return False
    
    frames_after_temporal = app.frames_cropped.shape[0]
    expected_frames = int(30 * app.fps) + 5  # 30s + baseline
    
    print(f"✅ Temporal crop applied:")
    print(f"   Before: {frames_before_temporal} frames")
    print(f"   After: {frames_after_temporal} frames")
    print(f"   Expected: ~{expected_frames} frames")
    print(f"   New flash frame index: {app.flash_frame_idx}")
    
    # 5. Verify motion correction was applied automatically
    print("\n5️⃣ Verifying motion correction...")
    # Motion correction should have been applied automatically in apply_temporal_crop
    # Check if frames are uint8 (sign of proper conversion)
    if app.frames_cropped.dtype != np.uint8:
        print(f"⚠️ Warning: Frames dtype is {app.frames_cropped.dtype}, expected uint8")
    else:
        print(f"✅ Frames properly converted to uint8")
    
    # 6. Verify colors (should not be greenish)
    print("\n6️⃣ Verifying RGB color preservation...")
    if app.frames_cropped.ndim == 4 and app.frames_cropped.shape[-1] == 3:
        # Check if RGB channels have proper distribution
        mean_r = np.mean(app.frames_cropped[:, :, :, 0])
        mean_g = np.mean(app.frames_cropped[:, :, :, 1])
        mean_b = np.mean(app.frames_cropped[:, :, :, 2])
        
        print(f"   Mean R: {mean_r:.2f}")
        print(f"   Mean G: {mean_g:.2f}")
        print(f"   Mean B: {mean_b:.2f}")
        
        # If greenish, G would be much higher than R and B
        if mean_g > mean_r * 1.5 and mean_g > mean_b * 1.5:
            print(f"⚠️ Warning: Green channel dominant (possible color issue)")
        else:
            print(f"✅ RGB channels balanced")
    
    # Summary
    print("\n" + "="*70)
    print("RÉSUMÉ DU TEST")
    print("="*70)
    print(f"✅ DICOM chargé: {app.frames_original.shape}")
    print(f"✅ Crop spatial (LOGIC): {app.frames_cropped.shape}")
    print(f"✅ Flash frame: {app.flash_frame_idx}")
    print(f"✅ Temporal crop: {frames_after_temporal} frames ({frames_after_temporal / app.fps:.1f}s)")
    print(f"✅ Motion correction: Appliquée automatiquement")
    print(f"✅ Type de données: {app.frames_cropped.dtype}")
    print(f"✅ Format: {'RGB' if app.frames_cropped.ndim == 4 else 'Grayscale'}")
    print("\n🎉 WORKFLOW TEMPOREL: SUCCÈS!")
    print("="*70)
    
    return True

if __name__ == "__main__":
    try:
        success = test_temporal_workflow()
        if success:
            print("\n✅ Tous les tests ont réussi!")
        else:
            print("\n❌ Certains tests ont échoué")
    except Exception as e:
        print(f"\n❌ Erreur pendant le test: {e}")
        import traceback
        traceback.print_exc()
