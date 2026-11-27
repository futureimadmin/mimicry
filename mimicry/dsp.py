"""Small DSP helpers (numpy/scipy only)."""
from __future__ import annotations

from math import gcd
from typing import Optional

import numpy as np
from scipy.signal import resample_poly


def to_mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x if x.ndim == 1 else x.mean(axis=1)


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return np.asarray(x, dtype=np.float32)
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def fix_length(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) == n:
        return x
    if len(x) > n:
        return x[:n]
    return np.pad(x, (0, n - len(x)))


def rms_db(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * np.log10(max(r, 1e-6))


def estimate_f0(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0) -> Optional[float]:
    """Median F0 over voiced frames using autocorrelation. None if unvoiced."""
    frame = int(0.04 * sr)
    hop = int(0.02 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    if len(x) < frame + hi:
        return None
    vals = []
    for s in range(0, len(x) - frame - hi, hop):
        seg = x[s:s + frame + hi].astype(np.float64)
        w = seg[:frame]
        if np.sqrt(np.mean(w ** 2)) < 0.01:
            continue
        w = w - w.mean()
        ac = np.array([np.dot(w, seg[l:l + frame] - seg[l:l + frame].mean()) for l in range(lo, hi)])
        e = np.dot(w, w)
        if e <= 0:
            continue
        peak = ac.max()
        if peak / e <= 0.45:
            continue
        # smallest lag whose autocorrelation is near the max: avoids octave-down errors
        k = int(np.argmax(ac >= 0.9 * peak))
        while k + 1 < len(ac) and ac[k + 1] > ac[k]:   # climb to the local peak
            k += 1
        vals.append(sr / (lo + k))
    return float(np.median(vals)) if len(vals) >= 3 else None


def clip_ratio(x: np.ndarray) -> float:
    return float(np.mean(np.abs(x) > 0.99)) if len(x) else 0.0
