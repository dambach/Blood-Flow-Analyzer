# 🎯 CEUS Analyzer - Advanced Features

## Inspirations from Open-Source Projects

This project incorporates best practices from leading napari plugins:

### 📊 ROI Analysis (inspired by [napari-skimage-regionprops](https://github.com/haesleinhuepf/napari-skimage-regionprops))

**ROI Properties Computed:**
- **Geometric properties:**
  - Area (pixels²)
  - Perimeter (pixels)
  - Width × Height dimensions
  - Bounding box coordinates

- **Intensity statistics (per frame):**
  - Mean intensity
  - Min intensity
  - Max intensity
  - Standard deviation

- **Temporal statistics (overall):**
  - Mean/Min/Max/Std across all frames
  - TIC curves with uncertainty bands

### 📈 Advanced Visualization (inspired by [napari-matplotlib](https://github.com/matplotlib/napari-matplotlib))

**Dual-Plot Layout:**
1. **Time-Intensity Curves (TIC):**
   - Mean intensity curves with markers
   - Min/Max intensity bands (shaded regions)
   - Color-coded by ROI label

2. **Intensity Variability:**
   - Standard deviation over time
   - Identifies frames with high variability
   - Useful for quality control

### 💾 Enhanced Data Export

**Two CSV Files Generated:**

#### 1. `TIC_TimeSeries_YYYYMMDD_HHMMSS.csv`
Time-series data with columns:
```
Frame, Time_s, liver_mean, liver_min, liver_max, liver_std, 
dia_mean, dia_min, dia_max, dia_std, cw_mean, cw_min, cw_max, cw_std
```

#### 2. `ROI_Properties_YYYYMMDD_HHMMSS.csv`
ROI characteristics table:
```
ROI_Label, ROI_Color, Area_pixels, Width_pixels, Height_pixels, 
Perimeter_pixels, BBox_x0, BBox_y0, BBox_x1, BBox_y1,
Mean_Intensity_Overall, Min_Intensity_Overall, 
Max_Intensity_Overall, Std_Intensity_Overall
```

## 🚀 Features

### Multi-ROI Management
- ✅ **3 ROI labels:** liver (red), dia (green), cw (blue)
- ✅ **One ROI per label** - automatic replacement
- ✅ **Persistent labels** - ROIs stay visible when switching labels
- ✅ **Color-coded** - RGBA colors for reliable identification

### Keyboard Shortcuts
- **`Space`** - Play/Pause video playback
- **`f`** - Mark current frame as flash frame
- **`Ctrl+Z` / `Cmd+Z`** - Undo last ROI drawn

### Automated Crop Presets
- **No Crop** - Full image
- **Aixplorer** - Fixed coordinates for Aixplorer ultrasound
- **LOGIC** - Dynamic: right half, -10% top/bottom

### Time-Intensity Analysis
- **Mean TIC curves** with min/max bands
- **Variability tracking** (standard deviation over time)
- **Statistical summary** displayed in console
- **Dual-plot visualization** for comprehensive analysis

## 📋 Workflow

1. **Load DICOM** → Select crop preset
2. **Select ROI label** → Rectangle mode auto-activated
3. **Draw ROI** → One per label (liver/dia/cw)
4. **Mark flash frame** → Press `f` during playback
5. **Compute TIC** → View statistics & plots
6. **Export data** → 2 CSV files (time-series + properties)

## 🎨 Visual Output

### Console Output (ROI Properties Summary)
```
======================================================================
ROI PROPERTIES SUMMARY
======================================================================

📍 LIVER (red)
  • Area: 15344 pixels²
  • Dimensions: 134 x 115 pixels
  • Perimeter: 498 pixels
  • Bounding box: (28, 125, 162, 240)
  • Mean intensity: 145.67
  • Min intensity: 89.23
  • Max intensity: 203.45
  • Std intensity: 18.92
```

### Matplotlib Plots
- **Top panel:** TIC curves with shaded min/max bands
- **Bottom panel:** Standard deviation evolution
- **Legend:** Color-coded ROI labels
- **Styling:** Clean Streamlit-like appearance

## 🔗 References

Inspired by these excellent napari plugins:
- [napari-skimage-regionprops](https://github.com/haesleinhuepf/napari-skimage-regionprops) - ROI feature extraction
- [napari-matplotlib](https://github.com/matplotlib/napari-matplotlib) - Interactive plotting
- [napari best practices](https://napari.org/stable/plugins/best_practices.html) - Plugin development

## 🎓 Technical Implementation

### ROI Label Mapping
Uses explicit label mapping instead of color-based inference:
```python
self.roi_labels_map = {0: 'liver', 1: 'dia', 2: 'cw'}
```

### Statistics Computation
Frame-by-frame analysis with numpy:
```python
for frame in frames:
    roi_frame = frame[y0:y1, x0:x1]
    tic_mean.append(np.mean(roi_frame))
    tic_min.append(np.min(roi_frame))
    tic_max.append(np.max(roi_frame))
    tic_std.append(np.std(roi_frame))
```

### Property Storage
Structured dictionary for each ROI:
```python
self.roi_properties[label] = {
    'area': roi_area,
    'perimeter': roi_perimeter,
    'mean_intensity_overall': np.mean(tic),
    'std_intensity_overall': np.mean(tic_std),
    # ... more properties
}
```

---

**Version:** 2.0  
**Date:** November 2025  
**License:** MIT
