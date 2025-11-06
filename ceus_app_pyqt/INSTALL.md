# CEUS Analyzer PyQt6 - Installation Guide

## 📦 Installation

### 1. Navigate to app directory
```bash
cd /Users/damienbachasson/GitHub_repos/Blood-Flow-Analyzer/ceus_app_pyqt
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

Or if you're using the existing virtual environment:
```bash
source ../.venv/bin/activate
pip install -r requirements.txt
```

### 3. Launch application

**Option A: From app directory**
```bash
python src/main.py
```

**Option B: Using launch script (from repo root)**
```bash
python ceus_app_pyqt/launch.py
```

**Option C: From any location**
```bash
cd /Users/damienbachasson/GitHub_repos/Blood-Flow-Analyzer
PYTHONPATH=ceus_app_pyqt/src python -m main
```

## 🎯 Quick Start

1. **Load DICOM**: Click "📁 Load DICOM" and select your DICOM file
   - GE and SuperSonic scanners are automatically detected
   - B-mode and CEUS regions are extracted automatically

2. **Detect Flash**: Click "⚡ Detect Flash"
   - Automatically finds microbubble destruction and washout

3. **Preprocess**: Click "🔧 Preprocess"
   - Applies temporal cropping (washout + 15s)
   - Log-compression and filtering

4. **Motion Correction**: Click "🎯 Motion Correction" (optional)
   - Phase-correlation based registration
   - Uses B-mode for estimation if available

5. **Define ROIs**: Go to "🎯 ROI Manager" tab
   - Click "➕ Add ROI" and draw on image
   - Multiple labeled ROIs supported

6. **View TIC**: Go to "📈 TIC Analysis" tab
   - Time-Intensity Curves for all ROIs
   - Click on curve to jump to frame
   - Frame slider syncs with TIC plot

7. **Fit Model**: Go to "📊 Fit Parameters" tab
   - Adjust start values and bounds
   - Click "🔬 Fit Model"
   - View metrics (R², AUC, A×B, etc.)

## 🔑 Keyboard Shortcuts

- **X**: Toggle frame exclusion
- **R**: Draw new ROI
- **Delete**: Remove selected ROI
- **Space**: Play/pause video
- **←/→**: Navigate frames

## 📁 Project Structure

```
ceus_app_pyqt/
├── src/
│   ├── main.py              # Entry point
│   ├── core/                # Analysis logic (from notebook)
│   │   ├── dicom_loader.py
│   │   ├── flash_detection.py
│   │   ├── preprocessing.py
│   │   ├── motion_compensation.py
│   │   ├── tic_analysis.py
│   │   └── roi_manager.py
│   ├── models/              # Fitting models
│   │   ├── washin_model.py
│   │   └── metrics.py
│   ├── ui/                  # PyQt6 interface
│   │   ├── main_window.py
│   │   └── widgets/
│   │       ├── image_viewer.py
│   │       ├── tic_plot_widget.py
│   │       ├── roi_panel.py
│   │       └── fit_panel.py
│   └── utils/               # Helpers
│       ├── converters.py
│       └── validators.py
├── resources/
│   └── styles/
│       └── app.qss          # Dark theme stylesheet
├── requirements.txt
└── README.md
```

## 🛠️ Troubleshooting

### PyQt6 not found
```bash
pip install PyQt6 PyQt6-Qt6
```

### pyqtgraph not found
```bash
pip install pyqtgraph
```

### scikit-image not found (for motion compensation)
```bash
pip install scikit-image
```

### Import errors
Make sure you're running from the correct directory or using PYTHONPATH:
```bash
cd ceus_app_pyqt
python src/main.py
```

## 📊 Data Flow

```
DICOM File
    ↓
[DICOM Loader] → B-mode + CEUS stacks
    ↓
[Flash Detection] → flash_idx, washout_idx
    ↓
[Temporal Crop] → washout + 15s
    ↓
[Motion Compensation] → Registered stack
    ↓
[Preprocessing] → Filtered, normalized stack
    ↓
[ROI Selection] → User draws ROIs
    ↓
[TIC Extraction] → Time-Intensity Curves
    ↓
[Median Filtering] → Smoothed TIC
    ↓
[Wash-in Fit] → A*(1-exp(-B*t)) model
    ↓
[Metrics] → R², AUC, Peak, Slope, etc.
```

## 🎨 Features

✅ **Implemented:**
- DICOM loading (GE + SuperSonic)
- Flash/washout detection
- Temporal cropping
- Motion compensation
- Preprocessing (log, filtering, baseline)
- Image viewer with frame slider
- TIC plot widget
- ROI manager (data structure)
- Fit panel (UI)
- Wash-in model fitting
- Metrics computation

🚧 **To be completed:**
- Interactive ROI drawing (currently placeholder)
- TIC computation integration
- Frame exclusion feature
- Export to CSV
- Batch processing

## 💡 Tips

- **Performance**: PyQtGraph is GPU-accelerated, handles large stacks efficiently
- **ROI Colors**: Automatically cycles through 8 distinct colors
- **Fit Window**: Default 5s captures wash-in phase, adjust if needed
- **Median Filter**: Window size auto-adjusts based on FPS
- **Reference Frame**: Motion compensation uses median of frames 3-13 for robustness

## 📚 References

- Pipeline logic: `../notebooks/ceus_notebook.ipynb`
- Fit parameters UI: `../app.R` (Shiny R app)
- DICOM extraction: Universal logic (GE = position, others = color variance)
