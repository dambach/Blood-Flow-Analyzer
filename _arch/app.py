"""Dash application for CEUS time–intensity analysis."""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate

from python_app import analysis
from python_app.analysis import ROI_LABELS
from python_app.cache import clear_cache, delete_array, load_array, save_array
from python_app.processing import (
    base64_to_ndarray,
    compute_tic_dataframe,
    crop_frames,
    frames_to_data_url,
    frame_to_color,
    load_dicom_from_bytes,
    make_preset_crop,
    ndarray_to_base64,
    time_axis_summary,
)


app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

MAX_CROP_HISTORY = 10
DEFAULT_CROP_STYLE = {
    "padding": "15px",
    "borderRadius": "6px",
    "backgroundColor": "#101820",
    "backgroundSize": "cover",
    "backgroundPosition": "center",
    "backgroundRepeat": "no-repeat",
    "color": "#f5f5f5",
}
ROI_COLOR_SEQUENCE = qualitative.Dark24
ROI_COLOR_MAP = {
    value: ROI_COLOR_SEQUENCE[idx % len(ROI_COLOR_SEQUENCE)]
    for idx, value in enumerate(ROI_LABELS.values())
}


def _color_to_rgba(color: str, alpha: float) -> str:
    if color.startswith("#") and len(color) in {7, 9}:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return f"rgba({r},{g},{b},{alpha})"
    if color.startswith("rgb"):
        components = color[color.find("(") + 1 : color.find(")")].split(",")
        try:
            r, g, b = [int(float(comp.strip())) for comp in components[:3]]
        except ValueError:
            r = g = b = 255
        return f"rgba({r},{g},{b},{alpha})"
    # Fallback to a neutral accent
    return f"rgba(255,89,94,{alpha})"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _status_card(header: str, text_id: str) -> html.Div:
    return html.Div(
        [
            html.H4(header),
            html.Div(id=text_id, className="status-text"),
    ],
    className="status-card",
    )


def _build_crop_controls() -> html.Div:
    return html.Div(
        [
            html.H3("1. Crop the DICOM frames"),
            html.P(
                "Use the preset that matches your scanner layout or switch to manual mode "
                "to draw the region containing the CEUS data."
            ),
            dcc.RadioItems(
                id="crop-mode",
                options=[
                    {"label": "Preset", "value": "preset"},
                    {"label": "Manual", "value": "manual"},
                ],
                value="preset",
                labelStyle={"display": "inline-block", "marginRight": "10px"},
            ),
            html.Div(
                [
                    dcc.Dropdown(
                        id="crop-preset",
                        options=[
                            {"label": "Full frame", "value": "full"},
                            {"label": "CEUS only (left half)", "value": "ceus-only"},
                            {"label": "B-mode only (right half)", "value": "bmode-only"},
                            {"label": "Centered", "value": "center"},
                        ],
                        value="full",
                        clearable=False,
                        style={"width": "300px"},
                    ),
                    html.Button("Apply preset", id="apply-crop-preset", n_clicks=0),
                ],
                style={"marginBottom": "10px"},
            ),
            html.Div(
                [
                    html.Button(
                        "Use drawn rectangle", id="apply-manual-crop", n_clicks=0, disabled=True
                    ),
                    html.Button(
                        "Undo manual crop",
                        id="undo-crop",
                        n_clicks=0,
                        disabled=True,
                        style={"marginLeft": "10px"},
                    ),
                    html.Span(
                        "Draw a rectangle on the frame preview below while in manual mode",
                        style={"marginLeft": "10px", "fontStyle": "italic"},
                    ),
                ],
                style={"marginBottom": "10px"},
            ),
            dcc.Loading(
                id="crop-loading",
                type="circle",
                children=dcc.Graph(
                    id="crop-figure",
                    config={
                        "modeBarButtonsToAdd": ["drawrect", "eraseshape"],
                        "modeBarButtonsToRemove": ["zoomIn2d", "zoomOut2d", "autoScale2d"],
                        "displaylogo": False,
                        "editable": True,
                    },
                ),
            ),
        ],
        className="stage-section",
        id="crop-controls",
        style=dict(DEFAULT_CROP_STYLE),
    )


def _build_flash_controls() -> html.Div:
    return html.Div(
        [
            html.H3("2. Detect the flash frame"),
            html.P(
                "The flash is highlighted as peaks in the derivative of the intensity curve. "
                "Adjust the slider if automatic detection misses the desired frame."
            ),
            dcc.Loading(id="flash-loading", type="circle", children=dcc.Graph(id="flash-figure")),
            html.Div(
                [
                    html.Button("Play clip", id="flash-toggle", n_clicks=0),
                    html.Span(
                        "Preview advances one frame per 100 ms; pause to fine-tune the slider.",
                        style={"marginLeft": "10px", "fontStyle": "italic"},
                    ),
                ],
                style={"margin": "10px 0"},
            ),
            html.Div(
                [
                    html.Img(id="flash-frame-preview", style={"maxWidth": "520px", "width": "100%"}),
                ],
                style={"marginBottom": "10px"},
            ),
            dcc.Interval(id="flash-playback-interval", interval=100, disabled=True),
            dcc.Slider(id="flash-slider", min=0, max=10, step=1, value=0),
            html.Div(id="flash-summary", style={"marginTop": "10px"}),
        ],
        className="stage-section",
    )


def _build_roi_controls() -> html.Div:
    return html.Div(
        [
            html.H3("3. Define ROIs"),
            html.P(
                "Select a region label and draw a rectangle around the anatomy of interest on the "
                "frame displayed below (first frame after the flash). Click 'Capture ROI' to store "
                "it."
            ),
            dcc.Dropdown(
                id="roi-label",
                options=[{"label": label, "value": value} for label, value in ROI_LABELS.items()],
                value="dia",
                clearable=False,
                style={"width": "250px"},
            ),
            html.Button("Capture ROI", id="capture-roi", n_clicks=0),
            html.Button("Delete ROI", id="delete-roi", n_clicks=0, style={"marginLeft": "10px"}),
            html.Button("Clear ROIs", id="clear-roi", n_clicks=0, style={"marginLeft": "10px"}),
            html.Div(id="roi-status", style={"marginTop": "10px"}),
            dcc.Loading(
                id="roi-loading",
                type="circle",
                children=dcc.Graph(
                    id="roi-graph",
                    config={
                        "modeBarButtonsToAdd": ["drawrect", "eraseshape", "select2d"],
                        "modeBarButtonsToRemove": ["zoomIn2d", "zoomOut2d", "autoScale2d"],
                        "displaylogo": False,
                        "editable": True,
                    },
                    style={"height": "520px"},
                ),
            ),
        ],
        className="stage-section",
    )


def _build_tic_controls() -> html.Div:
    return html.Div(
        [
            html.H3("4. Generate time–intensity CSV"),
            html.Button("Compute TIC", id="compute-tic", n_clicks=0),
            html.Button("Download CSV", id="download-tic", n_clicks=0, style={"marginLeft": "10px"}),
            dcc.Download(id="download-tic-target"),
            html.Div(id="tic-status", style={"marginTop": "10px"}),
            dash_table.DataTable(id="tic-preview", page_size=5),
        ],
        className="stage-section",
    )


def _build_analysis_tab() -> html.Div:
    return html.Div(
        [
            html.H2("Analysis"),
            html.P("Load a TIC CSV (or reuse the one generated above) and compute BFI metrics."),
            dcc.Upload(
                id="tic-upload",
                children=html.Div(["Drag and drop or ", html.A("select a TIC CSV")]),
                style={
                    "width": "100%",
                    "height": "60px",
                    "lineHeight": "60px",
                    "borderWidth": "1px",
                    "borderStyle": "dashed",
                    "borderRadius": "5px",
                    "textAlign": "center",
                    "margin": "10px 0",
                },
                multiple=False,
            ),
            html.Div(id="analysis-status", style={"marginBottom": "20px"}),
            html.Label("Region"),
            dcc.Dropdown(
                id="analysis-roi",
                options=[{"label": label, "value": value} for label, value in ROI_LABELS.items()],
                value="dia",
                clearable=False,
                style={"width": "250px"},
            ),
            html.Label("Baseline range (seconds)"),
            dcc.RangeSlider(id="analysis-baseline", min=0, max=5, step=0.1, value=[0.0, 3.0]),
            html.Label("Analysis window (max seconds)"),
            dcc.Slider(id="analysis-window", min=0, max=10, step=0.5, value=10),
            dcc.Graph(id="analysis-bfi-figure"),
            dash_table.DataTable(id="analysis-bfi-table"),
        ]
    )


app.layout = html.Div(
    [
        html.H1("Blood Flow Analyzer – Python"),
        html.Div(
            [
                _status_card("Uploaded DICOM", "dicom-status"),
                _status_card("Crop", "crop-status"),
                _status_card("ROIs", "roi-status-summary"),
                _status_card("TIC", "tic-status-summary"),
            ],
            className="status-row",
        ),
        dcc.Store(id="dicom-store"),
        dcc.Store(id="crop-store"),
    dcc.Store(id="crop-history-store", data=[]),
        dcc.Store(id="cropped-video-store"),
        dcc.Store(id="roi-store"),
        dcc.Store(id="tic-store"),
        dcc.Store(id="analysis-data-store"),
    dcc.Store(id="flash-play-state", data=False),
        dcc.Upload(
            id="dicom-upload",
            children=html.Div(["Drag and drop a CEUS DICOM clip or ", html.A("select a file")]),
            style={
                "width": "100%",
                "height": "80px",
                "lineHeight": "80px",
                "borderWidth": "1px",
                "borderStyle": "dashed",
                "borderRadius": "5px",
                "textAlign": "center",
                "margin": "10px 0",
            },
            multiple=False,
        ),
        dcc.Tabs(
            [
                dcc.Tab(
                    label="TIC Builder",
                    children=[
                        _build_crop_controls(),
                        _build_flash_controls(),
                        _build_roi_controls(),
                        _build_tic_controls(),
                    ],
                ),
                dcc.Tab(label="Analysis", children=[_build_analysis_tab()]),
            ]
        ),
    ],
    style={"fontFamily": "Arial, sans-serif", "padding": "20px"},
)


# ---------------------------------------------------------------------------
# Utility functions used inside callbacks
# ---------------------------------------------------------------------------


def _decode_upload(contents: str) -> bytes:
    """Return the raw bytes from a Dash upload component."""

    if contents is None:
        raise ValueError("No contents to decode")
    header, data = contents.split(",", 1)
    return base64.b64decode(data)


def _build_crop_figure(frames: np.ndarray, crop_box: Optional[List[int]]) -> go.Figure:
    raw_frame = frames[0]
    if raw_frame.ndim == 3 and raw_frame.shape[2] == 3:
        frame = raw_frame
    else:
        frame = frame_to_color(raw_frame)
    fig = go.Figure(data=go.Image(z=frame))
    fig.update_layout(
        dragmode="drawrect",
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, scaleanchor="x", autorange="reversed"),
        newshape=dict(line_color="lime", fillcolor="rgba(0,255,0,0.15)", line_width=3),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    if crop_box:
        x0, y0, x1, y1 = crop_box
        fig.add_shape(
            type="rect",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            line=dict(color="lime", width=3),
            fillcolor="rgba(0,255,0,0.1)",
        )
    return fig


def _parse_drawn_rectangle(relayout_data: Dict) -> Optional[List[int]]:
    if not relayout_data:
        return None
    if "shapes" in relayout_data:
        shapes = relayout_data["shapes"]
        if not shapes:
            return None
        rect = shapes[-1]
    else:
        keys = [key for key in relayout_data if key.startswith("shapes[") and key.endswith(".x0")]
        if not keys:
            return None
        index = keys[0].split("[")[1].split("]")[0]
        rect = {
            "x0": relayout_data[f"shapes[{index}].x0"],
            "y0": relayout_data[f"shapes[{index}].y0"],
            "x1": relayout_data[f"shapes[{index}].x1"],
            "y1": relayout_data[f"shapes[{index}].y1"],
        }
    x0 = float(rect["x0"])
    y0 = float(rect["y0"])
    x1 = float(rect["x1"])
    y1 = float(rect["y1"])
    if x0 == x1 or y0 == y1:
        return None
    return [int(round(min(x0, x1))), int(round(min(y0, y1))), int(round(max(x0, x1))), int(round(max(y0, y1)))]


def _roi_summary(roi_store: Optional[Dict[str, str]]) -> str:
    if not roi_store:
        return "No ROIs captured"
    labels = [next(label for label, value in ROI_LABELS.items() if value == key) for key in roi_store]
    return "Stored ROIs: " + ", ".join(labels)


def _build_roi_figure(frame: np.ndarray, roi_store: Optional[Dict[str, str]]) -> go.Figure:
    if frame.ndim == 3 and frame.shape[2] == 3:
        color_frame = frame
    else:
        color_frame = frame_to_color(frame)
    fig = go.Figure(data=go.Image(z=color_frame))
    fig.update_layout(
        dragmode="drawrect",
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, scaleanchor="x", autorange="reversed"),
        newshape=dict(line_color="#ff595e", fillcolor="rgba(255,89,94,0.18)", line_width=3),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    if roi_store:
        for roi_key, mask_b64 in roi_store.items():
            try:
                mask = base64_to_ndarray(mask_b64)
            except Exception:
                continue
            ys, xs = np.where(mask)
            if xs.size == 0 or ys.size == 0:
                continue
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            label_text = next((label for label, value in ROI_LABELS.items() if value == roi_key), roi_key)
            color = ROI_COLOR_MAP.get(roi_key, "#ff595e")
            fig.add_shape(
                type="rect",
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                line=dict(color=color, width=3),
                fillcolor=_color_to_rgba(color, 0.18),
            )
            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=y0,
                text=label_text,
                showarrow=False,
                font=dict(color="#f8f9fa", size=12),
                bgcolor="rgba(0,0,0,0.45)",
            )
    return fig


# ---------------------------------------------------------------------------
# Callbacks – DICOM upload and cropping
# ---------------------------------------------------------------------------


@app.callback(
    Output("dicom-store", "data"),
    Output("crop-store", "data"),
    Output("crop-history-store", "data"),
    Output("dicom-status", "children"),
    Input("dicom-upload", "contents"),
    State("dicom-upload", "filename"),
)
def load_dicom(contents, filename):
    if contents is None:
        return no_update, no_update, no_update, "Waiting for upload"

    try:
        raw = _decode_upload(contents)
        video = load_dicom_from_bytes(raw)
    except Exception as error:  # pragma: no cover - defensive path
        return no_update, no_update, no_update, f"Failed to load DICOM: {error}"

    clear_cache()

    frames_uint8 = video.as_uint8()
    crop_box = [0, 0, frames_uint8.shape[2], frames_uint8.shape[1]]
    frames_id = save_array(video.frames.astype(np.float32))
    display_id = save_array(frames_uint8.astype(np.uint8))
    store = {
        "frames_id": frames_id,
        "display_id": display_id,
        "time": video.time.tolist(),
        "shape": list(video.frames.shape),
        "metadata": video.metadata,
        "filename": filename,
    }
    summary = time_axis_summary(video.time)
    status = (
        f"DICOM ready – {filename or 'file'} | frames: {summary['frames']} | "
        f"duration: {summary['duration']:.2f}s | Δt ≈ {summary['frame_interval']:.3f}s"
    )
    return store, crop_box, [], status


@app.callback(
    Output("apply-manual-crop", "disabled"),
    Input("crop-mode", "value"),
)
def toggle_manual_button(mode):
    return mode != "manual"


@app.callback(
    Output("undo-crop", "disabled"),
    Input("crop-history-store", "data"),
    Input("crop-mode", "value"),
)
def toggle_undo_button(history, mode):
    return mode != "manual" or not history


@app.callback(
    Output("crop-controls", "style"),
    Input("dicom-store", "data"),
)
def update_crop_background(dicom_store):
    style = dict(DEFAULT_CROP_STYLE)
    if not dicom_store:
        return style

    try:
        frames_display = load_array(dicom_store["display_id"])
        first_frame = frames_display[0]
        data_url = frames_to_data_url(first_frame)
        style["backgroundImage"] = (
            f"linear-gradient(rgba(16,24,32,0.55), rgba(16,24,32,0.55)), url({data_url})"
        )
    except Exception:
        style.pop("backgroundImage", None)
    return style


@app.callback(
    Output("cropped-video-store", "data"),
    Output("crop-status", "children"),
    Output("crop-figure", "figure"),
    Input("dicom-store", "data"),
    Input("crop-store", "data"),
    State("cropped-video-store", "data"),
)
def update_crop_views(dicom_store, crop_store, existing_cropped):
    if not dicom_store:
        placeholder = go.Figure()
        placeholder.update_layout(
            annotations=[
                dict(
                    text="Upload a DICOM clip to begin",
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                    font=dict(size=18, color="gray"),
                )
            ],
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return no_update, "Waiting for DICOM", placeholder

    frames_display = load_array(dicom_store["display_id"])
    frames_full = load_array(dicom_store["frames_id"])
    crop_box = crop_store or [0, 0, frames_display.shape[2], frames_display.shape[1]]

    try:
        cropped_display = crop_frames(frames_display, tuple(crop_box))
    except ValueError as exc:
        return no_update, f"Invalid crop: {exc}", _build_crop_figure(frames_full, crop_box)

    figure = _build_crop_figure(frames_full, crop_box)
    status = f"Crop {crop_box[0]}:{crop_box[2]} × {crop_box[1]}:{crop_box[3]} (w={cropped_display.shape[2]}, h={cropped_display.shape[1]})"

    cropped_full = crop_frames(frames_full, tuple(crop_box))

    if existing_cropped:
        for key in ("frames_id", "display_id"):
            identifier = existing_cropped.get(key)
            if identifier:
                delete_array(identifier)

    cropped_store = {
        "frames_id": save_array(cropped_full.astype(np.float32)),
        "display_id": save_array(cropped_display.astype(np.uint8)),
        "shape": list(cropped_full.shape),
        "time": dicom_store["time"],
    }

    return cropped_store, status, figure


@app.callback(
    Output("crop-store", "data", allow_duplicate=True),
    Output("crop-history-store", "data", allow_duplicate=True),
    Input("apply-crop-preset", "n_clicks"),
    Input("apply-manual-crop", "n_clicks"),
    Input("undo-crop", "n_clicks"),
    State("crop-mode", "value"),
    State("crop-preset", "value"),
    State("dicom-store", "data"),
    State("crop-figure", "relayoutData"),
    State("crop-store", "data"),
    State("crop-history-store", "data"),
    prevent_initial_call=True,
)
def adjust_crop(n_preset, n_manual, n_undo, mode, preset, dicom_store, relayout_data, current_crop, history):
    if not dicom_store:
        return no_update, no_update

    triggered = ctx.triggered_id
    history = history or []
    current_crop = current_crop or [0, 0, dicom_store["shape"][2], dicom_store["shape"][1]]

    frames_shape = dicom_store["shape"]
    width = frames_shape[2]
    height = frames_shape[1]

    if triggered == "apply-crop-preset":
        if preset == "full":
            new_history = (history + [current_crop])[-MAX_CROP_HISTORY:]
            return [0, 0, width, height], new_history
        try:
            new_crop = list(make_preset_crop(height, width, preset))
            new_history = (history + [current_crop])[-MAX_CROP_HISTORY:]
            return new_crop, new_history
        except ValueError as exc:
            return no_update, no_update

    if triggered == "apply-manual-crop" and mode == "manual":
        rect = _parse_drawn_rectangle(relayout_data)
        if rect:
            new_history = (history + [current_crop])[-MAX_CROP_HISTORY:]
            return rect, new_history
        return no_update, no_update

    if triggered == "undo-crop" and history:
        restored = history[-1]
        return restored, history[:-1]

    return no_update, no_update


# ---------------------------------------------------------------------------
# Flash detection
# ---------------------------------------------------------------------------


@app.callback(
    Output("flash-slider", "max"),
    Output("flash-slider", "value"),
    Output("flash-summary", "children"),
    Input("cropped-video-store", "data"),
)
def init_flash_slider(cropped_store):
    if not cropped_store:
        return 0, 0, "Upload and crop a DICOM clip to select the flash frame."

    total_frames = int(cropped_store.get("shape", [0])[0])
    total_frames = max(total_frames - 1, 0)
    summary = "Use the slider or playback controls to choose the flash frame manually."
    return total_frames, 0, summary


@app.callback(
    Output("flash-slider", "marks"),
    Input("flash-slider", "value"),
    State("cropped-video-store", "data"),
)
def update_flash_marks(current_value, cropped_store):
    if not cropped_store:
        return {}
    time = np.array(cropped_store["time"], dtype=float)
    if time.size == 0:
        return {}
    index = int(np.clip(current_value or 0, 0, len(time) - 1))
    return {index: f"t={time[index]:.2f}s"}


@app.callback(
    Output("flash-frame-preview", "src"),
    Input("flash-slider", "value"),
    State("cropped-video-store", "data"),
)
def update_flash_preview(frame_index, cropped_store):
    if not cropped_store:
        return None

    frames = load_array(cropped_store["display_id"])
    if frames.size == 0:
        return None

    index = int(np.clip(frame_index or 0, 0, frames.shape[0] - 1))
    frame = frames[index]
    return frames_to_data_url(frame)


# ---------------------------------------------------------------------------
# ROI capture and TIC generation
# ---------------------------------------------------------------------------


@app.callback(
    Output("roi-graph", "figure"),
    Input("cropped-video-store", "data"),
    Input("flash-slider", "value"),
    Input("roi-store", "data"),
)
def update_roi_graph(cropped_store, flash_frame, roi_store):
    if not cropped_store:
        placeholder = go.Figure()
        placeholder.update_layout(
            annotations=[
                dict(
                    text="Upload and crop a DICOM clip to define ROIs",
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                    font=dict(size=16, color="#777"),
                )
            ],
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        return placeholder

    frames = load_array(cropped_store["display_id"])
    frame_index = min(int(flash_frame or 0) + 1, frames.shape[0] - 1)
    frame = frames[frame_index]
    return _build_roi_figure(frame, roi_store)


@app.callback(
    Output("roi-store", "data"),
    Output("roi-status", "children"),
    Output("roi-status-summary", "children"),
    Input("capture-roi", "n_clicks"),
    Input("delete-roi", "n_clicks"),
    Input("clear-roi", "n_clicks"),
    State("roi-graph", "relayoutData"),
    State("roi-label", "value"),
    State("roi-store", "data"),
    State("cropped-video-store", "data"),
    prevent_initial_call=True,
)
def capture_roi(n_capture, n_delete, n_clear, relayout_data, label, roi_store, cropped_store):
    roi_store = roi_store or {}
    triggered = ctx.triggered_id

    if triggered == "clear-roi":
        roi_store.clear()
        return roi_store, "Cleared all ROIs", _roi_summary(roi_store)

    if triggered == "delete-roi":
        if label in roi_store:
            roi_store.pop(label, None)
            return roi_store, f"Deleted ROI {label}", _roi_summary(roi_store)
        return roi_store, f"No stored ROI for {label} to delete", _roi_summary(roi_store)

    if triggered == "capture-roi":
        if not cropped_store:
            return roi_store, "Load and crop a clip before capturing ROIs", _roi_summary(roi_store)
        rect = _parse_drawn_rectangle(relayout_data or {})
        if not rect:
            return roi_store, "Draw a rectangle before capturing", _roi_summary(roi_store)

        width = cropped_store["shape"][2]
        height = cropped_store["shape"][1]
        x0, y0, x1, y1 = rect
        x0 = max(min(x0, width), 0)
        x1 = max(min(x1, width), 0)
        y0 = max(min(y0, height), 0)
        y1 = max(min(y1, height), 0)
        if x0 >= x1 or y0 >= y1:
            return roi_store, "Rectangle has zero area", _roi_summary(roi_store)

        mask = np.zeros((int(height), int(width)), dtype=bool)
        mask[y0:y1, x0:x1] = True
        roi_store[label] = ndarray_to_base64(mask)
        status = f"Captured ROI {label} at x[{x0}:{x1}] y[{y0}:{y1}]"
        return roi_store, status, _roi_summary(roi_store)

    return roi_store, no_update, _roi_summary(roi_store)


@app.callback(
    Output("tic-store", "data"),
    Output("tic-preview", "data"),
    Output("tic-preview", "columns"),
    Output("tic-status", "children"),
    Output("tic-status-summary", "children"),
    Input("compute-tic", "n_clicks"),
    State("cropped-video-store", "data"),
    State("roi-store", "data"),
    prevent_initial_call=True,
)
def compute_tic(n_clicks, cropped_store, roi_store):
    if not cropped_store or not roi_store:
        return no_update, no_update, no_update, "Upload data and define ROIs first", no_update

    frames_id = cropped_store.get("frames_id")
    if not frames_id:
        return no_update, no_update, no_update, "No frame data available", no_update
    frames = load_array(frames_id)
    time = np.array(cropped_store["time"], dtype=float)
    roi_masks = {name: base64_to_ndarray(mask) for name, mask in roi_store.items()}

    try:
        df = compute_tic_dataframe(frames, time, roi_masks)
    except ValueError as exc:
        return no_update, no_update, no_update, f"Failed to compute TIC: {exc}", no_update

    preview = df.head(10)
    columns = [{"name": col, "id": col} for col in preview.columns]
    tic_store = df.to_json(date_format="iso", orient="split")
    status = f"Generated TIC with {len(df)} rows"
    return tic_store, preview.to_dict("records"), columns, status, status


@app.callback(
    Output("download-tic-target", "data"),
    Input("download-tic", "n_clicks"),
    State("tic-store", "data"),
    prevent_initial_call=True,
)
def download_tic(n_clicks, tic_json):
    if not tic_json:
        return no_update
    df = pd.read_json(tic_json, orient="split")
    return dcc.send_data_frame(df.to_csv, "TIC_output.csv", index=False)


# ---------------------------------------------------------------------------
# Analysis callbacks
# ---------------------------------------------------------------------------


def _load_analysis_dataframe(tic_json: Optional[str], uploaded_contents: Optional[str]) -> Optional[pd.DataFrame]:
    if ctx.triggered_id == "tic-upload" and uploaded_contents:
        buffer = io.BytesIO(_decode_upload(uploaded_contents))
        return pd.read_csv(buffer)
    if tic_json:
        return pd.read_json(tic_json, orient="split")
    return None


@app.callback(
    Output("analysis-data-store", "data"),
    Output("analysis-status", "children"),
    Input("tic-store", "data"),
    Input("tic-upload", "contents"),
    State("tic-upload", "filename"),
)
def update_analysis_store(tic_json, upload_contents, upload_filename):
    df = _load_analysis_dataframe(tic_json, upload_contents)
    if df is None:
        return None, "Upload a TIC CSV or generate one in the previous tab."
    metadata = f"Using TIC data ({len(df)} rows) from {upload_filename or 'generator'}"
    return df.to_json(date_format="iso", orient="split"), metadata


@app.callback(
    Output("analysis-baseline", "max"),
    Output("analysis-baseline", "value"),
    Output("analysis-window", "max"),
    Output("analysis-window", "value"),
    Input("analysis-data-store", "data"),
)
def configure_analysis_sliders(data_json):
    if not data_json:
        return 10, [0, 3], 10, 10
    df = pd.read_json(data_json, orient="split")
    t_min = float(df["time"].min())
    t_max = float(df["time"].max())
    return t_max, [t_min, min(t_min + (t_max - t_min) * 0.1, t_max)], t_max, t_max


@app.callback(
    Output("analysis-bfi-figure", "figure"),
    Output("analysis-bfi-table", "data"),
    Output("analysis-bfi-table", "columns"),
    Input("analysis-data-store", "data"),
    Input("analysis-roi", "value"),
    Input("analysis-baseline", "value"),
    Input("analysis-window", "value"),
)
def update_analysis_outputs(data_json, roi_value, baseline_range, window_value):
    if not data_json:
        return go.Figure(), [], []

    df = pd.read_json(data_json, orient="split")
    if roi_value not in df.columns:
        return go.Figure(), [], []

    result = analysis.compute_bfi(df, roi_value, tuple(baseline_range), float(window_value))
    if not result:
        return go.Figure(), [], []

    region_key = next(label for label, value in ROI_LABELS.items() if value == roi_value)
    filtered_col = f"{roi_value}_filt"
    filtered = df[filtered_col] if filtered_col in df.columns else df[roi_value]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["time"], y=df[roi_value], mode="markers", name="Raw"))
    fig.add_trace(go.Scatter(x=df["time"], y=filtered, mode="lines", name="Filtered", line=dict(color="red")))
    fig.add_vrect(x0=baseline_range[0], x1=baseline_range[1], fillcolor="rgba(41,110,175,0.2)", line_width=0)
    fig.add_vline(result.rise_start, line=dict(color="orange", dash="dash"))
    fig.add_vline(result.rise_end, line=dict(color="orange", dash="dash"))
    fig.add_hline(result.baseline, line=dict(color="gray", dash="dot"))
    fig.add_hline(result.peak, line=dict(color="gray", dash="dot"))
    fig.update_layout(
        title=f"BFI Analysis – {region_key}",
        xaxis_title="Time (s)",
        yaxis_title="Intensity (dB)",
        margin=dict(l=40, r=20, t=40, b=40),
    )

    table = [result.as_row()]
    columns = [{"name": key, "id": key} for key in table[0]]
    return fig, table, columns


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=True, port=port)
