"""
Lightweight LOESS (local polynomial regression) for 1D data, tuned to mimic R's
loess defaults as closely as possible without extra dependencies:
- Degree 2 (quadratic local fit)
- Tri-cube weights
- Span in (0,1] as fraction of samples (like R's span)
- Neighborhood size uses floor(span * n) and excludes the evaluation point when
  determining the k-th neighbor distance (reduces boundary bias, avoids dk=0),
  which better matches R's behavior than a naive ceil(...)/include-self scheme.

Used for TIC golden overlay and optional metrics smoothing when statsmodels.lowess
is not a good match (it implements locally weighted linear regression only).
"""
from __future__ import annotations
import numpy as np
from typing import Tuple


def _tricube(u: np.ndarray) -> np.ndarray:
    a = 1.0 - np.clip(np.abs(u), 0.0, 1.0) ** 3
    return a ** 3

def loess_smooth(x: np.ndarray, y: np.ndarray, *, span: float = 0.3, degree: int = 2) -> np.ndarray:
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    n = x.size
    if n == 0:
        return y
    if n == 1 or span <= 0:
        return y.copy()

    # tri + suppression des duplicatas (comme R qui regroupe les x égaux)
    order = np.argsort(x)
    x_sorted = x[order]
    y_sorted = y[order]
    x_sorted, uniq_idx = np.unique(x_sorted, return_index=True)
    y_sorted = y_sorted[uniq_idx]
    n = x_sorted.size

    # taille du voisinage
    p_min = 2 if degree >= 2 else 1
    k = int(np.floor(max(0.0, min(1.0, span)) * n))
    k = max(p_min + 1, k)
    k = min(max(k, 2), max(n - 1, 1))

    y_fit_sorted = np.empty_like(y_sorted)

    for i in range(n):
        xi = x_sorted[i]
        d = np.abs(x_sorted - xi)

        d_nonzero = d[d > 0]
        if d_nonzero.size == 0:
            dk = 1.0
        else:
            kk = min(k, d_nonzero.size)
            dk = np.partition(d_nonzero, kk - 1)[kk - 1]
            if dk <= 0:
                dk = float(np.max(d_nonzero)) if np.max(d_nonzero) > 0 else 1.0

        u = d / dk
        w = _tricube(u)
        mask = w > 0
        xs = x_sorted[mask]
        ys = y_sorted[mask]
        ws = w[mask]

        # centrage + normalisation locale par dk
        z = (xs - xi) / dk

        X = np.ones((z.size, 1))
        X = np.hstack([X, z.reshape(-1, 1)])
        if degree >= 2:
            X = np.hstack([X, (z ** 2).reshape(-1, 1)])

        W = np.diag(ws)
        try:
            XtW = X.T @ W
            beta = np.linalg.lstsq(XtW @ X, XtW @ ys, rcond=None)[0]
            y_fit_sorted[i] = beta[0]  # valeur en z=0
        except Exception:
            y_fit_sorted[i] = np.average(ys, weights=ws)

    # réinjecter dans l’ordre d’origine (en tenant compte des uniques)
    y_fit_full = np.interp(x, x_sorted, y_fit_sorted)
    return y_fit_full

# def _tricube(u: np.ndarray) -> np.ndarray:
#     a = 1.0 - np.clip(np.abs(u), 0.0, 1.0) ** 3
#     return a ** 3


# def loess_smooth(x: np.ndarray, y: np.ndarray, *, span: float = 0.3, degree: int = 2) -> np.ndarray:
#     """
#     Smooth y(x) using LOESS with tri-cube weights and local polynomial regression.

#     Args:
#         x: 1D array of x values (time)
#         y: 1D array of y values (dVI)
#         span: fraction of points used in local neighborhood (0< span <=1)
#         degree: polynomial degree (1 or 2). Default 2 to mimic R loess.

#     Returns:
#         y_smooth: 1D array of smoothed values at the same x positions, preserving input order.
#     """
#     x = np.asarray(x, dtype=float).reshape(-1)
#     y = np.asarray(y, dtype=float).reshape(-1)
#     n = x.size
#     if n == 0:
#         return y
#     if n == 1 or span <= 0:
#         return y.copy()

#     # Sort by x for neighborhood queries; remember original order
#     order = np.argsort(x)
#     x_sorted = x[order]
#     y_sorted = y[order]

#     # Neighborhood size: floor(span * n) like R's loess, with a minimum of p+1
#     # and at most n-1 (so we can exclude the evaluation point for dk estimate).
#     p_min = 2 if degree >= 2 else 1
#     k = int(np.floor(max(0.0, min(1.0, span)) * n))
#     k = max(p_min + 1, k)  # ensure at least p+1 neighbors
#     k = min(max(k, 2), max(n - 1, 1))  # cap at n-1 for dk computation

#     y_fit_sorted = np.empty_like(y_sorted)

#     for i in range(n):
#         xi = x_sorted[i]
#         # distances to all points
#         d = np.abs(x_sorted - xi)
#         # scale = distance to k-th nearest neighbor EXCLUDING the point itself
#         # to avoid dk=0 (duplicates at xi) and reduce boundary bias.
#         # Build array of non-zero distances for dk selection.
#         d_nonzero = d[d > 0]
#         if d_nonzero.size == 0:
#             dk = 1.0
#         else:
#             kk = min(k, d_nonzero.size)
#             # kth smallest (1-based) -> index kk-1 in partitioned array
#             dk = np.partition(d_nonzero, kk - 1)[kk - 1]
#             if dk <= 0:
#                 # Fallback: use max distance if all extremely tiny
#                 dk = float(np.max(d_nonzero)) if np.max(d_nonzero) > 0 else 1.0
#         u = d / dk
#         w = _tricube(u)
#         # Use only neighbors with non-zero weight (within dk)
#         mask = w > 0
#         xs = x_sorted[mask]
#         ys = y_sorted[mask]
#         ws = w[mask]

#         # Build weighted design matrix for degree 1 or 2 around xi
#         X = np.ones((xs.size, 1))
#         X = np.hstack([X, (xs - xi).reshape(-1, 1)])
#         if degree >= 2:
#             X = np.hstack([X, ((xs - xi) ** 2).reshape(-1, 1)])

#         # Weighted least squares: solve (X^T W X) beta = X^T W y
#         W = np.diag(ws)
#         try:
#             XtW = X.T @ W
#             beta = np.linalg.lstsq(XtW @ X, XtW @ ys, rcond=None)[0]
#             # Evaluate at xi: design vector [1, 0, 0]
#             y_fit_sorted[i] = beta[0]
#         except Exception:
#             # Fallback: weighted average
#             y_fit_sorted[i] = np.average(ys, weights=ws)

#     # Unsort back to input order
#     inv_order = np.empty_like(order)
#     inv_order[order] = np.arange(n)
#     y_fit = y_fit_sorted[inv_order]
#     return y_fit
