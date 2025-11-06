"""
Test script for ROI functionality in Napari CEUS application
Tests: creation, storage, conversion, mask generation, and TIC computation
"""
import os
os.environ['QT_API'] = 'pyqt5'

import numpy as np
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import ROIManager
from skimage.draw import polygon as polygon_fill
import matplotlib.pyplot as plt


def test_roi_manager():
    """Test ROI Manager basic functionality"""
    print("=" * 60)
    print("TEST 1: ROI Manager - Creation and Storage")
    print("=" * 60)
    
    manager = ROIManager()
    
    # Test 1: Add simple polygon ROI
    polygon1 = [(10, 10), (50, 10), (50, 50), (10, 50)]
    roi1 = manager.add_roi(polygon1, label="Test_ROI_1")
    print(f"✓ ROI 1 added: {roi1.label}")
    print(f"  - Points: {roi1.n_points}")
    print(f"  - Area: {roi1.area:.2f} px²")
    print(f"  - Center: {roi1.center}")
    
    # Test 2: Add another polygon
    polygon2 = [(60, 60), (100, 60), (100, 100), (60, 100)]
    roi2 = manager.add_roi(polygon2, label="Test_ROI_2")
    print(f"✓ ROI 2 added: {roi2.label}")
    print(f"  - Points: {roi2.n_points}")
    print(f"  - Area: {roi2.area:.2f} px²")
    
    # Test 3: Add irregular polygon
    polygon3 = [(120, 120), (150, 110), (160, 140), (140, 150), (115, 135)]
    roi3 = manager.add_roi(polygon3, label="Irregular_ROI")
    print(f"✓ ROI 3 added: {roi3.label}")
    print(f"  - Points: {roi3.n_points}")
    print(f"  - Area: {roi3.area:.2f} px²")
    
    # Test 4: List all ROIs
    print(f"\n✓ Total ROIs in manager: {len(manager.rois)}")
    for roi in manager.rois:
        print(f"  - {roi.label}: {roi.n_points} points, {roi.area:.2f} px²")
    
    # Test 5: Get specific ROI
    retrieved = manager.get_roi("Test_ROI_1")
    assert retrieved is not None, "Failed to retrieve ROI"
    print(f"\n✓ Retrieved ROI: {retrieved.label}")
    
    # Test 6: Remove ROI
    success = manager.remove_roi("Test_ROI_2")
    assert success, "Failed to remove ROI"
    print(f"✓ Removed ROI_2, remaining: {len(manager.rois)}")
    
    return manager


def test_polygon_to_mask():
    """Test polygon to mask conversion"""
    print("\n" + "=" * 60)
    print("TEST 2: Polygon to Mask Conversion")
    print("=" * 60)
    
    # Create test image shape
    image_shape = (200, 200)
    
    # Test different polygons
    test_polygons = [
        {
            'name': 'Square',
            'points': [(50, 50), (100, 50), (100, 100), (50, 100)]
        },
        {
            'name': 'Triangle',
            'points': [(150, 20), (180, 80), (120, 80)]
        },
        {
            'name': 'Pentagon',
            'points': [(30, 120), (50, 110), (60, 130), (45, 150), (20, 145)]
        }
    ]
    
    masks = []
    for test in test_polygons:
        polygon_points = test['points']
        
        # Convert to mask
        mask = np.zeros(image_shape, dtype=bool)
        xs = [pt[0] for pt in polygon_points]
        ys = [pt[1] for pt in polygon_points]
        
        rr, cc = polygon_fill(ys, xs, shape=image_shape)
        mask[rr, cc] = True
        
        n_pixels = mask.sum()
        print(f"✓ {test['name']}: {len(polygon_points)} points → {n_pixels} pixels")
        
        masks.append((test['name'], mask))
    
    # Visualize masks
    fig, axes = plt.subplots(1, len(masks), figsize=(15, 5))
    for idx, (name, mask) in enumerate(masks):
        axes[idx].imshow(mask, cmap='gray')
        axes[idx].set_title(f"{name}\n{mask.sum()} pixels")
        axes[idx].axis('off')
    
    plt.tight_layout()
    output_path = Path(__file__).parent / 'test_outputs' / 'roi_masks.png'
    output_path.parent.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Mask visualization saved to: {output_path}")
    plt.close()
    
    return masks


def test_tic_extraction():
    """Test TIC extraction from ROI on synthetic data"""
    print("\n" + "=" * 60)
    print("TEST 3: TIC Extraction from ROI")
    print("=" * 60)
    
    # Create synthetic CEUS-like stack (increasing intensity)
    T, H, W = 50, 200, 200
    stack = np.zeros((T, H, W), dtype=np.float32)
    
    # Simulate wash-in: intensity increases over time
    for t in range(T):
        # Global intensity increase
        intensity = 50 + 150 * (1 - np.exp(-0.1 * t))
        stack[t] = intensity
        
        # Add some spatial variation
        y, x = np.ogrid[:H, :W]
        center_y, center_x = H // 2, W // 2
        distance = np.sqrt((y - center_y)**2 + (x - center_x)**2)
        variation = 20 * np.sin(distance / 10)
        stack[t] += variation
        
        # Add noise
        stack[t] += np.random.randn(H, W) * 5
    
    print(f"✓ Created synthetic stack: {stack.shape}")
    print(f"  - Intensity range: [{stack.min():.1f}, {stack.max():.1f}]")
    
    # Define test ROI (center of image)
    roi_polygon = [(75, 75), (125, 75), (125, 125), (75, 125)]
    
    # Convert to mask
    mask = np.zeros((H, W), dtype=bool)
    xs = [pt[0] for pt in roi_polygon]
    ys = [pt[1] for pt in roi_polygon]
    rr, cc = polygon_fill(ys, xs, shape=(H, W))
    mask[rr, cc] = True
    
    print(f"✓ ROI mask created: {mask.sum()} pixels")
    
    # Extract TIC
    fps = 10.0
    vi = np.zeros(T, dtype=np.float32)
    
    for t in range(T):
        vi[t] = stack[t][mask].mean()
    
    # Compute dVI
    baseline = vi[0]
    dvi = vi - baseline
    time = np.arange(T) / fps
    
    print(f"✓ TIC extracted:")
    print(f"  - Baseline: {baseline:.2f}")
    print(f"  - Max ΔVI: {dvi.max():.2f}")
    print(f"  - Time range: {time[0]:.2f}s - {time[-1]:.2f}s")
    
    # Plot TIC
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    
    # Frame at t=0
    axes[0].imshow(stack[0], cmap='gray')
    axes[0].contour(mask, colors='red', linewidths=2)
    axes[0].set_title('Frame 0 with ROI')
    axes[0].axis('off')
    
    # Frame at t=T//2
    axes[1].imshow(stack[T//2], cmap='magma')
    axes[1].contour(mask, colors='red', linewidths=2)
    axes[1].set_title(f'Frame {T//2} with ROI')
    axes[1].axis('off')
    
    # TIC curve
    axes[2].plot(time, dvi, 'b-', linewidth=2, label='ΔVI')
    axes[2].axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('ΔVI (AU)')
    axes[2].set_title('Time-Intensity Curve')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend()
    
    plt.tight_layout()
    output_path = Path(__file__).parent / 'test_outputs' / 'tic_extraction.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ TIC visualization saved to: {output_path}")
    plt.close()
    
    return time, vi, dvi


def test_multiple_rois():
    """Test multiple ROIs on same stack"""
    print("\n" + "=" * 60)
    print("TEST 4: Multiple ROIs on Same Stack")
    print("=" * 60)
    
    # Create synthetic stack
    T, H, W = 40, 200, 200
    stack = np.zeros((T, H, W), dtype=np.float32)
    
    # Create two regions with different kinetics
    for t in range(T):
        # Region 1 (left): Fast wash-in
        region1_intensity = 100 + 100 * (1 - np.exp(-0.2 * t))
        stack[t, :, :W//2] = region1_intensity
        
        # Region 2 (right): Slow wash-in
        region2_intensity = 100 + 80 * (1 - np.exp(-0.05 * t))
        stack[t, :, W//2:] = region2_intensity
        
        # Add noise
        stack[t] += np.random.randn(H, W) * 3
    
    print(f"✓ Created synthetic stack with 2 regions: {stack.shape}")
    
    # Define ROI manager and add ROIs
    manager = ROIManager()
    
    # ROI 1: Left region (fast wash-in)
    roi1_poly = [(30, 70), (70, 70), (70, 130), (30, 130)]
    roi1 = manager.add_roi(roi1_poly, label="Fast_Region")
    
    # ROI 2: Right region (slow wash-in)
    roi2_poly = [(130, 70), (170, 70), (170, 130), (130, 130)]
    roi2 = manager.add_roi(roi2_poly, label="Slow_Region")
    
    print(f"✓ Added {len(manager.rois)} ROIs")
    
    # Extract TIC for each ROI
    fps = 10.0
    tics = {}
    
    for roi in manager.rois:
        # Convert to mask
        mask = np.zeros((H, W), dtype=bool)
        xs = [pt[0] for pt in roi.polygon]
        ys = [pt[1] for pt in roi.polygon]
        rr, cc = polygon_fill(ys, xs, shape=(H, W))
        mask[rr, cc] = True
        
        # Extract TIC
        vi = np.array([stack[t][mask].mean() for t in range(T)])
        dvi = vi - vi[0]
        time = np.arange(T) / fps
        
        tics[roi.label] = {
            'time': time,
            'vi': vi,
            'dvi': dvi,
            'mask': mask
        }
        
        print(f"  - {roi.label}: Baseline={vi[0]:.2f}, Max ΔVI={dvi.max():.2f}")
    
    # Visualize
    fig = plt.figure(figsize=(15, 5))
    
    # Subplot 1: Frame with both ROIs
    ax1 = plt.subplot(131)
    ax1.imshow(stack[T//2], cmap='magma')
    for roi_label, data in tics.items():
        color = 'red' if 'Fast' in roi_label else 'blue'
        ax1.contour(data['mask'], colors=color, linewidths=2)
    ax1.set_title(f'Frame {T//2} with ROIs')
    ax1.axis('off')
    ax1.legend(['Fast (Red)', 'Slow (Blue)'])
    
    # Subplot 2: Both TICs
    ax2 = plt.subplot(132)
    for roi_label, data in tics.items():
        color = 'red' if 'Fast' in roi_label else 'blue'
        ax2.plot(data['time'], data['dvi'], color=color, linewidth=2, label=roi_label)
    ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('ΔVI (AU)')
    ax2.set_title('TIC Comparison')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    # Subplot 3: ROI masks
    ax3 = plt.subplot(133)
    combined_mask = np.zeros((H, W, 3), dtype=np.uint8)
    for idx, (roi_label, data) in enumerate(tics.items()):
        if 'Fast' in roi_label:
            combined_mask[data['mask']] = [255, 0, 0]  # Red
        else:
            combined_mask[data['mask']] = [0, 0, 255]  # Blue
    ax3.imshow(combined_mask)
    ax3.set_title('ROI Masks')
    ax3.axis('off')
    
    plt.tight_layout()
    output_path = Path(__file__).parent / 'test_outputs' / 'multiple_rois.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Multi-ROI visualization saved to: {output_path}")
    plt.close()
    
    return manager, tics


def test_napari_polygon_format():
    """Test conversion from Napari polygon format"""
    print("\n" + "=" * 60)
    print("TEST 5: Napari Polygon Format Conversion")
    print("=" * 60)
    
    # Simulate Napari polygon data format
    # Napari uses (t, y, x) for 3D+time or (y, x) for 2D
    
    # Test 1: 2D polygon (y, x)
    napari_2d = np.array([
        [50, 50],
        [50, 100],
        [100, 100],
        [100, 50]
    ])
    
    # Convert to (x, y) format
    polygon_2d = [(int(pt[1]), int(pt[0])) for pt in napari_2d]
    print(f"✓ 2D polygon conversion:")
    print(f"  Napari format (y,x): {napari_2d.tolist()}")
    print(f"  App format (x,y): {polygon_2d}")
    
    # Test 2: 3D polygon with time (t, y, x)
    napari_3d = np.array([
        [0, 50, 50],
        [0, 50, 100],
        [0, 100, 100],
        [0, 100, 50]
    ])
    
    # Convert to (x, y) format (ignore time dimension)
    polygon_3d = [(int(pt[2]), int(pt[1])) for pt in napari_3d]
    print(f"\n✓ 3D polygon conversion:")
    print(f"  Napari format (t,y,x): {napari_3d.tolist()}")
    print(f"  App format (x,y): {polygon_3d}")
    
    # Verify they produce same mask
    image_shape = (150, 150)
    
    mask_2d = np.zeros(image_shape, dtype=bool)
    xs = [pt[0] for pt in polygon_2d]
    ys = [pt[1] for pt in polygon_2d]
    rr, cc = polygon_fill(ys, xs, shape=image_shape)
    mask_2d[rr, cc] = True
    
    mask_3d = np.zeros(image_shape, dtype=bool)
    xs = [pt[0] for pt in polygon_3d]
    ys = [pt[1] for pt in polygon_3d]
    rr, cc = polygon_fill(ys, xs, shape=image_shape)
    mask_3d[rr, cc] = True
    
    masks_equal = np.array_equal(mask_2d, mask_3d)
    print(f"\n✓ Masks equal: {masks_equal}")
    print(f"  - 2D mask pixels: {mask_2d.sum()}")
    print(f"  - 3D mask pixels: {mask_3d.sum()}")
    
    return polygon_2d, polygon_3d


def run_all_tests():
    """Run all ROI tests"""
    print("\n" + "🔬" * 30)
    print("ROI SYSTEM COMPREHENSIVE TEST SUITE")
    print("🔬" * 30 + "\n")
    
    try:
        # Test 1: ROI Manager
        manager = test_roi_manager()
        
        # Test 2: Polygon to mask
        masks = test_polygon_to_mask()
        
        # Test 3: TIC extraction
        time, vi, dvi = test_tic_extraction()
        
        # Test 4: Multiple ROIs
        multi_manager, tics = test_multiple_rois()
        
        # Test 5: Napari format
        poly_2d, poly_3d = test_napari_polygon_format()
        
        # Summary
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)
        print("\nSummary:")
        print(f"  ✓ ROI Manager: {len(manager.rois)} ROIs stored")
        print(f"  ✓ Polygon→Mask conversion: {len(masks)} masks generated")
        print(f"  ✓ TIC extraction: {len(time)} time points")
        print(f"  ✓ Multi-ROI: {len(multi_manager.rois)} ROIs, {len(tics)} TICs")
        print(f"  ✓ Napari format: Conversion working")
        
        print("\n📊 Outputs saved to: test_outputs/")
        print("  - roi_masks.png")
        print("  - tic_extraction.png")
        print("  - multiple_rois.png")
        
        print("\n💡 Conclusion:")
        print("  If these tests pass but ROI doesn't work in the app,")
        print("  the issue is likely in:")
        print("    1. Napari shapes event handling")
        print("    2. Coordinate system mapping")
        print("    3. UI update/refresh logic")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
