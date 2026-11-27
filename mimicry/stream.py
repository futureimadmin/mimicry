"""StreamConverter: chunked conversion with context + crossfade (no audio I/O).

Pure and testable. Output is delayed by `xfade_ms` relative to input; total
latency ~= hop + xfade + processing time.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .backends import BackendManager
from .dsp import fix_length, resample, rms_db


class StreamConverter:
    def __init__(self, sr: int, manager: BackendManager, hop_ms=320, ctx_ms=480,
                 xfade_ms=40, gate_db=-50.0):
        self.sr, self.mgr = sr, manager
        self.ms = lambda v: int(sr * v / 1000)
        self.set_hop(hop_ms)
        self.ctx_n, self.xf = self.ms(ctx_ms), self.ms(xfade_ms)
        assert self.ctx_n >= self.xf
        self.gate_db = gate_db
        self.buf = np.zeros(0, np.float32)
        self.hist = np.zeros(self.ctx_n, np.float32)
        self.tail: Optional[np.ndarray] = None
        self.rtf = 0.0            # EMA of processing_time / hop_time
        self.last_proc_s = 0.0
        self.voiced_hops = 0
        self.total_hops = 0

    def set_hop(self, hop_ms: int) -> None:
        self.hop_ms = int(hop_ms)
        self.hop_n = int(self.sr * hop_ms / 1000)

    def process(self, x: np.ndarray) -> np.ndarray:
        self.buf = np.concatenate([self.buf, np.asarray(x, np.float32)])
        outs = []
        while len(self.buf) >= self.hop_n:
            new, self.buf = self.buf[: self.hop_n], self.buf[self.hop_n:]
            outs.append(self._hop(new))
        return np.concatenate(outs) if outs else np.zeros(0, np.float32)

    def _hop(self, new: np.ndarray) -> np.ndarray:
        n, xf = self.hop_n, self.xf
        window = np.concatenate([self.hist, new])
        self.hist = window[-self.ctx_n:]
        self.total_hops += 1

        if rms_db(new) < self.gate_db:                       # silence: skip the model
            out = np.zeros(n, np.float32)
            if self.tail is not None:                        # flush held tail
                out[:xf] = self.tail
                self.tail = None
            return out

        self.voiced_hops += 1
        t0 = time.perf_counter()
        be = self.mgr.active
        w = resample(window, self.sr, be.sample_rate)
        conv = self.mgr.convert(w, be.sample_rate)
        conv = resample(conv, be.sample_rate, self.sr)
        conv = fix_length(conv, len(window))
        self.last_proc_s = time.perf_counter() - t0
        inst = self.last_proc_s / (n / self.sr)
        self.rtf = inst if self.rtf == 0 else 0.7 * self.rtf + 0.3 * inst

        seg = conv[-(n):]                                    # time [T, T+hop)
        seg = np.concatenate([conv[len(conv) - n - xf: len(conv) - n], seg])  # prepend xf overlap
        out = np.empty(n, np.float32)
        head = seg[:xf]
        if self.tail is None:
            out[:xf] = head
        else:
            w_in = np.linspace(0.0, 1.0, xf, dtype=np.float32)
            out[:xf] = self.tail * (1 - w_in) + head * w_in
        out[xf:] = seg[xf:n]
        self.tail = seg[n:n + xf].copy()
        return out
