"""Audio cleanup for enrollment samples and output polish for live audio.

Clean enrollment audio is the single biggest factor in how good the cloned
voice sounds, so samples are denoised, trimmed and level-normalised.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, istft, sosfilt, sosfilt_zi, stft

from .dsp import rms_db


# ---------------------------------------------------------------- offline
def spectral_denoise(x: np.ndarray, sr: int, alpha: float = 1.6, floor: float = 0.12) -> np.ndarray:
    """Stationary spectral subtraction; noise profile = quietest 15% of frames."""
    if len(x) < sr // 2:
        return x
    nper = 2048
    f, t, Z = stft(x, fs=sr, nperseg=nper, noverlap=nper * 3 // 4)
    mag = np.abs(Z)
    energy = mag.sum(axis=0)
    quiet = energy <= np.percentile(energy, 15)
    noise = np.median(mag[:, quiet], axis=1, keepdims=True) if quiet.any() else mag.min(axis=1, keepdims=True)
    gain = np.clip(1.0 - alpha * noise / np.maximum(mag, 1e-9), floor, 1.0)
    # smooth gain over time/frequency to avoid musical noise
    k = np.ones(3) / 3
    gain = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, gain)
    gain = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 0, gain)
    _, y = istft(Z * gain, fs=sr, nperseg=nper, noverlap=nper * 3 // 4)
    return y[: len(x)].astype(np.float32)


def trim_silence(x: np.ndarray, sr: int, thresh_db: float = -45.0, pad_ms: int = 150) -> np.ndarray:
    blk = int(sr * 0.02)
    n = len(x) // blk
    if n == 0:
        return x
    lv = np.array([rms_db(x[i * blk:(i + 1) * blk]) for i in range(n)])
    voiced = np.where(lv > max(thresh_db, lv.max() - 45))[0]
    if len(voiced) == 0:
        return x
    pad = int(sr * pad_ms / 1000)
    return x[max(0, voiced[0] * blk - pad): min(len(x), (voiced[-1] + 1) * blk + pad)]


def normalize_peak(x: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    pk = float(np.abs(x).max())
    return x if pk < 1e-6 else (x * (10 ** (target_db / 20) / pk)).astype(np.float32)


def prepare_sample(x: np.ndarray, sr: int, denoise: bool = True) -> np.ndarray:
    x = x - float(np.mean(x))                                  # DC offset
    x = sosfilt(butter(4, 70, "highpass", fs=sr, output="sos"), x).astype(np.float32)
    if denoise:
        x = spectral_denoise(x, sr)
    x = trim_silence(x, sr)
    return normalize_peak(x)


# ---------------------------------------------------------------- streaming
def _high_shelf(sr: int, f0: float, gain_db: float, q: float = 0.707) -> np.ndarray:
    """RBJ high-shelf biquad as an SOS row."""
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w), np.sin(w)
    al = sw / (2 * q)
    sq = 2 * np.sqrt(A) * al
    b0 = A * ((A + 1) + (A - 1) * cw + sq)
    b1 = -2 * A * ((A - 1) + (A + 1) * cw)
    b2 = A * ((A + 1) + (A - 1) * cw - sq)
    a0 = (A + 1) - (A - 1) * cw + sq
    a1 = 2 * ((A - 1) - (A + 1) * cw)
    a2 = (A + 1) - (A - 1) * cw - sq
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def soft_limit(x: np.ndarray, knee: float = 0.8, ceil: float = 0.97) -> np.ndarray:
    a = np.abs(x)
    over = a > knee
    if not over.any():
        return x
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (ceil - knee) * np.tanh((a[over] - knee) / (ceil - knee)))
    return y


class Polish:
    """Stateful output chain: high-pass (rumble) -> gentle presence shelf -> soft limiter."""

    def __init__(self, sr: int, shelf_db: float = 2.0):
        sections = [butter(2, 80, "highpass", fs=sr, output="sos")]
        if shelf_db:
            sections.append(_high_shelf(sr, 4500, shelf_db))
        self.sos = np.concatenate(sections)
        self.zi = sosfilt_zi(self.sos)[:, :] * 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        y, self.zi = sosfilt(self.sos, x.astype(np.float64), zi=self.zi)
        return soft_limit(y.astype(np.float32))
