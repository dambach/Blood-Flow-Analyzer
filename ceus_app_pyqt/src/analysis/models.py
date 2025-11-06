"""
Model functions and multistart fitting for CEUS TICs.
Reimplements models inspired by R app (lognormal, gamma variate, LDRW, FPT).
"""
from __future__ import annotations
import numpy as np
from typing import Dict, Optional, Tuple

try:
    from scipy.optimize import curve_fit
except Exception:  # SciPy optional
    curve_fit = None  # type: ignore

EPS = 1e-9


def lognormal_func(t, AUC, u, s, t0, C):
    tt = np.clip(np.asarray(t, float) - t0, EPS, None)
    pdf = (1.0 / (np.sqrt(2*np.pi) * s * tt)) * np.exp(-0.5 * ((np.log(tt) - u) / s)**2)
    y = AUC * pdf + C
    return np.where(np.asarray(t) <= t0, C, y)


def gamma_variate_func(t, AUC, a, b, t0, C):
    tt = np.clip(np.asarray(t, float) - t0, EPS, None)
    # Normalized gamma-like shape
    pdf = (tt**a) * np.exp(-tt/b) / (b**(a+1) * np.math.gamma(a+1))
    y = AUC * pdf + C
    return np.where(np.asarray(t) <= t0, C, y)


def ldrw_func(t, AUC, u, lam, t0, C):
    tt = np.clip(np.asarray(t, float) - t0, EPS, None)
    coeff = np.exp(lam)/u * np.sqrt(u*lam/(2*np.pi*tt))
    y = AUC * coeff * np.exp(-0.5*lam*((u/tt) + (tt/u))) + C
    return np.where(np.asarray(t) <= t0, C, y)


def fpt_func(t, AUC, u, lam, t0, C):
    tt = np.clip(np.asarray(t, float) - t0, EPS, None)
    coeff = np.exp(lam)/u * np.sqrt(lam/(2*np.pi)) * (u/tt)**1.5
    y = AUC * coeff * np.exp(-0.5*lam*((u/tt) + (tt/u))) + C
    return np.where(np.asarray(t) <= t0, C, y)


MODEL_FUNCS = {
    "lognormal": lognormal_func,
    "gamma": gamma_variate_func,
    "ldrw": ldrw_func,
    "fpt": fpt_func,
}


def _initial_guesses(model: str, t: np.ndarray, y: np.ndarray, t0_hint: float, C_hint: float):
    AUC0 = max(float(np.trapz(np.clip(y - C_hint, 0, None), t)), EPS)
    if model == "lognormal":
        u0 = max(np.log(max(float(np.median(t - t0_hint)), EPS)), 0.0)
        s0 = 0.5
        return [AUC0, u0, s0, t0_hint, C_hint]
    if model == "gamma":
        a0, b0 = 2.0, max(float(np.std(t - t0_hint)), 0.5)
        return [AUC0, a0, b0, t0_hint, C_hint]
    if model in ("ldrw", "fpt"):
        u0 = max(float(np.median(t - t0_hint)), 0.5)
        lam0 = 2.0
        return [AUC0, u0, lam0, t0_hint, C_hint]
    return [AUC0, 1.0, 0.5, t0_hint, C_hint]


def _bounds(model: str, t: np.ndarray, y: np.ndarray):
    tmax = float(np.max(t)) if t.size else 1.0
    Cmax = max(float(np.max(y)) if y.size else 1.0, 1.0)
    if model == "lognormal":
        lower = [0.0, 0.0, 1e-2, 0.0, 0.0]
        upper = [np.inf, 10.0, 2.0, tmax, Cmax]
    elif model == "gamma":
        lower = [0.0, 1e-3, 1e-3, 0.0, 0.0]
        upper = [np.inf, 20.0, 20.0, tmax, Cmax]
    else:  # ldrw/fpt
        lower = [0.0, 1e-3, 1e-3, 0.0, 0.0]
        upper = [np.inf, 100.0, 20.0, tmax, Cmax]
    return (lower, upper)


def fit_model(model: str, t: np.ndarray, y: np.ndarray, *, t0_hint: Optional[float] = None, C_hint: Optional[float] = None, n_starts: int = 50, random_state: Optional[int] = None):
    rng = np.random.default_rng(random_state)
    func = MODEL_FUNCS[model]
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    if t0_hint is None:
        t0_hint = float(t[0]) if t.size else 0.0
    if C_hint is None:
        C_hint = float(np.percentile(y, 10)) if y.size else 0.0
    p0 = np.array(_initial_guesses(model, t, y, t0_hint, C_hint), float)
    lb, ub = _bounds(model, t, y)

    best = {"params": p0, "rss": np.inf, "y_fit": func(t, *p0)}
    starts = [p0]
    for _ in range(max(1, n_starts - 1)):
        jitter = p0 * rng.uniform(0.5, 1.5, size=p0.shape)
        # Keep t0 and C within bounds
        jitter[-2] = np.clip(jitter[-2], lb[-2], ub[-2])
        jitter[-1] = np.clip(jitter[-1], lb[-1], ub[-1])
        starts.append(jitter)

    for guess in starts:
        try:
            if curve_fit is not None:
                popt, _ = curve_fit(func, t, y, p0=guess, bounds=(lb, ub), maxfev=20000)
                yhat = func(t, *popt)
            else:
                popt = guess
                yhat = func(t, *popt)
            rss = float(np.sum((y - yhat) ** 2))
            if rss < best["rss"]:
                best = {"params": popt, "rss": rss, "y_fit": yhat}
        except Exception:
            continue
    return best


def fit_models(t: np.ndarray, y: np.ndarray, *, models=("lognormal", "gamma", "ldrw", "fpt"), t0_hint: Optional[float] = None, C_hint: Optional[float] = None, n_starts: int = 50, random_state: Optional[int] = None) -> Dict[str, Optional[dict]]:
    out: Dict[str, Optional[dict]] = {}
    for m in models:
        try:
            out[m] = fit_model(m, t, y, t0_hint=t0_hint, C_hint=C_hint, n_starts=n_starts, random_state=random_state)
        except Exception:
            out[m] = None
    return out
