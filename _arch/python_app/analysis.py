"""Core analysis routines for Blood Flow Index and indicator-dilution modelling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
from scipy.special import gamma as gamma_func


ROI_LABELS = {
    "Chest Wall": "cw",
    "Diaphragm": "dia",
    "Liver": "liver",
}


@dataclass
class BFIResult:
    region: str
    baseline: float
    peak: float
    intensity_range: float
    rise_start: float
    rise_end: float
    rise_time: float
    t_zero: float
    bfi: float

    def as_row(self) -> Dict[str, float]:
        return {
            "Region": self.region,
            "BFI (dB/s)": round(self.bfi, 3),
            "Intensity Range (dB)": round(self.intensity_range, 3),
            "Baseline (dB)": round(self.baseline, 3),
            "Peak Intensity (dB)": round(self.peak, 3),
            "Rise time (s)": round(self.rise_time, 3),
            "t0 (s)": round(self.t_zero, 3),
            "Rise Time Start (s)": round(self.rise_start, 3),
            "Rise Time End (s)": round(self.rise_end, 3),
        }


def _linear_regression(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def compute_bfi(
    df: pd.DataFrame,
    roi: str,
    baseline_range: Tuple[float, float],
    analysis_max: float,
) -> Optional[BFIResult]:
    """Mirror the R BFI calculation for a single ROI."""

    if roi not in df.columns:
        return None

    roi_label = next(key for key, value in ROI_LABELS.items() if value == roi)
    baseline_df = df.loc[(df["time"] >= baseline_range[0]) & (df["time"] <= baseline_range[1])]
    if baseline_df.empty:
        return None

    baseline = float(baseline_df[roi].mean())
    analysis_df = df.loc[df["time"] <= analysis_max]
    if analysis_df.empty:
        return None

    peak = float(analysis_df[roi].max())
    peak_time = float(analysis_df.loc[analysis_df[roi].idxmax(), "time"])
    intensity_range = peak - baseline

    ten_percent = baseline + 0.1 * intensity_range
    ninety_percent = baseline + 0.9 * intensity_range

    start_candidates = analysis_df.loc[analysis_df[roi] >= ten_percent, "time"]
    end_candidates = analysis_df.loc[analysis_df[roi] >= ninety_percent, "time"]
    if start_candidates.empty or end_candidates.empty:
        return None

    rise_start = float(start_candidates.iloc[0])
    rise_end = float(end_candidates.iloc[0])
    rise_time = rise_end - rise_start
    if rise_time <= 0:
        return None

    bfi = intensity_range / rise_time

    regression_df = df.loc[(df["time"] >= rise_start) & (df["time"] <= rise_end)]
    slope, intercept = _linear_regression(regression_df["time"].to_numpy(), regression_df[roi].to_numpy())
    t_zero = (baseline - intercept) / slope if slope else np.nan

    return BFIResult(
        region=roi_label,
        baseline=baseline,
        peak=peak,
        intensity_range=intensity_range,
        rise_start=rise_start,
        rise_end=rise_end,
        rise_time=rise_time,
        t_zero=float(t_zero),
        bfi=float(bfi),
    )


def _safe_curve_fit(func, x, y, bounds, attempts=25):
    best = None
    best_error = np.inf
    lower, upper = bounds
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    for _ in range(attempts):
        p0 = np.random.uniform(lower, upper)
        try:
            params, _ = curve_fit(func, x, y, p0=p0, bounds=bounds, maxfev=20000)
        except Exception:
            continue
        residuals = y - func(x, *params)
        error = float(np.sum(residuals**2))
        if error < best_error:
            best_error = error
            best = params
    return best


def model_lognormal(t, AUC, u, s, t0, C):
    dt = np.maximum(t - t0, 1e-6)
    return np.where(
        t <= t0,
        C,
        AUC / (np.sqrt(2 * np.pi) * s * dt) * np.exp(-((np.log(dt) - u) ** 2) / (2 * s**2)) + C,
    )


def model_gamma_variate(t, AUC, a, b, t0, C):
    dt = np.maximum(t - t0, 1e-6)
    numerator = (dt**a) * np.exp(-dt / b)
    denom = b ** (a + 1) * gamma_func(a + 1)
    return np.where(t <= t0, C, AUC / denom * numerator + C)


def model_ldrw(t, AUC, u, lamb, t0, C):
    dt = np.maximum(t - t0, 1e-6)
    pref = np.sqrt(u * lamb / (dt * 2 * np.pi))
    exponent = -0.5 * lamb * ((u / dt) + (dt / u))
    return np.where(t <= t0, C, AUC * np.exp(lamb) / u * pref * np.exp(exponent) + C)


def model_fpt(t, AUC, u, lamb, t0, C):
    dt = np.maximum(t - t0, 1e-6)
    pref = np.sqrt(lamb / (2 * np.pi)) * (u / dt) ** 1.5
    exponent = -0.5 * lamb * ((u / dt) + (dt / u))
    return np.where(t <= t0, C, AUC * np.exp(lamb) / u * pref * np.exp(exponent) + C)


def fit_models(df: pd.DataFrame, roi: str, baseline: float, t_zero: float) -> Optional[pd.DataFrame]:
    if roi not in df.columns:
        return None

    time = df["time"].to_numpy()
    signal = df[roi].to_numpy()

    log_bounds = ([0, -3, 0.1, 0, 0], [10, 5, 2, max(t_zero * 2, 0.1), baseline * 4 or 100])
    gamma_bounds = ([0, 0.1, 0.1, 0, 0], [10, 10, 10, max(t_zero * 2, 0.1), baseline * 4 or 100])
    ldrw_bounds = ([0, 0.1, 0.1, 0, 0], [10, 20, 10, max(t_zero * 2, 0.1), baseline * 4 or 100])
    fpt_bounds = ([0, 0.1, 0.1, 0, 0], [10, 20, 10, max(t_zero * 2, 0.1), baseline * 4 or 100])

    fits = {
        "Lognormal": (model_lognormal, log_bounds),
        "Gamma Variate": (model_gamma_variate, gamma_bounds),
        "LDRW": (model_ldrw, ldrw_bounds),
        "FPT": (model_fpt, fpt_bounds),
    }

    rows: List[Dict[str, float]] = []
    for name, (model, bounds) in fits.items():
        params = _safe_curve_fit(model, time, signal, bounds)
        if params is None:
            continue
        pred = model(time, *params)
        residuals = signal - pred
        dof = max(len(signal) - len(params), 1)
        rse = np.sqrt(np.sum(residuals**2) / dof)

        if name == "Lognormal":
            AUC, u, s, fitted_t0, baseline_param = params
            mtt = np.exp(u + s**2 / 2)
            tp = np.exp(u - s**2)
        elif name == "Gamma Variate":
            AUC, alpha, beta, fitted_t0, baseline_param = params
            mtt = beta * (alpha + 1)
            tp = alpha * beta
        else:
            AUC, u, lamb, fitted_t0, baseline_param = params
            mtt = u
            if name == "LDRW":
                tp = (u / (2 * lamb)) * (np.sqrt(1 + 4 * lamb**2) - 1)
            else:
                tp = (u / (2 * lamb)) * (np.sqrt(9 + 4 * lamb**2) - 3)

        rows.append(
            {
                "Model": name,
                "RSE": rse,
                "t0": fitted_t0,
                "AUC": AUC,
                "MTT": mtt,
                "Tp": tp,
                "Baseline": baseline_param,
                "1/AUC": 1 / AUC if AUC else np.nan,
                "MTT/AUC": mtt / AUC if AUC else np.nan,
                "Peak time (t0 + Tp)": fitted_t0 + tp if np.isfinite(tp) else np.nan,
            }
        )

    if not rows:
        return None

    return pd.DataFrame(rows)


def smooth_trace(y: np.ndarray) -> np.ndarray:
    if y.size < 5:
        return y
    window = min(len(y) // 2 * 2 + 1, 9)
    return savgol_filter(y, window_length=window, polyorder=2)

