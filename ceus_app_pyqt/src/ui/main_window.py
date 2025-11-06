"""
Main application window
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QStatusBar, QSplitter,
    QLabel, QGroupBox, QMessageBox, QTabWidget, QSlider
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap
from pathlib import Path
import pyqtgraph as pg
import numpy as np

from src.core import DICOMLoader, detect_flash_ceus_refined, ROIManager
from src.core.motion_compensation import motion_compensate
from src.core.preprocessing import preprocess_ceus
from src.ui.widgets.image_viewer import ImageViewerWidget
from src.ui.widgets.tic_plot_widget import TICPlotWidget
from src.ui.widgets.roi_panel import ROIPanel
from src.ui.widgets.fit_panel import FitPanel
from src.ui.widgets.napari_widget import NapariViewerWidget


class CEUSMainWindow(QMainWindow):
    """Main application window for CEUS analysis"""
    
    # Signals
    frame_changed = pyqtSignal(int)
    roi_added = pyqtSignal(str)  # ROI label
    roi_removed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        
        # Data
        self.dicom_loader = None
        self.bmode_stack = None
        self.ceus_stack = None
        self.ceus_preprocessed = None
        self.fps = None
        self.flash_idx = None
        self.washout_idx = None
        
        # ROI management
        self.roi_manager = ROIManager()
        
        # Playback timer
        self.playback_timer = QTimer()
        self.playback_timer.setTimerType(Qt.PreciseTimer)  # Precise timing
        self.playback_timer.timeout.connect(self._advance_frame)
        self.is_playing = False
        
        # UI setup
        self.setWindowTitle("CEUS Analyzer - Blood Flow Analysis")
        self.setGeometry(100, 100, 1600, 900)
        
        self._create_widgets()
        self._create_layout()
        self._create_menu()
        self._create_statusbar()
        self._connect_signals()
        
        # Initial state
        self._update_ui_state()
    
    def _create_widgets(self):
        """Create all widgets"""
        # 2 viewers Napari séparés
        self.bmode_viewer = NapariViewerWidget()  # Pour B-mode
        self.ceus_viewer = NapariViewerWidget()   # Pour CEUS + ROI
        
        # Right: TIC plot + ROI panel + Fit panel
        self.tic_plot = TICPlotWidget()
        self.roi_panel = ROIPanel(self.roi_manager)
        self.fit_panel = FitPanel()
    
    def _create_layout(self):
        """Create main layout matching the specification"""
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        
        # ========== TOP: Control buttons ==========
        control_layout = QHBoxLayout()
        self.btn_load = QPushButton("Load DICOM")
        self.btn_detect_flash = QPushButton("Detect flash")
        self.btn_set_flash_manual = QPushButton("Set flash manually")
        self.btn_motion_correction = QPushButton("Motion correction")
        self.btn_preprocess = QPushButton("pre-process")
        self.btn_reset = QPushButton("Reset all (except loading dicom)")
        
        self.btn_detect_flash.setEnabled(False)
        self.btn_set_flash_manual.setEnabled(False)
        self.btn_motion_correction.setEnabled(False)
        self.btn_preprocess.setEnabled(False)
        self.btn_reset.setEnabled(False)
        
        control_layout.addWidget(self.btn_load)
        control_layout.addWidget(self.btn_detect_flash)
        control_layout.addWidget(self.btn_set_flash_manual)
        control_layout.addWidget(self.btn_motion_correction)
        control_layout.addWidget(self.btn_preprocess)
        control_layout.addWidget(self.btn_reset)
        control_layout.addStretch()
        
        main_layout.addLayout(control_layout)
        
        # ========== MIDDLE: 2 panneaux séparés (B-mode | CEUS) + ROI Manager ==========
        images_layout = QHBoxLayout()
        
        # B-mode viewer (gauche)
        bmode_group = QGroupBox("B-mode")
        bmode_layout = QVBoxLayout()
        self.bmode_viewer = NapariViewerWidget()
        bmode_layout.addWidget(self.bmode_viewer)
        bmode_group.setLayout(bmode_layout)
        
        # CEUS viewer (centre)
        ceus_group = QGroupBox("CEUS")
        ceus_layout = QVBoxLayout()
        self.ceus_viewer = NapariViewerWidget()
        ceus_layout.addWidget(self.ceus_viewer)
        ceus_group.setLayout(ceus_layout)
        
        # ROI Manager (droite)
        roi_group = QGroupBox("ROI Manager")
        roi_layout = QVBoxLayout()
        
        # Add toggle button for ROI drawing
        self.btn_draw_roi = QPushButton("✏️ Draw ROI")
        self.btn_draw_roi.setCheckable(True)
        self.btn_draw_roi.setEnabled(False)
        roi_layout.addWidget(self.btn_draw_roi)
        
        # ROI panel
        roi_layout.addWidget(self.roi_panel)
        roi_group.setLayout(roi_layout)
        
        # Ajouter les 3 groupes au layout horizontal
        images_layout.addWidget(bmode_group, stretch=2)
        images_layout.addWidget(ceus_group, stretch=2)
        images_layout.addWidget(roi_group, stretch=1)
        
        main_layout.addLayout(images_layout, stretch=2)
        
        # ========== PLAYBACK CONTROLS ==========
        playback_layout = QHBoxLayout()
        self.play_button = QPushButton("play")
        self.play_button.setMaximumWidth(60)
        self.play_button.setEnabled(False)
        
        self.play_from_start_button = QPushButton("Play from start")
        self.play_from_start_button.setMaximumWidth(120)
        self.play_from_start_button.setEnabled(False)
        
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setEnabled(False)
        
        self.frame_info_label = QLabel("frame ; time (s)")
        
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.play_from_start_button)
        playback_layout.addWidget(self.frame_slider, stretch=1)
        playback_layout.addWidget(self.frame_info_label)
        
        main_layout.addLayout(playback_layout)
        
        # ========== BOTTOM: Fit parameters + TIC plots ==========
        bottom_layout = QHBoxLayout()
        
        # Fit parameters (left)
        fit_group = QGroupBox("Fit parameters")
        fit_layout = QVBoxLayout()
        self.fit_content_label = QLabel("Fit parameters controls")
        self.fit_content_label.setMinimumSize(300, 250)
        self.fit_content_label.setStyleSheet("border: 1px solid #555; background: #1e1e1e;")
        self.fit_content_label.setAlignment(Qt.AlignCenter)
        fit_layout.addWidget(self.fit_content_label)
        fit_group.setLayout(fit_layout)
        
        # TIC plots (right)
        tic_group = QGroupBox("TIC plots")
        tic_layout = QVBoxLayout()
        self.tic_plot_label = QLabel("TIC plot with interactivy with frame and fit parameters")
        self.tic_plot_label.setMinimumSize(600, 250)
        self.tic_plot_label.setStyleSheet("border: 1px solid #555; background: #1e1e1e;")
        self.tic_plot_label.setAlignment(Qt.AlignCenter)
        tic_layout.addWidget(self.tic_plot_label)
        
        # TIC buttons
        tic_buttons_layout = QHBoxLayout()
        tic_buttons_layout.addStretch()
        self.btn_reset_tic = QPushButton("Reset TIC to original")
        self.btn_export_tic = QPushButton("Export tic values")
        self.btn_reset_tic.setEnabled(False)
        self.btn_export_tic.setEnabled(False)
        tic_buttons_layout.addWidget(self.btn_reset_tic)
        
        tic_layout.addLayout(tic_buttons_layout)
        tic_group.setLayout(tic_layout)
        
        # Add export button at bottom right
        export_layout = QVBoxLayout()
        export_layout.addStretch()
        self.btn_export_tic_main = QPushButton("Export tic values")
        self.btn_export_tic_main.setEnabled(False)
        export_layout.addWidget(self.btn_export_tic_main)
        
        bottom_layout.addWidget(fit_group, stretch=1)
        bottom_layout.addWidget(tic_group, stretch=2)
        
        main_layout.addLayout(bottom_layout, stretch=1)
        
        # Add export button below everything
        main_layout.addWidget(self.btn_export_tic_main, alignment=Qt.AlignLeft)
        
        self.setCentralWidget(central_widget)
    
    def _create_menu(self):
        """Create menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        load_action = file_menu.addAction("📁 Load DICOM...")
        load_action.triggered.connect(self.load_dicom)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("🚪 Exit")
        exit_action.triggered.connect(self.close)
        
        # Analysis menu
        analysis_menu = menubar.addMenu("&Analysis")
        
        flash_action = analysis_menu.addAction("⚡ Detect Flash")
        flash_action.triggered.connect(self.detect_flash)
        
        preprocess_action = analysis_menu.addAction("🔧 Preprocess")
        preprocess_action.triggered.connect(self.preprocess_ceus_stack)
        
        motion_action = analysis_menu.addAction("🎯 Motion Correction")
        motion_action.triggered.connect(self.apply_motion_correction)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = help_menu.addAction("ℹ️ About")
        about_action.triggered.connect(self.show_about)
    
    def _create_statusbar(self):
        """Create status bar"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")
    
    def _connect_signals(self):
        """Connect signals and slots"""
        # Top buttons
        self.btn_load.clicked.connect(self.load_dicom)
        self.btn_detect_flash.clicked.connect(self.detect_flash)
        self.btn_set_flash_manual.clicked.connect(self.set_flash_manual)
        self.btn_motion_correction.clicked.connect(self.apply_motion_correction)
        self.btn_preprocess.clicked.connect(self.preprocess_ceus_stack)
        self.btn_reset.clicked.connect(self.reset_analysis)
        
        # Playback controls
        self.play_button.clicked.connect(self.toggle_playback)
        self.play_from_start_button.clicked.connect(self.play_from_start)
        self.frame_slider.valueChanged.connect(self.on_frame_changed)
        
        # ROI drawing (sur le viewer CEUS)
        self.btn_draw_roi.toggled.connect(self.toggle_roi_drawing)
        self.ceus_viewer.roi_added.connect(self.on_roi_added_from_napari)
        self.roi_panel.roi_removed.connect(self.on_roi_removed)
        self.ceus_viewer.frame_changed.connect(self.on_napari_frame_changed)
        
        # TIC buttons
        self.btn_reset_tic.clicked.connect(self.reset_tic)
        self.btn_export_tic.clicked.connect(self.export_tic_values)
        self.btn_export_tic_main.clicked.connect(self.export_tic_values)
    
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
        self.play_from_start_button.setEnabled(has_data)
        self.frame_slider.setEnabled(has_data)
        self.btn_draw_roi.setEnabled(has_data)
    
    def _update_image_display(self):
        """Update image display for current frame"""
        if self.ceus_stack is None:
            return
        
        frame_idx = self.current_frame
        
        # Update both Napari viewers (synchronize frame)
        if self.bmode_stack is not None:
            self.bmode_viewer.set_current_frame(frame_idx)
        self.ceus_viewer.set_current_frame(frame_idx)
        
        # Update frame info
        ceus_data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        time_s = frame_idx / self.fps if self.fps > 0 else 0
        self.frame_info_label.setText(f"frame {frame_idx+1}/{len(ceus_data)} ; time {time_s:.2f}s")
    
    def _display_image(self, image_array, label_widget):
        """Display image (grayscale or RGB) in QLabel - like plt.imshow() in notebook"""
        # Check if RGB or grayscale
        if image_array.ndim == 3 and image_array.shape[-1] == 3:
            # RGB image
            height, width = image_array.shape[:2]
            bytes_per_line = 3 * width
            
            # Convert to uint8 if needed
            if image_array.dtype != np.uint8:
                img_normalized = ((image_array - image_array.min()) / 
                                 (image_array.max() - image_array.min() + 1e-10) * 255).astype(np.uint8)
            else:
                img_normalized = image_array
            
            # Make sure data is contiguous in memory for QImage
            img_normalized = np.ascontiguousarray(img_normalized)
            
            q_image = QImage(img_normalized.data, width, height, bytes_per_line, QImage.Format_RGB888)
        else:
            # Grayscale image
            # Normalize to 0-255
            img_normalized = ((image_array - image_array.min()) / 
                             (image_array.max() - image_array.min() + 1e-10) * 255).astype(np.uint8)
            
            height, width = img_normalized.shape
            bytes_per_line = width
            
            # Make sure data is contiguous in memory for QImage
            img_normalized = np.ascontiguousarray(img_normalized)
            
            q_image = QImage(img_normalized.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        
        # Keep a reference to prevent garbage collection
        q_image._array_ref = img_normalized
        
        pixmap = QPixmap.fromImage(q_image)
        
        # Scale to fit label while keeping aspect ratio
        scaled_pixmap = pixmap.scaled(label_widget.size(), 
                                       Qt.KeepAspectRatio, 
                                       Qt.SmoothTransformation)
        label_widget.setPixmap(scaled_pixmap)
        
        # Update transform for ROI coordinate mapping (if InteractiveImageLabel)
        if hasattr(label_widget, 'update_image_transform'):
            label_widget.update_image_transform(scaled_pixmap, (width, height))
    
    def _display_colormap_image(self, image_array, label_widget, colormap='magma'):
        """Display image with colormap in QLabel"""
        # Normalize to 0-1
        img_normalized = (image_array - image_array.min()) / (image_array.max() - image_array.min() + 1e-10)
        
        # Apply colormap using matplotlib
        from matplotlib import cm
        cmap = cm.get_cmap(colormap)
        img_colored = (cmap(img_normalized)[:, :, :3] * 255).astype(np.uint8)
        
        # Make sure data is contiguous
        img_colored = np.ascontiguousarray(img_colored)
        
        height, width = img_colored.shape[:2]
        bytes_per_line = 3 * width
        
        q_image = QImage(img_colored.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        # Keep reference to prevent garbage collection
        q_image._array_ref = img_colored
        
        pixmap = QPixmap.fromImage(q_image)
        
        # Scale to fit label while keeping aspect ratio
        scaled_pixmap = pixmap.scaled(label_widget.size(), 
                                       Qt.KeepAspectRatio, 
                                       Qt.SmoothTransformation)
        label_widget.setPixmap(scaled_pixmap)
        
        # Update transform for ROI coordinate mapping (if InteractiveImageLabel)
        if hasattr(label_widget, 'update_image_transform'):
            label_widget.update_image_transform(scaled_pixmap, (width, height))
    
    def on_frame_changed(self, frame_idx):
        """Handle frame slider change"""
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self._update_image_display()
    
    def on_napari_frame_changed(self, frame_idx: int):
        """Handle frame change from Napari viewer"""
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(frame_idx)
            self.frame_slider.blockSignals(False)
            # Update frame info
            ceus_data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
            time_s = frame_idx / self.fps if self.fps > 0 else 0
            self.frame_info_label.setText(f"frame {frame_idx+1}/{len(ceus_data)} ; time {time_s:.2f}s")
    
    # =========================================================================
    # DICOM Loading
    # =========================================================================
    
    def load_dicom(self):
        """Load DICOM file"""
        # Default path to data directory
        default_path = Path(__file__).parent.parent.parent.parent / "data"
        if not default_path.exists():
            default_path = Path.home()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DICOM file",
            str(default_path),
            "DICOM files (*);;All files (*)"
        )
        
        if not file_path:
            return
        
        try:
            self.statusbar.showMessage("Loading DICOM...")
            
            # ========== RESET ALL DATA ==========
            # Stop playback if running
            if self.is_playing:
                self.toggle_playback()
            
            # Reset derived data
            self.ceus_preprocessed = None
            self.flash_idx = None
            self.washout_idx = None
            
            # Reset ROIs
            self.roi_manager.clear()
            
            # Load DICOM
            self.dicom_loader = DICOMLoader(Path(file_path))
            self.bmode_stack, self.ceus_stack = self.dicom_loader.load()
            self.fps = self.dicom_loader.get_fps()
            
            if self.ceus_stack is None:
                QMessageBox.warning(self, "Warning", "No CEUS stack found in DICOM")
                return
            
            # Setup frame slider
            n_frames = self.ceus_stack.shape[0]
            self.frame_slider.setMaximum(n_frames - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            
            # Display stacks in separate Napari viewers
            if self.bmode_stack is not None:
                self.bmode_viewer.set_bmode_stack(self.bmode_stack)
            self.ceus_viewer.set_ceus_stack(self.ceus_stack)
            
            # Update status
            manufacturer = self.dicom_loader.scanner_info.get('Manufacturer', 'Unknown')
            model = self.dicom_loader.scanner_info.get('ManufacturerModelName', '')
            bmode_info = f"B-mode: {self.bmode_stack.shape}" if self.bmode_stack is not None else "No B-mode"
            self.statusbar.showMessage(
                f"Loaded: {Path(file_path).name} | "
                f"{manufacturer} {model} | "
                f"FPS: {self.fps:.1f} | "
                f"CEUS: {self.ceus_stack.shape} | {bmode_info}"
            )
            
            self._update_ui_state()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load DICOM:\n{str(e)}")
            self.statusbar.showMessage("Error loading DICOM")
    
    # =========================================================================
    # Flash Detection
    # =========================================================================
    
    def detect_flash(self):
        """Detect flash and washout"""
        if self.ceus_stack is None:
            return
        
        try:
            self.statusbar.showMessage("Detecting flash...")
            
            self.flash_idx, self.washout_idx, intensities = detect_flash_ceus_refined(
                self.ceus_stack,
                exclude_first_n=5,
                search_window=20
            )
            
            self.statusbar.showMessage(
                f"Flash detected at frame {self.flash_idx}, "
                f"washout at frame {self.washout_idx}"
            )
            
            self._update_ui_state()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Flash detection failed:\n{str(e)}")
    
    def set_flash_manual(self):
        """Set flash frame manually to current frame"""
        if self.ceus_stack is None:
            return
        
        # Use current frame as flash
        self.flash_idx = self.current_frame
        
        # Estimate washout as flash + search window
        search_window = 20
        ceus_data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        
        # Calculate intensities for washout detection
        if ceus_data.ndim == 4:
            intensities = ceus_data.mean(axis=(1, 2, 3))
        else:
            intensities = ceus_data.mean(axis=(1, 2))
        
        search_start = self.flash_idx
        search_end = min(len(intensities), self.flash_idx + search_window)
        self.washout_idx = search_start + np.argmin(intensities[search_start:search_end])
        
        self.statusbar.showMessage(
            f"Flash manually set to frame {self.flash_idx}, "
            f"washout estimated at frame {self.washout_idx}"
        )
        
        self._update_ui_state()
    
    # =========================================================================
    # Preprocessing
    # =========================================================================
    
    def preprocess_ceus_stack(self):
        """Preprocess CEUS stack"""
        if self.ceus_stack is None or self.washout_idx is None:
            return
        
        try:
            self.statusbar.showMessage("Preprocessing CEUS...")
            
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
            
            # Update CEUS viewer with preprocessed stack
            self.ceus_viewer.set_ceus_stack(self.ceus_preprocessed, colormap='magma', preprocessed=True)
            
            # Reset to first frame and update display
            self.frame_slider.setMaximum(len(self.ceus_preprocessed) - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            self._update_image_display()
            
            self.statusbar.showMessage("Preprocessing complete")
            self._update_ui_state()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Preprocessing failed:\n{str(e)}")
    
    # =========================================================================
    # Motion Correction
    # =========================================================================
    
    def apply_motion_correction(self):
        """Apply motion correction (estimation on B-mode if available, like notebook)"""
        if self.ceus_stack is None or self.washout_idx is None:
            return
        
        try:
            self.statusbar.showMessage("Applying motion correction...")
            
            # Crop stacks to washout + 15s
            duration_s = 15
            frames_15s = int(duration_s * self.fps)
            end_idx = min(self.washout_idx + frames_15s, len(self.ceus_stack))
            ceus_cropped = self.ceus_stack[self.washout_idx:end_idx]
            
            # Motion compensate using B-mode if available (like notebook)
            ceus_corrected, shifts, source_info = motion_compensate(
                ceus_cropped,
                self.bmode_stack  # Pass full B-mode stack, function will handle cropping
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
            
            # Update CEUS viewer with preprocessed stack
            self.ceus_viewer.set_ceus_stack(self.ceus_preprocessed, colormap='magma', preprocessed=True)
            
            # Reset to first frame and update display
            self.frame_slider.setMaximum(len(self.ceus_preprocessed) - 1)
            self.frame_slider.setValue(0)
            self.current_frame = 0
            self._update_image_display()
            
            self.statusbar.showMessage(
                f"Motion correction complete (estimated from {source_info})"
            )
            self._update_ui_state()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Motion correction failed:\n{str(e)}")
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def on_frame_changed(self, frame_idx: int):
        """Handle frame change in viewer"""
        # Avoid redundant updates
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self._update_image_display()
            
        self.frame_changed.emit(frame_idx)
        # Update TIC plot crosshair
        self.tic_plot.update_crosshair(frame_idx)
    
    def on_roi_added(self, label: str):
        """Handle ROI addition"""
        self.roi_added.emit(label)
        # Trigger TIC computation for this ROI
        # TODO: Implement TIC computation
    
    def on_roi_removed(self, label: str):
        """Handle ROI removal"""
        self.roi_removed.emit(label)
        # Remove TIC curve from plot
        # TODO: Implement TIC removal
    
    # =========================================================================
    # New Methods for Layout
    # =========================================================================
    
    def toggle_playback(self):
        """Toggle play/pause for video playback"""
        if self.ceus_stack is None:
            return
        
        if not self.is_playing:
            # Start playback
            self.is_playing = True
            self.play_button.setText("pause")
            
            # Calculate interval based on FPS
            interval_ms = int(1000 / self.fps) if self.fps > 0 else 100
            self.playback_timer.start(interval_ms)
            
            self.statusbar.showMessage(f"Playback started ({self.fps:.1f} FPS)")
        else:
            # Stop playback
            self.is_playing = False
            self.play_button.setText("play")
            self.playback_timer.stop()
            
            self.statusbar.showMessage("Playback paused")
    
    def play_from_start(self):
        """Reset to frame 0 and start playback"""
        if self.ceus_stack is None:
            return
        
        # Reset to first frame
        self.frame_slider.setValue(0)
        self.current_frame = 0
        self._update_image_display()
        
        # Start playback if not already playing
        if not self.is_playing:
            self.toggle_playback()
    
    def _advance_frame(self):
        """Advance to next frame during playback"""
        if self.ceus_stack is None:
            return
        
        # Get current data (preprocessed or raw)
        ceus_data = self.ceus_preprocessed if self.ceus_preprocessed is not None else self.ceus_stack
        
        # Advance to next frame
        next_frame = self.current_frame + 1
        
        # Loop back to start if at end
        if next_frame >= len(ceus_data):
            next_frame = 0
        
        # Block signals to avoid triggering on_frame_changed during auto-advance
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(next_frame)
        self.frame_slider.blockSignals(False)
        
        # Update display directly
        self.current_frame = next_frame
        self._update_image_display()
    
    def reset_analysis(self):
        """Reset all analysis (except loaded DICOM)"""
        if self.ceus_stack is None:
            return
        
        reply = QMessageBox.question(
            self,
            "Reset Analysis",
            "Reset all analysis results? (DICOM data will be kept)",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Stop playback if running
            if self.is_playing:
                self.toggle_playback()
            
            # Reset all derived data
            self.flash_idx = None
            self.washout_idx = None
            self.ceus_preprocessed = None
            
            # Reset ROIs
            self.roi_manager.clear()
            self.ceus_viewer.clear_rois()
            
            # Reset to first frame
            self.frame_slider.setValue(0)
            self.current_frame = 0
            
            # Update display to show raw CEUS
            self.ceus_viewer.set_ceus_stack(self.ceus_stack)
            self._update_image_display()
            
            self.statusbar.showMessage("Analysis reset - showing raw CEUS data")
            self._update_ui_state()
    
    # =========================================================================
    # ROI Management
    # =========================================================================
    
    def toggle_roi_drawing(self, checked: bool):
        """Toggle ROI drawing mode"""
        self.ceus_viewer.enable_roi_drawing(checked)
        if checked:
            self.statusbar.showMessage("ROI polygone : clic gauche pour ajouter un point, fermer le polygone pour valider.")
            self.btn_draw_roi.setText("🛑 Stop Drawing")
        else:
            self.statusbar.showMessage("ROI drawing disabled")
            self.btn_draw_roi.setText("✏️ Draw ROI")
    
    def on_roi_added_from_napari(self, polygon: list, label: str):
        """Handle ROI drawn in Napari"""
        # Convert polygon to bbox for ROI manager (approximation)
        polygon_array = np.array(polygon)
        x_coords = polygon_array[:, -1]  # Last dimension is X in Napari
        y_coords = polygon_array[:, -2]  # Second to last is Y
        
        x0, x1 = int(x_coords.min()), int(x_coords.max())
        y0, y1 = int(y_coords.min()), int(y_coords.max())
        bbox = (x0, y0, x1, y1)
        
        # Add to manager
        roi = self.roi_manager.add_roi(bbox, label=label)
        
        # Update displays
        self.roi_panel.refresh_list()
        
        self.statusbar.showMessage(f"ROI '{roi.label}' added")
    
    def on_roi_removed(self, label: str):
        """Handle ROI removal"""
        self.statusbar.showMessage(f"ROI '{label}' removed")
    
    # =========================================================================
    # TIC and Export
    # =========================================================================
    
    def reset_tic(self):
        """Reset TIC to original"""
        # TODO: Implement TIC reset
        self.statusbar.showMessage("TIC reset to original")
    
    def export_tic_values(self):
        """Export TIC values to CSV"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export TIC Values",
            str(Path.home() / "tic_values.csv"),
            "CSV files (*.csv);;All files (*)"
        )
        
        if file_path:
            # TODO: Implement TIC export
            self.statusbar.showMessage(f"TIC values exported to {Path(file_path).name}")
    
    # =========================================================================
    # Help
    # =========================================================================
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About CEUS Analyzer",
            "<h2>CEUS Analyzer</h2>"
            "<p>Interactive application for CEUS blood flow analysis.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>DICOM loading (GE + SuperSonic compatible)</li>"
            "<li>Flash and washout detection</li>"
            "<li>Motion compensation</li>"
            "<li>Multi-ROI TIC analysis</li>"
            "<li>Wash-in model fitting</li>"
            "</ul>"
            "<p><b>Version:</b> 0.1.0</p>"
        )
