"""Backend interface: convert one mono float32 window to the target voice."""
from __future__ import annotations

import numpy as np


class BackendError(RuntimeError):
    pass


class Backend:
    name = "base"
    sample_rate = 16000

    def load(self, profile_dir, cfg) -> None:  # noqa: D401
        """Load models / profile data. Raise BackendError if unavailable."""

    def convert(self, audio: np.ndarray) -> np.ndarray:
        """audio: mono float32 at self.sample_rate. Return same length."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class MuteBackend(Backend):
    """Last resort: emit silence so the real voice is never leaked."""
    name = "mute"

    def convert(self, audio):
        return np.zeros_like(audio)


class PassthroughBackend(Backend):
    """Testing only - this does NOT change the voice."""
    name = "passthrough"

    def convert(self, audio):
        return audio
