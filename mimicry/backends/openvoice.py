"""Zero-shot voice conversion with OpenVoice v2 (tone color converter).

The target voice comes from the enrolled sample - no per-voice training.
NOTE: written against the OpenVoice v2 public API; it needs the OpenVoice repo
and checkpoints (scripts/install.* fetch them). Quality/latency depend on GPU.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")   # Apple GPU: let unsupported ops (stft) run on CPU
from pathlib import Path

import numpy as np

from .base import Backend, BackendError


def ensure_repo_on_path(cfg) -> None:
    repo = Path(cfg.openvoice_dir).resolve()
    if repo.exists() and str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def pick_device(pref: str) -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    if pref != "auto":
        return pref
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class OpenVoiceBackend(Backend):
    name = "openvoice"
    sample_rate = 22050

    def load(self, profile_dir, cfg):
        ckpt = Path(cfg.openvoice_ckpt).resolve()
        if not (ckpt / "converter" / "checkpoint.pth").exists():
            raise BackendError(f"OpenVoice checkpoints not found at {ckpt} (run the install script)")
        ensure_repo_on_path(cfg)
        try:
            import torch
            import openvoice.api  # noqa: F401
        except ImportError as e:
            raise BackendError(f"OpenVoice/torch not importable: {e}") from e

        self.device = pick_device(cfg.torch_device)
        self.conv = make_converter(ckpt, self.device, cfg.openvoice_watermark)
        self.tau = float(cfg.openvoice_tau)
        self.sample_rate = int(self.conv.hps.data.sampling_rate)

        se_t, se_s = profile_dir / "target_se.pt", profile_dir / "source_se.pt"
        if not (se_t.exists() and se_s.exists()):
            raise BackendError("profile has no speaker embeddings; run enroll with the OpenVoice backend")
        self.tgt_se = torch.load(se_t, map_location=self.device)
        self.src_se = torch.load(se_s, map_location=self.device)
        self._tmp = tempfile.mkdtemp(prefix="mimicry_")
        # warm-up so first live chunk isn't slow
        self.convert(np.zeros(self.sample_rate, dtype=np.float32) + 1e-4)

    def convert(self, audio):
        import soundfile as sf
        import torch
        p = os.path.join(self._tmp, "in.wav")
        sf.write(p, audio, self.sample_rate)
        with torch.inference_mode():
            out = self.conv.convert(audio_src_path=p, src_se=self.src_se, tgt_se=self.tgt_se,
                                    output_path=None, tau=self.tau)
        out = np.asarray(out, dtype=np.float32).reshape(-1)
        return out


def make_converter(ckpt: Path, device: str, watermark: bool = False):
    """Build the ToneColorConverter.

    Upstream always loads the 'wavmark' watermark model (a network download) in __init__ and rejects an
    `enable_watermark` kwarg, so when the watermark is off we swap in a stub module while constructing.
    """
    import types
    from openvoice.api import ToneColorConverter
    saved = sys.modules.get("wavmark")
    if not watermark:
        stub = types.ModuleType("wavmark")

        class _Null:
            def to(self, *a, **k):
                return self
        stub.load_model = lambda: _Null()
        sys.modules["wavmark"] = stub
    try:
        conv = ToneColorConverter(str(ckpt / "converter" / "config.json"), device=device)
    finally:
        if not watermark:
            if saved is not None:
                sys.modules["wavmark"] = saved
            else:
                sys.modules.pop("wavmark", None)
    conv.load_ckpt(str(ckpt / "converter" / "checkpoint.pth"))
    if not watermark:
        conv.watermark_model = None          # add_watermark() then returns audio unchanged
    return conv


def split_for_embedding(x: np.ndarray, sr: int, seg_s: float = 10.0, min_s: float = 2.0):
    """Cut a cleaned sample into ~10 s pieces for speaker-embedding extraction (no Whisper needed)."""
    n = int(sr * seg_s)
    segs = [x[i:i + n] for i in range(0, len(x), n)]
    segs = [g for g in segs if len(g) >= sr * min_s]
    return segs or [x]


def extract_embeddings(cfg, profile_dir: Path, source_wav: Path, target_wav: Path) -> None:
    """Called by `enroll`: computes and caches speaker embeddings (averaged over 10 s segments)."""
    import soundfile as sf
    ckpt = Path(cfg.openvoice_ckpt).resolve()
    ensure_repo_on_path(cfg)
    import torch
    conv = make_converter(ckpt, pick_device(cfg.torch_device), watermark=False)
    for wav, out in ((target_wav, "target_se.pt"), (source_wav, "source_se.pt")):
        x, sr = sf.read(str(wav), dtype="float32")
        with tempfile.TemporaryDirectory(prefix="mimicry_se_") as d:
            paths = []
            for k, seg in enumerate(split_for_embedding(x, sr)):
                p = os.path.join(d, f"seg{k}.wav")
                sf.write(p, seg, sr)
                paths.append(p)
            se = conv.extract_se(paths)
        torch.save(se.detach().cpu(), profile_dir / out)
