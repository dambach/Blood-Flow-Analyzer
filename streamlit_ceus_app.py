import streamlit as st
import numpy as np
import pandas as pd
import pydicom
from pathlib import Path
from PIL import Image, ImageDraw
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import time
import subprocess
import tempfile
import uuid
import shutil


def _prepare_frames_for_video(frames: np.ndarray, flip_vertical: bool = True) -> np.ndarray:
    """Convert frames to RGB uint8 suitable for ffmpeg export."""
    if frames is None:
        raise ValueError("No frames available for export.")

    arr = np.asarray(frames)
    if arr.ndim == 2:
        arr = arr[np.newaxis, :, :]
    if arr.ndim == 3:
        arr = arr[..., np.newaxis]
    if arr.ndim != 4:
        raise ValueError(f"Unexpected frame shape {arr.shape}")

    if flip_vertical:
        arr = np.flip(arr, axis=1)

    arr = np.nan_to_num(arr, nan=0.0)

    if arr.dtype != np.uint8:
        if arr.dtype.kind in {"f", "d"}:
            arr_min = float(arr.min())
            arr_max = float(arr.max())
            if arr_max > 1.0 or arr_min < 0.0:
                arr = arr - arr_min
                arr = arr / (arr_max - arr_min + 1e-8)
            arr = np.clip(arr, 0.0, 1.0)
            arr = (arr * 255.0).astype(np.uint8)
        else:
            arr = np.clip(arr, 0, 255).astype(np.uint8)

    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] > 3:
        arr = arr[..., :3]

    return np.ascontiguousarray(arr)


def _write_video_with_ffmpeg(frames_rgb: np.ndarray, fps: float, output_path: Path) -> None:
    """Pipe RGB frames into ffmpeg and encode an MP4."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg introuvable sur le système.")

    if frames_rgb.size == 0:
        raise ValueError("Aucune frame à encoder.")

    height, width = frames_rgb.shape[1:3]
    safe_fps = fps if fps and fps > 0 else 30.0

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{safe_fps:.6f}",
        "-i",
        "-",
        "-an",
        "-vcodec",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for frame in frames_rgb:
            if process.stdin:
                process.stdin.write(frame.tobytes())
        if process.stdin:
            process.stdin.close()
    except (BrokenPipeError, IOError) as e:
        # ffmpeg may have terminated early
        process.kill()
        process.wait()
        raise RuntimeError(f"Erreur d'écriture vers ffmpeg: {e}")
    except Exception as e:
        process.kill()
        process.wait()
        raise

    stdout, stderr = process.communicate()
    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Échec de ffmpeg."
        raise RuntimeError(error_msg)


def generate_mp4_from_frames(frames: np.ndarray, fps: float, flip_vertical: bool = True) -> Path:
    """Prepare frames then encode them into an MP4 file."""
    frames_rgb = _prepare_frames_for_video(frames, flip_vertical=flip_vertical)
    output_path = Path(tempfile.gettempdir()) / f"ceus_{uuid.uuid4().hex}.mp4"
    _write_video_with_ffmpeg(frames_rgb, fps, output_path)
    return output_path

st.set_page_config(layout="wide", page_title="DICOM CEUS Analyzer")
st.title("DICOM CEUS Analyzer")

# ============================================================================
# 1. INITIALIZATION
# ============================================================================
if "frames_raw" not in st.session_state:
    st.session_state.frames_raw = None
    st.session_state.frames_cropped = None
    st.session_state.first_frame = None  # Only first frame loaded initially
    st.session_state.crop_bounds = None
    st.session_state.crop_preset = "No Crop"  # Crop preset selection
    st.session_state.flash_frame_idx = None
    st.session_state.roi_bounds = None
    st.session_state.tic_data = None
    st.session_state.crop_shape = None
    st.session_state.roi_shape = None
    st.session_state.pending_crop = None
    st.session_state.pending_roi = None
    st.session_state.fps = 30  # Default FPS, can be updated from DICOM metadata
    st.session_state.generated_video_path = None
    st.session_state.generated_video_filename = None
    st.session_state.dicom_path = None  # Store DICOM path for later loading
    st.session_state.all_frames_loaded = False  # Track if all frames are loaded

# Crop presets
CROP_PRESETS = {
    "No Crop": None,
    "Aixplorer": {"x0": 75, "x1": 425, "y0": 125, "y1": 425}
}

# ============================================================================
# 2. SIDEBAR: Load DICOM
# ============================================================================
with st.sidebar:
    st.header("📂 Step 1: Load DICOM")
    
    # Crop preset selection
    crop_preset = st.selectbox(
        "Crop Preset",
        options=list(CROP_PRESETS.keys()),
        index=0,
        key="crop_preset_select"
    )
    st.session_state.crop_preset = crop_preset
    
    if crop_preset != "No Crop":
        preset_coords = CROP_PRESETS[crop_preset]
        st.info(f"📐 {crop_preset}: x=[{preset_coords['x0']}:{preset_coords['x1']}], y=[{preset_coords['y0']}:{preset_coords['y1']}]")
    
    dicom_path = st.text_input("DICOM file path", value="data/dicom_file")
    
    if st.button("Load First Frame", use_container_width=True, key="load_first_frame_btn"):
        try:
            # Handle directory or file
            p = Path(dicom_path)
            if p.is_dir():
                files = sorted([f for f in p.glob("*") if f.is_file()])
                if not files:
                    st.error("No files in directory")
                    st.stop()
                dicom_file = str(files[0])
                st.info(f"Loading: {files[0].name}")
            else:
                dicom_file = dicom_path
            
            # Read DICOM
            ds = pydicom.dcmread(dicom_file, force=True)
            
            # Get FPS from DICOM metadata if available
            fps = 30  # Default
            if hasattr(ds, 'CineRate'):
                fps = float(ds.CineRate)
            elif hasattr(ds, 'FrameTime'):
                fps = 1000.0 / float(ds.FrameTime)  # FrameTime is in ms
            elif hasattr(ds, 'RecommendedDisplayFrameRate'):
                fps = float(ds.RecommendedDisplayFrameRate)
            st.session_state.fps = fps
            
            # Load only first frame
            pixel_array = ds.pixel_array.astype(float)
            if pixel_array.ndim == 4:
                first_frame = pixel_array[0]
            elif pixel_array.ndim == 3 and pixel_array.shape[0] < 100:
                first_frame = pixel_array[0]
            else:
                first_frame = pixel_array
            
            # Normalize to 0-1
            first_frame = (first_frame - np.min(first_frame)) / (np.max(first_frame) - np.min(first_frame) + 1e-8)
            
            st.session_state.first_frame = first_frame
            st.session_state.dicom_path = dicom_file
            st.session_state.frames_raw = None
            st.session_state.frames_cropped = None
            st.session_state.all_frames_loaded = False
            st.session_state.crop_bounds = None
            st.session_state.roi_bounds = None
            st.session_state.tic_data = None
            st.session_state.pending_crop = None
            st.session_state.pending_roi = None
            st.session_state.generated_video_path = None
            
            # Apply preset crop automatically if selected
            if crop_preset != "No Crop":
                preset_coords = CROP_PRESETS[crop_preset]
                x0, x1 = preset_coords['x0'], preset_coords['x1']
                y0, y1 = preset_coords['y0'], preset_coords['y1']
                st.session_state.pending_crop = (x0, y0, x1, y1)
                st.success(f"✅ First frame loaded! Preset {crop_preset} auto-selected")
            else:
                st.success(f"✅ First frame loaded! Shape: {first_frame.shape}")
        except Exception as e:
            st.error(f"Error: {e}")

if st.session_state.first_frame is None and st.session_state.frames_raw is None:
    st.info("👈 Load first frame to begin")
    st.stop()

# Determine which frames to display
if st.session_state.frames_cropped is not None:
    frames = st.session_state.frames_cropped
    display_mode = "all_frames"
elif st.session_state.first_frame is not None:
    frames = st.session_state.first_frame[np.newaxis, ...]  # Add frame dimension
    display_mode = "first_frame_only"
else:
    st.info("👈 Load first frame to begin")
    st.stop()

# ============================================================================
# MAIN LAYOUT
# ============================================================================
col1, col2 = st.columns([2.5, 1.5])

# ============================================================================
# LEFT COLUMN: Image Display with Interactive Drawing
# ============================================================================
with col1:
    st.subheader("📺 Image Display")
    
    # Show status
    if display_mode == "first_frame_only":
        st.warning("⚠️ First frame only - Apply crop to load all frames")
    elif display_mode == "all_frames":
        st.success("✅ All frames loaded")
    
    # Video player option - only if all frames loaded
    if display_mode == "all_frames":
        col_video, col_frame = st.columns([1, 3])
        with col_video:
            if st.button("🎬 Générer Vidéo", help="Créer une vidéo MP4 pour lecture fluide"):
                with st.spinner("Génération de la vidéo..."):
                    try:
                        video_path = generate_mp4_from_frames(frames, st.session_state.fps, flip_vertical=True)
                        st.session_state.video_path = str(video_path)
                        st.success("✅ Vidéo prête !")
                    except Exception as e:
                        st.error(f"Erreur: {e}")
        
        # Show video if generated
        if 'video_path' in st.session_state and st.session_state.video_path:
            if Path(st.session_state.video_path).exists():
                st.video(st.session_state.video_path)
                st.info("💡 Utilisez les contrôles vidéo pour lire à vitesse réelle. Le slider ci-dessous permet de sélectionner une frame précise.")
        
        # Frame selector for precise selection
        with col_frame:
            if 'current_frame' not in st.session_state:
                st.session_state.current_frame = 0
            frame_idx = st.slider("Sélectionner une frame précise", 0, frames.shape[0]-1, st.session_state.current_frame, key="frame_slider")
            st.session_state.current_frame = frame_idx
    else:
        # First frame only
        frame_idx = 0
        st.info("👉 Apply crop to load all frames and access video controls")
    
    # Calculate time in seconds (only if all frames loaded)
    if display_mode == "all_frames":
        time_sec = frame_idx / st.session_state.fps
        st.caption(f"⏱️ Temps: {time_sec:.2f}s | Frame {frame_idx+1}/{frames.shape[0]}")
    else:
        st.caption(f"📸 First frame for crop selection")
    
    # Get current frame
    frame = frames[frame_idx]
    h, w = frame.shape[:2]
    
    # Normalize frame for display - ENSURE 2D (grayscale)
    if frame.ndim == 3 and frame.shape[2] >= 3:
        # Color image - convert to grayscale
        display_frame = 0.299 * frame[:, :, 0] + 0.587 * frame[:, :, 1] + 0.114 * frame[:, :, 2]
    elif frame.ndim == 3:
        # 3D but only 1 channel - flatten to 2D
        display_frame = frame[:, :, 0]
    else:
        # Already 2D
        display_frame = frame
    
    # Flip image vertically to correct orientation
    display_frame = np.flipud(display_frame)
    
    # Choose colormap: Gray for first frame only, Hot after all frames loaded
    if display_mode == "first_frame_only":
        colormap = 'Gray'
    else:
        colormap = 'Hot'
    
    # Create Plotly figure with image as heatmap (better display)
    fig = go.Figure()
    
    # Add image as heatmap with correct axes
    fig.add_trace(go.Heatmap(
        z=display_frame,
        x=np.arange(w),  # X axis from 0 to width
        y=np.arange(h),  # Y axis from 0 to height
        colorscale=colormap,
        showscale=False,
        hovertemplate='X: %{x}<br>Y: %{y}<br>Intensity: %{z:.3f}<extra></extra>'
    ))
    
    # Draw crop rectangle if exists AND we're working on raw frames (not cropped yet)
    # Only show yellow rectangle BEFORE crop is applied
    if st.session_state.crop_bounds is not None and frames is st.session_state.frames_raw:
        x0, y0, x1, y1 = st.session_state.crop_bounds
        # Flip Y coordinates because display is flipped
        y0_flip = h - y1
        y1_flip = h - y0
        fig.add_shape(
            type="rect",
            x0=x0, y0=y0_flip, x1=x1, y1=y1_flip,
            line=dict(color="yellow", width=4),
            name="Crop (applied)"
        )
    
    # Draw ROI rectangle if exists (adjust Y for flipped image)
    if st.session_state.roi_bounds is not None:
        x0, y0, x1, y1 = st.session_state.roi_bounds
        # Flip Y coordinates because display is flipped
        y0_flip = h - y1
        y1_flip = h - y0
        fig.add_shape(
            type="rect",
            x0=x0, y0=y0_flip, x1=x1, y1=y1_flip,
            line=dict(color="cyan", width=4),
            name="ROI"
        )
    
    fig.update_layout(
        title=f"Frame {frame_idx+1}/{frames.shape[0]} - Draw rectangle with box select tool (□)",
        height=600,
        width=None,  # Auto width
        xaxis=dict(
            title="",  # No label
            range=[0, w],
            scaleanchor="y",
            scaleratio=1,
            constrain="domain",
            showticklabels=False  # Hide tick labels
        ),
        yaxis=dict(
            title="",  # No label
            range=[0, h],
            constrain="domain",
            showticklabels=False  # Hide tick labels
        ),
        hovermode='closest',
        dragmode="select",  # Use box select instead of drawrect
        margin=dict(l=0, r=0, t=40, b=0)  # Reduce margins
    )
    
    # Capture selection data
    selected = st.plotly_chart(fig, use_container_width=True, key="frame_plot", on_select="rerun", selection_mode="box")
    
    # Frame info
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Frame", f"{frame_idx+1}/{frames.shape[0]}")
    with col_b:
        st.metric("Height", h)
    with col_c:
        st.metric("Width", w)

# ============================================================================
# RIGHT COLUMN: Controls
# ============================================================================
with col2:
    st.subheader("⚙️ Controls")
    
    # Instructions for drawing
    st.info("💡 Use the Box Select tool (□) in the plot toolbar, drag to select a region")
    
    # Display selected coordinates if available
    if selected and hasattr(selected, 'selection') and selected.selection and 'box' in selected.selection:
        box_list = selected.selection['box']
        if box_list and len(box_list) > 0:
            box = box_list[0]
            if 'x' in box and 'y' in box:
                x_range = box['x']
                y_range = box['y']
                x0, x1 = int(min(x_range)), int(max(x_range))
                y0_plot, y1_plot = int(min(y_range)), int(max(y_range))
                
                # Flip Y coordinates back because display was flipped
                y0 = h - y1_plot
                y1 = h - y0_plot
                
                st.session_state.pending_crop = (x0, y0, x1, y1)
                st.success(f"📦 Selection captured: ({x0}, {y0}) to ({x1}, {y1})")
    
    # --- STEP 1: Crop ---
    st.markdown("### 📐 Step 1: Crop")
    st.caption("Draw a yellow rectangle on the image, then click Apply")
    
    # Manual coordinate input for crop
    with st.expander("Manual Crop Coordinates"):
        col_x, col_y = st.columns(2)
        with col_x:
            crop_x0 = st.number_input("X0", value=0, key="crop_x0", min_value=0, max_value=w)
            crop_x1 = st.number_input("X1", value=w, key="crop_x1", min_value=0, max_value=w)
        with col_y:
            crop_y0 = st.number_input("Y0", value=0, key="crop_y0", min_value=0, max_value=h)
            crop_y1 = st.number_input("Y1", value=h, key="crop_y1", min_value=0, max_value=h)
        
        if st.button("Apply Manual Crop", key="manual_crop_btn"):
            if crop_x0 < crop_x1 and crop_y0 < crop_y1:
                st.session_state.pending_crop = (crop_x0, crop_y0, crop_x1, crop_y1)
    
    if st.button("✂️ Apply Crop", use_container_width=True, key="apply_crop_btn"):
        if st.session_state.pending_crop is not None:
            x0, y0, x1, y1 = st.session_state.pending_crop
            
            # Load all frames from DICOM
            with st.spinner("Loading all frames from DICOM..."):
                try:
                    ds = pydicom.dcmread(st.session_state.dicom_path, force=True)
                    frames_all = ds.pixel_array.astype(float)
                    
                    # Normalize to 0-1
                    frames_all = (frames_all - np.min(frames_all)) / (np.max(frames_all) - np.min(frames_all) + 1e-8)
                    
                    # Crop all frames
                    if frames_all.ndim == 2:
                        cropped = frames_all[y0:y1, x0:x1]
                        cropped = cropped[np.newaxis, :, :]
                    elif frames_all.ndim == 3:
                        cropped = frames_all[:, y0:y1, x0:x1]
                    elif frames_all.ndim == 4:
                        cropped = frames_all[:, y0:y1, x0:x1, :]
                    
                    st.session_state.frames_raw = frames_all
                    st.session_state.frames_cropped = cropped
                    st.session_state.crop_bounds = None  # Clear crop bounds after applying
                    st.session_state.crop_shape = cropped.shape
                    st.session_state.roi_bounds = None
                    st.session_state.tic_data = None
                    st.session_state.pending_crop = None
                    st.session_state.all_frames_loaded = True
                    st.session_state.generated_video_path = None
                    st.session_state.generated_video_filename = None
                    st.success(f"✅ Loaded {cropped.shape[0]} frames and cropped to {cropped.shape}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error loading frames: {e}")
        else:
            st.warning("⚠️ Draw a rectangle first or use manual coordinates")
    
    if st.button("🔄 Reset Crop", use_container_width=True, key="reset_crop_btn"):
        # Reset to first frame only
        st.session_state.frames_cropped = None
        st.session_state.frames_raw = None
        st.session_state.crop_bounds = None
        st.session_state.roi_bounds = None
        st.session_state.tic_data = None
        st.session_state.crop_shape = None
        st.session_state.pending_crop = None
        st.session_state.all_frames_loaded = False
        st.session_state.generated_video_path = None
        st.session_state.generated_video_filename = None
        st.info("Reset to first frame - click 'Load First Frame' to reload")
        st.rerun()
    
    if st.session_state.crop_bounds is not None:
        x0, y0, x1, y1 = st.session_state.crop_bounds
        st.success(f"✅ Crop applied: ({x0}, {y0}) to ({x1}, {y1})")
        st.success(f"Shape: {st.session_state.crop_shape}")
    
    st.divider()
    
    # --- STEP 2: Flash Frame Selection ---
    st.markdown("### ⚡ Step 2: Flash Frame")
    
    # Only show if all frames loaded
    if display_mode == "all_frames":
        st.caption("Select the flash frame index")
        
        flash_idx = st.slider(
            "Flash frame index",
            0,
            frames.shape[0] - 1,
            0,
            key="flash_slider"
        )
        st.session_state.flash_frame_idx = flash_idx
        st.info(f"Flash frame: {flash_idx + 1}")
    else:
        st.warning("⚠️ Apply crop first to load all frames")
    
    st.divider()
    
    # --- STEP 3: ROI ---
    st.markdown("### 🎯 Step 3: ROI & TIC")
    
    # Only show if all frames loaded
    if display_mode == "all_frames":
        st.caption("Draw a red ROI rectangle, then compute")
        
        # Manual coordinate input for ROI
        with st.expander("Manual ROI Coordinates"):
            col_x, col_y = st.columns(2)
            with col_x:
                roi_x0 = st.number_input("ROI X0", value=0, key="roi_x0", min_value=0, max_value=w)
                roi_x1 = st.number_input("ROI X1", value=w, key="roi_x1", min_value=0, max_value=w)
            with col_y:
                roi_y0 = st.number_input("ROI Y0", value=0, key="roi_y0", min_value=0, max_value=h)
                roi_y1 = st.number_input("ROI Y1", value=h, key="roi_y1", min_value=0, max_value=h)
            
            if st.button("Apply Manual ROI", key="manual_roi_btn"):
                if roi_x0 < roi_x1 and roi_y0 < roi_y1:
                    st.session_state.pending_roi = (roi_x0, roi_y0, roi_x1, roi_y1)
        
        if st.button("📊 Compute TIC", use_container_width=True, key="compute_tic_btn"):
            if st.session_state.pending_roi is not None:
                x0, y0, x1, y1 = st.session_state.pending_roi
                frames_work = st.session_state.frames_cropped
                tic = []
                
                for i in range(frames_work.shape[0]):
                    frame = frames_work[i]
                    
                    # Extract ROI - ensure 2D
                    if frame.ndim == 3 and frame.shape[2] >= 3:
                        roi_frame = frame[y0:y1, x0:x1, 0]
                    elif frame.ndim == 3:
                        roi_frame = frame[y0:y1, x0:x1, 0]
                    else:
                        roi_frame = frame[y0:y1, x0:x1]
                    
                    mean_intensity = np.mean(roi_frame)
                    tic.append(mean_intensity)
                
                st.session_state.tic_data = np.array(tic)
                st.session_state.roi_bounds = (x0, y0, x1, y1)
                st.session_state.roi_shape = (y1 - y0, x1 - x0)
                st.session_state.pending_roi = None
                st.session_state.generated_video_path = None
                st.session_state.generated_video_filename = None
                st.success("✅ TIC computed!")
                st.rerun()
            else:
                st.warning("⚠️ Draw a rectangle first or use manual coordinates")
        
        if st.button("❌ Clear ROI", use_container_width=True, key="clear_roi_btn"):
            st.session_state.roi_bounds = None
            st.session_state.tic_data = None
            st.session_state.pending_roi = None
            st.session_state.generated_video_path = None
            st.session_state.generated_video_filename = None
            st.rerun()
        
        if st.session_state.roi_bounds is not None:
            x0, y0, x1, y1 = st.session_state.roi_bounds
            st.success(f"✅ ROI applied: ({x0}, {y0}) to ({x1}, {y1})")
            st.success(f"Size: {st.session_state.roi_shape[0]}x{st.session_state.roi_shape[1]}")
    else:
        st.warning("⚠️ Apply crop first to load all frames")

    st.divider()

    # --- STEP 4: Export MP4 ---
    st.markdown("### 🎬 Step 4: Export Video")
    st.caption("Génère un MP4 depuis les frames DICOM avec les couleurs originales.")

    export_source = st.radio(
        "Frames à utiliser",
        options=[
            "Vue actuelle (crop)",
            "Clip complet (brut)",
        ],
        index=0,
        key="video_export_source",
    )

    flip_for_export = st.checkbox(
        "Retourner verticalement (comme l'affichage)",
        value=True,
        key="video_export_flip",
    )

    if st.button("🎞️ Générer le MP4", use_container_width=True, key="generate_mp4_btn"):
        try:
            source_frames = (
                st.session_state.frames_cropped
                if export_source == "Vue actuelle (crop)"
                else st.session_state.frames_raw
            )
            if source_frames is None:
                st.warning("📭 Aucune frame disponible pour l'export.")
            else:
                existing_path = st.session_state.get("generated_video_path")
                if existing_path:
                    existing_file = Path(existing_path)
                    if existing_file.exists():
                        try:
                            existing_file.unlink()
                        except OSError:
                            pass

                video_path = generate_mp4_from_frames(
                    source_frames,
                    st.session_state.fps,
                    flip_vertical=flip_for_export,
                )
                st.session_state.generated_video_path = str(video_path)
                st.session_state.generated_video_filename = (
                    f"CEUS_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                )
                st.success("🎉 MP4 généré !")
        except Exception as e:
            st.error(f"⚠️ Impossible de créer le MP4 : {e}")

    video_path = st.session_state.get("generated_video_path")
    if video_path and Path(video_path).exists():
        st.video(video_path)
        with open(video_path, "rb") as video_file:
            st.download_button(
                label="⬇️ Télécharger le MP4",
                data=video_file.read(),
                file_name=(
                    st.session_state.generated_video_filename
                    or Path(video_path).name
                ),
                mime="video/mp4",
                use_container_width=True,
            )

# ============================================================================
# DISPLAY TIC RESULTS
# ============================================================================
if st.session_state.tic_data is not None:
    st.divider()
    st.subheader("📈 Time-Intensity Curve (TIC)")
    
    tic = st.session_state.tic_data
    
    # Plot TIC
    col_plot, col_info = st.columns([2, 1])
    
    with col_plot:
        fig_tic = go.Figure()
        fig_tic.add_trace(go.Scatter(
            y=tic,
            mode='lines+markers',
            name='Intensity',
            line=dict(color='blue', width=2),
            marker=dict(size=4)
        ))
        fig_tic.update_layout(
            title="Time-Intensity Curve",
            xaxis_title="Frame",
            yaxis_title="Mean Intensity",
            height=400,
            hovermode='x unified'
        )
        st.plotly_chart(fig_tic, use_container_width=True)
    
    with col_info:
        st.metric("Max Intensity", f"{np.max(tic):.4f}")
        st.metric("Min Intensity", f"{np.min(tic):.4f}")
        st.metric("Mean Intensity", f"{np.mean(tic):.4f}")
        st.metric("ROI Size", f"{st.session_state.roi_shape[0]}x{st.session_state.roi_shape[1]}" if st.session_state.roi_shape else "N/A")
    
    # TIC table
    df_tic = pd.DataFrame({
        "Frame": np.arange(1, len(tic) + 1),
        "Intensity": tic
    })
    
    st.dataframe(df_tic, use_container_width=True, height=300)
    
    # Download button
    csv = df_tic.to_csv(index=False)
    st.download_button(
        label="⬇️ Download TIC CSV",
        data=csv,
        file_name=f"TIC_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True
    )
