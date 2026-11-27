"""Backend registry and the failover manager."""
from __future__ import annotations

import threading
from typing import Callable, List, Optional

import numpy as np

from .base import Backend, BackendError, MuteBackend, PassthroughBackend


def make(name: str) -> Backend:
    if name == "openvoice":
        from .openvoice import OpenVoiceBackend
        return OpenVoiceBackend()
    if name == "pitch":
        from .pitch import PitchBackend
        return PitchBackend()
    if name == "passthrough":
        return PassthroughBackend()
    if name == "mute":
        return MuteBackend()
    raise ValueError(f"unknown backend {name}")


class BackendManager:
    """Holds an ordered chain of backends; demotes on error, can promote later."""

    def __init__(self, names: List[str], profile_dir, cfg, fail_mode="mute",
                 on_event: Optional[Callable[[str, dict], None]] = None):
        self.names, self.profile_dir, self.cfg = list(names), profile_dir, cfg
        self.fail_mode = fail_mode
        self.on_event = on_event or (lambda *_: None)
        self.lock = threading.Lock()
        self.chain: List[Backend] = []
        self.idx = 0
        self.errors = 0
        for n in self.names:
            b = make(n)
            try:
                b.load(profile_dir, cfg)
                self.chain.append(b)
                self.on_event("backend_loaded", {"name": n, "sr": b.sample_rate})
            except BackendError as e:
                self.on_event("backend_unavailable", {"name": n, "reason": str(e)})
        self.chain.append(MuteBackend() if fail_mode == "mute" else PassthroughBackend())

    @property
    def active(self) -> Backend:
        return self.chain[self.idx]

    @property
    def degraded(self) -> bool:
        return self.idx > 0

    def demote(self, reason: str) -> bool:
        with self.lock:
            if self.idx >= len(self.chain) - 1:
                return False
            old = self.chain[self.idx].name
            self.idx += 1
            self.on_event("demote", {"from": old, "to": self.chain[self.idx].name, "reason": reason})
            return True

    def promote(self) -> bool:
        with self.lock:
            if self.idx == 0:
                return False
            self.idx -= 1
            self.on_event("promote", {"to": self.chain[self.idx].name})
            return True

    def convert(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """audio at `sr` must already equal backend.sample_rate; engine handles resampling."""
        try:
            return self.active.convert(audio)
        except Exception as e:  # noqa: BLE001 - any backend crash must not kill the call
            self.errors += 1
            self.demote(f"exception: {e!r}")
            return np.zeros_like(audio)
