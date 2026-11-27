"""Run audio through the exact live pipeline, offline (used by `convert` and the UI's Try-it)."""
from __future__ import annotations

import numpy as np

from .audio_clean import Polish
from .stream import StreamConverter


def convert_array(cfg, mgr, x: np.ndarray, sr: int):
    """x mono float32 at sr. Returns (converted same length, rtf)."""
    sc = StreamConverter(sr, mgr, cfg.hop_ms, cfg.ctx_ms, cfg.xfade_ms, cfg.gate_db)
    pol = Polish(sr, cfg.polish_shelf_db) if cfg.polish else None
    pad = np.zeros(int(sr * 0.8), np.float32)                  # flush the last hop
    xin = np.concatenate([x, pad])
    outs = []
    for i in range(0, len(xin), 960):
        y = sc.process(xin[i:i + 960])
        outs.append(pol.process(y) if pol is not None else y)
    y = np.concatenate(outs)
    y = y[sc.xf: sc.xf + len(x)]                                # remove crossfade delay
    return y, sc.rtf
