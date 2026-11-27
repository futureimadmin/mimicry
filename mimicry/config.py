"""Configuration (JSON file + defaults)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class Config:
    profile: str = "default"
    profiles_dir: str = "profiles"
    logs_dir: str = "logs"

    # Audio routing. None = auto-detect.
    input_device: Optional[str] = None      # your real microphone
    output_device: Optional[str] = None     # virtual mic (BlackHole / VB-Cable)
    monitor: bool = False                   # also play converted voice on your own speakers/headphones
    monitor_device: Optional[str] = None
    sample_rate: int = 48000

    # Streaming
    hop_ms: int = 320
    ctx_ms: int = 480
    xfade_ms: int = 40
    gate_db: float = -50.0
    prebuffer_ms: int = 120
    polish: bool = True                     # output HPF + presence shelf + soft limiter
    polish_shelf_db: float = 2.0

    # Backends tried in order; supervisor demotes on trouble.
    backends: List[str] = field(default_factory=lambda: ["openvoice", "pitch"])
    # What happens if every backend fails: "mute" never leaks your real voice.
    fail_mode: str = "mute"
    torch_device: str = "auto"              # auto | cuda | mps | cpu

    # Supervisor
    max_hop_ms: int = 800
    rtf_high: float = 0.80
    rtf_low: float = 0.35

    openvoice_dir: str = "third_party/OpenVoice"
    openvoice_ckpt: str = "third_party/OpenVoice/checkpoints_v2"
    openvoice_tau: float = 0.3              # lower = closer to your own prosody, higher = more target-like timbre
    openvoice_watermark: bool = False       # OpenVoice invisible watermark; off for lower live latency

    @classmethod
    def load(cls, path: Optional[str]) -> "Config":
        cfg = cls()
        if path and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def profile_path(self) -> Path:
        return Path(self.profiles_dir) / self.profile
