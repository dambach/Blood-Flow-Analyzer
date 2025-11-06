# CEUS Analyzer - PyQt5/Napari Application

Interactive application for CEUS (Contrast-Enhanced Ultrasound) blood flow analysis with two versions:
- **PyQt5 Version**: Original with PyQtGraph viewers
- **Napari Version**: Full Napari integration (recommended)

## 🎯 Napari Version (Recommended)

Full-featured version using Napari for visualization. See [NAPARI_VERSION.md](NAPARI_VERSION.md) for details.

### Quick Start

```bash
# Launch with automatic .venv activation
./launch_napari.sh

# Or manually
source ../.venv/bin/activate
python napari_main.py
```

### Key Features
- 🖼️ Dual Napari viewers (B-mode + CEUS)
- ✏️ Interactive polygon ROI drawing (Napari shapes)
- 📊 Multi-ROI TIC analysis with synchronized playback
- 🎯 Motion compensation (B-mode or CEUS-based)
- 🔧 Advanced preprocessing pipeline
- ⚡ Automatic flash detection

## Features

- **DICOM Loading**: Automatic B-mode/CEUS region extraction (GE + SuperSonic compatible)
- **Motion Compensation**: Phase-correlation based registration
- **Flash Detection**: Automatic microbubble destruction and washout detection
- **ROI Management**: Multiple labeled ROIs with interactive polygon drawing
- **TIC Analysis**: Time-Intensity Curves with preprocessing
- **Wash-in Modeling**: Non-linear least squares fit (A*(1-exp(-B*t)))
- **Interactive Plots**: Bidirectional sync between frames and TIC curves
- **Export**: CSV export (TIC values, parameters)

## Installation

```bash
cd ceus_app_pyqt
pip install -r requirements.txt
```

## Usage

**Napari Version (Recommended):**
```bash
./launch_napari.sh
# Or: python napari_main.py
```

**PyQt5 Original Version:**
```bash
python -m src.main
```

## Architecture

```
src/
├── main.py              # Entry point
├── ui/
│   ├── main_window.py   # Main application window
│   ├── data_tab.py      # Data view tab
│   ├── model_tab.py     # Model fit tab
│   └── widgets/
│       ├── roi_selector.py       # ROI drawing widget
│       ├── parameter_panel.py    # Fit parameters panel
│       └── interactive_plot.py   # TIC plot with sync
├── core/
│   ├── dicom_loader.py           # DICOM parsing
│   ├── preprocessing.py          # Image preprocessing
│   ├── motion_compensation.py    # Registration
│   ├── flash_detection.py        # Flash/washout detection
│   ├── roi_manager.py            # ROI management
│   └── tic_analysis.py           # TIC extraction
├── models/
│   ├── washin_model.py           # Wash-in curve fitting
│   └── metrics.py                # AUC, peak, slope, etc.
└── utils/
    ├── converters.py             # YCbCr→RGB, etc.
    └── validators.py             # Input validation
```

## Keyboard Shortcuts

- **X**: Toggle frame exclusion
- **R**: Draw new ROI
- **Delete**: Remove selected ROI
- **Space**: Play/pause video
- **Arrow keys**: Navigate frames

## Inspired by

- `notebooks/ceus_notebook.ipynb` (pipeline logic)
- `app.R` (Shiny R application - fit parameters UI)
