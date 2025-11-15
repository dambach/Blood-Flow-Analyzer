"""
Napari-native CEUS Analysis Application
Full-featured version using Napari for visualization and Qt for controls
"""
import os
os.environ['QT_API'] = 'pyqt5'  # Force PyQt5 before Napari import

import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple
import napari
from napari._qt.qt_event_loop import get_qapp
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QGroupBox, QFileDialog, QMessageBox, QListWidget, QInputDialog, QShortcut, QApplication, QSpacerItem, QFrame,
    QAbstractItemView, QSplitter, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QFormLayout, QDoubleSpinBox
)
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QKeySequence, QMovie
# Savitzky–Golay no longer used for overlay/fit; LOESS is used to match R app.

from src.core import (
    DICOMLoader, detect_flash_ceus_refined, 
    preprocess_ceus, motion_compensate, ROIManager
)
from src.utils.converters import to_gray
from src.ui.widgets.tic_plot_widget import TICPlotWidget
from src.utils.loess import loess_smooth
from src.ui.widgets.fit_panel import FitPanel
import pandas as pd
try:
    from src.analysis.models import fit_models
except Exception:
    fit_models = None
from skimage.draw import polygon as sk_polygon


class NapariCEUSWindow(QWidget):
    """Main CEUS analysis window using Napari viewers"""
    
    def __init__(self):
        super().__init__()
        
        # Get shared Qt application
        self.app = get_qapp()
        
        # Data
        self.dicom_loader = None
        self.bmode_stack = None
        self.ceus_stack = None
        self.ceus_preprocessed = None
        self.fps = None
        self.flash_idx = None
        self.washout_idx = None
        self.current_frame = 0
        self._bmode_display_stack = None
        self._bmode_channel_axis = None
        self._bmode_is_rgb = False
        self._ceus_display_stack = None
        self._ceus_channel_axis = None
        self._ceus_is_rgb = False
        self._current_ceus_layer_name = 'CEUS'
        
        # ROI management
        self.roi_manager = ROIManager()
        self.roi_tic_data = {}  # {roi_label: (time, vi, dvi)}
        # (Undo removed for TIC toggling simplification)
        
        # Create Napari viewers
        self._create_napari_viewers()
        
        # Create UI
        self._create_widgets()
        self._create_layout()
        self._connect_signals()
        # Shortcuts and default camera sync
        self._setup_shortcuts()
        try:
            self.btn_sync_zoom.setChecked(True)
        except Exception:
            pass
        
        # Playback timer
        self.playback_timer = QTimer()
        self.playback_timer.setTimerType(Qt.PreciseTimer)
        self.playback_timer.timeout.connect(self._advance_frame)
        self.is_playing = False
        
        self.setWindowTitle("CEUS Analyzer - Napari Edition")
        self.resize(1800, 1000)
        # Global UI font sizing and background
        self.setStyleSheet(
            """
            QWidget { background-color: white; font-size: 12pt; }
            QGroupBox::title { font-size: 12pt; }
            QPushButton { font-size: 12pt; }
            QLabel { font-size: 12pt; }
            QTableWidget { font-size: 12pt; }
            QListWidget { font-size: 12pt; }
            QCheckBox { font-size: 12pt; }
            QSlider { font-size: 12pt; }
            """
        )
        # ROI master shapes layer: 'bmode' or 'ceus'
        self._roi_master = 'ceus'
        # Dernier point TIC cliqué (label, idx) pour raccourcis clavier
        self._last_tic_target = None  # (label, idx)
        # Résultats de fit par ROI {label: {model: {params, rss, y_fit}}}
        self.fit_results = {}
        # Ensure we can receive key events
        try:
            self.setFocusPolicy(Qt.StrongFocus)
        except Exception:
            pass
        # B-mode display tuning
        self._bmode_auto_clims = None  # (low, high) computed from data
        self._bmode_gamma = 0.9        # slight gamma for better visibility

    def _estimate_washin_initials(self, t: np.ndarray, y: np.ndarray, t0_hint: Optional[float]) -> Tuple[float, float]:
        """Estimate (A_start, B_start) from data for wash-in model.

        - A_start ≈ max(y - C) within [0, Tmax]
        - B_start from half-plateau time: B ≈ ln(2) / max(t_half - t0, eps)
          Fallback to initial slope S near t0: B ≈ S / max(A_start, eps)
        """
        try:
            t = np.asarray(t, float)
            y = np.asarray(y, float)
            if t.size == 0 or y.size == 0:
                return 0.25, 0.1
            # Baseline estimate
            C = float(np.percentile(y, 10))
            yb = y - C
            # Plateau estimate
            A = float(max(1e-6, np.nanmax(yb)))
            # Half-plateau time
            target = 0.5 * A
            # Define effective origin
            t0 = float(t0_hint) if (t0_hint is not None) else float(t[0])
            tt = t - t0
            # Find first time reaching half plateau
            idx = np.where(yb >= target)[0]
            if idx.size >= 1:
                i = int(idx[0])
                t_half = float(max(tt[i], 1e-6))
                B = float(np.log(2.0) / t_half)
            else:
                # Fallback: slope at early segment (first 5 points or within 2s)
                try:
                    m = min(5, int(t.size))
                    # Choose points within first 2 seconds from t0 if possible
                    early = (tt <= 2.0)
                    if np.any(early) and np.sum(early) >= 2:
                        te = tt[early]
                        ye = yb[early]
                    else:
                        te = tt[:m]
                        ye = yb[:m]
                    # Linear fit slope
                    coef = np.polyfit(te, ye, 1)
                    slope = float(max(coef[0], 1e-6))
                except Exception:
                    slope = 1e-3
                B = float(slope / max(A, 1e-6))
            # Clip to reasonable range
            B = float(max(1e-5, min(B, 5.0)))
            return A, B
        except Exception:
            return 0.25, 0.1
    
    def _create_napari_viewers(self):
        """Create two Napari viewer instances"""
        # B-mode viewer
        self.bmode_viewer = napari.Viewer(
            show=False,
            title="B-mode"
        )
        
        # CEUS viewer (with ROI shapes)
        self.ceus_viewer = napari.Viewer(
            show=False,
            title="CEUS"
        )
        
        # Defer creation of shapes layer for ROI drawing until after images are added
        self.shapes_layer = None
        # A blank image layer we place above CEUS to anchor ROI rendering order
        self.roi_canvas_layer = None
        # Separate shapes layer to mirror ROIs on B-mode viewer
        self.bmode_shapes_layer = None
        
        # Overlay viewer (B-mode + CEUS)
        self.overlay_viewer = napari.Viewer(
            show=False,
            title="Overlay (B-mode + CEUS)"
        )

        # Store references to Qt widgets
        self.bmode_widget = self.bmode_viewer.window._qt_viewer
        self.ceus_widget = self.ceus_viewer.window._qt_viewer
        self.overlay_widget = self.overlay_viewer.window._qt_viewer

        # Hide in-viewer controls (dims sliders, left controls) to declutter UI
        self._hide_napari_ui(self.bmode_viewer)
        self._hide_napari_ui(self.ceus_viewer)
        self._hide_napari_ui(self.overlay_viewer)

    def _hide_napari_ui(self, viewer: napari.Viewer):
        """Hide Napari in-viewer UI elements like dims sliders and left controls."""
        try:
            qt_viewer = viewer.window._qt_viewer
            # Hide left controls panel
            if hasattr(qt_viewer, 'controls'):
                qt_viewer.controls.hide()
            # Hide dims play/axis sliders
            if hasattr(qt_viewer, 'dims'):
                qt_viewer.dims.setVisible(False)
            # Optionally hide layer buttons if present
            if hasattr(qt_viewer, 'layerButtons'):
                qt_viewer.layerButtons.setVisible(False)
        except Exception:
            # Be tolerant to napari API changes
            pass
    
    def _create_widgets(self):
        """Create control widgets"""
        # Top control buttons
        self.btn_load = QPushButton("📁 Load DICOM")
        self.btn_detect_flash = QPushButton("⚡ Detect Flash")
        self.btn_set_flash_manual = QPushButton("✋ Set Flash Manually")
        self.btn_motion_correction = QPushButton("🎯 Motion Correction")
        self.btn_preprocess = QPushButton("🔧 Preprocess")
        self.btn_reset = QPushButton("🔄 Reset Analysis")
        self.btn_sync_zoom = QPushButton("🔍 Sync Zoom/Pan")
        self.btn_sync_zoom.setCheckable(True)
        self.btn_sync_zoom.setToolTip("Synchroniser le zoom/pan sur les 3 viewers (CEUS maître)")
        
        self.btn_detect_flash.setEnabled(False)
        self.btn_set_flash_manual.setEnabled(False)
        self.btn_motion_correction.setEnabled(False)
        self.btn_preprocess.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self.btn_sync_zoom.setEnabled(True)
        
        # ROI controls
        self.btn_draw_roi = QPushButton("✏️ Draw ROI (Polygon)")
        self.btn_draw_roi.setCheckable(True)
        self.btn_draw_roi.setEnabled(False)
        
        self.btn_clear_roi = QPushButton("🗑️ Clear All ROIs")
        self.btn_clear_roi.setEnabled(False)
        
        self.btn_compute_tic = QPushButton("📊 Compute TICs")
        self.btn_compute_tic.setEnabled(False)

        # ROI list + actions
        self.roi_list_label = QLabel("<b>Active ROIs:</b>")
        self.roi_info_widget = QListWidget()
        # Autoriser la sélection multiple (Shift/Cmd pour sélectionner plusieurs ROIs)
        try:
            self.roi_info_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        except Exception:
            pass
        self.btn_remove_selected_roi = QPushButton("🗑️ Remove Selected ROI")
        self.btn_remove_selected_roi.setEnabled(False)
        self.btn_rename_roi = QPushButton("✏️ Rename ROI")
        self.btn_rename_roi.setEnabled(False)
        self.btn_rename_roi.setToolTip("Rename the selected ROI")
        
        # Playback controls
        self.play_button = QPushButton("▶ Play")
        self.play_button.setMaximumWidth(80)
        self.play_button.setEnabled(False)
        
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setEnabled(False)
        
        self.frame_info_label = QLabel("Frame: 0 / 0 (0.00s)")
        
        # Status label
        self.status_label = QLabel("Ready to load DICOM")
        self.status_label.setStyleSheet("padding: 5px; background: #eaeaea; border-radius: 3px; color: #222;")
        
        # Analysis info label (above viewers)
        self.analysis_info_label = QLabel("Flash: —   Washout: —   ROI: 0 active")
        try:
            self.analysis_info_label.setStyleSheet("color:#444; padding: 2px 4px;")
        except Exception:
            pass
        
        # TIC plot widget
        self.tic_plot = TICPlotWidget()
        
        # Fit panel
        self.fit_panel = FitPanel()
    
    def _create_layout(self):
        """Create main layout"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ========== TOP: Control buttons ==========
        control_layout = QHBoxLayout()
        control_layout.setSpacing(12)
        control_layout.addWidget(self.btn_load)
        control_layout.addWidget(self.btn_detect_flash)
        control_layout.addWidget(self.btn_set_flash_manual)
        control_layout.addWidget(self.btn_motion_correction)
        control_layout.addWidget(self.btn_preprocess)
        control_layout.addWidget(self.btn_reset)
        control_layout.addWidget(self.btn_sync_zoom)
        control_layout.addStretch()
        main_layout.addLayout(control_layout)

        # Info label above viewers
        main_layout.addWidget(self.analysis_info_label)
        # Tips label above the image viewers (moved from TIC panel)
        try:
            self.tips_label = QLabel("💡 Tip: Click = Go to frame | E = Include/Exclude at current frame (selected ROI(s)) | Right-click + drag = Pan | Mouse wheel = Zoom | Space = Play/Pause | ←/→ = Previous/Next frame | Ctrl/Cmd+R = Reset")
            self.tips_label.setStyleSheet("color: gray; font-size: 12px; padding-left: 4px;")
            main_layout.addWidget(self.tips_label)
        except Exception:
            pass

        # ========== MIDDLE: Napari viewers + Playback + ROI panel ==========
        viewers_layout = QHBoxLayout()
        viewers_layout.setContentsMargins(0, 0, 0, 0)
        viewers_layout.setSpacing(6)

        # Left: three viewers in a row
        left_viewers_row = QHBoxLayout()
        left_viewers_row.setContentsMargins(0, 0, 0, 0)
        left_viewers_row.setSpacing(6)

        # B-mode viewer
        self.bmode_group = QGroupBox("B-mode")
        bmode_layout = QVBoxLayout()
        bmode_layout.setContentsMargins(0, 0, 0, 0)
        bmode_layout.setSpacing(0)
        bmode_layout.addWidget(self.bmode_widget)
        self.bmode_group.setLayout(bmode_layout)
        self.bmode_group.setStyleSheet("QGroupBox{border:0px;} QGroupBox::title{padding:2px 4px;}")
        left_viewers_row.addWidget(self.bmode_group, stretch=2)

        # Center: CEUS viewer
        self.ceus_group = QGroupBox("CEUS / Preprocessed")
        ceus_layout = QVBoxLayout()
        ceus_layout.setContentsMargins(0, 0, 0, 0)
        ceus_layout.setSpacing(0)
        ceus_layout.addWidget(self.ceus_widget)
        self.ceus_group.setLayout(ceus_layout)
        self.ceus_group.setStyleSheet("QGroupBox{border:0px;} QGroupBox::title{padding:2px 4px;}")
        left_viewers_row.addWidget(self.ceus_group, stretch=2)

        # Right-center: Overlay viewer
        self.overlay_group = QGroupBox("Overlay")
        overlay_layout = QVBoxLayout()
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        overlay_layout.addWidget(self.overlay_widget)
        self.overlay_group.setLayout(overlay_layout)
        self.overlay_group.setStyleSheet("QGroupBox{border:0px;} QGroupBox::title{padding:2px 4px;}")
        left_viewers_row.addWidget(self.overlay_group, stretch=2)

        # Under the three viewers: playback bar spanning full width of the three viewers
        playback_layout = QHBoxLayout()
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(6)
        playback_layout.addWidget(self.play_button)
        # Spacer between Play button and Frame label/slider
        playback_layout.addItem(QSpacerItem(25, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))
        playback_layout.addWidget(QLabel("Frame:"))
        playback_layout.addWidget(self.frame_slider, stretch=1)
        playback_layout.addWidget(self.frame_info_label)

        left_col_layout = QVBoxLayout()
        left_col_layout.setContentsMargins(0, 0, 0, 0)
        left_col_layout.setSpacing(6)
        left_col_layout.addLayout(left_viewers_row, stretch=1)
        left_col_layout.addLayout(playback_layout)

        left_col_container = QWidget()
        left_col_container.setLayout(left_col_layout)
        viewers_layout.addWidget(left_col_container, stretch=6)

        # Right: ROI controls
        roi_group = QGroupBox("ROI Manager")
        roi_layout = QVBoxLayout()
        roi_layout.setContentsMargins(6, 6, 6, 6)
        roi_layout.setSpacing(12)
        roi_layout.addWidget(self.btn_draw_roi)
        roi_layout.addWidget(self.btn_clear_roi)
        roi_layout.addWidget(self.btn_compute_tic)
        # Separator
        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setFrameShadow(QFrame.Sunken)
        roi_layout.addWidget(sep1)
        roi_layout.addWidget(self.roi_list_label)
        roi_layout.addWidget(self.roi_info_widget)
        # Separator
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        roi_layout.addWidget(sep2)
        roi_layout.addWidget(self.btn_rename_roi)
        roi_layout.addWidget(self.btn_remove_selected_roi)
        roi_layout.addStretch()
        roi_group.setLayout(roi_layout)
        roi_group.setMaximumWidth(250)
        viewers_layout.addWidget(roi_group)

        # ========== BOTTOM: TIC Plot + Fit Panel ==========
        bottom_layout = QHBoxLayout()

        # TIC plot
        tic_group = QGroupBox("Time-Intensity Curves")
        tic_layout = QVBoxLayout()
        tic_layout.addWidget(self.tic_plot)
        tic_group.setLayout(tic_layout)
        # Reduce plot width: make columns more balanced (plot not dominant)
        # Make TIC plot slightly wider than a single viewer column
        bottom_layout.addWidget(tic_group, stretch=3)

        # Fit panel (moved interval toggle into panel + scrollable container)
        fit_group = QGroupBox("Model Fitting")
        fit_layout = QVBoxLayout()
        # Plot settings: expose Tmax first (drives LOESS overlays and model fitting window)
        try:
            self.spin_plot_tmax = QDoubleSpinBox()
            self.spin_plot_tmax.setRange(0.1, 60.0)
            self.spin_plot_tmax.setSingleStep(0.1)
            self.spin_plot_tmax.setValue(7.0)
            self.spin_plot_tmax.setSuffix(" s")
            self.spin_plot_tmax.setToolTip("Maximum time used for LOESS overlays and model fits")
        except Exception:
            self.spin_plot_tmax = None
        # LOESS span control (match R app): affects overlay and optional metrics smoothing (not fitting)
        try:
            # Spin to display precise span value
            self.spin_fit_smooth_window = QDoubleSpinBox()
            self.spin_fit_smooth_window.setRange(0.1, 1.0)
            self.spin_fit_smooth_window.setSingleStep(0.1)
            # Default span set to 0.1 as requested
            self.spin_fit_smooth_window.setValue(0.1)
            self.spin_fit_smooth_window.setSuffix(" span")
            self.spin_fit_smooth_window.setToolTip("LOESS span (fraction of points), like R app")

            # Slider for span (more convenient than only a spinbox)
            self.slider_fit_smooth_span = QSlider(Qt.Horizontal)
            self.slider_fit_smooth_span.setMinimum(10)   # 0.10
            self.slider_fit_smooth_span.setMaximum(100)  # 1.00
            self.slider_fit_smooth_span.setSingleStep(1)
            self.slider_fit_smooth_span.setPageStep(5)
            self.slider_fit_smooth_span.setValue(int(round(self.spin_fit_smooth_window.value() * 100)))
            self.slider_fit_smooth_span.setToolTip("LOESS span (0.10 → 1.00)")

            # Keep spin and slider in sync
            def _sync_span_from_slider(val: int):
                try:
                    span = max(0.1, min(1.0, float(val) / 100.0))
                    if abs(self.spin_fit_smooth_window.value() - span) > 1e-9:
                        self.spin_fit_smooth_window.blockSignals(True)
                        self.spin_fit_smooth_window.setValue(span)
                        self.spin_fit_smooth_window.blockSignals(False)
                    # Trigger overlay recompute
                    self._recompute_overlays_all()
                except Exception:
                    pass

            def _sync_slider_from_spin(val: float):
                try:
                    sval = int(round(float(val) * 100))
                    if self.slider_fit_smooth_span.value() != sval:
                        self.slider_fit_smooth_span.blockSignals(True)
                        self.slider_fit_smooth_span.setValue(sval)
                        self.slider_fit_smooth_span.blockSignals(False)
                except Exception:
                    pass

            self.slider_fit_smooth_span.valueChanged.connect(_sync_span_from_slider)
            self.spin_fit_smooth_window.valueChanged.connect(_sync_slider_from_spin)
        except Exception:
            self.spin_fit_smooth_window = QDoubleSpinBox(); self.spin_fit_smooth_window.setValue(0.66)
        # Combined controls row: Max time + Loess span + slider on a single line
        try:
            from PyQt5.QtWidgets import QWidget as _QW, QHBoxLayout as _QHB, QLabel as _QL
            ctrl_w = _QW()
            row = _QHB(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
            if getattr(self, 'spin_plot_tmax', None) is not None:
                row.addWidget(_QL("Max time:"))
                row.addWidget(self.spin_plot_tmax)
            if getattr(self, 'spin_fit_smooth_window', None) is not None:
                row.addSpacing(12)
                row.addWidget(_QL("Loess span:"))
                row.addWidget(self.spin_fit_smooth_window)
            if getattr(self, 'slider_fit_smooth_span', None) is not None:
                row.addWidget(self.slider_fit_smooth_span)
            ctrl_w.setLayout(row)
            fit_layout.addWidget(ctrl_w)
        except Exception:
            pass
        fit_layout.addWidget(self.fit_panel)
        # Sync Plot Max Time with FitPanel t_max
        try:
            if getattr(self, 'spin_plot_tmax', None) is not None and hasattr(self.fit_panel, 't_max_spin'):
                # Initialize panel from plot setting
                try:
                    self.fit_panel.t_max_spin.setValue(self.spin_plot_tmax.value())
                except Exception:
                    pass
                # Two-way sync
                try:
                    self.spin_plot_tmax.valueChanged.connect(lambda v: self.fit_panel.t_max_spin.setValue(float(v)))
                except Exception:
                    pass
                try:
                    self.fit_panel.t_max_spin.valueChanged.connect(lambda v: self._on_tmax_changed_from_panel(float(v)))
                except Exception:
                    pass
            elif getattr(self, 'spin_plot_tmax', None) is not None:
                # Fallback: just recompute overlays when plot Tmax changes
                try:
                    self.spin_plot_tmax.valueChanged.connect(lambda _: self._recompute_overlays_all())
                except Exception:
                    pass
        except Exception:
            pass
        fit_group.setLayout(fit_layout)
        try:
            from PyQt5.QtWidgets import QScrollArea
            fit_scroll = QScrollArea()
            fit_scroll.setWidgetResizable(True)
            try:
                fit_scroll.setFrameShape(QFrame.NoFrame)
            except Exception:
                pass
            fit_scroll.setWidget(fit_group)
            bottom_layout.addWidget(fit_scroll, stretch=2)
        except Exception:
            bottom_layout.addWidget(fit_group, stretch=2)

        # Metrics table column
        metrics_group = QGroupBox("Metrics")
        metrics_layout = QVBoxLayout()
        try:
            # Option: use smoothed curve for RAW metrics
            from PyQt5.QtWidgets import QCheckBox
            self.chk_metrics_smooth = QCheckBox("Use LOESS for metrics")
            # Enable by default to mirror R app behavior
            self.chk_metrics_smooth.setChecked(True)
            self.chk_metrics_smooth.setToolTip("Compute metrics on LOESS-smoothed TIC (span above), like R")
            metrics_layout.addWidget(self.chk_metrics_smooth)

            self.metrics_table = QTableWidget()
            self.metrics_table.setColumnCount(3)
            self.metrics_table.setHorizontalHeaderLabels(["ROI", "Metric", "Value"])
            try:
                self.metrics_table.horizontalHeader().setStretchLastSection(True)
                self.metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
                self.metrics_table.setSortingEnabled(True)
            except Exception:
                pass
            # Buttons row (refresh + export)
            self.btn_refresh_metrics = QPushButton("🔄 Refresh Metrics")
            self.btn_refresh_metrics.setToolTip("Recompute RAW metrics using only currently included points")
            self.btn_export_metrics = QPushButton("⬇ Export CSV")
            self.btn_export_metrics.setToolTip("Export all RAW and fitted metrics for all ROIs")
            btn_row = QHBoxLayout()
            btn_row.addWidget(self.btn_refresh_metrics)
            btn_row.addWidget(self.btn_export_metrics)
            btn_row.addStretch()
            metrics_layout.addLayout(btn_row)
            # Placeholder initial state
            self.metrics_table.setRowCount(1)
            self.metrics_table.setItem(0, 0, QTableWidgetItem("No metrics"))
            self.metrics_table.setItem(0, 1, QTableWidgetItem("—"))
            self.metrics_table.setItem(0, 2, QTableWidgetItem("—"))
            metrics_layout.addWidget(self.metrics_table)
        except Exception:
            placeholder = QLabel("No metrics yet")
            metrics_layout.addWidget(placeholder)
        metrics_group.setLayout(metrics_layout)
        bottom_layout.addWidget(metrics_group, stretch=2)

        # ---- Combine viewers and bottom sections using a vertical splitter ----
        viewers_container = QWidget()
        viewers_container.setLayout(viewers_layout)

        bottom_container = QWidget()
        bottom_container.setLayout(bottom_layout)
        bottom_container.setMinimumHeight(220)  # Ensure bottom panel never too small

        # Splitter for adjustable ratio
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(viewers_container)
        splitter.addWidget(bottom_container)

        # Default ratio: increase plot height by ~10% (50/50)
        total_h = self.height() if self.height() > 0 else 1000
        splitter.setSizes([int(total_h * 0.5), int(total_h * 0.5)])

        main_layout.addWidget(splitter)

        # Status bar with spinner on the right
        try:
            # Build spinner (single reusable instance)
            self.spinner_label = QLabel()
            # Try local resources first, fallback to Qt built-in working.gif
            try:
                local_gif = Path(__file__).parent.parent / 'resources' / 'loading.gif'
                if local_gif.exists():
                    self.spinner_movie = QMovie(str(local_gif))
                else:
                    self.spinner_movie = QMovie(":/qt-project.org/styles/commonstyle/images/working.gif")
            except Exception:
                self.spinner_movie = QMovie(":/qt-project.org/styles/commonstyle/images/working.gif")
            try:
                self.spinner_movie.setScaledSize(QSize(16, 16))
            except Exception:
                pass
            self.spinner_label.setMovie(self.spinner_movie)
            self.spinner_label.setFixedSize(16, 16)
            self.spinner_label.setVisible(False)
            self.spinner_label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)

            self.status_layout = QHBoxLayout()
            self.status_layout.setContentsMargins(0, 0, 0, 0)
            self.status_layout.setSpacing(6)
            self.status_layout.addWidget(self.status_label)
            self.status_layout.addWidget(self.spinner_label)
            self.status_layout.addStretch()

            self.status_container = QWidget()
            self.status_container.setLayout(self.status_layout)
            main_layout.addWidget(self.status_container)
        except Exception:
            # Fallback to status label alone if spinner init fails
            main_layout.addWidget(self.status_label)

        # Let Qt manage heights: ensure viewers expand evenly without fixed heights
        try:
            for grp in (self.bmode_group, self.ceus_group, self.overlay_group):
                grp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        except Exception:
            pass

        self.setLayout(main_layout)
    
    def _connect_signals(self):
        """Connect signals and slots"""
        # Top buttons
        self.btn_load.clicked.connect(self.load_dicom)
        self.btn_detect_flash.clicked.connect(self.detect_flash)
        self.btn_set_flash_manual.clicked.connect(self.set_flash_manual)
        self.btn_motion_correction.clicked.connect(self.apply_motion_correction)
        self.btn_preprocess.clicked.connect(self.preprocess_ceus_stack)
        self.btn_reset.clicked.connect(self.reset_analysis)
        
        # ROI controls
        self.btn_draw_roi.toggled.connect(self.toggle_roi_drawing)
        self.btn_clear_roi.clicked.connect(self.clear_rois)
        self.btn_compute_tic.clicked.connect(self.compute_all_tics)
        self.btn_sync_zoom.toggled.connect(self._enable_sync_camera)
        # ROI list actions
        self.roi_info_widget.itemSelectionChanged.connect(self._on_roi_selection_changed)
        self.btn_remove_selected_roi.clicked.connect(self._on_remove_selected_roi)
        self.btn_rename_roi.clicked.connect(self._on_rename_selected_roi)
        
        # Playback
        self.play_button.clicked.connect(self.toggle_playback)
        self.frame_slider.valueChanged.connect(self.on_frame_changed)
        # TIC interactions
        try:
            self.tic_plot.point_clicked.connect(self._on_tic_point_clicked)
        except Exception:
            pass
        
        # Napari viewer events
        self.ceus_viewer.dims.events.current_step.connect(self._on_napari_frame_changed)
        # Connect shapes events for B-mode (master layer) if it exists now; else it will be connected upon creation
        if getattr(self, 'bmode_shapes_layer', None) is not None:
            try:
                self.bmode_shapes_layer.events.data.connect(self._on_shapes_changed)
            except Exception:
                pass
        
        # Fit panel
        self.fit_panel.fit_requested.connect(self.on_fit_requested)
        # Interval selector disabled; do not connect/use it
        self.chk_fit_use_region = None
        # Metrics buttons
        try:
            if hasattr(self, 'btn_refresh_metrics'):
                self.btn_refresh_metrics.clicked.connect(self._refresh_metrics_table)
            if hasattr(self, 'btn_export_metrics'):
                self.btn_export_metrics.clicked.connect(self._export_metrics_csv)
            if hasattr(self, 'chk_metrics_smooth'):
                self.chk_metrics_smooth.toggled.connect(lambda _: self._refresh_metrics_table())
            # Recompute overlay when LOESS span changes
            if hasattr(self, 'spin_fit_smooth_window'):
                try:
                    self.spin_fit_smooth_window.valueChanged.connect(lambda _: self._recompute_overlays_all())
                except Exception:
                    pass
        except Exception:
            pass

    def _setup_shortcuts(self):
        """Define keyboard shortcuts for faster workflow"""
        try:
            # D: Toggle ROI drawing
            sc_draw = QShortcut(QKeySequence('D'), self)
            sc_draw.activated.connect(lambda: self.btn_draw_roi.toggle())
            # Delete: Remove selected ROI(s)
            sc_del = QShortcut(QKeySequence('Delete'), self)
            sc_del.activated.connect(self._on_remove_selected_roi)
            # R: Rename selected ROI
            sc_ren = QShortcut(QKeySequence('R'), self)
            sc_ren.activated.connect(self._on_rename_selected_roi)
            # S: Toggle sync zoom/pan
            sc_sync = QShortcut(QKeySequence('S'), self)
            sc_sync.activated.connect(lambda: self.btn_sync_zoom.toggle())
            # E: Toggle point for current frame and selected ROI
            sc_toggle_frame = QShortcut(QKeySequence('E'), self)
            sc_toggle_frame.activated.connect(self._toggle_current_frame_selected_roi)
        except Exception:
            pass
    
    # =========================================================================
    # DICOM Loading
    # =========================================================================
    
    def load_dicom(self):
        """Load DICOM file"""
        default_path = Path(__file__).parent.parent.parent / "data"
        if not default_path.exists():
            default_path = Path.home()
        # Improve perceived responsiveness before opening the file dialog
        try:
            self.status_label.setText("Sélection d'un fichier DICOM…")
            self.app.processEvents()
        except Exception:
            pass
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DICOM file",
            str(default_path),
            "DICOM files (*);;All files (*)"
        )
        
        if not file_path:
            return
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._show_spinner(True)
            self.status_label.setText("Loading DICOM...")
            
            # Stop playback
            if self.is_playing:
                self.toggle_playback()
            
            # Reset data
            self.ceus_preprocessed = None
            self.flash_idx = None
            self.washout_idx = None
            self.roi_manager.clear()
            self.roi_tic_data.clear()
            self.tic_plot.clear()
            
            # Load DICOM
            self.dicom_loader = DICOMLoader(Path(file_path))
            self.bmode_stack, self.ceus_stack = self.dicom_loader.load()
            self.fps = self.dicom_loader.get_fps()
            (
                self._bmode_display_stack,
                self._bmode_is_rgb,
                self._bmode_channel_axis,
            ) = self._prepare_display_stack(self.bmode_stack)
            # Precompute robust contrast limits for B-mode
            try:
                self._bmode_auto_clims = self._compute_bmode_limits(self._bmode_display_stack, q=(1, 99))
            except Exception:
                self._bmode_auto_clims = None
            (
                self._ceus_display_stack,
                self._ceus_is_rgb,
                self._ceus_channel_axis,
            ) = self._prepare_display_stack(self.ceus_stack)
            self._current_ceus_layer_name = 'CEUS (raw)'
            
            if self.ceus_stack is None:
                QMessageBox.warning(self, "Warning", "No CEUS stack found in DICOM")
                return
            
            # Display in Napari viewers
            if self.bmode_stack is not None:
                # Remove existing layers
                for layer in list(self.bmode_viewer.layers):
                    if layer.name != 'ROIs':
                        self.bmode_viewer.layers.remove(layer)
                if self._bmode_display_stack is not None:
                    b_layer = self._add_image_layer(
                        self.bmode_viewer,
                        self._bmode_display_stack,
                        name='B-mode',
                        channel_axis=self._bmode_channel_axis,
                        rgb=self._bmode_is_rgb,
                        colormap='gray',
                        blending='opaque'
                    )
                    # Apply auto-contrast and gamma
                    try:
                        if b_layer is not None and self._bmode_auto_clims is not None:
                            lo, hi = self._bmode_auto_clims
                            if lo is not None and hi is not None:
                                b_layer.contrast_limits = (float(lo), float(hi))
                        if b_layer is not None and hasattr(b_layer, 'gamma'):
                            b_layer.gamma = float(self._bmode_gamma)
                    except Exception:
                        pass
            
            # Remove existing CEUS layers
            for layer in list(self.ceus_viewer.layers):
                if layer.name not in ['ROIs']:
                    self.ceus_viewer.layers.remove(layer)
            if self._ceus_display_stack is not None:
                self._add_image_layer(
                    self.ceus_viewer,
                    self._ceus_display_stack,
                    name=self._current_ceus_layer_name,
                    channel_axis=self._ceus_channel_axis,
                    rgb=self._ceus_is_rgb,
                    colormap='gray',
                    blending='additive',
                    opacity=0.7
                )

            # Create/update ROI canvas above CEUS and shapes layer on top
            self._remove_roi_canvas_if_exists()
            self._ensure_roi_canvas_layer()
            self._ensure_shapes_layer_exists_on_top()
            # Configure ROI master depending on B-mode presence
            if self.bmode_stack is not None:
                self._ensure_bmode_shapes_layer_exists_on_top()
                self._set_roi_master('bmode')
                self._mirror_shapes_to_ceus()
            else:
                self._set_roi_master('ceus')

            # Update overlay with current data
            self._update_overlay_layers()
            # Equalize initial camera view across viewers (one-time)
            try:
                self._on_master_camera_changed()
            except Exception:
                pass
            
            # Setup frame slider
            n_frames = self.ceus_stack.shape[0]
            self.frame_slider.setMaximum(n_frames - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            
            # Update status
            manufacturer = self.dicom_loader.scanner_info.get('Manufacturer', 'Unknown')
            model = self.dicom_loader.scanner_info.get('ManufacturerModelName', '')
            bmode_info = f"B-mode: {self.bmode_stack.shape}" if self.bmode_stack is not None else "No B-mode"
            self.status_label.setText(
                f"✅ Loaded: {Path(file_path).name} | "
                f"{manufacturer} {model} | "
                f"FPS: {self.fps:.1f} | "
                f"CEUS: {self.ceus_stack.shape} | {bmode_info}"
            )
            # Diagnostics (status tooltip + console) to investigate color format issues
            try:
                photo = self.dicom_loader.metadata.get('PhotometricInterpretation', None)
                def _ch_stats(frame):
                    try:
                        if frame.ndim == 3 and frame.shape[-1] == 3:
                            ch = [frame[..., i] for i in range(3)]
                            stats = [
                                (float(np.nanmin(c)), float(np.nanmax(c)), float(np.nanmean(c)), float(np.nanstd(c)))
                                for c in ch
                            ]
                            return stats
                        else:
                            return [(float(np.nanmin(frame)), float(np.nanmax(frame)), float(np.nanmean(frame)), float(np.nanstd(frame)))]
                    except Exception:
                        return []
                # Sample middle frame when possible
                ceus_sample = None
                bmode_sample = None
                try:
                    if self.ceus_stack is not None:
                        ceus_sample = self.ceus_stack[min(len(self.ceus_stack)//2, len(self.ceus_stack)-1)]
                    if self.bmode_stack is not None:
                        bmode_sample = self.bmode_stack[min(len(self.bmode_stack)//2, len(self.bmode_stack)-1)]
                except Exception:
                    pass
                ceus_dtype = getattr(self.ceus_stack, 'dtype', None)
                bmode_dtype = getattr(self.bmode_stack, 'dtype', None)
                ceus_stats = _ch_stats(ceus_sample) if ceus_sample is not None else []
                bmode_stats = _ch_stats(bmode_sample) if bmode_sample is not None else []
                diag_lines = [
                    f"PhotometricInterpretation={photo}",
                    f"CEUS dtype={ceus_dtype}, stats={ceus_stats[:3] if ceus_stats else 'n/a'}",
                    f"B-mode dtype={bmode_dtype}, stats={bmode_stats[:3] if bmode_stats else 'n/a'}",
                ]
                diag_text = " | ".join(diag_lines)
                # Console log
                print("[DICOM DIAG]", diag_text)
                # Tooltip for quick inspection
                try:
                    self.status_label.setToolTip(diag_text)
                except Exception:
                    pass
            except Exception:
                pass
            
            self._update_ui_state()
            self._update_frame_info()
            # Set initial TIC x-range to full raw duration
            try:
                if self.fps and self.fps > 0 and self.ceus_stack is not None:
                    total_dur = len(self.ceus_stack) / float(self.fps)
                    self.tic_plot.plotItem.setXRange(0, total_dur)
            except Exception:
                pass
            # Refresh info label defaults
            self._update_status_info()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load DICOM:\n{str(e)}")
            self.status_label.setText(f"❌ Error loading DICOM: {str(e)}")
        finally:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            try:
                self._show_spinner(False)
            except Exception:
                pass
    
    # =========================================================================
    # Flash Detection
    # =========================================================================
    
    def detect_flash(self):
        """Detect flash and washout"""
        if self.ceus_stack is None:
            return
        
        try:
            self._show_spinner(True)
            self.status_label.setText("Detecting flash...")
            
            self.flash_idx, self.washout_idx, _ = detect_flash_ceus_refined(
                self.ceus_stack,
                exclude_first_n=5,
                search_window=20
            )
            
            self.status_label.setText(
                f"⚡ Flash detected at frame {self.flash_idx}, "
                f"washout at frame {self.washout_idx}"
            )
            
            self._update_ui_state()
            self._update_status_info()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Flash detection failed:\n{str(e)}")
        finally:
            try:
                self._show_spinner(False)
            except Exception:
                pass
    
    def set_flash_manual(self):
        """Set flash frame manually to current frame"""
        if self.ceus_stack is None:
            return
        
        self.flash_idx = self.current_frame
        
        # Estimate washout
        search_window = 20
        ceus_data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        
        if ceus_data.ndim == 4:
            intensities = ceus_data.mean(axis=(1, 2, 3))
        else:
            intensities = ceus_data.mean(axis=(1, 2))
        
        search_start = self.flash_idx
        search_end = min(len(intensities), self.flash_idx + search_window)
        self.washout_idx = search_start + np.argmin(intensities[search_start:search_end])
        
        self.status_label.setText(
            f"✋ Flash manually set to frame {self.flash_idx}, "
            f"washout estimated at frame {self.washout_idx}"
        )
        
        self._update_ui_state()
        self._update_status_info()
    
    # =========================================================================
    # Preprocessing
    # =========================================================================
    
    def preprocess_ceus_stack(self):
        """Preprocess CEUS stack"""
        if self.ceus_stack is None or self.washout_idx is None:
            return
        
        try:
            self.status_label.setText("Preprocessing CEUS...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._show_spinner(True)
            
            # Crop to washout + 15s
            duration_s = 15
            frames_15s = int(duration_s * self.fps)
            end_idx = min(self.washout_idx + frames_15s, len(self.ceus_stack))
            ceus_cropped = self.ceus_stack[self.washout_idx:end_idx]
            
            # Preprocess
            self.ceus_preprocessed = preprocess_ceus(
                ceus_cropped,
                use_log=True,
                spatial='median',
                temporal='gaussian',
                t_win=3,
                baseline_frames=5
            )
            (
                self._ceus_display_stack,
                self._ceus_is_rgb,
                self._ceus_channel_axis,
            ) = self._prepare_display_stack(self.ceus_preprocessed)
            self._current_ceus_layer_name = 'CEUS (preprocessed)'
            
            # Update CEUS viewer
            for layer in list(self.ceus_viewer.layers):
                if 'CEUS' in layer.name:
                    self.ceus_viewer.layers.remove(layer)
            if self._ceus_display_stack is not None:
                self._add_image_layer(
                    self.ceus_viewer,
                    self._ceus_display_stack,
                    name=self._current_ceus_layer_name,
                    channel_axis=self._ceus_channel_axis,
                    rgb=self._ceus_is_rgb,
                    colormap='magma',
                    blending='additive',
                    opacity=0.7
                )

            # Recreate ROI canvas and ensure shapes on top
            self._remove_roi_canvas_if_exists()
            self._ensure_roi_canvas_layer()
            self._ensure_shapes_layer_exists_on_top()
            if self.bmode_stack is not None:
                self._ensure_bmode_shapes_layer_exists_on_top()
                self._set_roi_master('bmode')
                self._mirror_shapes_to_ceus()
            else:
                self._set_roi_master('ceus')

            # Update overlay with preprocessed data
            self._update_overlay_layers()
            # Keep cameras aligned after update
            try:
                self._on_master_camera_changed()
            except Exception:
                pass
            # Constrain TIC x-axis to preprocessing duration
            try:
                duration_s = 15
                self.tic_plot.plotItem.setXRange(0, duration_s)
            except Exception:
                pass
            
            # Reset frame controls
            self.frame_slider.setMaximum(len(self.ceus_preprocessed) - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            self._update_frame_info()
            
            self.status_label.setText("✅ Preprocessing complete")
            self._update_ui_state()
            self._update_status_info()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Preprocessing failed:\n{str(e)}")
            self.status_label.setText(f"❌ Preprocessing error: {str(e)}")
        finally:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            try:
                self._show_spinner(False)
            except Exception:
                pass
    
    # =========================================================================
    # Motion Correction
    # =========================================================================
    
    def apply_motion_correction(self):
        """Apply motion correction"""
        if self.ceus_stack is None or self.washout_idx is None:
            return
        
        try:
            self.status_label.setText("Applying motion correction...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._show_spinner(True)
            
            # Crop stacks (align B-mode and CEUS on same time window)
            duration_s = 15
            frames_15s = int(duration_s * self.fps)
            end_idx = min(self.washout_idx + frames_15s, len(self.ceus_stack))
            ceus_cropped = self.ceus_stack[self.washout_idx:end_idx]
            bmode_cropped = None
            if self.bmode_stack is not None:
                try:
                    bmode_cropped = self.bmode_stack[self.washout_idx:end_idx]
                except Exception:
                    bmode_cropped = None
            
            # Motion compensate (estimate shifts on B-mode window when available)
            from src.core.motion_compensation import apply_shifts_to_stack
            ceus_corrected, shifts, source_info = motion_compensate(
                ceus_cropped,
                bmode_cropped
            )
            
            # Preprocess corrected stack
            self.ceus_preprocessed = preprocess_ceus(
                ceus_corrected,
                use_log=True,
                spatial='median',
                temporal='gaussian',
                t_win=3,
                baseline_frames=5
            )
            (
                self._ceus_display_stack,
                self._ceus_is_rgb,
                self._ceus_channel_axis,
            ) = self._prepare_display_stack(self.ceus_preprocessed)
            self._current_ceus_layer_name = 'CEUS (motion corrected + preprocessed)'

            # Also stabilize B-mode for the same window using estimated shifts
            if bmode_cropped is not None and shifts is not None:
                try:
                    bmode_stabilized = apply_shifts_to_stack(bmode_cropped, shifts, pad_mode='nearest', order=1)
                    (
                        self._bmode_display_stack,
                        self._bmode_is_rgb,
                        self._bmode_channel_axis,
                    ) = self._prepare_display_stack(bmode_stabilized)
                    # Recompute auto-contrast for stabilized window
                    try:
                        self._bmode_auto_clims = self._compute_bmode_limits(self._bmode_display_stack, q=(1, 99))
                    except Exception:
                        pass
                    # Update B-mode viewer layer
                    for layer in list(self.bmode_viewer.layers):
                        if layer.name != 'ROIs':
                            self.bmode_viewer.layers.remove(layer)
                    b_layer = self._add_image_layer(
                        self.bmode_viewer,
                        self._bmode_display_stack,
                        name='B-mode (stabilized)',
                        channel_axis=self._bmode_channel_axis,
                        rgb=self._bmode_is_rgb,
                        colormap='gray',
                        blending='opaque'
                    )
                    try:
                        if b_layer is not None and self._bmode_auto_clims is not None:
                            lo, hi = self._bmode_auto_clims
                            if lo is not None and hi is not None:
                                b_layer.contrast_limits = (float(lo), float(hi))
                        if b_layer is not None and hasattr(b_layer, 'gamma'):
                            b_layer.gamma = float(self._bmode_gamma)
                    except Exception:
                        pass
                except Exception:
                    pass
            
            # Update viewer
            for layer in list(self.ceus_viewer.layers):
                if 'CEUS' in layer.name:
                    self.ceus_viewer.layers.remove(layer)
            if self._ceus_display_stack is not None:
                self._add_image_layer(
                    self.ceus_viewer,
                    self._ceus_display_stack,
                    name=self._current_ceus_layer_name,
                    channel_axis=self._ceus_channel_axis,
                    rgb=self._ceus_is_rgb,
                    colormap='magma',
                    blending='additive',
                    opacity=0.7
                )

            # Recreate ROI canvas and ensure shapes on top
            self._remove_roi_canvas_if_exists()
            self._ensure_roi_canvas_layer()
            self._ensure_shapes_layer_exists_on_top()
            if self.bmode_stack is not None:
                self._ensure_bmode_shapes_layer_exists_on_top()
                self._set_roi_master('bmode')
                self._mirror_shapes_to_ceus()
            else:
                self._set_roi_master('ceus')
            
            # Reset frame controls
            self.frame_slider.setMaximum(len(self.ceus_preprocessed) - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            self._update_frame_info()
            # Constrain TIC x-axis to preprocessing duration (same 15s window)
            try:
                duration_s = 15
                self.tic_plot.plotItem.setXRange(0, duration_s)
            except Exception:
                pass
            
            self.status_label.setText(
                f"✅ Motion correction complete (estimated from {source_info})"
            )
            self._update_ui_state()
            self._update_status_info()

            # Update overlay with motion-corrected preprocessed data
            self._update_overlay_layers()
            try:
                self._on_master_camera_changed()
            except Exception:
                pass
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Motion correction failed:\n{str(e)}")
            self.status_label.setText(f"❌ Motion correction error: {str(e)}")
        finally:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            try:
                self._show_spinner(False)
            except Exception:
                pass
    
    # =========================================================================
    # ROI Management
    # =========================================================================
    
    def toggle_roi_drawing(self, checked: bool):
        """Toggle ROI drawing mode"""
        if checked:
            # Choose master layer depending on availability
            if self.bmode_stack is not None:
                self._set_roi_master('bmode')
                self._ensure_bmode_shapes_layer_exists_on_top()
                self.bmode_viewer.layers.selection = [self.bmode_shapes_layer]
                self.bmode_shapes_layer.mode = 'add_polygon'
            else:
                self._set_roi_master('ceus')
                self._ensure_shapes_layer_exists_on_top()
                self.ceus_viewer.layers.selection = [self.shapes_layer]
                self.shapes_layer.mode = 'add_polygon'
            # Disable pan/zoom on all viewers while drawing to avoid accidental moves
            self._set_cameras_interactive(False)
            self.status_label.setText("✏️ ROI drawing (B-mode): cliquez pour placer des points, fermez le polygone pour terminer")
            self.btn_draw_roi.setText("🛑 Stop Drawing")
        else:
            # Return B-mode shapes layer to pan/zoom
            try:
                if self._roi_master == 'bmode' and getattr(self, 'bmode_shapes_layer', None) is not None:
                    self.bmode_shapes_layer.mode = 'pan_zoom'
                elif self._roi_master == 'ceus' and getattr(self, 'shapes_layer', None) is not None:
                    self.shapes_layer.mode = 'pan_zoom'
            except Exception:
                pass
            # Re-enable camera interactions
            self._set_cameras_interactive(True)
            self.status_label.setText("ROI drawing disabled")
            self.btn_draw_roi.setText("✏️ Draw ROI (Polygon)")

    def _set_camera_interactive(self, enabled: bool):
        """Enable/disable camera interactions (pan/zoom) on CEUS viewer."""
        try:
            # Prefer napari viewer camera to avoid Qt deprecations
            self.ceus_viewer.camera.interactive = enabled
        except Exception:
            pass

    def _set_cameras_interactive(self, enabled: bool):
        """Enable/disable camera interactions on all viewers."""
        try:
            self.bmode_viewer.camera.interactive = enabled
        except Exception:
            pass
        try:
            self.ceus_viewer.camera.interactive = enabled
        except Exception:
            pass
        try:
            self.overlay_viewer.camera.interactive = enabled
        except Exception:
            pass

    def _bring_shapes_to_front(self):
        """Move the ROIs shapes layer to the top of the CEUS viewer stack so it appears above image layers."""
        try:
            layers = self.ceus_viewer.layers
            if getattr(self, 'shapes_layer', None) in layers:
                idx = layers.index(self.shapes_layer)
                layers.move(idx, len(layers) - 1)
        except Exception:
            pass

    def _ensure_shapes_on_top(self):
        """Ensure the shapes layer is last; if moving fails, recreate it at the top preserving data."""
        try:
            layers = self.ceus_viewer.layers
            if getattr(self, 'shapes_layer', None) in layers:
                if layers.index(self.shapes_layer) != len(layers) - 1:
                    try:
                        layers.move(layers.index(self.shapes_layer), len(layers) - 1)
                        return
                    except Exception:
                        pass
                else:
                    return  # already on top
        except Exception:
            pass

        # Fallback: recreate shapes layer at top
        try:
            data = []
            if getattr(self, 'shapes_layer', None) is not None:
                try:
                    data = list(self.shapes_layer.data)
                except Exception:
                    data = []
                # remove old layer
                try:
                    self.ceus_viewer.layers.remove(self.shapes_layer)
                except Exception:
                    pass
            # add new shapes layer on top
            self.shapes_layer = self.ceus_viewer.add_shapes(
                data=data,
                name='ROIs',
                edge_color='red',
                edge_width=2,
                face_color='transparent',
                opacity=0.7,
                blending='translucent_no_depth'
            )
            # reconnect events
            self.shapes_layer.events.data.connect(self._on_shapes_changed)
        except Exception as e:
            print(f"[DEBUG] Failed to recreate shapes layer on top: {e}")

    def _ensure_shapes_layer_exists_on_top(self):
        """Create the shapes layer if missing, with proper properties and z-order above images."""
        try:
            if self.shapes_layer is None or self.shapes_layer not in self.ceus_viewer.layers:
                self.shapes_layer = self.ceus_viewer.add_shapes(
                    name='ROIs',
                    edge_color='red',
                    edge_width=2,
                    face_color='transparent',
                    opacity=0.7,
                    blending='translucent_no_depth'
                )
                # Place on top and ensure very high z-index for 2D draw order
                try:
                    self.shapes_layer.z_index = 10_000
                except Exception:
                    pass
            # Make sure it's last anyway
            self._ensure_shapes_on_top()
        except Exception as e:
            print(f"[DEBUG] ensure shapes layer exists error: {e}")

    def _ensure_bmode_shapes_layer_exists_on_top(self):
        """Create a shapes layer on the B-mode viewer if missing, used to mirror CEUS ROIs."""
        try:
            if self.bmode_stack is None:
                return
            if self.bmode_shapes_layer is None or self.bmode_shapes_layer not in self.bmode_viewer.layers:
                self.bmode_shapes_layer = self.bmode_viewer.add_shapes(
                    name='ROIs (B-mode)',
                    edge_color='red',
                    edge_width=2,
                    face_color='transparent',
                    opacity=0.7,
                    blending='translucent_no_depth'
                )
                try:
                    self.bmode_shapes_layer.z_index = 10_000
                except Exception:
                    pass
                # Connect events for ROI updates (B-mode as master)
                try:
                    self.bmode_shapes_layer.events.data.connect(self._on_shapes_changed)
                except Exception:
                    pass
            # Move last
            try:
                layers = self.bmode_viewer.layers
                if self.bmode_shapes_layer in layers and layers.index(self.bmode_shapes_layer) != len(layers) - 1:
                    layers.move(layers.index(self.bmode_shapes_layer), len(layers) - 1)
            except Exception:
                pass
        except Exception as e:
            print(f"[DEBUG] ensure B-mode shapes layer exists error: {e}")

    def _mirror_shapes_to_ceus(self):
        """Copy current B-mode shapes into CEUS shapes layer (2D coords)."""
        try:
            if self.shapes_layer is None or self.bmode_shapes_layer is None:
                return
            self._ensure_shapes_layer_exists_on_top()
            shapes = []
            for poly in list(self.bmode_shapes_layer.data):
                try:
                    # poly shape: (N,2) [y,x] or (N,3) [t,y,x]; convert to (N,2)
                    if hasattr(poly, 'shape') and len(poly.shape) == 2 and poly.shape[1] == 3:
                        coords = poly[:, 1:3]
                    else:
                        coords = poly
                except Exception:
                    coords = poly
                shapes.append(coords)
            self.shapes_layer.data = shapes
        except Exception as e:
            print(f"[DEBUG] mirror shapes to CEUS error: {e}")

    def _mirror_shapes_to_bmode(self):
        """Copy current CEUS shapes into B-mode shapes layer (2D coords)."""
        try:
            if self.shapes_layer is None or self.bmode_shapes_layer is None:
                return
            shapes = []
            for poly in list(self.shapes_layer.data):
                try:
                    shapes.append(poly)
                except Exception:
                    shapes.append(poly)
            self.bmode_shapes_layer.data = shapes
        except Exception as e:
            print(f"[DEBUG] mirror shapes to B-mode error: {e}")

    def _set_roi_master(self, master: str):
        """Set which shapes layer is the ROI master ('bmode' or 'ceus') and connect events accordingly."""
        if master not in ('bmode', 'ceus'):
            return
        self._roi_master = master
        try:
            # Disconnect to avoid duplicate callbacks
            if getattr(self, 'bmode_shapes_layer', None) is not None:
                try:
                    self.bmode_shapes_layer.events.data.disconnect(self._on_shapes_changed)
                except Exception:
                    pass
            if getattr(self, 'shapes_layer', None) is not None:
                try:
                    self.shapes_layer.events.data.disconnect(self._on_shapes_changed)
                except Exception:
                    pass
            if master == 'bmode' and self.bmode_stack is not None:
                self._ensure_bmode_shapes_layer_exists_on_top()
                try:
                    self.bmode_shapes_layer.events.data.connect(self._on_shapes_changed)
                except Exception:
                    pass
                self._mirror_shapes_to_ceus()
            else:
                self._ensure_shapes_layer_exists_on_top()
                try:
                    self.shapes_layer.events.data.connect(self._on_shapes_changed)
                except Exception:
                    pass
                if self.bmode_stack is not None:
                    self._ensure_bmode_shapes_layer_exists_on_top()
                    self._mirror_shapes_to_bmode()
        except Exception as e:
            print(f"[DEBUG] set_roi_master error: {e}")

    def _ensure_roi_canvas_layer(self):
        """Ensure an empty image layer exists above CEUS to anchor ROI draw order.
        This layer is fully transparent and same shape as CEUS; it helps force ROIs to render above.
        """
        try:
            data, _, channel_axis, is_rgb = self._get_current_ceus_data()
            if data is None:
                return
            # Create an all-zeros float32 image matching CEUS spatial dims
            # If CEUS is RGB, drop the color channel for the canvas
            if is_rgb:
                canvas_shape = data.shape[:-1]
            else:
                canvas_shape = data.shape if channel_axis is None else data.shape[:-1]
            canvas = np.zeros(canvas_shape, dtype=np.float32)
            # Add as image with zero opacity to anchor ROI z-order
            self.roi_canvas_layer = self._add_image_layer(
                self.ceus_viewer,
                canvas,
                name='ROI Canvas',
                channel_axis=None,
                rgb=False,
                colormap='gray',
                blending='translucent_no_depth',
                opacity=0.0,
            )
            try:
                self.roi_canvas_layer.z_index = 9_999
            except Exception:
                pass
        except Exception as e:
            print(f"[DEBUG] ensure ROI canvas error: {e}")

    def _remove_roi_canvas_if_exists(self):
        try:
            if self.roi_canvas_layer is not None and self.roi_canvas_layer in self.ceus_viewer.layers:
                self.ceus_viewer.layers.remove(self.roi_canvas_layer)
            self.roi_canvas_layer = None
        except Exception:
            pass

    def _show_spinner(self, show: bool = True):
        """Show or hide the small loading spinner next to the status text."""
        try:
            if hasattr(self, 'spinner_label') and hasattr(self, 'spinner_movie'):
                self.spinner_label.setVisible(show)
                if show:
                    try:
                        self.spinner_movie.start()
                    except Exception:
                        pass
                else:
                    try:
                        self.spinner_movie.stop()
                    except Exception:
                        pass
        except Exception:
            pass

    def _update_status_info(self):
        """Met à jour le label d'information d'analyse au-dessus des viewers.
        Affiche Flash, Washout (en frame et secondes si FPS connu) et le nombre de ROIs actifs.
        """
        try:
            # ROI count
            roi_count = len(self.roi_manager.rois) if hasattr(self, 'roi_manager') and self.roi_manager else 0

            def fmt_idx_time(idx):
                if idx is None:
                    return "—"
                if self.fps and self.fps > 0:
                    t = idx / float(self.fps)
                    return f"{idx} ({t:.2f}s)"
                return f"{idx}"

            flash_txt = fmt_idx_time(self.flash_idx)
            washout_txt = fmt_idx_time(self.washout_idx)

            self.analysis_info_label.setText(
                f"Flash: {flash_txt}   Washout: {washout_txt}   ROI: {roi_count} active"
            )
        except Exception:
            # Ne casse pas l'appli si le label n'est pas prêt
            pass

    def _prepare_display_stack(
        self,
        stack: Optional[np.ndarray]
    ) -> tuple[Optional[np.ndarray], bool, Optional[int]]:
        """Prepare a stack for Napari display, preserving true-color RGB.

        Returns (data, is_rgb, channel_axis). `is_rgb=True` when the last dimension
        is a color channel of size 3 or 4 and we want to display with original colors.
        `channel_axis` is used only for true multi-channel (non-RGB) stacks.
        """
        if stack is None:
            return None, False, None

        data = np.asarray(stack)
        is_rgb = False
        channel_axis: Optional[int] = None
        # Preserve RGB and ensure dtype/scale compatible with napari
        if data.ndim >= 3 and data.shape[-1] in (3, 4):
            is_rgb = True
            if np.issubdtype(data.dtype, np.integer):
                if data.dtype in (np.uint8, np.uint16):
                    # OK for napari
                    pass
                else:
                    # Linearly scale arbitrary integer type to uint8
                    info = np.iinfo(data.dtype)
                    d = data.astype(np.float32)
                    rng = float(info.max - info.min) if info.max > info.min else 1.0
                    d = (d - float(info.min)) * (255.0 / rng)
                    data = np.clip(d, 0, 255).astype(np.uint8)
            else:
                # Float input: prefer [0,1]; if looks like 0..255, convert to uint8
                try:
                    vmin = float(np.nanmin(data))
                    vmax = float(np.nanmax(data))
                except Exception:
                    vmin, vmax = 0.0, 1.0
                if 0.0 <= vmin and vmax <= 1.0:
                    data = data.astype(np.float32, copy=False)
                else:
                    data = np.clip(data, 0.0, 255.0).astype(np.uint8)
        else:
            # Grayscale path for analysis
            if data.dtype != np.float32:
                data = data.astype(np.float32, copy=False)

        return data, is_rgb, channel_axis

    def _to_grayscale_stack(self, stack: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Return a float32 grayscale representation used for analysis tasks."""
        if stack is None:
            return None

        data = np.asarray(stack)
        if data.ndim == 4 and data.shape[-1] == 3:
            try:
                data = np.stack([to_gray(frame) for frame in data], axis=0)
            except Exception:
                try:
                    data = data.mean(axis=-1)
                except Exception:
                    try:
                        data = data[..., 0]
                    except Exception:
                        return None

        return data.astype(np.float32, copy=False)

    def _compute_bmode_limits(self, stack: Optional[np.ndarray], q: tuple = (1, 99)) -> Optional[tuple]:
        """Compute robust contrast limits for B-mode display using percentiles.

        - Works for 3D (T,H,W) and 4D (T,H,W,C) stacks; for color stacks uses channel mean.
        - Samples up to 10 frames evenly to keep it fast.
        """
        try:
            if stack is None:
                return None
            X = np.asarray(stack)
            # Convert color to luminance-like by averaging channels for limits
            if X.ndim == 4 and X.shape[-1] in (3, 4):
                X = X[..., :3].mean(axis=-1)
            # Sample frames
            if X.ndim >= 3:
                T = X.shape[0]
                idx = np.linspace(0, T - 1, num=min(T, 10), dtype=int)
                sample = X[idx].ravel()
            else:
                sample = X.ravel()
            low, high = np.percentile(sample, q)
            if not np.isfinite(low) or not np.isfinite(high) or low >= high:
                return None
            return float(low), float(high)
        except Exception:
            return None

    def _add_image_layer(
        self,
        viewer: napari.Viewer,
        data: Optional[np.ndarray],
        *,
        name: str,
        channel_axis: Optional[int],
        rgb: Optional[bool] = None,
        colormap: str = 'gray',
        **kwargs
    ):
        """Utility to add an image layer with optional RGB handling."""
        if data is None:
            return None

        layer_kwargs = dict(name=name, **kwargs)
        # Prefer true-color display when requested
        if bool(rgb):
            layer_kwargs['rgb'] = True
        elif channel_axis is not None:
            layer_kwargs['channel_axis'] = channel_axis
        else:
            layer_kwargs['colormap'] = colormap

        return viewer.add_image(data, **layer_kwargs)

    def _get_current_ceus_data(self):
        """Return CEUS display stack with metadata for layer creation."""
        return (
            self._ceus_display_stack,
            self._current_ceus_layer_name,
            self._ceus_channel_axis,
            self._ceus_is_rgb,
        )

    def _update_overlay_layers(self):
        """Create/update overlay viewer layers to show CEUS over B-mode.
        Ensures time dimension alignment and frame sync with current frame.
        """
        # Clear existing overlay layers
        try:
            for layer in list(self.overlay_viewer.layers):
                self.overlay_viewer.layers.remove(layer)
        except Exception:
            pass

        # Need both stacks
        if self._bmode_display_stack is None:
            return
        ceus_data, ceus_name, ceus_channel_axis, ceus_is_rgb = self._get_current_ceus_data()
        if ceus_data is None:
            return

        # Align time dimension: crop both to min length
        try:
            T_ceus = ceus_data.shape[0]
            T_b = self._bmode_display_stack.shape[0]
            T = min(T_ceus, T_b)
            b_aligned = self._bmode_display_stack[:T]
            c_aligned = ceus_data[:T]
        except Exception:
            # Fallback to raw arrays if unexpected dims
            b_aligned = self._bmode_display_stack
            c_aligned = ceus_data

        # Add base B-mode
        b_base_layer = self._add_image_layer(
            self.overlay_viewer,
            b_aligned,
            name='B-mode (base)',
            channel_axis=self._bmode_channel_axis,
            rgb=self._bmode_is_rgb,
            colormap='gray',
            blending='opaque'
        )
        # Apply same display tuning to overlay base
        try:
            if b_base_layer is not None:
                if self._bmode_auto_clims is not None:
                    lo, hi = self._bmode_auto_clims
                    if lo is not None and hi is not None:
                        b_base_layer.contrast_limits = (float(lo), float(hi))
                if hasattr(b_base_layer, 'gamma'):
                    b_base_layer.gamma = float(self._bmode_gamma)
        except Exception:
            pass
        # Add CEUS overlay with transparency
        self._add_image_layer(
            self.overlay_viewer,
            c_aligned,
            name=f'{ceus_name} (overlay)',
            channel_axis=ceus_channel_axis,
            rgb=ceus_is_rgb,
            colormap='magma',
            blending='additive',
            opacity=0.6
        )

        # Sync current frame in overlay viewer
        try:
            current_step = list(self.overlay_viewer.dims.current_step)
            if len(current_step) > 0:
                current_step[0] = min(self.current_frame, len(c_aligned) - 1)
                self.overlay_viewer.dims.current_step = tuple(current_step)
        except Exception:
            pass
        # Keep mirrored shapes consistent with B-mode as master
        try:
            self._ensure_bmode_shapes_layer_exists_on_top()
            self._ensure_shapes_layer_exists_on_top()
            self._mirror_shapes_to_ceus()
        except Exception:
            pass
    
    def _on_shapes_changed(self, event):
        """Handle shapes layer data change (master layer drives ROI updates)."""
        # Only react to changes on the configured master layer
        try:
            source_layer = getattr(event, 'source', None)
        except Exception:
            source_layer = None
        if self._roi_master == 'bmode':
            if source_layer is not self.bmode_shapes_layer:
                return
            master_layer = self.bmode_shapes_layer
        else:
            if source_layer is not self.shapes_layer:
                return
            master_layer = self.shapes_layer

        # Synchronize Napari shapes with ROI manager based on master shapes
        if master_layer is None:
            return
        current_napari_shapes = len(master_layer.data)
        current_managed_rois = len(self.roi_manager.rois)
        
        if current_napari_shapes > current_managed_rois:
            # New shape added
            new_shape_data = master_layer.data[-1]
            # Debug infos to verify shape dimensionality
            try:
                print(f"[DEBUG] New shape data shape: {getattr(new_shape_data, 'shape', None)}")
                print(f"[DEBUG] New shape data sample: {new_shape_data[:3] if len(new_shape_data) > 2 else new_shape_data}")
            except Exception:
                pass
            
            # Convert Napari polygon coordinates (frame, y, x) to (x, y) list
            # Note: Napari uses (t, y, x) for 3D+time data
            if new_shape_data.shape[1] == 3:
                # Has time dimension, extract spatial coords only
                polygon_points = [(int(pt[2]), int(pt[1])) for pt in new_shape_data]
            else:
                # 2D polygon (y, x)
                polygon_points = [(int(pt[1]), int(pt[0])) for pt in new_shape_data]
            
            # Add to manager
            label = f"ROI_{len(self.roi_manager.rois) + 1}"
            self.roi_manager.add_roi(polygon_points, label=label)
            
            self._update_roi_info()
            self.status_label.setText(f"✅ Added {label} with {len(polygon_points)} points")
            
            # Enable TIC computation if we have ROIs and data
            if len(self.roi_manager.rois) > 0:
                self.btn_compute_tic.setEnabled(True)
        # Mirror any shape changes from master to the other viewer if present
        if self._roi_master == 'bmode':
            self._mirror_shapes_to_ceus()
        else:
            if self.bmode_stack is not None:
                self._mirror_shapes_to_bmode()
        # Refresh analysis info label (ROI count may have changed)
        self._update_status_info()

    # --- Sync camera (zoom/pan) across viewers ---
    def _enable_sync_camera(self, enabled: bool):
        """Enable/disable synchronized camera (zoom/pan) across all viewers.
        Any viewer can act as the source; updates propagate to the others.
        """
        try:
            if not hasattr(self, '_camera_sync_callbacks'):
                self._camera_sync_callbacks = {}
            if enabled:
                # Create and connect callbacks for each viewer
                for name, viewer in (('ceus', self.ceus_viewer), ('bmode', self.bmode_viewer), ('overlay', self.overlay_viewer)):
                    cb = (lambda v: (lambda event=None: self._on_any_camera_changed(v)))(viewer)
                    self._camera_sync_callbacks[name] = cb
                    ev = viewer.camera.events
                    ev.zoom.connect(cb)
                    ev.center.connect(cb)
                    ev.angles.connect(cb)
                self.status_label.setText("🔍 Sync Zoom/Pan: ON (bidirectionnel)")
                # Initial alignment from CEUS (arbitrary) to others
                self._on_any_camera_changed(self.ceus_viewer)
            else:
                # Disconnect all if present
                for name, viewer in (('ceus', self.ceus_viewer), ('bmode', self.bmode_viewer), ('overlay', self.overlay_viewer)):
                    cb = self._camera_sync_callbacks.get(name)
                    if cb is None:
                        continue
                    ev = viewer.camera.events
                    try:
                        ev.zoom.disconnect(cb)
                    except Exception:
                        pass
                    try:
                        ev.center.disconnect(cb)
                    except Exception:
                        pass
                    try:
                        ev.angles.disconnect(cb)
                    except Exception:
                        pass
                self._camera_sync_callbacks.clear()
                self.status_label.setText("🔍 Sync Zoom/Pan: OFF")
        except Exception as e:
            print(f"[DEBUG] Sync camera toggle error: {e}")
            pass

    def _on_any_camera_changed(self, source_viewer):
        """Propagate camera settings from the source viewer to the others, with recursion guard."""
        if getattr(self, '_camera_sync_changing', False):
            return
        try:
            self._camera_sync_changing = True
            src = source_viewer.camera
            for target in (self.ceus_viewer, self.bmode_viewer, self.overlay_viewer):
                if target is source_viewer:
                    continue
                try:
                    cam = target.camera
                    cam.zoom = src.zoom
                    cam.center = src.center
                    cam.angles = src.angles
                except Exception:
                    pass
        finally:
            self._camera_sync_changing = False

    def _on_master_camera_changed(self):
        """Back-compat: align all viewers from CEUS."""
        try:
            self._on_any_camera_changed(self.ceus_viewer)
        except Exception as e:
            print(f"[DEBUG] Camera sync error: {e}")
    
    def clear_rois(self):
        """Clear all ROIs"""
        if self.shapes_layer is not None:
            self.shapes_layer.data = []
        if getattr(self, 'bmode_shapes_layer', None) is not None:
            try:
                self.bmode_shapes_layer.data = []
            except Exception:
                pass
        self.roi_manager.clear()
        self.roi_tic_data.clear()
        self.tic_plot.clear()
        self._update_roi_info()
        self.status_label.setText("🗑️ All ROIs cleared")
        self.btn_compute_tic.setEnabled(False)
        self._update_status_info()
        # Nettoie le tableau des métriques
        try:
            if hasattr(self, 'metrics_table') and self.metrics_table is not None:
                self.metrics_table.setRowCount(0)
                # Placeholder row to avoid an empty look
                from PyQt5.QtWidgets import QTableWidgetItem
                self.metrics_table.setRowCount(1)
                self.metrics_table.setItem(0, 0, QTableWidgetItem("No metrics"))
                # Ensure 3 columns exist
                try:
                    self.metrics_table.setItem(0, 1, QTableWidgetItem("—"))
                    self.metrics_table.setItem(0, 2, QTableWidgetItem("—"))
                except Exception:
                    pass
        except Exception:
            pass
    
    def _update_roi_info(self):
        """Refresh ROI list widget and action states"""
        self.roi_info_widget.blockSignals(True)
        self.roi_info_widget.clear()
        if len(self.roi_manager.rois) == 0:
            # Show a placeholder disabled item
            from PyQt5.QtWidgets import QListWidgetItem
            item = QListWidgetItem("No ROIs defined")
            item.setFlags(Qt.NoItemFlags)
            self.roi_info_widget.addItem(item)
            self.btn_clear_roi.setEnabled(False)
            self.btn_compute_tic.setEnabled(False)
        else:
            from PyQt5.QtWidgets import QListWidgetItem
            for roi in self.roi_manager.rois:
                text = f"{roi.label} — {roi.n_points} pts, {roi.area:.0f} px²"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, roi.label)
                self.roi_info_widget.addItem(item)
            self.btn_clear_roi.setEnabled(True)
            # compute button enabled elsewhere when appropriate
        self.roi_info_widget.blockSignals(False)
        self._on_roi_selection_changed()

    def _on_roi_selection_changed(self):
        has_selection = len(self.roi_info_widget.selectedItems()) > 0
        self.btn_remove_selected_roi.setEnabled(has_selection)
        self.btn_rename_roi.setEnabled(has_selection and len(self.roi_info_widget.selectedItems()) == 1)

    def _on_remove_selected_roi(self):
        items = self.roi_info_widget.selectedItems()
        if not items:
            return
        labels = []
        for it in items:
            lbl = it.data(Qt.UserRole)
            if lbl:
                labels.append(lbl)
        if not labels:
            return
        # Determine indices in current ROI order before modifying manager
        to_remove_idx = [i for i, r in enumerate(self.roi_manager.rois) if r.label in labels]
        # Update master shapes layer to remove corresponding polygons
        target_layer = self.bmode_shapes_layer if self._roi_master == 'bmode' else self.shapes_layer
        if target_layer is not None and hasattr(target_layer, 'data'):
            try:
                data_list = list(target_layer.data)
                remaining = [d for i, d in enumerate(data_list) if i not in to_remove_idx]
                target_layer.data = remaining
            except Exception:
                pass
        # Remove from manager and TICs
        for lbl in labels:
            self.roi_manager.remove_roi(lbl)
            if lbl in self.roi_tic_data:
                self.roi_tic_data.pop(lbl, None)
                self.tic_plot.remove_tic_curve(lbl)
        # Sync mirrored shapes according to master
        if self._roi_master == 'bmode':
            self._mirror_shapes_to_ceus()
        else:
            if self.bmode_stack is not None:
                self._mirror_shapes_to_bmode()
        self._update_roi_info()
        self.status_label.setText(f"🗑️ Removed {len(labels)} ROI(s)")
        self._update_status_info()

    def _on_rename_selected_roi(self):
        items = self.roi_info_widget.selectedItems()
        if not items:
            return
        item = items[0]
        old_label = item.data(Qt.UserRole) or ""
        if not old_label:
            return
        new_label, ok = QInputDialog.getText(self, "Rename ROI", "New label:", text=old_label)
        if not ok:
            return
        new_label = new_label.strip()
        if not new_label or new_label == old_label:
            return
        # Try rename in manager (checks duplicates)
        if not self.roi_manager.rename_roi(old_label, new_label):
            QMessageBox.warning(self, "Rename ROI", f"Label '{new_label}' is already in use.")
            return
        # Update list item
        # Recompute text
        roi = self.roi_manager.get_roi(new_label)
        if roi is not None:
            item.setData(Qt.UserRole, new_label)
            item.setText(f"{roi.label} — {roi.n_points} pts, {roi.area:.0f} px²")
        # Update TIC curve label and stored data key
        if old_label in self.roi_tic_data:
            self.roi_tic_data[new_label] = self.roi_tic_data.pop(old_label)
            self.tic_plot.rename_tic_curve(old_label, new_label)
        self.status_label.setText(f"✏️ Renamed ROI '{old_label}' → '{new_label}'")
    
    # =========================================================================
    # TIC Analysis
    # =========================================================================
    
    def compute_all_tics(self):
        """Compute TIC for all ROIs"""
        if len(self.roi_manager.rois) == 0:
            QMessageBox.warning(self, "Warning", "No ROIs defined")
            return
        
        # Use preprocessed data if available, otherwise raw
        data_stack = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        
        if data_stack is None:
            QMessageBox.warning(self, "Warning", "No image data available")
            return
        
        try:
            self.status_label.setText("Computing TICs...")
            
            # Clear existing TIC data and plot
            self.roi_tic_data.clear()
            self.tic_plot.clear()
            self.tic_plot.clear_smooth_overlays()
            
            data_gray = self._to_grayscale_stack(data_stack)
            if data_gray is None:
                QMessageBox.warning(self, "Warning", "Unable to prepare CEUS data for TIC computation")
                return
            data_gray = data_gray.astype(np.float32, copy=False)
            
            # Compute TIC for each ROI
            for roi in self.roi_manager.rois:
                # Create mask from polygon
                mask = self._polygon_to_mask(roi.polygon, data_gray.shape[1:])
                
                # Extract mean intensity in ROI for each frame
                T = data_gray.shape[0]
                vi = np.zeros(T, dtype=np.float32)
                
                for t in range(T):
                    vi[t] = data_gray[t][mask].mean()
                
                # Compute dVI (delta from baseline)
                baseline = vi[0]
                dvi = vi - baseline
                
                # Time axis
                time = np.arange(T, dtype=np.float32) / self.fps
                valid_mask = np.ones_like(dvi, dtype=bool)
                
                # Store
                self.roi_tic_data[roi.label] = {
                    'time': time,
                    'dvi': dvi,
                    'valid_mask': valid_mask,
                }

                # Add to plot
                self.tic_plot.add_tic_curve(
                    roi.label,
                    time,
                    dvi,
                    valid_mask,
                    color=self._rgb_to_pyqtgraph_color(roi.color)
                )
                # Overlays will be computed after all curves are added
                # based on current smoothing settings and valid_mask
                
            # After plotting all ROIs, set crosshair and overlays
            try:
                self.tic_plot.update_crosshair(self.current_frame)
            except Exception:
                pass
            # Build/update smoothing overlays according to UI state
            try:
                self._recompute_overlays_all()
            except Exception:
                pass
            # Interval selector disabled per user request

            self.status_label.setText(f"✅ Computed TICs for {len(self.roi_manager.rois)} ROI(s)")
            # Met à jour le tableau des métriques (RAW uniquement tant qu'il n'y a pas de fit)
            try:
                self._refresh_metrics_table()
            except Exception:
                pass
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"TIC computation failed:\n{str(e)}")
            self.status_label.setText(f"❌ TIC computation error: {str(e)}")
    
    def _polygon_to_mask(self, poly_points: List[tuple], image_shape: tuple) -> np.ndarray:
        """Convert polygon to binary mask"""
        mask = np.zeros(image_shape, dtype=bool)
        if poly_points is None or len(poly_points) == 0:
            print("[DEBUG] _polygon_to_mask: poly_points is empty, returning empty mask.")
            return mask
        # Extract x, y coordinates
        xs = [pt[0] for pt in poly_points]
        ys = [pt[1] for pt in poly_points]
        # Log pour vérification
        print(f"[DEBUG] ROI polygon points (x, y): {poly_points}")
        print(f"[DEBUG] xs: {xs}")
        print(f"[DEBUG] ys: {ys}")
        print(f"[DEBUG] image_shape: {image_shape}")
        # Use skimage polygon to fill
        rr, cc = sk_polygon(ys, xs, shape=image_shape)
        print(f"[DEBUG] mask indices rr: {rr}, cc: {cc}")
        mask[rr, cc] = True
        return mask
    
    def _rgb_to_pyqtgraph_color(self, rgb: tuple) -> str:
        """Convert RGB tuple to PyQtGraph color code"""
        # Simple color mapping
        if rgb == (255, 0, 0):
            return 'r'
        elif rgb == (0, 255, 0):
            return 'g'
        elif rgb == (0, 0, 255):
            return 'b'
        elif rgb == (255, 255, 0):
            return 'y'
        elif rgb == (255, 0, 255):
            return 'm'
        elif rgb == (0, 255, 255):
            return 'c'
        else:
            return 'w'
    
    # =========================================================================
    # Model Fitting
    # =========================================================================
    def _metrics_from_curve(self, t: np.ndarray, y: np.ndarray) -> dict:
        """Compute basic perfusion metrics on a curve: AUC, MTT, Peak, TTP, Slope 10–90%."""
        try:
            t = np.asarray(t, float)
            y = np.asarray(y, float)
        except Exception:
            return {'AUC': float('nan'), 'MTT': float('nan'), 'Peak': float('nan'), 'TTP': float('nan'), 'Slope_10_90': float('nan')}
        if t.size == 0 or y.size == 0:
            return {'AUC': float('nan'), 'MTT': float('nan'), 'Peak': float('nan'), 'TTP': float('nan'), 'Slope_10_90': float('nan')}

        # AUC with non-negative clamp
        y_pos = np.clip(y, 0, None)
        try:
            auc = float(np.trapz(y_pos, t))
        except Exception:
            auc = float('nan')
        # MTT = first moment / area
        try:
            mtt = float(np.trapz(t * y_pos, t) / auc) if np.isfinite(auc) and auc > 0 else float('nan')
        except Exception:
            mtt = float('nan')
        # Peak and TTP
        try:
            i_max = int(np.argmax(y)) if y.size else -1
            peak = float(y[i_max]) if i_max >= 0 else float('nan')
            ttp = float(t[i_max]) if i_max >= 0 else float('nan')
        except Exception:
            peak, ttp = float('nan'), float('nan')
        # Slope between 10% and 90% of peak
        try:
            if np.isfinite(peak) and peak > 0:
                y10, y90 = 0.1 * peak, 0.9 * peak
                idx = np.where((y >= y10) & (y <= y90))[0]
                if idx.size >= 2:
                    coef = np.polyfit(t[idx], y[idx], 1)
                    slope = float(coef[0])
                else:
                    slope = float('nan')
            else:
                slope = float('nan')
        except Exception:
            slope = float('nan')
        # MaxDiff = max absolute derivative
        try:
            if t.size >= 2:
                dt = np.diff(t)
                dy = np.diff(y)
                # Avoid division by zero
                dt = np.where(dt == 0, 1e-9, dt)
                maxdiff = float(np.nanmax(np.abs(dy / dt)))
            else:
                maxdiff = float('nan')
        except Exception:
            maxdiff = float('nan')
        return {'AUC': auc, 'MTT': mtt, 'Peak': peak, 'TTP': ttp, 'Slope_10_90': slope, 'MaxDiff': maxdiff}

    def _export_metrics_csv(self):
        """Export results to a ZIP archive with three CSVs: augmented, predicted, parameters.
        Mirrors the R app export structure as closely as possible.
        """
        if not self.roi_tic_data:
            QMessageBox.information(self, "Export", "No ROI TIC data to export.")
            return
        # Choose output path
        try:
            default_name = "CEUS-Export.zip"
            save_path, sel = QFileDialog.getSaveFileName(self, "Export CEUS Results", default_name, "ZIP Files (*.zip);;All Files (*)")
        except Exception:
            save_path = None
        if not save_path:
            return
        if not save_path.lower().endswith('.zip'):
            save_path = save_path + '.zip'

        import os
        import tempfile
        import zipfile
        import numpy as np
        try:
            from src.analysis.models import washin_func
        except Exception:
            washin_func = None

        span = float(self.spin_fit_smooth_window.value()) if hasattr(self, 'spin_fit_smooth_window') else 0.8
        span = min(1.0, max(0.1, span))

        augmented_rows = []
        predicted_rows = []
        params_rows = []

        for label, tic in self.roi_tic_data.items():
            try:
                t_all = np.asarray(tic.get('time', []), float)
                y_all = np.asarray(tic.get('dvi', []), float)
                mask = np.asarray(tic.get('valid_mask', np.ones_like(y_all, dtype=bool)))
            except Exception:
                continue
            t_inc = t_all[mask]
            y_inc = y_all[mask]
            if t_inc.size == 0 or y_inc.size == 0:
                continue

            # LOESS smoothing on included points (like R app)
            try:
                y_loess = loess_smooth(t_inc, y_inc, span=span, degree=2) if t_inc.size >= 3 else y_inc.copy()
                if y_loess.size:
                    y_loess = y_loess - y_loess[0]
                    y_loess = np.maximum(y_loess, 0.0)
            except Exception:
                y_loess = y_inc.copy()

            # Wash-in predicted values on included times (using fitted params if available)
            y_pred_inc = None
            A = B = AB = np.nan
            r2 = np.nan
            auc_pred = np.nan
            mean_pred = np.nan
            maxdiff_pred = np.nan
            try:
                wres = (self.fit_results or {}).get(label, {}).get('washin') if hasattr(self, 'fit_results') else None
            except Exception:
                wres = None
            if wres and wres.get('params') is not None and washin_func is not None:
                try:
                    p = np.asarray(wres['params'], float).ravel()
                    if p.size >= 2:
                        A = float(p[0]); B = float(p[1]); AB = float(A * B)
                    y_pred_inc = washin_func(t_inc, *p)
                    # R2 on included window
                    if y_inc.size > 1:
                        ss_res = float(np.sum((y_inc - y_pred_inc) ** 2))
                        ss_tot = float(np.sum((y_inc - np.mean(y_inc)) ** 2)) + 1e-12
                        r2 = 1.0 - ss_res / ss_tot
                    # Predicted curve on 0..8s grid (like R)
                    t_grid = np.arange(0.0, 8.0 + 1e-12, 0.1)
                    y_grid = washin_func(t_grid, *p)
                    for ti, yi in zip(t_grid, y_grid):
                        predicted_rows.append({
                            'ROI': label,
                            'Time': float(ti),
                            'dVI_predict': float(yi),
                        })
                    # AUC/mean/MaxDiff on predicted grid
                    try:
                        auc_pred = float(np.trapz(y_grid, t_grid))
                    except Exception:
                        auc_pred = float('nan')
                    mean_pred = float(np.nanmean(y_grid)) if y_grid.size else float('nan')
                    try:
                        if t_grid.size >= 2:
                            dtg = np.diff(t_grid); dyg = np.diff(y_grid)
                            dtg = np.where(dtg == 0, 1e-9, dtg)
                            maxdiff_pred = float(np.nanmax(np.abs(dyg / dtg)))
                        else:
                            maxdiff_pred = float('nan')
                    except Exception:
                        maxdiff_pred = float('nan')
                except Exception:
                    y_pred_inc = None

            # Augmented rows (included points)
            for i in range(t_inc.size):
                row = {
                    'ROI': label,
                    'Time': float(t_inc[i]),
                    'dVI': float(y_inc[i]),
                    'dVI_filt': float(y_loess[i])
                }
                if y_pred_inc is not None and i < len(y_pred_inc):
                    row['dVI_predict'] = float(y_pred_inc[i])
                augmented_rows.append(row)

            # Parameters/metrics (tidy style)
            # Peak by magnitude (R's peak_value)
            try:
                max_pos = float(np.nanmax(y_inc))
                min_neg = float(np.nanmin(y_inc))
                peak_raw = max_pos if abs(max_pos) >= abs(min_neg) else min_neg
            except Exception:
                peak_raw = float('nan')
            try:
                max_pos_f = float(np.nanmax(y_loess))
                min_neg_f = float(np.nanmin(y_loess))
                peak_filt = max_pos_f if abs(max_pos_f) >= abs(min_neg_f) else min_neg_f
            except Exception:
                peak_filt = float('nan')
            # AUC/means for filtered
            try:
                auc_filt = float(np.trapz(y_loess, t_inc))
            except Exception:
                auc_filt = float('nan')
            mean_raw = float(np.nanmean(y_inc)) if y_inc.size else float('nan')
            mean_filt = float(np.nanmean(y_loess)) if y_loess.size else float('nan')
            # MaxDiff for filtered (abs slope)
            try:
                if t_inc.size >= 2:
                    dt = np.diff(t_inc); dy = np.diff(y_loess)
                    dt = np.where(dt == 0, 1e-9, dt)
                    maxdiff_filt = float(np.nanmax(np.abs(dy / dt)))
                else:
                    maxdiff_filt = float('nan')
            except Exception:
                maxdiff_filt = float('nan')

            # Build tidy rows
            def add_param(name: str, value: float):
                params_rows.append({'ROI': label, 'parameter': name, 'value': float(value) if np.isfinite(value) else np.nan})

            add_param('A', A)
            add_param('B', B)
            add_param('AB', AB)
            add_param('R-squared', r2)
            add_param('AUC dVI_filt', auc_filt)
            add_param('AUC dVI_predict', auc_pred)
            add_param('Peak dVI', peak_raw)
            add_param('Peak dVI_filt', peak_filt)
            add_param('Mean dVI', mean_raw)
            add_param('Mean dVI_filt', mean_filt)
            add_param('Mean dVI_predict', mean_pred)
            add_param('MaxDiff dVI_filt', maxdiff_filt)
            add_param('MaxDiff dVI_predict', maxdiff_pred)

        # Write CSVs into a temp directory, then zip
        try:
            with tempfile.TemporaryDirectory() as tmp:
                aug_path = os.path.join(tmp, 'signals.csv')
                pred_path = os.path.join(tmp, 'predicted.csv')
                par_path = os.path.join(tmp, 'parameters.csv')
                # DataFrames
                if augmented_rows:
                    pd.DataFrame(augmented_rows).to_csv(aug_path, index=False)
                if predicted_rows:
                    pd.DataFrame(predicted_rows).to_csv(pred_path, index=False)
                if params_rows:
                    pd.DataFrame(params_rows).to_csv(par_path, index=False)
                # Create ZIP
                with zipfile.ZipFile(save_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    if os.path.exists(aug_path):
                        zf.write(aug_path, arcname=os.path.basename(aug_path))
                    if os.path.exists(pred_path):
                        zf.write(pred_path, arcname=os.path.basename(pred_path))
                    if os.path.exists(par_path):
                        zf.write(par_path, arcname=os.path.basename(par_path))
            QMessageBox.information(self, "Export", f"Exported results to:\n{save_path}")
        except Exception as e:
            QMessageBox.warning(self, "Export", f"Failed to export: {e}")

    def _extract_metrics_for_label(self, label: str) -> dict:
        """Return metrics dict for a single ROI label: {'raw': {...}, 'fits': {model: {..., RSS}}}."""
        out = {'raw': {}, 'fits': {}}
        tic = self.roi_tic_data.get(label)
        if not tic:
            return out
        t_all = np.asarray(tic.get('time', []))
        y_all = np.asarray(tic.get('dvi', []))
        mask = np.asarray(tic.get('valid_mask', np.ones_like(y_all, dtype=bool)))
        # Apply region selector if enabled
        region = None
        try:
            if getattr(self, 'chk_fit_use_region', None) is not None and self.chk_fit_use_region.isChecked():
                region = self.tic_plot.get_region_range()
        except Exception:
            region = None
        if region is not None and t_all.size:
            a, b = region
            mask = mask & (t_all >= a) & (t_all <= b)
        t = t_all[mask]; y = y_all[mask]
        # Optional smoothing for metrics: LOESS on included points (match R's filtered metrics)
        y_for_metrics = y
        try:
            if getattr(self, 'chk_metrics_smooth', None) is not None and self.chk_metrics_smooth.isChecked():
                span = float(self.spin_fit_smooth_window.value()) if hasattr(self, 'spin_fit_smooth_window') else 0.8
                span = min(1.0, max(0.1, span))
                if len(t) >= 3:
                    try:
                        y_for_metrics = loess_smooth(t, y, span=span, degree=2)
                        # Anchor to zero baseline for ΔVI metrics
                        if y_for_metrics.size:
                            y_for_metrics = np.maximum(y_for_metrics - y_for_metrics[0], 0.0)
                    except Exception:
                        pass
        except Exception:
            pass
        out['raw'] = self._metrics_from_curve(t, y_for_metrics)
        # Fits if present
        res = self.fit_results.get(label, {})
        for m, r in (res or {}).items():
            try:
                yhat = np.asarray(r.get('y_fit', []))
                md = self._metrics_from_curve(t, yhat)
                md['RSS'] = float(r.get('rss', np.nan))
                out['fits'][m] = md
            except Exception:
                pass
        return out

    def _display_metrics_table(self, flat: dict, roi_label: Optional[str] = None):
        """Display flattened metrics for a single ROI in a grouped 3-column table.

        roi_label: if provided, used as the ROI name instead of a generic placeholder.
        """
        if not hasattr(self, 'metrics_table') or self.metrics_table is None:
            return
        tbl = self.metrics_table
        try:
            tbl.setSortingEnabled(False)
        except Exception:
            pass
        tbl.setRowCount(0)
        row = 0
        # Header row
        tbl.insertRow(row)
        name = roi_label if roi_label else "Selected ROI"
        hdr = QTableWidgetItem(name)
        try:
            f = hdr.font(); f.setBold(True); hdr.setFont(f)
        except Exception:
            pass
        hdr.setFlags(Qt.ItemIsEnabled)
        tbl.setItem(row, 0, hdr)
        tbl.setItem(row, 1, QTableWidgetItem("RAW + FIT"))
        tbl.setItem(row, 2, QTableWidgetItem(f"{len(flat)} metrics"))
        row += 1
        for k, v in flat.items():
            tbl.insertRow(row)
            tbl.setItem(row, 0, QTableWidgetItem(name))
            tbl.setItem(row, 1, QTableWidgetItem(k))
            if isinstance(v, float):
                val_str = f"{v:.4f}" if np.isfinite(v) else "N/A"
            else:
                val_str = str(v)
            tbl.setItem(row, 2, QTableWidgetItem(val_str))
            row += 1
        try:
            tbl.setSortingEnabled(True)
            tbl.resizeColumnsToContents()
        except Exception:
            pass

    def _refresh_metrics_table(self):
        """Recalcule et affiche les métriques RAW pour toutes les ROIs.
        Ne montre pas les fits (ceci est réservé aux résultats d'un fit sur une sélection).
        Crée un flatten clair: ROI.<label>.<Metric>
        Si aucune ROI ou TICs absents, affiche un placeholder.
        """
        if not hasattr(self, 'metrics_table') or self.metrics_table is None:
            return
        try:
            tbl = self.metrics_table
            try:
                tbl.setSortingEnabled(False)
            except Exception:
                pass
            if len(self.roi_tic_data) == 0:
                # Table placeholder
                tbl.setRowCount(1)
                from PyQt5.QtWidgets import QTableWidgetItem
                tbl.setItem(0, 0, QTableWidgetItem("No TIC metrics yet"))
                tbl.setItem(0, 1, QTableWidgetItem("Compute TICs"))
                tbl.setItem(0, 2, QTableWidgetItem("—"))
                return
            tbl.setRowCount(0)
            row = 0
            for label, tic in self.roi_tic_data.items():
                # ROI header
                tbl.insertRow(row)
                hdr = QTableWidgetItem(label)
                try:
                    f = hdr.font(); f.setBold(True); hdr.setFont(f)
                except Exception:
                    pass
                hdr.setFlags(Qt.ItemIsEnabled)
                tbl.setItem(row, 0, hdr)
                # Indicate smoothing if enabled
                raw_tag = "RAW (LOESS)" if (getattr(self, 'chk_metrics_smooth', None) is not None and self.chk_metrics_smooth.isChecked()) else "RAW"
                tbl.setItem(row, 1, QTableWidgetItem(raw_tag))
                tbl.setItem(row, 2, QTableWidgetItem(""))
                row += 1
                try:
                    t = np.asarray(tic.get('time', []))
                    y = np.asarray(tic.get('dvi', []))
                    mask = np.asarray(tic.get('valid_mask', np.ones_like(y, dtype=bool)))
                    t_use = t[mask]; y_use = y[mask]
                    # Apply LOESS for metrics if enabled (match R)
                    try:
                        if getattr(self, 'chk_metrics_smooth', None) is not None and self.chk_metrics_smooth.isChecked():
                            span = float(self.spin_fit_smooth_window.value()) if hasattr(self, 'spin_fit_smooth_window') else 0.8
                            span = min(1.0, max(0.1, span))
                            if len(t_use) >= 3:
                                try:
                                    y_use = loess_smooth(t_use, y_use, span=span, degree=2)
                                    # Anchor to zero baseline for displayed RAW(LOESS) metrics
                                    if y_use.size:
                                        y_use = np.maximum(y_use - y_use[0], 0.0)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    md = self._metrics_from_curve(t_use, y_use)
                    for k, v in md.items():
                        tbl.insertRow(row)
                        tbl.setItem(row, 0, QTableWidgetItem(label))
                        tbl.setItem(row, 1, QTableWidgetItem(k))
                        val_str = f"{v:.4f}" if isinstance(v, float) and np.isfinite(v) else "N/A"
                        tbl.setItem(row, 2, QTableWidgetItem(val_str))
                        row += 1
                except Exception:
                    pass
            try:
                tbl.setSortingEnabled(True)
                tbl.resizeColumnsToContents()
            except Exception:
                pass
        except Exception:
            pass
    
    def on_fit_requested(self, params: dict):
        """Fit des modèles pour les ROI sélectionnées, en respectant valid_mask et l'intervalle optionnel."""
        if len(self.roi_tic_data) == 0:
            QMessageBox.warning(self, "Warning", "No TIC data available. Compute TICs first.")
            return

        if fit_models is None:
            self.status_label.setText("❌ Fitting module unavailable.")
            return

        # ROI(s) ciblées: sélection multiple ou fallback dernière TIC cliquée
        items = getattr(self.roi_info_widget, "selectedItems", lambda: [])()
        labels = [it.data(Qt.UserRole) for it in items if it.data(Qt.UserRole)]
        if not labels:
            if getattr(self, "_last_tic_target", None):
                labels = [self._last_tic_target[0]]
            else:
                self.status_label.setText("Select at least one ROI to fit.")
                return

        # Hints: t0 (flash) si dispo, baseline approx
        fps = float(self.fps) if getattr(self, "fps", None) else None
        flash_idx = getattr(self, "flash_idx", None)
        t0_hint = None
        if fps is not None and flash_idx is not None:
            try:
                t0_hint = float(flash_idx) / fps
            except Exception:
                t0_hint = None

        # Interval selector disabled; use only global Tmax window
        use_region = None
        region = None

        model_colors = {
            "lognormal": "#e41a1c",
            "gamma": "#377eb8",
            "ldrw": "#4daf4a",
            "fpt": "#984ea3",
            "washin": "#000080",  # navy
        }

        any_fitted = False
        for label in labels:
            tic = self.roi_tic_data.get(label)
            if not tic:
                continue
            t_all = np.asarray(tic["time"])  # type: ignore
            y_all = np.asarray(tic["dvi"])   # type: ignore
            mask_valid = np.asarray(tic.get("valid_mask", np.ones_like(y_all, dtype=bool)))
            if t_all.size == 0 or y_all.size == 0:
                continue

            mask = mask_valid.copy()
            # Region selection removed; do nothing here

            # If no explicit region requested, apply global Tmax window [0, Tmax]
            if (use_region is None) or (not use_region.isChecked()):
                try:
                    tmax_global = float(params.get('t_max')) if params and 't_max' in params else (
                        float(self.spin_plot_tmax.value()) if getattr(self, 'spin_plot_tmax', None) is not None else None
                    )
                except Exception:
                    tmax_global = None
                if tmax_global is not None and tmax_global > 0:
                    mask &= (t_all <= float(tmax_global))

            t = t_all[mask]
            y = y_all[mask]
            if t.size < 5:
                continue

            # Match R app: do NOT smooth before fitting; fit uses raw dVI (after exclusions/region)

            C_hint = float(np.percentile(y, 10))
            try:
                # Core models
                results = fit_models(t, y, models=("lognormal", "gamma", "ldrw", "fpt"),
                                     t0_hint=t0_hint, C_hint=C_hint, n_starts=60)
                # Wash-in model using UI A/B starts and bounds
                # Data-driven initial guesses for wash-in when possible
                A_start, B_start = self._estimate_washin_initials(t, y, t0_hint)
                # If UI provided values, blend by prioritizing UI when they differ significantly
                try:
                    if params and 'A_start' in params:
                        A_ui = float(params['A_start'])
                        if A_ui > 0:
                            A_start = A_ui
                    if params and 'B_start' in params:
                        B_ui = float(params['B_start'])
                        if B_ui > 0:
                            B_start = B_ui
                except Exception:
                    pass
                bounds = params.get('bounds') if params else None
                from src.analysis.models import fit_washin_model
                wres = fit_washin_model(t, y, A_start=A_start, B_start=B_start, bounds=bounds, t0_hint=t0_hint, C_hint=C_hint, n_starts=40)
                results["washin"] = wres
            except Exception as e:
                self.status_label.setText(f"Fit failed for {label}: {e}")
                continue

            # Force all fitted model curves to start at zero (baseline anchored)
            try:
                for _m, _r in (results or {}).items():
                    if not _r:
                        continue
                    yhat = np.asarray(_r.get('y_fit', []), dtype=float)
                    if yhat.size:
                        yhat0 = float(yhat[0])
                        yhat = np.maximum(yhat - yhat0, 0.0)
                        _r['y_fit'] = yhat
            except Exception:
                pass

            self.fit_results[label] = results
            any_fitted = True

            # Superposer les courbes de fit sur la plage t filtrée
            try:
                for m, res in results.items():
                    if not res:
                        continue
                    color = model_colors.get(m, "#666")
                    dashed = False if m == "washin" else True
                    width = 6.0 if m == "washin" else 2.0
                    self.tic_plot.set_fit_curve(label, m, t, res["y_fit"], color=color, width=width, dashed=dashed)
            except Exception:
                pass

        # Summary status after processing all labels
        self.status_label.setText("✅ Fit completed" if any_fitted else "ℹ️ Nothing to fit (empty selection or insufficient points)")

        # Display metrics for single selected ROI (raw + fits)
        try:
            if len(labels) == 1:
                metrics_dict = self._extract_metrics_for_label(labels[0])
                flat = {}
                # Prefix indicates whether raw metrics are smoothed
                raw_prefix = "RAW_LOESS" if (getattr(self, 'chk_metrics_smooth', None) is not None and self.chk_metrics_smooth.isChecked()) else "RAW"
                for k, v in metrics_dict.get('raw', {}).items():
                    flat[f"{raw_prefix}.{k}"] = v
                for mname, md in metrics_dict.get('fits', {}).items():
                    for k, v in md.items():
                        flat[f"{mname}.{k}"] = v
                try:
                    self.fit_panel.display_results(flat)
                except Exception:
                    pass
                try:
                    self._display_metrics_table(flat, roi_label=labels[0])
                except Exception:
                    pass
        except Exception:
            pass

    # =========================================================================
    # TIC ↔ Frame interactions
    # =========================================================================
    def _on_tic_point_clicked(self, label: str, idx: int):
        """Clic sur un point TIC: naviguer vers la frame correspondante."""
        data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        if data is None:
            return
        idx = max(0, min(int(idx), data.shape[0] - 1))
        # Mémorise la dernière cible TIC cliquée uniquement si le label correspond à une courbe réelle
        try:
            if label in self.roi_tic_data:
                self._last_tic_target = (label, idx)
        except Exception:
            pass
        self.frame_slider.setValue(idx)
        # Assure un feedback immédiat même si la valeur ne change pas
        try:
            self.tic_plot.update_crosshair(idx)
        except Exception:
            pass

    # (Removed old modifier-based toggle handlers)

    def _toggle_last_tic_point(self):
        """Toggle valid_mask for the last clicked TIC point."""
        if self._last_tic_target is None:
            return
        label, idx = self._last_tic_target
        tic = self.roi_tic_data.get(label)
        if not tic:
            return
        mask = tic.get('valid_mask')
        print(f"[DEBUG] valid_mask before: {mask}")
        if mask is None or idx < 0 or idx >= len(mask):
            print(f"[DEBUG] mask is None or idx out of bounds: idx={idx}, mask_len={len(mask) if mask is not None else 'N/A'}")
            return
        mask[idx] = not bool(mask[idx])
        print(f"[DEBUG] valid_mask after: {mask}")
        try:
            self.tic_plot.update_tic_curve(label, tic['time'], tic['dvi'], tic['valid_mask'])
            # Recompute smoothing overlay for this label according to UI state
            self._recompute_overlay_for_label(label)
        except Exception:
            pass
        # Refresh metrics to reflect included/excluded points
        try:
            self._refresh_metrics_table()
        except Exception:
            pass

    def _toggle_current_frame_selected_roi(self):
        """Toggle valid_mask for the current frame on all selected ROIs (or last clicked ROI if none selected)."""
        items = self.roi_info_widget.selectedItems()
        labels = []
        if items:
            for it in items:
                lbl = it.data(Qt.UserRole)
                if lbl:
                    labels.append(lbl)
        else:
            # Pas de sélection: repli sur la dernière courbe cliquée si dispo
            if self._last_tic_target and self._last_tic_target[0]:
                labels = [self._last_tic_target[0]]

        if not labels:
            return

        idx = self.current_frame
        for label in labels:
            tic = self.roi_tic_data.get(label)
            if not tic:
                continue
            mask = tic.get('valid_mask')
            if mask is None or idx < 0 or idx >= len(mask):
                continue
            mask[idx] = not bool(mask[idx])
            try:
                self.tic_plot.update_tic_curve(label, tic['time'], tic['dvi'], tic['valid_mask'])
                self._recompute_overlay_for_label(label)
            except Exception:
                pass
        # Recompute metrics display after exclusions/inclusions changed
        try:  # Initial metrics refresh (placeholder updated)
            self._refresh_metrics_table()
        except Exception:
            pass

        # Also refresh after toggling the last clicked TIC point (single-label case)
        try:
            if self._last_tic_target and self._last_tic_target[0]:
                self._refresh_metrics_table()
        except Exception:
            pass

    # --- Smoothing overlay utilities ---

    def _recompute_overlay_for_label(self, label: str):
        tic = self.roi_tic_data.get(label)
        if tic is None:
            return
        time = np.asarray(tic['time'])
        dvi = np.asarray(tic['dvi'])
        mask = np.asarray(tic.get('valid_mask', np.ones_like(dvi, dtype=bool)))
        if time.size == 0 or dvi.size == 0:
            return
        # Apply optional global Tmax filter from plot settings
        try:
            tmax = float(self.spin_plot_tmax.value()) if getattr(self, 'spin_plot_tmax', None) is not None else None
        except Exception:
            tmax = None
        if tmax is not None and tmax > 0:
            mask = mask & (time <= tmax)
        # Always compute LOESS on included points (to match R app) and plot only at included x
        t_sel = time[mask]
        y_sel = dvi[mask]
        if t_sel.size < 3:
            self.tic_plot.add_smooth_overlay(label, t_sel, y_sel, color='#EEB422')
            return
        span = float(self.spin_fit_smooth_window.value()) if hasattr(self, 'spin_fit_smooth_window') else 0.8
        span = min(1.0, max(0.1, span))
        try:
            # Use custom LOESS (quadratic, tri-cube) to mimic R's smoothing
            # Default behavior: anchor LOESS to zero at first included point
            y_sm_sel = loess_smooth(t_sel, y_sel, span=span, degree=2)
            if y_sm_sel.size:
                y_sm_sel = y_sm_sel - y_sm_sel[0]
                y_sm_sel = np.maximum(y_sm_sel, 0.0)
            if y_sm_sel.shape[0] == t_sel.shape[0]:
                self.tic_plot.add_smooth_overlay(label, t_sel, y_sm_sel, color='#EEB422')
            else:
                # Fallback: plot raw selection without re-baselining
                self.tic_plot.add_smooth_overlay(label, t_sel, y_sel, color='#EEB422')
        except Exception:
            # Fallback: plot raw selection without re-baselining
            self.tic_plot.add_smooth_overlay(label, t_sel, y_sel, color='#EEB422')

    def _recompute_overlays_all(self):
        if not self.roi_tic_data:
            return
        try:
            self.tic_plot.clear_smooth_overlays()
        except Exception:
            pass
        for label in list(self.roi_tic_data.keys()):
            self._recompute_overlay_for_label(label)

    def _on_tmax_changed_from_panel(self, v: float):
        try:
            if getattr(self, 'spin_plot_tmax', None) is not None:
                if abs(self.spin_plot_tmax.value() - float(v)) > 1e-9:
                    self.spin_plot_tmax.blockSignals(True)
                    self.spin_plot_tmax.setValue(float(v))
                    self.spin_plot_tmax.blockSignals(False)
            # Recompute overlays when Tmax changes
            self._recompute_overlays_all()
        except Exception:
            pass

    # =========================================================================
    # Global keyboard shortcuts (Space, arrows, Cmd/Ctrl+R)
    # =========================================================================
    def keyPressEvent(self, event):
        try:
            key = event.key()
            mods = event.modifiers()
        except Exception:
            return super().keyPressEvent(event)

        # Cmd/Ctrl helpers
        ctrl_like = bool(mods & (Qt.ControlModifier | Qt.MetaModifier))

        # Reset: Cmd/Ctrl+R
        if ctrl_like and key == Qt.Key_R:
            try:
                self.reset_analysis()
            except Exception:
                pass
            event.accept()
            return

        # Space: play/pause
        if key == Qt.Key_Space:
            try:
                self.toggle_playback()
            except Exception:
                pass
            event.accept()
            return

        # Left/Right arrows: previous/next frame
        if key in (Qt.Key_Left, Qt.Key_Right):
            data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
            if data is not None:
                max_idx = data.shape[0] - 1
                new_idx = self.current_frame + (-1 if key == Qt.Key_Left else 1)
                new_idx = max(0, min(max_idx, new_idx))
                self.frame_slider.setValue(new_idx)
            event.accept()
            return

        return super().keyPressEvent(event)

    # (Undo logic removed as part of TIC simplification)
    
    # =========================================================================
    # Playback
    # =========================================================================
    
    def toggle_playback(self):
        """Toggle play/pause"""
        if self.ceus_stack is None:
            return
        
        if not self.is_playing:
            self.is_playing = True
            self.play_button.setText("⏸ Pause")
            interval_ms = int(1000 / self.fps) if self.fps > 0 else 100
            self.playback_timer.start(interval_ms)
            self.status_label.setText(f"▶ Playing at {self.fps:.1f} FPS")
        else:
            self.is_playing = False
            self.play_button.setText("▶ Play")
            self.playback_timer.stop()
            self.status_label.setText("⏸ Paused")
    
    def _advance_frame(self):
        """Advance to next frame during playback"""
        data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        if data is None:
            return
        
        next_frame = self.current_frame + 1
        if next_frame >= len(data):
            next_frame = 0
        
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(next_frame)
        self.frame_slider.blockSignals(False)
        
        self.current_frame = next_frame
        self._sync_viewer_frames()
        self._update_frame_info()
    
    def on_frame_changed(self, frame_idx: int):
        """Handle frame slider change"""
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self._sync_viewer_frames()
            self._update_frame_info()
            self.tic_plot.update_crosshair(frame_idx)
    
    def _on_napari_frame_changed(self, event):
        """Handle frame change from Napari viewer"""
        if len(self.ceus_viewer.dims.current_step) > 0:
            frame_idx = self.ceus_viewer.dims.current_step[0]
            if frame_idx != self.current_frame:
                self.current_frame = frame_idx
                self.frame_slider.blockSignals(True)
                self.frame_slider.setValue(frame_idx)
                self.frame_slider.blockSignals(False)
                self._update_frame_info()
                self.tic_plot.update_crosshair(frame_idx)
    
    def _sync_viewer_frames(self):
        """Synchronize both viewers to current frame"""
        if self.bmode_stack is not None and self.current_frame < len(self.bmode_stack):
            current_step = list(self.bmode_viewer.dims.current_step)
            if len(current_step) > 0:
                current_step[0] = self.current_frame
                self.bmode_viewer.dims.current_step = tuple(current_step)
        
        data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        if data is not None and self.current_frame < len(data):
            current_step = list(self.ceus_viewer.dims.current_step)
            if len(current_step) > 0:
                current_step[0] = self.current_frame
                self.ceus_viewer.dims.current_step = tuple(current_step)

        # Also sync overlay viewer frame
        try:
            current_step = list(self.overlay_viewer.dims.current_step)
            if len(current_step) > 0:
                current_step[0] = self.current_frame
                self.overlay_viewer.dims.current_step = tuple(current_step)
        except Exception:
            pass
    
    def _update_frame_info(self):
        """Update frame info label"""
        data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        if data is None:
            self.frame_info_label.setText("Frame: 0 / 0 (0.00s)")
            return
        
        total_frames = len(data)
        time_s = self.current_frame / self.fps if self.fps > 0 else 0
        self.frame_info_label.setText(
            f"Frame: {self.current_frame + 1} / {total_frames} ({time_s:.2f}s)"
        )
    
    # =========================================================================
    # Reset
    # =========================================================================
    
    def reset_analysis(self):
        """Reset all analysis (keep DICOM loaded)"""
        if self.ceus_stack is None:
            return
        
        reply = QMessageBox.question(
            self,
            "Reset Analysis",
            "Reset all analysis results? (DICOM data will be kept)",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Stop playback
            if self.is_playing:
                self.toggle_playback()
            
            # Reset derived data
            self.flash_idx = None
            self.washout_idx = None
            self.ceus_preprocessed = None
            (
                self._ceus_display_stack,
                self._ceus_is_rgb,
                self._ceus_channel_axis,
            ) = self._prepare_display_stack(self.ceus_stack)
            self._current_ceus_layer_name = 'CEUS (raw)'
            # Restore raw B-mode display as well
            if self.bmode_stack is not None:
                try:
                    (
                        self._bmode_display_stack,
                        self._bmode_is_rgb,
                        self._bmode_channel_axis,
                    ) = self._prepare_display_stack(self.bmode_stack)
                    self._bmode_auto_clims = self._compute_bmode_limits(self._bmode_display_stack, q=(1, 99))
                    for layer in list(self.bmode_viewer.layers):
                        if layer.name != 'ROIs':
                            self.bmode_viewer.layers.remove(layer)
                    b_layer = self._add_image_layer(
                        self.bmode_viewer,
                        self._bmode_display_stack,
                        name='B-mode',
                        channel_axis=self._bmode_channel_axis,
                        rgb=self._bmode_is_rgb,
                        colormap='gray',
                        blending='opaque'
                    )
                    try:
                        if b_layer is not None and self._bmode_auto_clims is not None:
                            lo, hi = self._bmode_auto_clims
                            if lo is not None and hi is not None:
                                b_layer.contrast_limits = (float(lo), float(hi))
                        if b_layer is not None and hasattr(b_layer, 'gamma'):
                            b_layer.gamma = float(self._bmode_gamma)
                    except Exception:
                        pass
                except Exception:
                    pass
            
            # Clear ROIs
            self.clear_rois()
            
            # Restore raw CEUS view
            for layer in list(self.ceus_viewer.layers):
                if 'CEUS' in layer.name:
                    self.ceus_viewer.layers.remove(layer)
            if self._ceus_display_stack is not None:
                self._add_image_layer(
                    self.ceus_viewer,
                    self._ceus_display_stack,
                    name=self._current_ceus_layer_name,
                    channel_axis=self._ceus_channel_axis,
                    rgb=self._ceus_is_rgb,
                    colormap='gray',
                    blending='opaque'
                )

            # Refresh overlay to raw
            self._update_overlay_layers()

            # Ensure shapes remain on top after reset
            self._ensure_shapes_on_top()
            
            # Reset frame controls
            self.frame_slider.setMaximum(len(self.ceus_stack) - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            self._update_frame_info()
            
            self.status_label.setText("🔄 Analysis reset - showing raw CEUS data")
            self._update_ui_state()
            # Update TIC x-range to raw duration again
            try:
                if self.fps and self.fps > 0 and self.ceus_stack is not None:
                    total_dur = len(self.ceus_stack) / float(self.fps)
                    self.tic_plot.plotItem.setXRange(0, total_dur)
            except Exception:
                pass
            self._update_status_info()
    
    def _update_ui_state(self):
        """Update UI state based on loaded data"""
        has_data = self.ceus_stack is not None
        has_flash = self.flash_idx is not None
        has_preprocessed = self.ceus_preprocessed is not None
        
        self.btn_detect_flash.setEnabled(has_data)
        self.btn_set_flash_manual.setEnabled(has_data)
        self.btn_motion_correction.setEnabled(has_data and has_flash)
        self.btn_preprocess.setEnabled(has_data and has_flash)
        self.btn_reset.setEnabled(has_data)
        self.play_button.setEnabled(has_data)
        self.frame_slider.setEnabled(has_data)
        self.btn_draw_roi.setEnabled(has_data)
        self.btn_clear_roi.setEnabled(len(self.roi_manager.rois) > 0)
    
    def closeEvent(self, event):
        """Handle window close"""
        # Close Napari viewers
        self.bmode_viewer.close()
        self.ceus_viewer.close()
        event.accept()
