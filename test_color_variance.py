#!/usr/bin/env python3
"""
Test script to analyze color variance in GE vs SuperSonic DICOMs
Determines correct classification logic for CEUS vs B-mode
"""

import pydicom
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def ycbcr_to_rgb(ycbcr):
    """Convert YCbCr to RGB (BT.601)"""
    y = ycbcr[:, :, 0].astype(float)
    cb = ycbcr[:, :, 1].astype(float)
    cr = ycbcr[:, :, 2].astype(float)
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    rgb = np.stack([np.clip(r, 0, 255), np.clip(g, 0, 255), np.clip(b, 0, 255)], axis=-1)
    return rgb.astype(np.uint8)

def analyze_dicom_regions(dicom_path):
    """Analyze regions in a DICOM file"""
    print(f"\n{'='*80}")
    print(f"📂 Analyzing: {dicom_path.name}")
    print(f"{'='*80}")
    
    # Read DICOM
    ds = pydicom.dcmread(str(dicom_path), force=True)
    arr = ds.pixel_array
    
    # Get manufacturer
    manufacturer = getattr(ds, 'Manufacturer', 'Unknown')
    model = getattr(ds, 'ManufacturerModelName', 'Unknown')
    
    print(f"📊 Manufacturer: {manufacturer}")
    print(f"📊 Model: {model}")
    print(f"📊 Array shape: {arr.shape}")
    print(f"📊 PhotometricInterpretation: {getattr(ds, 'PhotometricInterpretation', None)}")
    
    # Get regions
    regions = getattr(ds, 'SequenceOfUltrasoundRegions', None)
    if regions is None:
        print("❌ No SequenceOfUltrasoundRegions found")
        return
    
    print(f"\n🔍 Found {len(regions)} regions:")
    
    # Extract and analyze regions
    region_data = []
    
    for i, reg in enumerate(regions):
        dtype = getattr(reg, 'RegionDataType', None)
        flags = getattr(reg, 'RegionFlags', None)
        x0 = getattr(reg, 'RegionLocationMinX0', None)
        y0 = getattr(reg, 'RegionLocationMinY0', None)
        x1 = getattr(reg, 'RegionLocationMaxX1', None)
        y1 = getattr(reg, 'RegionLocationMaxY1', None)
        
        print(f"\n   Region {i}:")
        print(f"      DataType: {dtype} (1=ambiguous, 2=explicit CEUS)")
        print(f"      RegionFlags: {flags}")
        print(f"      Coordinates: [{x0}, {y0}] → [{x1}, {y1}]")
        
        if None in [x0, y0, x1, y1]:
            print(f"      ⚠️ Missing coordinates, skipping")
            continue
        
        # Clip coordinates
        H, W = arr.shape[1], arr.shape[2]
        x0 = max(0, min(int(x0), W - 1))
        y0 = max(0, min(int(y0), H - 1))
        x1 = max(0, min(int(x1), W - 1))
        y1 = max(0, min(int(y1), H - 1))
        
        if x0 >= x1 or y0 >= y1:
            print(f"      ⚠️ Invalid coordinates after clipping")
            continue
        
        # Extract region
        if arr.ndim == 4:
            region_stack = arr[:, y0:y1+1, x0:x1+1, :]
        else:
            region_stack = arr[:, y0:y1+1, x0:x1+1]
        
        print(f"      Extracted shape: {region_stack.shape}")
        
        # Convert YBR to RGB if needed
        photo = getattr(ds, 'PhotometricInterpretation', None)
        if photo and 'YBR' in str(photo) and region_stack.ndim == 4:
            frame_mid = ycbcr_to_rgb(region_stack[len(region_stack)//2])
        else:
            frame_mid = region_stack[len(region_stack)//2]
        
        # Calculate color variance
        if frame_mid.ndim == 3 and frame_mid.shape[-1] == 3:
            r, g, b = frame_mid[..., 0], frame_mid[..., 1], frame_mid[..., 2]
            
            rg_var = np.std(r.astype(float) - g.astype(float))
            gb_var = np.std(g.astype(float) - b.astype(float))
            rb_var = np.std(r.astype(float) - b.astype(float))
            total_var = rg_var + gb_var + rb_var
            
            # Channel statistics
            r_mean, g_mean, b_mean = r.mean(), g.mean(), b.mean()
            r_std, g_std, b_std = r.std(), g.std(), b.std()
            
            print(f"      📊 Color variance analysis:")
            print(f"         R-G variance: {rg_var:.2f}")
            print(f"         G-B variance: {gb_var:.2f}")
            print(f"         R-B variance: {rb_var:.2f}")
            print(f"         TOTAL: {total_var:.2f}")
            print(f"      📊 Channel means: R={r_mean:.1f}, G={g_mean:.1f}, B={b_mean:.1f}")
            print(f"      📊 Channel stds:  R={r_std:.1f}, G={g_std:.1f}, B={b_std:.1f}")
            
            # Determine type
            if total_var > 15:
                detected_type = "🎨 COLOR (likely Doppler/CEUS)"
            elif total_var > 5:
                detected_type = "🟡 INTERMEDIATE (mixed/overlay?)"
            else:
                detected_type = "⚫ GRAYSCALE (likely B-mode)"
            
            print(f"      ➜ {detected_type}")
            
            region_data.append({
                'index': i,
                'dtype': dtype,
                'flags': flags,
                'x0': x0,
                'variance': total_var,
                'frame': frame_mid,
                'detected': detected_type
            })
        else:
            print(f"      ⚠️ Not RGB, skipping variance analysis")
    
    # Visual comparison
    if len(region_data) >= 2:
        print(f"\n{'='*80}")
        print("🔬 VISUAL COMPARISON")
        print(f"{'='*80}")
        
        fig, axes = plt.subplots(2, len(region_data), figsize=(6*len(region_data), 10))
        if len(region_data) == 1:
            axes = axes.reshape(-1, 1)
        
        for col_idx, rdata in enumerate(region_data):
            # Top: Image
            ax_img = axes[0, col_idx]
            ax_img.imshow(rdata['frame'])
            ax_img.set_title(f"Region {rdata['index']}\n{rdata['detected']}\nVariance={rdata['variance']:.2f}",
                           fontweight='bold', fontsize=11)
            ax_img.axis('off')
            
            # Bottom: RGB histograms
            ax_hist = axes[1, col_idx]
            r = rdata['frame'][..., 0].flatten()
            g = rdata['frame'][..., 1].flatten()
            b = rdata['frame'][..., 2].flatten()
            
            ax_hist.hist(r, bins=50, alpha=0.5, color='red', label='R', density=True)
            ax_hist.hist(g, bins=50, alpha=0.5, color='green', label='G', density=True)
            ax_hist.hist(b, bins=50, alpha=0.5, color='blue', label='B', density=True)
            ax_hist.set_xlabel('Pixel value')
            ax_hist.set_ylabel('Density')
            ax_hist.legend()
            ax_hist.grid(True, alpha=0.3)
            ax_hist.set_title(f"RGB Histograms (Region {rdata['index']})", fontsize=11)
        
        plt.suptitle(f"{manufacturer} - Color Variance Analysis", fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.savefig(f'/tmp/dicom_analysis_{dicom_path.stem}.png', dpi=150, bbox_inches='tight')
        print(f"\n✅ Saved visualization: /tmp/dicom_analysis_{dicom_path.stem}.png")
        plt.close()
        
        # Conclusion
        print(f"\n{'='*80}")
        print("🎯 CONCLUSION")
        print(f"{'='*80}")
        
        sorted_regions = sorted(region_data, key=lambda x: x['variance'], reverse=True)
        
        print(f"\nSorted by variance (HIGH → LOW):")
        for i, rdata in enumerate(sorted_regions):
            rank = "1st (HIGHEST)" if i == 0 else f"{i+1}{'th' if i >= 3 else ['nd', 'rd'][i-1]} "
            print(f"   {rank}: Region {rdata['index']} → variance={rdata['variance']:.2f} → {rdata['detected']}")
        
        print(f"\n💡 INTERPRETATION for {manufacturer}:")
        highest_var = sorted_regions[0]
        lowest_var = sorted_regions[-1]
        
        if 'GE' in manufacturer.upper():
            print(f"   GE Scanner detected:")
            print(f"   • Highest variance (Region {highest_var['index']}, {highest_var['variance']:.2f}) = ?")
            print(f"   • Lowest variance (Region {lowest_var['index']}, {lowest_var['variance']:.2f}) = ?")
            print(f"\n   ❓ WHICH IS CEUS? Look at the images:")
            print(f"      - CEUS should have Doppler COLOR overlay (red/blue blood flow)")
            print(f"      - B-mode should be GRAYSCALE anatomical image")
        else:
            print(f"   Standard (SuperSonic/other):")
            print(f"   • Highest variance (Region {highest_var['index']}, {highest_var['variance']:.2f}) → likely CEUS (color Doppler)")
            print(f"   • Lowest variance (Region {lowest_var['index']}, {lowest_var['variance']:.2f}) → likely B-mode (grayscale)")


# Main analysis
if __name__ == "__main__":
    data_dir = Path('/Users/damienbachasson/GitHub_repos/Blood-Flow-Analyzer/data')
    
    # Test both DICOMs
    dicom_files = [
        data_dir / 'd_00010230',  # GE?
        data_dir / 'f_aixplorerdcm'  # SuperSonic?
    ]
    
    for dicom_path in dicom_files:
        if dicom_path.exists():
            analyze_dicom_regions(dicom_path)
        else:
            print(f"⚠️ File not found: {dicom_path}")
    
    print(f"\n\n{'='*80}")
    print("✅ ANALYSIS COMPLETE")
    print(f"{'='*80}")
    print("Check the saved visualizations in /tmp/ to determine the correct classification logic.")
