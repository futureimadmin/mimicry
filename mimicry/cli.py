"""Command line: python -m mimicry <command>"""
from __future__ import annotations

import argparse
import platform
import sys
import time

from . import __version__, devices
from .config import Config


def cmd_devices(a, cfg):
    for r in devices.list_devices():
        kind = ("IN " if r["in"] else "   ") + ("OUT" if r["out"] else "   ")
        print(f"{r['index']:>3} {kind}  {r['name']}  [{r['api']}, {int(r['sr'])} Hz]")


def cmd_doctor(a, cfg):
    print(f"Mimicry {__version__} on {platform.system()} {platform.machine()}, Python {platform.python_version()}")
    for mod in ["numpy", "scipy", "sounddevice", "soundfile", "pedalboard", "torch"]:
        try:
            m = __import__(mod)
            print(f"  [ok] {mod} {getattr(m, '__version__', '')}")
        except Exception as e:  # noqa: BLE001
            print(f"  [--] {mod}: {e.__class__.__name__}")
    try:
        import torch
        from .backends.openvoice import pick_device
        print(f"  torch device: {pick_device(cfg.torch_device)} (cuda={torch.cuda.is_available()})")
    except Exception:  # noqa: BLE001
        pass
    from pathlib import Path
    try:
        repo = Path(cfg.openvoice_dir).resolve()
        if repo.exists():
            sys.path.insert(0, str(repo))
        import openvoice.api  # noqa: F401
        print("  [ok] openvoice.api imports")
    except Exception as e:  # noqa: BLE001
        print(f"  [--] openvoice.api import failed: {e!r}\n"
              "       fix: re-run the installer (Mac: setup_mac.command --fresh | Windows: install.ps1 -Fresh)")
    ok = (Path(cfg.openvoice_ckpt) / "converter" / "checkpoint.pth").exists()
    print(f"  [{'ok' if ok else '--'}] OpenVoice checkpoints at {cfg.openvoice_ckpt}"
          + ("" if ok else "  (download: see README \u00a72, 'Model files')"))
    try:
        v = devices.auto_virtual_output()
        if v:
            print(f"  [ok] virtual mic driver: {v['name']}  -> select '{devices.call_app_mic_name(v['name'])}' in your call app")
        else:
            print("  [--] " + devices.virtual_driver_help())
        i, o = devices.default_devices()
        print(f"  default mic: {i and i['name']} | default speaker: {o and o['name']}")
    except Exception as e:  # noqa: BLE001
        print(f"  [--] audio query failed: {e}")


def cmd_record(a, cfg):
    import sounddevice as sd
    import soundfile as sf
    dev = devices.find(a.input, "in")["index"] if a.input else None
    print(f"Recording {a.seconds}s - read something naturally (a news article works well)...")
    x = sd.rec(int(a.seconds * 48000), samplerate=48000, channels=1, dtype="float32", device=dev)
    sd.wait()
    sf.write(a.out, x, 48000)
    print("saved", a.out)


def cmd_enroll(a, cfg):
    from .profile import enroll
    enroll(cfg, a.target, a.source, a.name or cfg.profile, assume_consent=a.i_agree)


def cmd_convert(a, cfg):
    """Offline test: run a wav through the exact streaming pipeline."""
    import soundfile as sf
    from .agent import EventLog
    from .backends import BackendManager
    from .offline import convert_array
    from .profile import load_wav, require_profile
    emit = EventLog(cfg.logs_dir)
    pdir = require_profile(cfg)
    if a.backend:
        cfg.backends = [a.backend]
    mgr = BackendManager(cfg.backends, pdir, cfg, cfg.fail_mode, emit)
    x, sr = load_wav(a.input, cfg.sample_rate)
    y, rtf = convert_array(cfg, mgr, x, sr)
    sf.write(a.out, y, sr)
    print(f"wrote {a.out}; backend={mgr.active.name}; rtf={rtf:.2f} (must stay < 1.0 for live use)")


def cmd_selftest(a, cfg):
    """Proves the neural model really loads and converts audio on this machine."""
    import tempfile
    import numpy as np
    import soundfile as sf
    from pathlib import Path
    from .backends.openvoice import ensure_repo_on_path, make_converter, pick_device
    ensure_repo_on_path(cfg)
    dev = pick_device(cfg.torch_device)
    t0 = time.perf_counter()
    conv = make_converter(Path(cfg.openvoice_ckpt).resolve(), dev, False)
    load_s = time.perf_counter() - t0
    sr = int(conv.hps.data.sampling_rate)
    t = np.arange(sr * 4) / sr
    x = sum(0.3 / k * np.sin(2 * np.pi * 140 * k * t) for k in range(1, 8)) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "a.wav")
        sf.write(p, x.astype("float32"), sr)
        se = conv.extract_se([p])
        conv.convert(audio_src_path=p, src_se=se, tgt_se=se, tau=cfg.openvoice_tau)   # warm-up
        t1 = time.perf_counter()
        y = conv.convert(audio_src_path=p, src_se=se, tgt_se=se, tau=cfg.openvoice_tau)
        dt = time.perf_counter() - t1
    rtf = dt / 4.0
    print(f"NEURAL SELFTEST OK  device={dev}  model-load={load_s:.1f}s  speed={rtf:.2f}x realtime  out={len(y)/sr:.1f}s")
    print("Live use needs speed < 1.0x" + ("" if rtf < 1 else "  -> too slow on this device; the agent will fall back to larger chunks / pitch-only"))


def cmd_ui(a, cfg):
    from .ui.server import serve
    serve(cfg, port=a.port, open_browser=not a.no_browser)


def cmd_run(a, cfg):
    from .agent import EventLog, PlannerAgent, Supervisor
    from .backends import BackendManager
    from .engine import Engine
    from .profile import require_profile
    emit = EventLog(cfg.logs_dir)
    pdir = require_profile(cfg)
    inp, out, mon = PlannerAgent(cfg, emit).plan()
    mgr = BackendManager(cfg.backends, pdir, cfg, cfg.fail_mode, emit)
    eng = Engine(cfg, mgr, inp, out, mon, emit)
    sup = Supervisor(cfg, eng, mgr, emit)
    eng.start(); sup.start()
    print(f"\nLive. In your call app set the microphone to: {devices.call_app_mic_name(out['name'])}")
    print("Your real voice is never sent; if conversion fails the agent mutes. Ctrl+C to stop.\n")
    emit.echo = True
    try:
        while True:
            time.sleep(1)
            s = eng.stats()
            sys.stdout.write("\r" + " | ".join(f"{k}={v}" for k, v in s.items()) + "   ")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sup.stop(); eng.stop()
        print("\nstopped. log:", emit.path)


def build_parser():
    p = argparse.ArgumentParser(prog="mimicry", description="Real-time voice conversion to a virtual microphone")
    p.add_argument("--config", default="config.json")
    p.add_argument("--profile")
    p.add_argument("--input", help="real microphone (name substring or index)")
    p.add_argument("--output", help="virtual mic sink (default: auto-detect BlackHole/VB-Cable)")
    p.add_argument("--monitor", action="store_true", help="also hear the converted voice locally (use headphones)")
    p.add_argument("--monitor-device")
    p.add_argument("--hop-ms", type=int)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("selftest", help="load the neural model and convert a test signal").set_defaults(fn=cmd_selftest)
    r = sub.add_parser("record"); r.add_argument("--seconds", type=int, default=30)
    r.add_argument("--out", default="me.wav"); r.set_defaults(fn=cmd_record)
    e = sub.add_parser("enroll"); e.add_argument("--target", required=True)
    e.add_argument("--source"); e.add_argument("--name"); e.add_argument("--i-agree", action="store_true")
    e.set_defaults(fn=cmd_enroll)
    c = sub.add_parser("convert"); c.add_argument("input"); c.add_argument("--out", default="converted.wav")
    c.add_argument("--backend"); c.set_defaults(fn=cmd_convert)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sub.add_parser("ui", help="open the web UI (default)").set_defaults(fn=cmd_ui)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    cfg = Config.load(a.config)
    for k, attr in [("profile", "profile"), ("input", "input_device"), ("output", "output_device"),
                    ("monitor_device", "monitor_device"), ("hop_ms", "hop_ms")]:
        if getattr(a, k, None):
            setattr(cfg, attr, getattr(a, k))
    if a.monitor:
        cfg.monitor = True
    (getattr(a, "fn", None) or cmd_ui)(a, cfg)


if __name__ == "__main__":
    main()
