"""Lightweight fallback: shifts pitch toward the target's average pitch.

Not a true voice clone (timbre is only approximated) but runs on any CPU,
so the supervisor can fall back to it when the neural backend is too slow.
"""
from __future__ import annotations

import json
from collections import deque
from math import log2

import numpy as np

from ..dsp import estimate_f0
from .base import Backend, BackendError


class PitchBackend(Backend):
    name = "pitch"
    sample_rate = 22050

    def __init__(self):
        self.target_f0 = None
        self.recent = deque(maxlen=40)   # running source F0 estimates (self-calibrating)
        self._ps = None
        self._cur = 0.0

    def load(self, profile_dir, cfg):
        try:
            from pedalboard import PitchShift
        except ImportError as e:
            raise BackendError("pedalboard not installed (pip install pedalboard)") from e
        self._PitchShift = PitchShift
        meta = json.loads((profile_dir / "meta.json").read_text())
        self.target_f0 = meta.get("target_f0")
        if not self.target_f0:
            raise BackendError("profile has no target F0; re-run enroll")
        self._ps = PitchShift(semitones=0.0)

    def convert(self, audio):
        f0 = estimate_f0(audio, self.sample_rate)
        if f0:
            self.recent.append(f0)
        if not self.recent:
            return audio
        src = float(np.median(self.recent))
        st = float(np.clip(12 * log2(self.target_f0 / src), -12, 12))
        self._cur = 0.8 * self._cur + 0.2 * st if self._cur else st   # smooth
        self._ps.semitones = self._cur
        out = self._ps(audio.astype(np.float32), self.sample_rate, reset=True)
        return np.asarray(out, dtype=np.float32).reshape(-1)[: len(audio)]
