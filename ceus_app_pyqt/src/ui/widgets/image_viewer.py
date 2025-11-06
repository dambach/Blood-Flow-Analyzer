"""
Image viewer widget with PyQtGraph
Displays B-mode and CEUS frames with temporal slider
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider, 
                             QLabel, QGroupBox, QPushButton)
from PyQt5.QtCore import Qt, pyqtSignal
import pyqtgraph as pg
import numpy as np


class ImageViewerWidget(QWidget):
    """Dual image viewer (B-mode + CEUS) with frame slider"""
    
    frame_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.bmode_stack = None
        self.ceus_stack = None
        self.fps = None
        self.current_frame = 0
        
        self._create_widgets()
        self._create_layout()
        self._connect_signals()
    
    def _create_widgets(self):
        """Create widgets"""
        # B-mode ImageView
        self.bmode_view = pg.ImageView()
        self.bmode_view.ui.roiBtn.hide()
        self.bmode_view.ui.menuBtn.hide()
        self.bmode_view.ui.histogram.hide()
        self.bmode_label = QLabel("B-mode")
        self.bmode_label.setAlignment(Qt.AlignCenter)
        self.bmode_label.setStyleSheet("font-weight: bold; color: #4CAF50;")        # CEUS ImageView
        self.ceus_view = pg.ImageView()
        self.ceus_view.ui.roiBtn.hide()
        self.ceus_view.ui.menuBtn.hide()
        self.ceus_view.ui.histogram.hide()
        self.ceus_label = QLabel("CEUS")
        self.ceus_label.setAlignment(Qt.AlignCenter)
        self.ceus_label.setStyleSheet("font-weight: bold; color: #FF9800;")
        
        # Frame slider
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setValue(0)
        
        # Playback controls
        self.play_btn = QPushButton("▶")
        self.play_btn.setMaximumWidth(40)
        self.play_btn.setEnabled(False)
        
        # Frame info label
        self.frame_label = QLabel("Frame: 0 / 0 (0.00s)")
    
    def _create_layout(self):
        """Create layout"""
        layout = QVBoxLayout()
        
        # Image views side by side
        images_layout = QHBoxLayout()
        
        # B-mode group
        bmode_group = QGroupBox()
        bmode_layout = QVBoxLayout()
        bmode_layout.addWidget(self.bmode_label)
        bmode_layout.addWidget(self.bmode_view)
        bmode_group.setLayout(bmode_layout)
        images_layout.addWidget(bmode_group)
        
        # CEUS group
        ceus_group = QGroupBox()
        ceus_layout = QVBoxLayout()
        ceus_layout.addWidget(self.ceus_label)
        ceus_layout.addWidget(self.ceus_view)
        ceus_group.setLayout(ceus_layout)
        images_layout.addWidget(ceus_group)
        
        layout.addLayout(images_layout)
        
        # Controls
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(QLabel("Frame:"))
        controls_layout.addWidget(self.frame_slider, stretch=1)
        controls_layout.addWidget(self.frame_label)
        
        layout.addLayout(controls_layout)
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """Connect signals"""
        self.frame_slider.valueChanged.connect(self._on_slider_changed)
        self.play_btn.clicked.connect(self._toggle_play)
        
        # Connect timeline changes from both views
        self.bmode_view.timeLine.sigPositionChanged.connect(self._on_timeline_changed)
        self.ceus_view.timeLine.sigPositionChanged.connect(self._on_timeline_changed)
    
    def set_stacks(self, bmode_stack: np.ndarray = None, ceus_stack: np.ndarray = None, 
                   fps: float = 10.0, ceus_is_preprocessed: bool = False):
        """
        Set image stacks to display
        
        Args:
            bmode_stack: B-mode stack (T, H, W) or (T, H, W, 3), can be None
            ceus_stack: CEUS stack (T, H, W) or (T, H, W, 3)
            fps: Frames per second
            ceus_is_preprocessed: If True, use 'magma' colormap for CEUS, else 'gray'
        """
        self.bmode_stack = bmode_stack
        self.ceus_stack = ceus_stack
        self.fps = fps
        
        # Prepare stacks for PyQtGraph (needs transpose for correct orientation)
        # PyQtGraph expects (T, H, W) but displays as (W, H) so we need to be careful
        # The notebook shows images correctly with matplotlib's imshow which uses (H, W)
        # PyQtGraph ImageView uses row-major indexing, so we transpose spatial dims
        
        if bmode_stack is not None:
            # Convert to grayscale if RGB
            if bmode_stack.ndim == 4 and bmode_stack.shape[-1] == 3:
                bmode_gray = np.mean(bmode_stack, axis=-1).astype(np.float32)
            else:
                bmode_gray = bmode_stack.astype(np.float32)
            
            # Transpose to correct orientation: (T, H, W) -> (T, W, H) for PyQtGraph
            bmode_display = np.transpose(bmode_gray, (0, 2, 1))
            
            # Display B-mode (don't set colormap, PyQtGraph uses grayscale by default)
            self.bmode_view.setImage(bmode_display, autoRange=True, autoLevels=True)
            self.bmode_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        else:
            self.bmode_view.clear()
            self.bmode_label.setStyleSheet("font-weight: bold; color: #666;")
        
        if ceus_stack is not None:
            # Convert to grayscale if RGB
            if ceus_stack.ndim == 4 and ceus_stack.shape[-1] == 3:
                ceus_gray = np.mean(ceus_stack, axis=-1).astype(np.float32)
            else:
                ceus_gray = ceus_stack.astype(np.float32)
            
            # Transpose to correct orientation: (T, H, W) -> (T, W, H) for PyQtGraph
            ceus_display = np.transpose(ceus_gray, (0, 2, 1))
            
            # Set image first
            self.ceus_view.setImage(ceus_display, autoRange=True, autoLevels=True)
            
            # Choose colormap based on preprocessing state (like notebook)
            if ceus_is_preprocessed:
                # Preprocessed CEUS uses 'magma' colormap (available in PyQtGraph)
                try:
                    cmap = pg.colormap.get('magma')
                    if cmap is not None:
                        self.ceus_view.setColorMap(cmap)
                except Exception as e:
                    print(f"Warning: Could not set magma colormap: {e}")
                    # Don't set colormap, keep default
                self.ceus_label.setText("CEUS (preprocessed)")
                self.ceus_label.setStyleSheet("font-weight: bold; color: #FFA726;")
            else:
                # Raw CEUS uses default grayscale (don't call setColorMap)
                self.ceus_label.setText("CEUS (raw)")
                self.ceus_label.setStyleSheet("font-weight: bold; color: #FF9800;")
            
            # Update slider based on CEUS stack
            self.frame_slider.setMaximum(len(ceus_stack) - 1)
            self.frame_slider.setValue(0)
            self.play_btn.setEnabled(True)
        else:
            self.ceus_view.clear()
            self.ceus_label.setStyleSheet("font-weight: bold; color: #666;")
            self.play_btn.setEnabled(False)
        
        # Update label
        self._update_frame_label(0)
    
    def _on_slider_changed(self, value: int):
        """Handle slider value change"""
        if self.ceus_stack is None:
            return
        
        self.current_frame = value
        
        # Sync both views
        if self.bmode_stack is not None and value < len(self.bmode_stack):
            self.bmode_view.setCurrentIndex(value)
        if self.ceus_stack is not None and value < len(self.ceus_stack):
            self.ceus_view.setCurrentIndex(value)
        
        self._update_frame_label(value)
        self.frame_changed.emit(value)
    
    def _on_timeline_changed(self):
        """Handle timeline position change (from ImageView)"""
        if self.ceus_stack is None:
            return
        
        # Get index from CEUS view (master)
        value = self.ceus_view.currentIndex
        if value != self.current_frame:
            self.current_frame = value
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(value)
            self.frame_slider.blockSignals(False)
            
            # Sync B-mode view
            if self.bmode_stack is not None and value < len(self.bmode_stack):
                self.bmode_view.setCurrentIndex(value)
            
            self._update_frame_label(value)
            self.frame_changed.emit(value)
    
    def _toggle_play(self):
        """Toggle play/pause"""
        if self.ceus_view.isPlaying():
            self.ceus_view.pause()
            if self.bmode_stack is not None:
                self.bmode_view.pause()
            self.play_btn.setText("▶")
        else:
            self.ceus_view.play(self.fps if self.fps else 10)
            if self.bmode_stack is not None:
                self.bmode_view.play(self.fps if self.fps else 10)
            self.play_btn.setText("⏸")
    
    def _update_frame_label(self, frame_idx: int):
        """Update frame info label"""
        if self.ceus_stack is None:
            self.frame_label.setText("Frame: 0 / 0 (0.00s)")
            return
        
        total_frames = len(self.ceus_stack)
        time_s = frame_idx / self.fps if self.fps else 0
        
        self.frame_label.setText(f"Frame: {frame_idx} / {total_frames-1} ({time_s:.2f}s)")
    
    def jump_to_frame(self, frame_idx: int):
        """Jump to specific frame"""
        if self.stack is None:
            return
        
        frame_idx = max(0, min(frame_idx, len(self.stack) - 1))
        self.frame_slider.setValue(frame_idx)
