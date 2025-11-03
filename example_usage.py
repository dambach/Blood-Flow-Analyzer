"""
Example: Using the CEUS Analyzer with Advanced ROI Analysis
Inspired by napari-skimage-regionprops workflow
"""

import napari
from napari_ceus_app import CEUSAnalyzer

# Create and run the analyzer
if __name__ == "__main__":
    app = CEUSAnalyzer()
    
    print("""
    ╔════════════════════════════════════════════════════════════════╗
    ║   CEUS Analyzer - Advanced Multi-ROI Analysis                 ║
    ╠════════════════════════════════════════════════════════════════╣
    ║                                                                ║
    ║  WORKFLOW:                                                     ║
    ║                                                                ║
    ║  1. 📂 Load DICOM                                              ║
    ║     • Select crop preset (Aixplorer, LOGIC, or No Crop)       ║
    ║                                                                ║
    ║  2. ✏️ Draw ROIs                                               ║
    ║     • Select label: liver (red), dia (green), or cw (blue)    ║
    ║     • Rectangle mode auto-activates                           ║
    ║     • Draw one ROI per label                                  ║
    ║                                                                ║
    ║  3. ⚡ Mark Flash Frame                                        ║
    ║     • Press 'f' during playback or use widget                 ║
    ║                                                                ║
    ║  4. 📊 Compute TIC                                             ║
    ║     • Calculates mean, min, max, std for each frame          ║
    ║     • Displays ROI properties summary in console              ║
    ║     • Shows dual-plot: TIC curves + variability               ║
    ║                                                                ║
    ║  5. 💾 Export Data                                             ║
    ║     • TIC_TimeSeries_*.csv (frame-by-frame statistics)        ║
    ║     • ROI_Properties_*.csv (geometric & intensity props)      ║
    ║                                                                ║
    ║  KEYBOARD SHORTCUTS:                                           ║
    ║  • Space: Play/Pause                                          ║
    ║  • f: Mark flash frame                                        ║
    ║  • Ctrl/Cmd+Z: Undo last ROI                                  ║
    ║                                                                ║
    ║  FEATURES (inspired by napari plugins):                        ║
    ║  ✓ Multi-ROI with persistent labels                           ║
    ║  ✓ ROI properties (area, perimeter, bbox, etc.)              ║
    ║  ✓ Statistics: mean/min/max/std per frame                    ║
    ║  ✓ Uncertainty bands in TIC plots                            ║
    ║  ✓ Comprehensive CSV export                                   ║
    ║                                                                ║
    ╚════════════════════════════════════════════════════════════════╝
    """)
    
    app.run()
