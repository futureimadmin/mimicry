"""Voice profiles: enrollment of the target sample, quality checks, consent record."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import List, Optional

import numpy as np

from .audio_clean import prepare_sample
from .dsp import clip_ratio, estimate_f0, resample, rms_db, to_mono

CONSENT_TEXT = (
    "I confirm that the target voice is my own, or that the person it belongs to has given me "
    "explicit permission to use it, and that I will not use this tool to deceive, defraud or "
    "impersonate anyone without their knowledge."
)


def load_wav(path: str, sr: Optional[int] = None) -> tuple[np.ndarray, int]:
    import soundfile as sf
    x, file_sr = sf.read(path, dtype="float32", always_2d=False)
    x = to_mono(x)
    if sr and sr != file_sr:
        x, file_sr = resample(x, file_sr, sr), sr
    return x, file_sr


def quality_report(x: np.ndarray, sr: int) -> tuple[List[str], dict]:
    """Return (warnings, metrics) for a voice sample."""
    warns = []
    dur = len(x) / sr
    frames = x[: len(x) // 400 * 400].reshape(-1, 400)
    lv = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    noise, speech = float(np.percentile(lv, 10)), float(np.percentile(lv, 90))
    snr = speech - noise
    if dur < 10:
        warns.append(f"sample is only {dur:.1f}s; 20-60s of clean speech gives a much better clone")
    if clip_ratio(x) > 0.001:
        warns.append("sample is clipped (too loud); re-record with lower input gain")
    if snr < 20:
        warns.append(f"estimated SNR {snr:.0f} dB is low; record somewhere quieter")
    return warns, {"duration_s": round(dur, 1), "snr_db": round(snr, 1), "peak": float(np.abs(x).max())}


def ask_consent(assume_yes: bool = False) -> bool:
    print("\n" + CONSENT_TEXT)
    if assume_yes:
        return True
    return input("Type 'I agree' to continue: ").strip().lower() == "i agree"


def enroll(cfg, target_wav: str, source_wav: Optional[str], name: str, assume_consent=False,
           log=print) -> Path:
    if not ask_consent(assume_consent):
        raise SystemExit("Consent not given; profile not created.")
    pdir = Path(cfg.profiles_dir) / name
    pdir.mkdir(parents=True, exist_ok=True)

    import soundfile as sf
    tgt, sr = load_wav(target_wav)
    warns, metrics = quality_report(tgt, sr)
    for w in warns:
        log(f"  warning: {w}")
    sf.write(pdir / "target_raw.wav", tgt, sr)
    tgt_c = prepare_sample(tgt, sr)                       # denoise + trim + normalise
    _, after = quality_report(tgt_c, sr)
    metrics["snr_after_db"] = after["snr_db"]
    metrics["duration_clean_s"] = after["duration_s"]
    log(f"  cleaned target: SNR {metrics['snr_db']} -> {after['snr_db']} dB, {after['duration_s']}s of speech")
    sf.write(pdir / "target.wav", resample(tgt_c, sr, 22050), 22050)
    f0 = estimate_f0(resample(tgt_c, sr, 22050), 22050)

    if source_wav:
        src, ssr = load_wav(source_wav)
        src_c = prepare_sample(src, ssr)
        sf.write(pdir / "source.wav", resample(src_c, ssr, 22050), 22050)

    meta = {"name": name, "target_f0": f0, "metrics": metrics, "warnings": warns,
            "consent": {"text": CONSENT_TEXT, "at": dt.datetime.now(dt.timezone.utc).isoformat()},
            "target_file": Path(target_wav).name}
    (pdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if source_wav:
        try:
            from .backends.openvoice import extract_embeddings
            extract_embeddings(cfg, pdir, pdir / "source.wav", pdir / "target.wav")
            log("  OpenVoice speaker embeddings created")
        except Exception as e:  # noqa: BLE001
            log(f"  OpenVoice embeddings skipped ({e!r}); only the 'pitch' backend will be usable")
    else:
        log("  no --source given: OpenVoice backend needs a recording of YOUR voice (see `record`)")
    log(f"Profile '{name}' saved to {pdir}  (target F0 ~ {f0 and round(f0)} Hz)")
    return pdir


def require_profile(cfg) -> Path:
    pdir = cfg.profile_path()
    meta = pdir / "meta.json"
    if not meta.exists():
        raise SystemExit(f"No profile '{cfg.profile}'. Run: mimicry enroll --target sample.wav --source me.wav")
    if not json.loads(meta.read_text()).get("consent"):
        raise SystemExit("Profile has no consent record; re-run enroll.")
    return pdir
