"""
CEUS Analyzer with Napari - Optimized Version
Interactive DICOM CEUS analysis with automatic crop and smooth playback
"""

import napari
from napari.utils.theme import get_theme, register_theme
import numpy as np
import pandas as pd
import pydicom
from pathlib import Path
from magicgui import magicgui
# from qtpy.QtWidgets import QMessageBox  # no longer used; keep commented for future dialogs
import matplotlib.pyplot as plt
from datetime import datetime
from skimage.registration import phase_cross_correlation
from scipy.ndimage import shift as scipy_shift
import imageio


def ycbcr_to_rgb(ycbcr):
    """
    Convert YCbCr (YBR_FULL_422) to RGB
    Standard ITU-R BT.601 conversion
    """
    y = ycbcr[:, :, 0].astype(float)
    cb = ycbcr[:, :, 1].astype(float)
    cr = ycbcr[:, :, 2].astype(float)
    
    # Convert to RGB
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    
    # Clip to valid range
    r = np.clip(r, 0, 255)
    g = np.clip(g, 0, 255)
    b = np.clip(b, 0, 255)
    
    # Stack into RGB image
    rgb = np.stack([r, g, b], axis=-1)
    
    return rgb.astype(np.uint8)

class CEUSAnalyzer:
    # Predefined crop presets
    CROP_PRESETS = {
        "No Crop": None,
        "Aixplorer": {"x0": 28, "x1": 346, "y0": 125, "y1": 430},
        "LOGIC": "dynamic"  # Calculated based on image dimensions
    }
    
    # ROI labels and colors
    ROI_LABELS = ["liver", "dia", "cw"]
    ROI_COLORS = {
        "liver": "red",
        "dia": "green", 
        "cw": "blue"
    }
    
    # RGBA color mappings for comparison (normalized 0-1)
    ROI_COLORS_RGBA = {
        "liver": np.array([1., 0., 0., 1.]),  # Red
        "dia": np.array([0., 1., 0., 1.]),    # Green
        "cw": np.array([0., 0., 1., 1.])      # Blue
    }
    
    def __init__(self):
        # Create viewer with default light theme
        self.viewer = napari.Viewer()
        self.viewer.theme = 'light'  # Use built-in light theme
        
        self.frames_cropped = None           # Back-compat view frames (uint8)
        self.frames_view = None              # Display/video frames (uint8)
        self.frames_analyze = None           # Analysis frames (float32, 0-1)
        self.frames_original = None          # Store original frames (as read)
        self.first_frame_rgb = None  # RGB first frame for display
        self.is_ycbcr = False  # Flag to track if frames are in YCbCr format
        self.dicom_path = None
        self.all_frames_loaded = False
        self.fps = 30
        self.flash_frame_idx = 0
        self.tic_data = {}  # Dictionary to store TIC for each ROI label
        self.roi_properties = {}  # Dictionary to store ROI properties (area, perimeter, etc.)
        self.crop_preset = "No Crop"  # Default to No Crop
        self.current_roi_label = "liver"  # Current ROI being drawn
        self.roi_shapes_layer = None  # Shape layer for ROIs
        self._updating_rois = False  # Flag to prevent recursion
        self.roi_labels_map = {}  # Maps shape index to label name (e.g., {0: 'liver', 1: 'dia', 2: 'cw'})
        self.roi_index_by_label = {}  # Direct mapping label -> shape index
        
        self.viewer.title = "CEUS Analyzer"
        
        self._setup_widgets()

        # Hide Layer Controls by default (keep Layer List visible)
        try:
            self._set_layer_ui_visibility(show_layer_list=True, show_layer_controls=False)
        except Exception as e:
            print(f"Note: could not set initial layer UI visibility: {e}")

        # Bind overlay updates for time in seconds
        try:
            self._bind_time_update_events()
        except Exception as e:
            print(f"Note: could not bind time overlay events: {e}")
        
    def _setup_widgets(self):
        """Setup simplified control widgets"""
        
        # Combined load widget with preset selection
        @magicgui(
            call_button="📂 Load DICOM",
            dicom_path={"label": "DICOM File", "mode": "r", "filter": "DICOM files (*)"},
            crop_preset={"label": "Crop Preset", "choices": list(self.CROP_PRESETS.keys())}
        )
        def load_and_crop(dicom_path: Path = Path("data/"), crop_preset: str = "No Crop"):
            self.crop_preset = crop_preset
            self.load_and_process(dicom_path)
        
        # Flash frame widget with display
        @magicgui(
            call_button="⚡ Set Flash Frame",
            flash_frame={"label": "Flash Frame", "min": 0, "max": 1000}
        )
        def set_flash_frame(flash_frame: int = 0):
            self.flash_frame_idx = flash_frame
            self.viewer.status = f"⚡ Flash frame set to: {flash_frame}"
            print(f"⚡ Flash frame set to: {flash_frame}")
            # Update viewer title to show flash frame
            self.viewer.title = f"CEUS Analyzer - Flash Frame: {flash_frame}"
        
        # Temporal crop widget
        @magicgui(
            call_button="✂️ Temporal Crop (Flash+30s)",
            duration_seconds={"label": "Duration (s)", "min": 5, "max": 120, "value": 30}
        )
        def temporal_crop(duration_seconds: int = 30):
            self.apply_temporal_crop(duration_seconds)
        
        # ROI Label selector
        @magicgui(
            auto_call=True,
            roi_label={"label": "ROI Label", "choices": self.ROI_LABELS}
        )
        def select_roi_label(roi_label: str = "liver"):
            self.current_roi_label = roi_label
            print(f"ROI Label changed to: {roi_label}")
            
            # Always update status
            self.viewer.status = f"Selected ROI: {roi_label} ({self.ROI_COLORS[roi_label]})"
            
            # Set to rectangle mode if shapes layer exists
            if self.roi_shapes_layer is not None and self.roi_shapes_layer in self.viewer.layers:
                # Force selection and mode
                self.viewer.layers.selection.active = self.roi_shapes_layer
                self.roi_shapes_layer.mode = 'add_rectangle'
                print(f"Activated rectangle mode for {roi_label}")
        
        # Compute TIC widget
        @magicgui(call_button="📊 Compute TIC (All ROIs)")
        def compute_tic():
            self.compute_tic()
        
        # Export TIC widget
        @magicgui(call_button="💾 Export TIC CSV")
        def export_tic():
            self.export_tic()
        
        # View options: toggle Layer List / Layer Controls
        @magicgui(
            auto_call=True,
            show_layer_list={"label": "Layer List", "value": True},
            show_layer_controls={"label": "Layer Controls", "value": False}
        )
        def view_options(show_layer_list: bool = True, show_layer_controls: bool = False):
            self._set_layer_ui_visibility(show_layer_list, show_layer_controls)

        # Reset widget
        @magicgui(call_button="🔄 Reset")
        def reset():
            self.reset()
        
        # Motion correction widget
        @magicgui(call_button="🔀 Apply Motion Correction")
        def motion_correction():
            self.apply_motion_correction()
        
        # Add widgets to viewer
        self.viewer.window.add_dock_widget(load_and_crop, area="left", name="Load")
        self.viewer.window.add_dock_widget(set_flash_frame, area="left", name="Flash")
        self.viewer.window.add_dock_widget(temporal_crop, area="left", name="Temporal Crop")
        self.viewer.window.add_dock_widget(motion_correction, area="left", name="Motion")
        self.viewer.window.add_dock_widget(select_roi_label, area="left", name="ROI Label")
        self.viewer.window.add_dock_widget(compute_tic, area="left", name="TIC")
        self.viewer.window.add_dock_widget(export_tic, area="left", name="Export")
        self.viewer.window.add_dock_widget(reset, area="left", name="Reset")
        # Place the view options on the right to avoid clutter on the left
        self.viewer.window.add_dock_widget(view_options, area="right", name="View")
        
        # Store widget references
        self.set_flash_frame_widget = set_flash_frame
        self.temporal_crop_widget = temporal_crop
        self.select_roi_label_widget = select_roi_label
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()

    def _bind_time_update_events(self):
        """Bind viewer events to update the on-screen time overlay (t in seconds)."""
        # Initialize overlay style if available
        try:
            overlay = getattr(self.viewer, 'text_overlay', None)
            if overlay is not None:
                overlay.visible = True
                overlay.color = 'white'
                overlay.font_size = 14
                overlay.anchor = 'upper_left'
        except Exception:
            pass
        # Connect to current_step changes
        try:
            self.viewer.dims.events.current_step.connect(lambda e=None: self._update_time_overlay())
        except Exception:
            pass

    def _update_time_overlay(self):
        """Update the viewer text overlay with time (seconds) and frame index."""
        try:
            if len(self.viewer.layers) == 0:
                return
            layer = self.viewer.layers[0]
            # Only if stack (has time axis)
            if hasattr(layer.data, 'shape') and layer.data.ndim >= 3:
                # Assume axis 0 is time
                total = int(layer.data.shape[0])
                idx = 0
                try:
                    step = self.viewer.dims.current_step
                    if len(step) > 0:
                        idx = int(step[0])
                except Exception:
                    idx = 0
                t = idx / float(self.fps if self.fps else 1.0)
                text = f"t = {t:.2f} s   |   frame {idx+1}/{total}"
                overlay = getattr(self.viewer, 'text_overlay', None)
                if overlay is not None:
                    overlay.text = text
                # Also show in status for visibility
                self.viewer.status = text
        except Exception:
            pass

    def _set_layer_ui_visibility(self, show_layer_list: bool = True, show_layer_controls: bool = False):
        """Show/hide the built-in napari Layer List and Layer Controls docks.
        Uses private Qt attributes for compatibility and guards if missing.
        """
        qv = getattr(self.viewer.window, '_qt_viewer', None)
        if qv is None:
            return
        # Candidate attribute names across napari versions
        list_attrs = ('dockLayerList', 'dock_layer_list')
        ctrl_attrs = ('dockLayerControls', 'dock_layer_controls')
        # Toggle Layer List
        for attr in list_attrs:
            dock = getattr(qv, attr, None)
            if dock is not None:
                try:
                    dock.setVisible(show_layer_list)
                except Exception:
                    pass
                break
        # Toggle Layer Controls
        for attr in ctrl_attrs:
            dock = getattr(qv, attr, None)
            if dock is not None:
                try:
                    dock.setVisible(show_layer_controls)
                except Exception:
                    pass
                break
    
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for the viewer"""
        
        @self.viewer.bind_key('Shift-F')  # Use Shift+F to avoid napari conflicts
        def mark_flash_frame(viewer):
            """Mark current frame as flash frame (press Shift+F)"""
            # Get current frame index from viewer dims
            try:
                # Try to get current step from dims
                current_step = viewer.dims.current_step
                if len(current_step) > 0:
                    current_frame = current_step[0]  # First dimension is time/frame
                    self.flash_frame_idx = current_frame
                    # Update the widget value
                    if hasattr(self, 'set_flash_frame_widget'):
                        self.set_flash_frame_widget.flash_frame.value = current_frame
                    # Update viewer title to show flash frame prominently
                    viewer.title = f"CEUS Analyzer - Flash Frame: {current_frame}"
                    viewer.status = f"⚡ Flash frame set to: {current_frame} (press Shift+F)"
                    print(f"⚡ Flash frame marked at frame {current_frame}")
                else:
                    viewer.status = "No frame data available"
            except Exception as e:
                viewer.status = f"Error marking flash frame: {e}"
                print(f"Error in mark_flash_frame: {e}")
        
        @self.viewer.bind_key('Space')
        def toggle_play(viewer):
            """Toggle play/pause for image sequence (press Space)"""
            if len(viewer.layers) > 0:
                # Use the dims controls to toggle play
                try:
                    # Access the dims play button functionality
                    if hasattr(viewer.window, '_qt_viewer'):
                        qt_viewer = viewer.window._qt_viewer
                        dims_slider = qt_viewer.dims
                        
                        # Try to toggle play state
                        if hasattr(dims_slider, 'is_playing') and hasattr(dims_slider, 'stop') and hasattr(dims_slider, 'play'):
                            if dims_slider.is_playing:
                                dims_slider.stop()
                                viewer.status = "⏸ Paused"
                                print("Paused playback")
                            else:
                                dims_slider.play()
                                viewer.status = "▶ Playing"
                                print("Started playback")
                        else:
                            viewer.status = "Play/Pause not available (use Napari play button)"
                            print("Could not access play controls")
                except Exception as e:
                    viewer.status = f"Play/Pause error: {e}"
                    print(f"Error toggling play: {e}")
        
        def undo_last_shape_func(viewer):
            """Undo last drawn shape"""
            shapes_layers = [l for l in viewer.layers if isinstance(l, napari.layers.Shapes)]
            if shapes_layers and len(shapes_layers[0].data) > 0:
                # Remove last shape
                shapes_layer = shapes_layers[0]
                shapes_layer.data = shapes_layer.data[:-1]
                viewer.status = f"↶ Undone - {len(shapes_layer.data)} shapes remaining"
                print(f"Removed last shape, {len(shapes_layer.data)} remaining")
            else:
                viewer.status = "↶ Nothing to undo"
        
        # Bind to both Ctrl+Z (Windows/Linux) and Command+Z (macOS)
        self.viewer.bind_key('Control-Z')(undo_last_shape_func)
        self.viewer.bind_key('Command-Z')(undo_last_shape_func)
    
    def load_and_process(self, dicom_path: Path):
        """Load DICOM, show RGB first frame with original colors"""
        try:
            # If already loaded and just changing preset
            if self.dicom_path and str(dicom_path) == self.dicom_path:
                # Just apply or remove crop based on preset
                if self.crop_preset == "No Crop":
                    # Restore original
                    if self.frames_original is not None:
                        # Ensure original frames are in RGB for display if they were YCbCr
                        frames_to_show = self.frames_original
                        try:
                            if self.is_ycbcr and frames_to_show.ndim == 4 and frames_to_show.shape[-1] == 3:
                                print("Restoring original: converting full stack from YCbCr to RGB for display")
                                rgb = np.zeros_like(frames_to_show)
                                for i in range(frames_to_show.shape[0]):
                                    rgb[i] = ycbcr_to_rgb(frames_to_show[i])
                                frames_to_show = np.clip(rgb, 0, 255).astype(np.uint8)
                        except Exception as _:
                            pass
                        self.display_frames(frames_to_show, "Original Frames (No Crop)")
                        self.viewer.status = "Restored original frames (No Crop)"
                    return
                else:
                    # Apply crop preset
                    self.apply_crop_and_load_all()
                    return
            
            # Handle directory or file
            if dicom_path.is_dir():
                files = sorted([f for f in dicom_path.glob("*") if f.is_file()])
                if not files:
                    self.show_error("No files in directory")
                    return
                dicom_file = files[0]
            else:
                dicom_file = dicom_path
            
            self.dicom_path = str(dicom_file)
            
            # Read DICOM metadata
            ds = pydicom.dcmread(self.dicom_path, force=True)
            
            # Get FPS
            if hasattr(ds, 'CineRate'):
                self.fps = float(ds.CineRate)
            elif hasattr(ds, 'FrameTime'):
                self.fps = 1000.0 / float(ds.FrameTime)
            elif hasattr(ds, 'RecommendedDisplayFrameRate'):
                self.fps = float(ds.RecommendedDisplayFrameRate)
            
            # Load pixel array
            pixel_array = ds.pixel_array
            
            # Check if we need to convert from YCbCr to RGB
            self.is_ycbcr = False
            if hasattr(ds, 'PhotometricInterpretation'):
                photo_interp = ds.PhotometricInterpretation
                if 'YBR' in photo_interp:
                    self.is_ycbcr = True
                    print(f"Detected YCbCr format: {photo_interp}, will convert to RGB")
            
            # Extract first frame based on array dimensions (like display_first_frame.py)
            if pixel_array.ndim == 4:
                # (frames, height, width, channels) - RGB/YCbCr sequence
                first_frame = pixel_array[0, :, :, :]
                total_frames = pixel_array.shape[0]
                # Store all original frames
                self.frames_original = pixel_array.copy()
            elif pixel_array.ndim == 3:
                if pixel_array.shape[0] < pixel_array.shape[1] and pixel_array.shape[0] < pixel_array.shape[2]:
                    # (frames, height, width) - grayscale sequence
                    first_frame = pixel_array[0, :, :]
                    total_frames = pixel_array.shape[0]
                    # Store all original frames
                    self.frames_original = pixel_array.copy()
                else:
                    # (height, width, channels) - single RGB/YCbCr frame
                    first_frame = pixel_array
                    total_frames = 1
                    self.frames_original = pixel_array.copy()
            else:
                # (height, width) - single grayscale frame
                first_frame = pixel_array
                total_frames = 1
                self.frames_original = pixel_array.copy()
            
            # Convert YCbCr to RGB if necessary
            if self.is_ycbcr and first_frame.ndim == 3 and first_frame.shape[-1] == 3:
                first_frame = ycbcr_to_rgb(first_frame)
                print(f"Converted first frame from YCbCr to RGB")
            
            # Store original first frame RGB (no conversion, no normalization)
            self.first_frame_rgb = first_frame
            
            # Clear viewer
            self.viewer.layers.clear()
            
            # Display first frame with ORIGINAL RGB colors
            if first_frame.ndim == 3 and first_frame.shape[-1] == 3:
                # RGB image - display as-is with original colors
                self.viewer.add_image(
                    first_frame,
                    name="First Frame (Original RGB)",
                    rgb=True
                )
            else:
                # Grayscale - display with inferno colormap
                self.viewer.add_image(
                    first_frame,
                    name="First Frame (Grayscale)",
                    colormap="inferno"
                )
            
            self.viewer.status = f"First frame loaded | {total_frames} frames total | FPS: {self.fps:.1f}"
            
            # Apply crop if Aixplorer preset selected, otherwise stay on first frame
            if self.crop_preset != "No Crop":
                self.viewer.status = f"Loading and cropping with {self.crop_preset}..."
                self.apply_crop_and_load_all()
            else:
                # Add shapes layer for manual crop
                self.viewer.add_shapes(
                    name="Draw Crop Rectangle",
                    face_color=[0, 0, 0, 0],  # Transparent
                    edge_color='orange',  # Orange visible on light background
                    edge_width=4
                )
                self.viewer.status += " | Draw rectangle for manual crop"
                
        except Exception as e:
            self.show_error(f"Error loading DICOM: {e}")
    
    def display_frames(self, frames, layer_name="Frames"):
        """Display frames in the viewer.
        Expectations:
        - frames is either
          • grayscale stack: (T, H, W) uint8/float
          • RGB stack: (T, H, W, 3) uint8
          • single frame (H, W, 3) uint8 or (H, W) uint8/float
        - Any YCbCr conversion must be done BEFORE calling this function.
        """
        # Save existing ROI data before clearing
        saved_rois = None
        saved_roi_colors = None
        saved_roi_labels = None
        if self.roi_shapes_layer is not None and self.roi_shapes_layer in self.viewer.layers:
            if len(self.roi_shapes_layer.data) > 0:
                saved_rois = [np.array(shape) for shape in self.roi_shapes_layer.data]
                saved_roi_colors = list(self.roi_shapes_layer.edge_color)
                saved_roi_labels = self.roi_labels_map.copy()
                print(f"Saving {len(saved_rois)} existing ROIs")

        # Clear viewer
        self.viewer.layers.clear()

        # Ensure frames are uint8 (but DON'T re-convert if already uint8)
        if frames.dtype != np.uint8:
            print(f"⚠️  Converting frames from {frames.dtype} to uint8 for proper color display")
            frames = np.clip(frames, 0, 255).astype(np.uint8)
            print(f"✅ Frames converted to uint8")
        else:
            print(f"✅ Frames already uint8, displaying with original colors (like load_and_process)")

        # Display frames - preserve RGB colors if present
        if frames.ndim == 4 and frames.shape[-1] == 3:
            # RGB sequence - display with original RGB colors (no colormap)
            print(f"Displaying {frames.shape[0]} RGB frames with original colors (dtype: {frames.dtype})")
            self.viewer.add_image(frames, name=layer_name, rgb=True)
            # Go to first frame and update overlay
            try:
                if hasattr(self.viewer, 'dims'):
                    # stop if playing then reset to frame 0
                    qv = getattr(self.viewer.window, '_qt_viewer', None)
                    if qv is not None and hasattr(qv, 'dims') and hasattr(qv.dims, 'is_playing') and qv.dims.is_playing:
                        qv.dims.stop()
                    self.viewer.dims.set_current_step(0, 0)
                self._update_time_overlay()
            except Exception:
                pass
        elif frames.ndim == 3:
            # Could be grayscale sequence or single RGB frame
            if frames.shape[-1] == 3:
                # Single RGB frame
                print("Displaying single RGB frame")
                self.viewer.add_image(frames, name=layer_name, rgb=True)
            else:
                # Grayscale sequence
                print(f"Displaying {frames.shape[0]} grayscale frames")
                self.viewer.add_image(frames, name=layer_name, colormap="gray")
                # Go to first frame and update overlay
                try:
                    if hasattr(self.viewer, 'dims'):
                        qv = getattr(self.viewer.window, '_qt_viewer', None)
                        if qv is not None and hasattr(qv, 'dims') and hasattr(qv.dims, 'is_playing') and qv.dims.is_playing:
                            qv.dims.stop()
                        self.viewer.dims.set_current_step(0, 0)
                    self._update_time_overlay()
                except Exception:
                    pass
        else:
            # Fallback - single grayscale frame
            print("Displaying single grayscale frame")
            self.viewer.add_image(frames, name=layer_name, colormap="gray")

        # Restore ROIs if they existed
        if saved_rois is not None:
            print(f"Restoring {len(saved_rois)} ROIs")
            self._setup_shapes_layer()
            self.roi_shapes_layer.data = saved_rois
            self.roi_shapes_layer.edge_color = saved_roi_colors
            self.roi_labels_map = saved_roi_labels
            print(f"ROIs restored: {self.roi_labels_map}")
        else:
            # Add shapes layer for ROI drawing with multiple labels
            self._setup_shapes_layer()
    
    def _setup_shapes_layer(self):
        """Setup shapes layer for ROI drawing with current label color"""
        # Only create if it doesn't exist yet
        if self.roi_shapes_layer is not None and self.roi_shapes_layer in self.viewer.layers:
            # Layer already exists, make sure it's active and in rectangle mode
            self.viewer.layers.selection.active = self.roi_shapes_layer
            self.roi_shapes_layer.mode = 'add_rectangle'
            return
        
        # Create new shapes layer with color for current ROI label
        current_color = self.ROI_COLORS[self.current_roi_label]
        self.roi_shapes_layer = self.viewer.add_shapes(
            name=f"ROIs",
            face_color=[0, 0, 0, 0],
            edge_color=current_color,
            edge_width=4,
            shape_type='rectangle'
        )
        # Ensure it's selected and in rectangle mode
        self.viewer.layers.selection.active = self.roi_shapes_layer
        self.roi_shapes_layer.mode = 'add_rectangle'
        
        # Add callback to enforce one ROI per label and set proper color
        @self.roi_shapes_layer.events.data.connect
        def on_shape_added(event):
            self._on_shape_added()
    
    def _on_shape_added(self):
        """Handle new shape: assign label and color, enforce one ROI per label"""
        if self.roi_shapes_layer is None or len(self.roi_shapes_layer.data) == 0:
            return
        
        # Avoid recursion
        if self._updating_rois:
            return
        
        self._updating_rois = True
        
        try:
            current_label = self.current_roi_label
            current_color_rgba = self.ROI_COLORS_RGBA[current_label]
            
            print(f"\n=== Shape Added: label={current_label}, color={self.ROI_COLORS[current_label]} ===")
            
            # Get all current shapes
            shapes_list = list(self.roi_shapes_layer.data)
            
            # Find if we already have a shape with this label
            old_index = None
            for idx, label in self.roi_labels_map.items():
                if label == current_label:
                    old_index = idx
                    print(f"Found existing ROI with label '{current_label}' at index {idx}")
                    break
            
            # Build new shapes list and labels map
            new_shapes = []
            new_colors = []
            new_labels_map = {}
            
            for idx in range(len(shapes_list)):
                # Skip the old shape with same label
                if idx == old_index:
                    print(f"  Skipping old shape at index {idx}")
                    continue
                
                # Keep this shape
                new_shapes.append(shapes_list[idx])
                
                # Preserve color if it had a label
                if idx in self.roi_labels_map:
                    label = self.roi_labels_map[idx]
                    new_colors.append(self.ROI_COLORS_RGBA[label])
                    new_idx = len(new_shapes) - 1
                    new_labels_map[new_idx] = label
                    print(f"  Keeping shape {idx} -> {new_idx} with label '{label}'")
                else:
                    # This is the new shape
                    new_colors.append(current_color_rgba)
                    new_idx = len(new_shapes) - 1
                    new_labels_map[new_idx] = current_label
                    print(f"  Adding new shape at index {new_idx} with label '{current_label}'")
            
            # Update the layer with all shapes at once
            self.roi_shapes_layer.data = new_shapes
            self.roi_shapes_layer.edge_color = new_colors
            self.roi_labels_map = new_labels_map
            
            # Clear selection
            self.roi_shapes_layer.selected_data = set()
            
            # Ensure layer visibility
            self.roi_shapes_layer.visible = True
            self.roi_shapes_layer.opacity = 1.0
            
            print(f"Final: {len(new_shapes)} shapes")
            print(f"Labels map: {self.roi_labels_map}")
            
            self.viewer.status = f"✓ ROI '{current_label}' saved ({self.ROI_COLORS[current_label]}) - {len(self.roi_labels_map)} total"
            
        finally:
            self._updating_rois = False
    
    def _load_existing_rois(self):
        """Load existing ROIs from tic_data into shapes layer"""
        if not self.tic_data:
            return
        
        shapes_data = []
        edge_colors = []
        
        for label in self.ROI_LABELS:
            if label in self.tic_data and 'roi' in self.tic_data[label]:
                roi = self.tic_data[label]['roi']
                # Convert ROI to rectangle shape format
                shapes_data.append(roi)
                edge_colors.append(self.ROI_COLORS[label])
        
        if shapes_data:
            self.roi_shapes_layer.data = shapes_data
            self.roi_shapes_layer.edge_color = edge_colors
    
    def apply_crop_and_load_all(self):
        """Load all frames and apply crop (preset or manual)"""
        try:
            if self.dicom_path is None:
                self.show_error("Load DICOM first")
                return
            
            if self.frames_original is None:
                self.show_error("Original frames not loaded")
                return
            
            # Get crop coordinates
            if self.crop_preset != "No Crop":
                # Use preset
                preset_coords = self.CROP_PRESETS[self.crop_preset]
                
                if preset_coords == "dynamic":
                    # Dynamic LOGIC preset: right half minus 10% top and bottom
                    frames = self.frames_original
                    
                    # Get image dimensions
                    if frames.ndim == 4:
                        # (frames, height, width, channels)
                        height, width = frames.shape[1], frames.shape[2]
                    elif frames.ndim == 3:
                        if frames.shape[0] < frames.shape[1]:
                            # (frames, height, width) - grayscale
                            height, width = frames.shape[1], frames.shape[2]
                        else:
                            # (height, width, channels) - single frame
                            height, width = frames.shape[0], frames.shape[1]
                    else:
                        # (height, width) - single grayscale
                        height, width = frames.shape
                    
                    # Calculate LOGIC coordinates: right half, minus 10% top/bottom
                    x0 = width // 2  # Start at middle
                    x1 = width  # End at right edge
                    y0 = int(height * 0.1)  # 10% from top
                    y1 = int(height * 0.9)  # 10% from bottom
                    
                    print(f"LOGIC preset: Image {width}x{height} → Crop x:[{x0},{x1}], y:[{y0},{y1}]")
                else:
                    # Fixed coordinates preset (like Aixplorer)
                    x0, x1 = preset_coords["x0"], preset_coords["x1"]
                    y0, y1 = preset_coords["y0"], preset_coords["y1"]
            else:
                # Get from drawn shape
                shapes_layers = [l for l in self.viewer.layers if isinstance(l, napari.layers.Shapes)]
                if not shapes_layers or len(shapes_layers[0].data) == 0:
                    self.show_error("Draw a rectangle first or select a preset")
                    return
                
                shape_data = shapes_layers[0].data[0]
                y_coords = shape_data[:, 0]
                x_coords = shape_data[:, 1]
                y0, y1 = int(np.min(y_coords)), int(np.max(y_coords))
                x0, x1 = int(np.min(x_coords)), int(np.max(x_coords))
            
            # Use stored original frames
            self.viewer.status = "Applying crop..."
            frames = self.frames_original.copy()
            
            # Crop frames
            if frames.ndim == 3:
                # Grayscale sequence (frames, height, width)
                cropped = frames[:, y0:y1, x0:x1]
                is_ycbcr_cropped = False  # Grayscale, no conversion needed
            elif frames.ndim == 4:
                # RGB/YCbCr sequence (frames, height, width, channels)
                cropped = frames[:, y0:y1, x0:x1, :]
                is_ycbcr_cropped = self.is_ycbcr  # Use stored flag
            else:
                self.show_error(f"Unexpected frame dimensions: {frames.shape}")
                return

            # If original was YCbCr, CONVERT cropped frames to RGB NOW and store as RGB
            if cropped.ndim == 4 and is_ycbcr_cropped:
                print(f"YCbCr detected → converting cropped frames ({cropped.shape[0]}) to RGB once")
                frames_rgb = np.zeros_like(cropped)
                for i in range(cropped.shape[0]):
                    frames_rgb[i] = ycbcr_to_rgb(cropped[i])
                cropped = np.clip(frames_rgb, 0, 255).astype(np.uint8)
                is_ycbcr_cropped = False  # Now RGB
                print("✔️ Cropped frames converted to RGB and stored")

            # Ensure uint8 storage for consistent display
            if cropped.dtype != np.uint8:
                cropped = np.clip(cropped, 0, 255).astype(np.uint8)

            self.frames_cropped = cropped
            self.all_frames_loaded = True
            
            # Display cropped frames (no further YCbCr conversion needed)
            self.display_frames(cropped, f"CEUS Cropped ({self.crop_preset})")
            
            self.viewer.status = f"✅ Loaded {cropped.shape[0]} frames | Cropped: {cropped.shape}"
            
            # DO NOT apply motion correction automatically - user should:
            # 1. Set flash frame first
            # 2. Apply temporal crop (Flash + 30s)
            # 3. Then motion correction will be applied automatically
            
        except Exception as e:
            self.show_error(f"Error loading and cropping: {e}")
    
    def apply_temporal_crop(self, duration_seconds=30):
        """Crop video temporally: Flash frame + duration (e.g., 30s)"""
        if self.frames_cropped is None or not self.all_frames_loaded:
            self.show_error("Load and crop frames first")
            return
        
        if self.flash_frame_idx == 0:
            self.show_error("⚠️ Set flash frame first (press 'Shift+F' or use widget)")
            return
        
        try:
            # Calculate temporal crop window
            duration_frames = int(duration_seconds * self.fps)
            
            # Include a few frames before flash for baseline (5 frames or 10% of flash, whichever is smaller)
            baseline_frames = min(5, max(1, int(self.flash_frame_idx * 0.1)))
            start_frame = max(0, self.flash_frame_idx - baseline_frames)
            end_frame = min(self.frames_cropped.shape[0], self.flash_frame_idx + duration_frames)
            
            print(f"\n=== TEMPORAL CROP ===")
            print(f"Flash frame: {self.flash_frame_idx}")
            print(f"FPS: {self.fps}")
            print(f"Requested duration: {duration_seconds}s = {duration_frames} frames")
            print(f"Baseline: {baseline_frames} frames before flash")
            print(f"Crop window: frames {start_frame} to {end_frame} ({end_frame - start_frame} frames total)")
            print(f"Actual duration: {(end_frame - start_frame) / self.fps:.1f}s")
            
            # Crop temporally
            self.frames_cropped = self.frames_cropped[start_frame:end_frame]
            
            # Adjust flash frame index to new timeline
            old_flash_idx = self.flash_frame_idx
            self.flash_frame_idx = self.flash_frame_idx - start_frame
            
            # Update the widget value and viewer title
            if hasattr(self, 'set_flash_frame_widget'):
                self.set_flash_frame_widget.flash_frame.value = self.flash_frame_idx
                # Update max value to new frame count
                self.set_flash_frame_widget.flash_frame.max = self.frames_cropped.shape[0] - 1
            
            # Update viewer title to show new flash frame
            self.viewer.title = f"CEUS Analyzer - Flash Frame: {self.flash_frame_idx}"
            
            # Ensure uint8
            print(f"Frames before update: dtype={self.frames_cropped.dtype}, shape={self.frames_cropped.shape}")
            if self.frames_cropped.dtype != np.uint8:
                print(f"⚠️  Converting to uint8 before layer update")
                self.frames_cropped = np.clip(self.frames_cropped, 0, 255).astype(np.uint8)

            # IMPORTANT: Do NOT clear/re-display to avoid Qt slider deletion
            # Update the existing image layer data directly
            if len(self.viewer.layers) > 0:
                try:
                    image_layer = self.viewer.layers[0]
                    image_layer.data = self.frames_cropped
                    # Reset to first frame for playback from start
                    try:
                        qv = getattr(self.viewer.window, '_qt_viewer', None)
                        if qv is not None and hasattr(qv, 'dims') and hasattr(qv.dims, 'is_playing') and qv.dims.is_playing:
                            qv.dims.stop()
                        self.viewer.dims.set_current_step(0, 0)
                    except Exception:
                        pass
                    self._update_time_overlay()
                    print("✅ Updated image layer data after temporal crop (no re-display)")
                except Exception as e:
                    print(f"⚠️ Could not update image layer directly: {e}")
            else:
                # Fallback (should not happen): display once
                self.display_frames(self.frames_cropped, f"CEUS Temporal (Flash+{duration_seconds}s)")
            
            actual_duration = (end_frame - start_frame) / self.fps
            self.viewer.status = f"✂️ Temporal crop: {end_frame - start_frame} frames ({actual_duration:.1f}s)"
            
            print(f"✅ Temporal crop complete")
            print(f"Flash frame adjusted: {old_flash_idx} → {self.flash_frame_idx}")
            
            # Stop any ongoing animation to avoid RuntimeError with slider
            try:
                if hasattr(self.viewer.window, '_qt_viewer'):
                    qt_viewer = self.viewer.window._qt_viewer
                    if hasattr(qt_viewer, 'dims'):
                        dims_slider = qt_viewer.dims
                        if hasattr(dims_slider, 'is_playing') and dims_slider.is_playing:
                            dims_slider.stop()
                            print("⏸ Stopped animation before motion correction")
            except Exception as e:
                print(f"Note: Could not stop animation (not critical): {e}")
            
            # Apply motion correction automatically after temporal crop
            print(f"\n🔀 Applying motion correction on temporal window...")
            self.apply_motion_correction()
            
        except Exception as e:
            self.show_error(f"Temporal crop error: {e}")
            import traceback
            traceback.print_exc()
    
    def apply_motion_correction(self):
        """Apply motion correction to align all frames to reference frame"""
        if self.frames_cropped is None or not self.all_frames_loaded:
            self.show_error("Load and crop frames first")
            return
        
        try:
            self.viewer.status = "🔄 Applying motion correction..."
            print("\n=== MOTION CORRECTION ===")
            
            frames = self.frames_cropped.copy()
            frames_before = frames.copy()  # Keep copy for video export
            
            # Use first frame as reference (or flash frame if set)
            reference_idx = self.flash_frame_idx if self.flash_frame_idx > 0 else 0
            
            # Handle RGB or grayscale
            if frames.ndim == 4 and frames.shape[-1] == 3:
                # RGB: convert to grayscale for registration
                reference_frame = np.mean(frames[reference_idx, :, :, :], axis=2)
                is_rgb = True
            else:
                # Grayscale
                reference_frame = frames[reference_idx, :, :]
                is_rgb = False
            
            print(f"Reference frame: {reference_idx}")
            print(f"Frame shape: {reference_frame.shape}")
            print(f"RGB mode: {is_rgb}")
            
            # Store aligned frames
            aligned_frames = np.zeros_like(frames)
            shifts_log = []
            
            # Progress tracking
            total_frames = frames.shape[0]
            
            for i in range(total_frames):
                # Get current frame
                if is_rgb:
                    current_frame_gray = np.mean(frames[i, :, :, :], axis=2)
                    current_frame_rgb = frames[i, :, :, :]
                else:
                    current_frame_gray = frames[i, :, :]
                
                # Calculate shift using phase cross-correlation
                shift_result = phase_cross_correlation(
                    reference_frame, 
                    current_frame_gray,
                    upsample_factor=10  # Sub-pixel precision
                )
                shift_y, shift_x = shift_result[0]
                
                # Apply shift to RGB or grayscale
                if is_rgb:
                    for c in range(3):  # Apply to each color channel
                        aligned_frames[i, :, :, c] = scipy_shift(
                            current_frame_rgb[:, :, c],
                            shift=(shift_y, shift_x),
                            order=3,  # Cubic interpolation
                            mode='nearest'
                        )
                else:
                    aligned_frames[i, :, :] = scipy_shift(
                        current_frame_gray,
                        shift=(shift_y, shift_x),
                        order=3,
                        mode='nearest'
                    )
                
                # Log shift
                shifts_log.append((i, shift_y, shift_x))
                
                # Update status every 10 frames
                if i % 10 == 0 or i == total_frames - 1:
                    progress = (i + 1) / total_frames * 100
                    self.viewer.status = f"🔄 Motion correction: {progress:.1f}% ({i+1}/{total_frames})"
            
            # Convert aligned frames to uint8 for proper RGB display
            # scipy_shift returns float64, we need uint8 for correct colors
            self.frames_cropped = np.clip(aligned_frames, 0, 255).astype(np.uint8)
            print(f"Frames converted to uint8: {self.frames_cropped.dtype}, shape: {self.frames_cropped.shape}")
            
            # Calculate statistics
            shifts_array = np.array([(s[1], s[2]) for s in shifts_log])
            max_shift_y = np.max(np.abs(shifts_array[:, 0]))
            max_shift_x = np.max(np.abs(shifts_array[:, 1]))
            mean_shift_y = np.mean(np.abs(shifts_array[:, 0]))
            mean_shift_x = np.mean(np.abs(shifts_array[:, 1]))
            
            print(f"\n✅ Motion correction complete!")
            print(f"Max shift: Y={max_shift_y:.2f}, X={max_shift_x:.2f} pixels")
            print(f"Mean shift: Y={mean_shift_y:.2f}, X={mean_shift_x:.2f} pixels")
            
            # Save shift log
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            shift_df = pd.DataFrame(shifts_log, columns=['Frame', 'Shift_Y', 'Shift_X'])
            filename_csv = f"Motion_Shifts_{timestamp}.csv"
            shift_df.to_csv(filename_csv, index=False)
            
            # Export videos for comparison
            self.viewer.status = "🎬 Exporting comparison videos..."
            print("\n🎬 Exporting videos...")
            
            video_before = f"Video_BEFORE_MotionCorrection_{timestamp}.mp4"
            video_after = f"Video_AFTER_MotionCorrection_{timestamp}.mp4"
            
            # Export before video
            self._export_video(frames_before, video_before, fps=self.fps)
            print(f"✅ Before: {video_before}")
            
            # Export after video
            self._export_video(self.frames_cropped, video_after, fps=self.fps)
            print(f"✅ After: {video_after}")
            
            # CRITICAL: Verify frames are uint8
            print(f"\n🔍 Verifying frames...")
            print(f"   dtype: {self.frames_cropped.dtype}")
            print(f"   shape: {self.frames_cropped.shape}")
            print(f"   min: {np.min(self.frames_cropped)}, max: {np.max(self.frames_cropped)}")
            
            if self.frames_cropped.dtype != np.uint8:
                print(f"⚠️  WARNING: Frames are {self.frames_cropped.dtype}, converting to uint8...")
                self.frames_cropped = np.clip(self.frames_cropped, 0, 255).astype(np.uint8)
                print(f"✅ Converted to uint8")
            else:
                print(f"✅ Frames are already uint8 - NO RE-DISPLAY NEEDED")
            
            # DO NOT re-display to avoid Qt slider errors
            # Frames are already displayed from temporal_crop or previous display_frames
            # Just update the image layer data directly
            if len(self.viewer.layers) > 0:
                image_layer = self.viewer.layers[0]  # First layer is the image
                image_layer.data = self.frames_cropped
                # Reset to first frame for playback from start of the corrected clip
                try:
                    qv = getattr(self.viewer.window, '_qt_viewer', None)
                    if qv is not None and hasattr(qv, 'dims') and hasattr(qv.dims, 'is_playing') and qv.dims.is_playing:
                        qv.dims.stop()
                    self.viewer.dims.set_current_step(0, 0)
                except Exception:
                    pass
                self._update_time_overlay()
                print(f"✅ Updated image layer data without recreating viewer")
            
            self.viewer.status = f"✅ Motion corrected | Max shift: {max_shift_y:.1f}×{max_shift_x:.1f}px"
            self.show_info(f"Motion correction applied!\n\n"
                          f"📊 Statistics:\n"
                          f"  • Max shift: Y={max_shift_y:.2f}, X={max_shift_x:.2f} px\n"
                          f"  • Mean shift: Y={mean_shift_y:.2f}, X={mean_shift_x:.2f} px\n"
                          f"  • Reference frame: {reference_idx}\n\n"
                          f"💾 Files saved:\n"
                          f"  • Shifts: {filename_csv}\n"
                          f"  • Before: {video_before}\n"
                          f"  • After: {video_after}")
            
        except Exception as e:
            self.show_error(f"Motion correction error: {e}")
            import traceback
            traceback.print_exc()
    
    def _export_video(self, frames, filename, fps=13):
        """Export frames as MP4 video"""
        try:
            print(f"  Exporting {filename}...")
            
            # Prepare frames for export
            if frames.ndim == 4 and frames.shape[-1] == 3:
                # RGB: use as-is
                video_frames = frames.astype(np.uint8)
            elif frames.ndim == 3:
                # Grayscale: convert to RGB
                video_frames = np.stack([frames]*3, axis=-1).astype(np.uint8)
            else:
                raise ValueError(f"Unsupported frame dimensions: {frames.shape}")
            
            # Ensure dimensions are even (required by H.264 encoder)
            n_frames, height, width, channels = video_frames.shape
            new_height = height if height % 2 == 0 else height - 1
            new_width = width if width % 2 == 0 else width - 1
            
            if new_height != height or new_width != width:
                print(f"    Adjusting dimensions: {height}x{width} → {new_height}x{new_width} (H.264 requires even dimensions)")
                video_frames = video_frames[:, :new_height, :new_width, :]
            
            # Write video with imageio
            imageio.mimwrite(
                filename,
                video_frames,
                fps=fps,
                codec='libx264',
                quality=8,  # 0-10, higher is better
                macro_block_size=1
            )
            
            print(f"  ✅ Video saved: {filename} ({video_frames.shape[0]} frames @ {fps} FPS, {new_height}x{new_width})")
            
        except Exception as e:
            print(f"  ⚠️  Error exporting video: {e}")
            import traceback
            traceback.print_exc()
    
    def compute_tic(self):
        """Compute Time-Intensity Curve for all ROIs"""
        try:
            if self.frames_cropped is None or not self.all_frames_loaded:
                self.show_error("Load and crop frames first")
                return
            
            # Find shapes layer for ROI
            if self.roi_shapes_layer is None or len(self.roi_shapes_layer.data) == 0:
                self.show_error("Draw at least one ROI rectangle first")
                return
            
            # Get all ROIs from shapes layer
            shapes_data = self.roi_shapes_layer.data
            
            print(f"\n=== COMPUTE TIC DEBUG ===")
            print(f"Number of shapes: {len(shapes_data)}")
            print(f"ROI labels map: {self.roi_labels_map}")
            
            # Process each ROI using our label mapping
            self.tic_data = {}
            
            for idx, shape_data in enumerate(shapes_data):
                
                # Get label from our mapping
                if idx not in self.roi_labels_map:
                    print(f"Shape {idx}: No label in map, skipping")
                    continue
                
                label = self.roi_labels_map[idx]
                print(f"Shape {idx}: Label = '{label}'")
                
                # Skip if we already have a ROI for this label (shouldn't happen)
                if label in self.tic_data:
                    print(f"  ⚠ Skipping duplicate ROI for label {label}")
                    continue
                
                # Get ROI coordinates
                y_coords = shape_data[:, 0]
                x_coords = shape_data[:, 1]
                y0, y1 = int(np.min(y_coords)), int(np.max(y_coords))
                x0, x1 = int(np.min(x_coords)), int(np.max(x_coords))
                
                # Calculate ROI properties (inspired by regionprops)
                roi_width = x1 - x0
                roi_height = y1 - y0
                roi_area = roi_width * roi_height
                roi_perimeter = 2 * (roi_width + roi_height)
                
                print(f"  ROI coords: x[{x0}:{x1}], y[{y0}:{y1}]")
                print(f"  ROI size: {roi_width}x{roi_height} pixels, area={roi_area} px²")
                
                # Compute TIC for this ROI
                tic = []
                tic_min = []
                tic_max = []
                tic_std = []
                frames = self.frames_cropped
                
                for i in range(frames.shape[0]):
                    frame = frames[i]
                    
                    # Extract ROI
                    if frame.ndim == 3 and frame.shape[2] >= 3:
                        roi_frame = frame[y0:y1, x0:x1, 0]
                    elif frame.ndim == 2:
                        roi_frame = frame[y0:y1, x0:x1]
                    else:
                        roi_frame = frame[y0:y1, x0:x1]
                    
                    # Calculate statistics (inspired by regionprops)
                    mean_intensity = np.mean(roi_frame)
                    min_intensity = np.min(roi_frame)
                    max_intensity = np.max(roi_frame)
                    std_intensity = np.std(roi_frame)
                    
                    tic.append(mean_intensity)
                    tic_min.append(min_intensity)
                    tic_max.append(max_intensity)
                    tic_std.append(std_intensity)
                
                # Store TIC and ROI info with extended properties
                self.tic_data[label] = {
                    'tic_mean': np.array(tic),
                    'tic_min': np.array(tic_min),
                    'tic_max': np.array(tic_max),
                    'tic_std': np.array(tic_std),
                    'roi': shape_data,
                    'coords': (x0, y0, x1, y1)
                }
                
                # Store ROI properties
                self.roi_properties[label] = {
                    'area': roi_area,
                    'perimeter': roi_perimeter,
                    'width': roi_width,
                    'height': roi_height,
                    'bbox': (x0, y0, x1, y1),
                    'mean_intensity_overall': np.mean(tic),
                    'min_intensity_overall': np.min(tic_min),
                    'max_intensity_overall': np.max(tic_max),
                    'std_intensity_overall': np.mean(tic_std)
                }
                
                print(f"  ✓ Computed TIC with {len(tic)} frames")
                print(f"  ✓ ROI properties saved")
            
            if not self.tic_data:
                self.show_error("No valid ROIs found")
                return
            
            # Display ROI properties summary
            self._display_roi_properties()
            
            # Plot all TICs
            self.plot_tic()
            
            roi_summary = ", ".join([f"{lbl} ({self.ROI_COLORS[lbl]})" for lbl in self.tic_data.keys()])
            self.viewer.status = f"✅ TIC computed for: {roi_summary}"
            
        except Exception as e:
            self.show_error(f"Error computing TIC: {e}")
    
    def _display_roi_properties(self):
        """Display ROI properties summary in console (inspired by regionprops)"""
        print("\n" + "="*70)
        print("ROI PROPERTIES SUMMARY")
        print("="*70)
        
        for label in self.ROI_LABELS:
            if label in self.roi_properties:
                props = self.roi_properties[label]
                print(f"\n📍 {label.upper()} ({self.ROI_COLORS[label]})")
                print(f"  • Area: {props['area']} pixels²")
                print(f"  • Dimensions: {props['width']} x {props['height']} pixels")
                print(f"  • Perimeter: {props['perimeter']} pixels")
                print(f"  • Bounding box: {props['bbox']}")
                print(f"  • Mean intensity: {props['mean_intensity_overall']:.2f}")
                print(f"  • Min intensity: {props['min_intensity_overall']:.2f}")
                print(f"  • Max intensity: {props['max_intensity_overall']:.2f}")
                print(f"  • Std intensity: {props['std_intensity_overall']:.2f}")
        
        print("\n" + "="*70 + "\n")
    
    def plot_tic(self):
        """Plot TIC curves for all ROIs with mean ± std on a single plot"""
        if not self.tic_data:
            return
        
        # Close any existing TIC plots to refresh
        plt.close('TIC - Time Intensity Curves')
        
        # Set style for clean look
        plt.style.use('seaborn-v0_8-whitegrid')
        
        # Single plot with larger size
        fig, ax = plt.subplots(1, 1, figsize=(14, 8), facecolor='white')
        fig.canvas.manager.set_window_title('TIC Analysis - All ROIs')
        
        ax.set_facecolor('#f0f2f6')
        
        # Plot all ROIs: mean ± std
        for label, data in self.tic_data.items():
            tic_mean = data['tic_mean']
            tic_std = data['tic_std']
            color = self.ROI_COLORS[label]
            frames = np.arange(len(tic_mean))
            
            # Calculate mean ± std bounds
            upper_bound = tic_mean + tic_std
            lower_bound = tic_mean - tic_std
            
            # Plot mean line with markers
            ax.plot(frames, tic_mean, color=color, linewidth=3, marker='o', 
                   markersize=5, markerfacecolor='white', markeredgewidth=2, 
                   markeredgecolor=color, alpha=0.95, label=f'{label.upper()}', zorder=3)
            
            # Add std band (mean ± std)
            ax.fill_between(frames, lower_bound, upper_bound, color=color, alpha=0.2, zorder=1)
        
        # Styling
        ax.set_xlabel('Frame', fontsize=14, fontweight='bold', color='#262730')
        ax.set_ylabel('Intensity (mean ± std)', fontsize=14, fontweight='bold', color='#262730')
        ax.set_title('Time-Intensity Curves (TIC) - All ROIs', fontsize=16, 
                    fontweight='bold', color='#262730', pad=20)
        ax.legend(loc='best', fontsize=12, framealpha=0.95, fancybox=True, shadow=True)
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5, color='white')
        
        # Spine styling
        for spine in ax.spines.values():
            spine.set_color('#e0e0e0')
            spine.set_linewidth(1.5)
        
        plt.tight_layout()
        plt.show(block=False)  # Non-blocking to allow interaction
        plt.pause(0.1)  # Small pause to ensure window appears
    
    def export_tic(self):
        """Export TIC and ROI properties to CSV (inspired by regionprops export)"""
        if not self.tic_data:
            self.show_info("Compute TIC first")
            return
        
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 1. Export TIC time series data
            tic_length = len(next(iter(self.tic_data.values()))['tic_mean'])
            data_tic = {
                "Frame": np.arange(1, tic_length + 1),
                "Time_s": np.arange(tic_length) / self.fps
            }
            
            # Add each ROI's TIC statistics as columns
            for label, tic_info in self.tic_data.items():
                data_tic[f"{label}_mean"] = tic_info['tic_mean']
                data_tic[f"{label}_min"] = tic_info['tic_min']
                data_tic[f"{label}_max"] = tic_info['tic_max']
                data_tic[f"{label}_std"] = tic_info['tic_std']
            
            df_tic = pd.DataFrame(data_tic)
            filename_tic = f"TIC_TimeSeries_{timestamp}.csv"
            df_tic.to_csv(filename_tic, index=False)
            
            # 2. Export ROI properties (inspired by regionprops table)
            if self.roi_properties:
                props_rows = []
                for label in self.ROI_LABELS:
                    if label in self.roi_properties:
                        props = self.roi_properties[label]
                        row = {
                            'ROI_Label': label,
                            'ROI_Color': self.ROI_COLORS[label],
                            'Area_pixels': props['area'],
                            'Width_pixels': props['width'],
                            'Height_pixels': props['height'],
                            'Perimeter_pixels': props['perimeter'],
                            'BBox_x0': props['bbox'][0],
                            'BBox_y0': props['bbox'][1],
                            'BBox_x1': props['bbox'][2],
                            'BBox_y1': props['bbox'][3],
                            'Mean_Intensity_Overall': props['mean_intensity_overall'],
                            'Min_Intensity_Overall': props['min_intensity_overall'],
                            'Max_Intensity_Overall': props['max_intensity_overall'],
                            'Std_Intensity_Overall': props['std_intensity_overall']
                        }
                        props_rows.append(row)
                
                df_props = pd.DataFrame(props_rows)
                filename_props = f"ROI_Properties_{timestamp}.csv"
                df_props.to_csv(filename_props, index=False)
                
                self.viewer.status = f"✅ Exported: {filename_tic} & {filename_props}"
                self.show_info(f"Data exported successfully:\n\n"
                              f"📊 Time series: {filename_tic}\n"
                              f"   • Columns: {', '.join(data_tic.keys())}\n\n"
                              f"📋 ROI properties: {filename_props}\n"
                              f"   • {len(props_rows)} ROIs with {len(df_props.columns)} properties each")
            else:
                self.viewer.status = f"✅ TIC exported to {filename_tic}"
                self.show_info(f"TIC time series exported to:\n{filename_tic}")
            
        except Exception as e:
            self.show_error(f"Error exporting data: {e}")
    
    def reset(self):
        """Reset application"""
        self.frames_cropped = None
        self.frames_original = None
        self.first_frame_rgb = None
        self.dicom_path = None
        self.all_frames_loaded = False
        self.tic_data = {}
        self.roi_properties = {}  # Clear ROI properties
        self.flash_frame_idx = 0
        self.current_roi_label = "liver"
        self.roi_shapes_layer = None
        self.roi_labels_map = {}  # Clear the labels mapping
        
        # Clear viewer
        self.viewer.layers.clear()
        
        self.viewer.status = "Reset - load DICOM to begin"
    
    def show_error(self, message):
        """Show error message"""
        self.viewer.status = f"❌ {message}"
        print(f"ERROR: {message}")
    
    def show_info(self, message):
        """Show info message"""
        self.viewer.status = f"ℹ️ {message}"
        print(f"INFO: {message}")
    
    def run(self):
        """Run the application"""
        napari.run()


if __name__ == "__main__":
    # Create and run app
    app = CEUSAnalyzer()
    
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║       CEUS Analyzer with Napari - LIGHT THEME 🌟             ║
    ╠═══════════════════════════════════════════════════════════════╣
    ║                                                               ║
    ║  OPTIMIZED WORKFLOW FOR CEUS:                                 ║
    ║                                                               ║
    ║  1. 📂 Load DICOM                                             ║
    ║     • Select DICOM file directly                              ║
    ║     • Choose crop preset: LOGIC, Aixplorer, or No Crop        ║
    ║     • LOGIC: Right half, -10% top/bottom (dynamic)            ║
    ║                                                               ║
    ║  2. ⚡ Set Flash Frame                                        ║
    ║     • Navigate frames with slider                             ║
    ║     • Press Shift+F to mark flash frame (injection)           ║
    ║                                                               ║
    ║  3. ✂️ Temporal Crop (Flash + 30s)                            ║
    ║     • Crops video to: Flash frame + 30s (default)             ║
    ║     • Includes baseline frames before flash                   ║
    ║     • Adjustable duration (5-120s)                            ║
    ║     • 🔀 Motion correction applied AUTOMATICALLY              ║
    ║                                                               ║
    ║  4. ✏️ Draw ROIs (Multi-ROI Support)                          ║
    ║     • Select ROI label: liver, dia, cw                        ║
    ║     • Rectangle tool AUTO-SELECTED                            ║
    ║     • Draw up to 3 ROIs (one per label)                       ║
    ║     • All ROIs stay visible                                   ║
    ║                                                               ║
    ║  5. 📊 Compute TIC (All ROIs)                                 ║
    ║     • Calculates TIC for all visible ROIs                     ║
    ║     • Single plot: mean ± std for each ROI                    ║
    ║     • Displays ROI properties summary                         ║
    ║                                                               ║
    ║  6. 💾 Export TIC to CSV                                      ║
    ║     • Time-series data (mean, min, max, std)                  ║
    ║     • ROI properties (area, dimensions, intensities)          ║
    ║     • Motion shift logs (if motion correction applied)        ║
    ║                                                               ║
    ║  WHY THIS WORKFLOW?                                           ║
    ║  ✓ Temporal crop BEFORE motion correction                    ║
    ║    → Faster computation (30s vs 2+ min)                       ║
    ║    → Better alignment (less anatomical variation)             ║
    ║    → Focus on clinically relevant phase                       ║
    ║  ✓ Baseline frames preserved for normalization                ║
    ║  ✓ Motion correction on reduced dataset                       ║
    ║                                                               ║
    ║  FEATURES:                                                    ║
    ║  ✓ Multi-ROI analysis (liver, dia, cw)                       ║
    ║  ✓ Temporal + motion correction workflow                     ║
    ║  ✓ YCbCr → RGB automatic conversion                          ║
    ║  ✓ Dynamic LOGIC crop preset                                 ║
    ║  ✓ Keyboard shortcuts (f=flash, Space=play)                  ║
    ║  ✓ Clean light theme                                         ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    app.run()
