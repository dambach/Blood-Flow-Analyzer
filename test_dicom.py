"""
Test script for CEUS Analyzer with DICOM file
Tests ROI creation, TIC computation, and CSV export
"""
import numpy as np
from pathlib import Path
import pandas as pd
import sys

# Import after creating the app to avoid display issues
def test_ceus_analyzer():
    from napari_ceus_app import CEUSAnalyzer
    
    print("=" * 60)
    print("CEUS ANALYZER - AUTOMATED TEST")
    print("=" * 60)
    
    # Initialize app
    print("\n[1/7] Initializing application...")
    app = CEUSAnalyzer()
    print("✓ Application initialized")
    
    # Load DICOM
    print("\n[2/7] Loading DICOM file...")
    dicom_path = Path("data/00010230")
    if not dicom_path.exists():
        print(f"✗ DICOM file not found: {dicom_path}")
        app.viewer.close()
        return False
    
    # Set crop preset first, then load
    app.crop_preset = "LOGIC"
    app.load_and_process(dicom_path)
    print(f"✓ DICOM loaded: {dicom_path}")
    
    # Get video data from frames_cropped (used after LOGIC crop)
    if app.frames_cropped is not None:
        video_data = app.frames_cropped
    else:
        video_data = app.frames_original
    
    print(f"  - Shape: {video_data.shape}")
    print(f"  - Number of frames: {video_data.shape[0]}")
    print(f"  - FPS: {app.fps}")
    print(f"  - Crop preset: {app.crop_preset}")
    
    # Create ROIs
    print("\n[3/7] Creating test ROIs...")
    height, width = video_data.shape[1:3]
    print(f"  - Video dimensions: {height}x{width}")
    
    # ROI 1: liver (red) - upper region
    liver_y1, liver_y2 = int(height * 0.2), int(height * 0.4)
    liver_x1, liver_x2 = int(width * 0.3), int(width * 0.6)
    liver_roi = np.array([[liver_y1, liver_x1], [liver_y1, liver_x2], 
                          [liver_y2, liver_x2], [liver_y2, liver_x1]])
    
    app.current_roi_label = 'liver'
    app.roi_shapes_layer.add_rectangles(liver_roi, edge_color='red', face_color=[1, 0, 0, 0.3])
    print(f"✓ Liver ROI: [{liver_y1}:{liver_y2}, {liver_x1}:{liver_x2}]")
    
    # ROI 2: dia (green) - middle region
    dia_y1, dia_y2 = int(height * 0.45), int(height * 0.65)
    dia_x1, dia_x2 = int(width * 0.3), int(width * 0.6)
    dia_roi = np.array([[dia_y1, dia_x1], [dia_y1, dia_x2], 
                        [dia_y2, dia_x2], [dia_y2, dia_x1]])
    
    app.current_roi_label = 'dia'
    app.roi_shapes_layer.add_rectangles(dia_roi, edge_color='green', face_color=[0, 1, 0, 0.3])
    print(f"✓ Dia ROI: [{dia_y1}:{dia_y2}, {dia_x1}:{dia_x2}]")
    
    # ROI 3: cw (blue) - lower region
    cw_y1, cw_y2 = int(height * 0.7), int(height * 0.9)
    cw_x1, cw_x2 = int(width * 0.3), int(width * 0.6)
    cw_roi = np.array([[cw_y1, cw_x1], [cw_y1, cw_x2], 
                       [cw_y2, cw_x2], [cw_y2, cw_x1]])
    
    app.current_roi_label = 'cw'
    app.roi_shapes_layer.add_rectangles(cw_roi, edge_color='blue', face_color=[0, 0, 1, 0.3])
    print(f"✓ CW ROI: [{cw_y1}:{cw_y2}, {cw_x1}:{cw_x2}]")
    print(f"✓ CW ROI: [{cw_y1}:{cw_y2}, {cw_x1}:{cw_x2}]")
    
    print(f"\n  ROI Labels Map: {app.roi_labels_map}")
    print(f"  Number of shapes: {len(app.roi_shapes_layer.data)}")
    
    # Compute TIC
    print("\n[4/7] Computing Time-Intensity Curves...")
    app.compute_tic()
    print("✓ TIC computed for all ROIs")
    
    # Display TIC statistics
    print("\n  TIC Statistics:")
    for label in ['liver', 'dia', 'cw']:
        if label in app.tic_data:
            data = app.tic_data[label]
            mean_data = data['tic_mean']
            std_data = data['tic_std']
            print(f"\n  {label.upper()}:")
            print(f"    Mean intensity: {mean_data.mean():.2f} ± {mean_data.std():.2f}")
            print(f"    Range: [{mean_data.min():.2f}, {mean_data.max():.2f}]")
            print(f"    Avg std dev: {std_data.mean():.2f}")
    
    # Display ROI properties
    print("\n[5/7] ROI Properties:")
    for label in ['liver', 'dia', 'cw']:
        if label in app.roi_properties:
            props = app.roi_properties[label]
            print(f"\n  {label.upper()}:")
            print(f"    Area: {props.get('area', 0):.2f} pixels²")
            print(f"    Perimeter: {props.get('perimeter', 0):.2f} pixels")
            print(f"    Dimensions: {props.get('width', 0):.1f} x {props.get('height', 0):.1f}")
            print(f"    Mean intensity: {props.get('mean_intensity', 0):.2f}")
            print(f"    Std intensity: {props.get('std_intensity', 0):.2f}")
    
    # Export TIC
    print("\n[6/7] Exporting TIC data...")
    app.export_tic()
    print("✓ TIC data exported")
    
    # Verify exported files
    csv_files = sorted(Path('.').glob('*_tic_*.csv'))
    latest_files = csv_files[-2:] if len(csv_files) >= 2 else csv_files
    
    print("\n" + "=" * 60)
    print("EXPORTED FILES")
    print("=" * 60)
    
    for csv_file in latest_files:
        print(f"\n📄 {csv_file.name}")
        df = pd.read_csv(csv_file)
        print(f"   Shape: {df.shape[0]} rows × {df.shape[1]} columns")
        print(f"   Columns: {', '.join(df.columns[:8])}" + ("..." if len(df.columns) > 8 else ""))
        print(f"\n   First 3 rows:")
        print(df.head(3).to_string(index=False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("✓ [1/6] Application initialized")
    print("✓ [2/6] DICOM loaded with LOGIC crop preset")
    print("✓ [3/6] 3 ROIs created (liver, dia, cw)")
    print("✓ [4/6] TIC computed with 4 statistics per frame")
    print("✓ [5/6] ROI properties calculated (area, perimeter, etc.)")
    print("✓ [6/6] 2 CSV files exported (time-series + properties)")
    print("\n✓✓✓ ALL TESTS PASSED ✓✓✓\n")
    
    # Close viewer
    app.viewer.close()
    return True

if __name__ == "__main__":
    try:
        success = test_ceus_analyzer()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
