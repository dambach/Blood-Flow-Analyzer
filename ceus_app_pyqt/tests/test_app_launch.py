"""
Test script to verify application functionality
"""
import sys
from pathlib import Path

# Add src to path
app_dir = Path(__file__).parent.parent
sys.path.insert(0, str(app_dir))

from src.core import DICOMLoader
import numpy as np


def test_dicom_loading():
    """Test DICOM loading with sample file"""
    print("=" * 60)
    print("Testing DICOM Loading")
    print("=" * 60)
    
    # Use example DICOM
    data_dir = app_dir.parent / "data"
    dicom_options = [
        data_dir / "a_aixplorerdcm",
        data_dir / "b_00010230",
    ]
    
    for dicom_path in dicom_options:
        if dicom_path.exists():
            print(f"\n✅ Found DICOM: {dicom_path.name}")
            
            try:
                loader = DICOMLoader(dicom_path)
                bmode, ceus = loader.load()
                
                print(f"\n📊 Scanner Info:")
                print(f"  Manufacturer: {loader.scanner_info.get('Manufacturer', 'N/A')}")
                print(f"  Model: {loader.scanner_info.get('ManufacturerModelName', 'N/A')}")
                
                print(f"\n📐 Metadata:")
                print(f"  Rows: {loader.metadata.get('Rows')}")
                print(f"  Columns: {loader.metadata.get('Columns')}")
                print(f"  Number of Frames: {loader.metadata.get('NumberOfFrames')}")
                print(f"  Photometric Interpretation: {loader.metadata.get('PhotometricInterpretation')}")
                
                if bmode is not None:
                    print(f"\n🖼️  B-mode stack: {bmode.shape} (region {loader.bmode_region_idx})")
                else:
                    print(f"\n⚠️  No B-mode detected")
                
                if ceus is not None:
                    print(f"🎬 CEUS stack: {ceus.shape} (region {loader.ceus_region_idx})")
                    print(f"   FPS: {loader.get_fps():.2f}")
                else:
                    print(f"❌ No CEUS detected!")
                    return False
                
                print("\n✅ DICOM loading successful!")
                return True
                
            except Exception as e:
                print(f"\n❌ Error loading DICOM: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    print("\n⚠️  No DICOM files found in data directory")
    return False


def test_flash_detection():
    """Test flash detection"""
    from src.core import detect_flash_ceus_refined
    
    print("\n" + "=" * 60)
    print("Testing Flash Detection")
    print("=" * 60)
    
    # Create dummy CEUS stack
    n_frames = 100
    dummy_stack = np.random.rand(n_frames, 128, 128).astype(np.float32)
    
    # Simulate flash at frame 20
    dummy_stack[20:25] *= 3.0  # Bright flash
    dummy_stack[25:] *= 0.5  # Washout
    
    try:
        flash_idx, washout_idx = detect_flash_ceus_refined(dummy_stack, fps=10.0)
        print(f"\n📍 Flash detected at frame: {flash_idx}")
        print(f"📍 Washout detected at frame: {washout_idx}")
        print("✅ Flash detection successful!")
        return True
    except Exception as e:
        print(f"\n❌ Error in flash detection: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_preprocessing():
    """Test preprocessing"""
    from src.core import preprocess_ceus
    
    print("\n" + "=" * 60)
    print("Testing Preprocessing")
    print("=" * 60)
    
    # Create dummy stack
    dummy_stack = np.random.rand(50, 128, 128).astype(np.float32) * 255
    
    try:
        preprocessed = preprocess_ceus(
            dummy_stack,
            use_log=True,
            spatial_filter_size=3,
            temporal_filter_window=5
        )
        print(f"\n📊 Input shape: {dummy_stack.shape}")
        print(f"📊 Output shape: {preprocessed.shape}")
        print(f"📊 Input range: [{dummy_stack.min():.2f}, {dummy_stack.max():.2f}]")
        print(f"📊 Output range: [{preprocessed.min():.2f}, {preprocessed.max():.2f}]")
        print("✅ Preprocessing successful!")
        return True
    except Exception as e:
        print(f"\n❌ Error in preprocessing: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_motion_compensation():
    """Test motion compensation"""
    from src.core import motion_compensate
    
    print("\n" + "=" * 60)
    print("Testing Motion Compensation")
    print("=" * 60)
    
    # Create dummy stack with simulated motion
    n_frames = 30
    dummy_stack = np.zeros((n_frames, 128, 128), dtype=np.float32)
    
    # Create a moving object
    for i in range(n_frames):
        x = 40 + i
        y = 40 + i // 2
        dummy_stack[i, y:y+20, x:x+20] = 1.0
    
    try:
        compensated = motion_compensate(dummy_stack, use_bmode=False)
        print(f"\n📊 Input shape: {dummy_stack.shape}")
        print(f"📊 Output shape: {compensated.shape}")
        print("✅ Motion compensation successful!")
        return True
    except Exception as e:
        print(f"\n❌ Error in motion compensation: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧪 CEUS Analyzer - Functionality Tests")
    print("=" * 60)
    
    results = {
        "DICOM Loading": test_dicom_loading(),
        "Flash Detection": test_flash_detection(),
        "Preprocessing": test_preprocessing(),
        "Motion Compensation": test_motion_compensation(),
    }
    
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
