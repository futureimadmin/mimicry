import numpy as np
import pytest

from mimicry.backends import BackendManager
from mimicry.backends.base import Backend
from mimicry.dsp import estimate_f0, resample
from mimicry.ring import Ring
from mimicry.stream import StreamConverter

SR = 48000


class Cfg:  # minimal stand-in
    pass


def tone(f, secs, amp=0.3, sr=SR):
    t = np.arange(int(secs * sr)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def mgr(names, fail_mode="mute", events=None):
    return BackendManager(names, None, Cfg(), fail_mode, (lambda k, d: events.append((k, d))) if events is not None else None)


def run(sc, x, blk=960):
    return np.concatenate([sc.process(x[i:i + blk]) for i in range(0, len(x), blk)])


def test_identity_stream_is_delayed_copy():
    sc = StreamConverter(SR, mgr(["passthrough"]), hop_ms=320, ctx_ms=480, xfade_ms=40)
    x = tone(220, 3.0)
    y = run(sc, x)
    d = sc.xf
    n = len(y)
    assert n == (len(x) // sc.hop_n) * sc.hop_n
    ref = np.concatenate([np.zeros(d, np.float32), x])[:n]
    assert np.max(np.abs(y[d:] - ref[d:])) < 1e-2   # resampler edge effects


def test_silence_skips_model():
    class Boom(Backend):
        name = "boom"
        def convert(self, a): raise AssertionError("must not be called on silence")
    m = mgr(["passthrough"]); m.chain.insert(0, Boom()); m.idx = 0
    sc = StreamConverter(SR, m, gate_db=-50)
    y = run(sc, np.zeros(SR, np.float32))
    assert not np.any(y) and sc.voiced_hops == 0


def test_backend_crash_demotes_and_mutes_never_leaks():
    class Crash(Backend):
        name = "crash"
        def convert(self, a): raise RuntimeError("gpu oom")
    ev = []
    m = mgr([], events=ev); m.chain.insert(0, Crash()); m.idx = 0
    sc = StreamConverter(SR, m)
    y = run(sc, tone(220, 1.5))
    assert m.active.name == "mute" and m.errors == 1
    assert np.max(np.abs(y)) < 1e-6          # real voice never emitted
    assert any(k == "demote" for k, _ in ev)


def test_promote_after_demote():
    m = mgr(["passthrough"])
    assert m.demote("x") and m.active.name == "mute"
    assert m.promote() and m.active.name == "passthrough"


def test_ring_underrun_and_overflow():
    r = Ring(100)
    r.write(np.ones(60, np.float32))
    out = r.read(80)
    assert out[:60].all() and not out[60:].any() and r.underruns == 1
    r.write(np.arange(150, dtype=np.float32))     # > capacity
    assert len(r) == 100 and r.read(1)[0] == 50.0


def test_resample_roundtrip_length():
    x = tone(300, 1.0)
    y = resample(resample(x, SR, 22050), 22050, SR)
    assert abs(len(y) - len(x)) <= 2


@pytest.mark.parametrize("f", [110, 180, 260])
def test_f0_estimate(f):
    est = estimate_f0(tone(f, 1.0, 0.3, 22050), 22050)
    assert est and abs(est - f) / f < 0.03


def test_pitch_backend_shifts_toward_target(tmp_path):
    pytest.importorskip("pedalboard")
    import json
    from mimicry.backends.pitch import PitchBackend
    (tmp_path / "meta.json").write_text(json.dumps({"target_f0": 220.0}))
    b = PitchBackend(); b.load(tmp_path, None)
    x = tone(110, 1.0, 0.3, b.sample_rate)
    y = b.convert(x)
    assert abs(estimate_f0(y, b.sample_rate) - 220) / 220 < 0.08


def test_polish_and_clean():
    from mimicry.audio_clean import Polish, prepare_sample, soft_limit
    from mimicry.dsp import rms_db
    rng = np.random.default_rng(0)
    clean = tone(220, 4.0, 0.3) * (0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * np.arange(4 * SR) / SR))
    noisy = (clean + 0.02 * rng.standard_normal(len(clean))).astype(np.float32)
    out = prepare_sample(noisy, SR)
    assert abs(np.abs(out).max() - 10 ** (-3 / 20)) < 0.02             # normalised
    from mimicry.profile import quality_report
    assert quality_report(out, SR)[1]["snr_db"] > quality_report(noisy, SR)[1]["snr_db"] + 3   # denoise helps
    p = Polish(SR)
    y = np.concatenate([p.process(tone(220, 0.2, 1.5)[i:i + 480]) for i in range(0, 9600, 480)])
    assert np.abs(y).max() <= 0.97 + 1e-6                                # limiter ceiling
    assert np.abs(soft_limit(np.array([0.5], np.float32))[0]) == 0.5     # transparent below knee


def test_split_for_embedding_segments():
    from mimicry.backends.openvoice import split_for_embedding
    sr = 22050
    segs = split_for_embedding(np.zeros(sr * 25, np.float32), sr)        # 10 + 10 + 5 s
    assert [len(s) // sr for s in segs] == [10, 10, 5]
    segs = split_for_embedding(np.zeros(sr * 21, np.float32) + 1, sr)    # 1 s tail dropped (<2 s)
    assert len(segs) == 2
    assert len(split_for_embedding(np.zeros(sr * 1, np.float32), sr)) == 1   # too short: keep whole
