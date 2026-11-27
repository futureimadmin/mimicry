"""Local web UI server (stdlib only). Binds to 127.0.0.1; every API call needs a per-run token."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import platform
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import numpy as np

from .. import __version__, devices
from ..agent import EventLog, PlannerAgent, Supervisor
from ..backends import BackendManager
from ..dsp import resample, to_mono
from ..offline import convert_array
from ..profile import CONSENT_TEXT, enroll, quality_report

MAX_BODY = 80 * 1024 * 1024
ID_RE = re.compile(r"^(target|source|try)-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PAGE = Path(__file__).with_name("index.html")


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = secrets.token_urlsafe(24)
        self.events = EventLog(cfg.logs_dir)
        self.events.echo = False
        self.rec_dir = Path("recordings")
        self.rec_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.status, self.error = "idle", None
        self.engine = self.supervisor = self.manager = None
        self.manager_profile: Optional[str] = None
        self.plan: dict = {}

    # ---- helpers --------------------------------------------------------
    def profiles(self):
        out = []
        root = Path(self.cfg.profiles_dir)
        for d in sorted(root.glob("*/meta.json")) if root.exists() else []:
            m = json.loads(d.read_text())
            pd = d.parent
            out.append({"name": m["name"], "target_f0": m.get("target_f0"), "metrics": m.get("metrics", {}),
                        "neural_ready": (pd / "target_se.pt").exists() and (pd / "source_se.pt").exists()})
        return out

    def get_manager(self, profile: str):
        with self.lock:
            if self.manager is None or self.manager_profile != profile:
                cfg = copy.copy(self.cfg); cfg.profile = profile
                pdir = cfg.profile_path()
                if not (pdir / "meta.json").exists():
                    raise ValueError(f"profile '{profile}' not found")
                self.manager = BackendManager(cfg.backends, pdir, cfg, cfg.fail_mode, self.events)
                self.manager_profile = profile
            return self.manager

    def state(self):
        try:
            devs = devices.list_devices()
            err = None
        except Exception as e:  # noqa: BLE001
            devs, err = [], f"audio system unavailable: {e}"
        virt = None
        try:
            v = devices.auto_virtual_output() if devs else None
            if v:
                virt = {"index": v["index"], "name": v["name"], "call_app_mic": devices.call_app_mic_name(v["name"])}
        except Exception:  # noqa: BLE001
            pass
        ckpt = (Path(self.cfg.openvoice_ckpt) / "converter" / "checkpoint.pth").exists()
        s = {"version": __version__, "platform": platform.system(), "arch": platform.machine(),
             "status": self.status, "error": self.error, "plan": self.plan,
             "devices": {"inputs": [d for d in devs if d["in"] and not devices.is_virtual_input(d)],
                         "outputs": [d for d in devs if d["out"]]},
             "audio_error": err, "virtual": virt,
             "virtual_help": devices.virtual_driver_help(),
             "profiles": self.profiles(), "consent_text": CONSENT_TEXT,
             "neural": {"torch": importlib.util.find_spec("torch") is not None, "checkpoints": ckpt},
             "events": list(self.events.recent)[-14:]}
        if self.engine and self.status == "live":
            s["stats"] = self.engine.stats()
        return s

    # ---- recordings ------------------------------------------------------
    def save_upload(self, kind: str, data: bytes):
        import soundfile as sf
        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
        x = to_mono(x)
        if len(x) < sr * 1.0:
            raise ValueError("recording is shorter than 1 second")
        rid = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
        sf.write(self.rec_dir / f"{rid}.wav", x, sr, subtype="PCM_24")
        warns, m = quality_report(x, sr)
        m["peak_db"] = round(20 * np.log10(max(float(np.abs(x).max()), 1e-6)), 1)
        return {"id": rid, "sr": sr, "metrics": m, "warnings": warns}

    def rec_path(self, rid: str) -> Path:
        if not ID_RE.match(rid or ""):
            raise ValueError("bad recording id")
        p = self.rec_dir / f"{rid}.wav"
        if not p.exists():
            raise ValueError("recording not found")
        return p

    # ---- actions ---------------------------------------------------------
    def do_enroll(self, b: dict):
        if b.get("consent") is not True:
            raise ValueError("consent confirmation is required")
        name = b.get("name", "default")
        if not NAME_RE.match(name):
            raise ValueError("profile name: letters, digits, - and _ only (max 40)")
        tgt = self.rec_path(b.get("target"))
        src = self.rec_path(b["source"]) if b.get("source") else None
        if self.status in ("live", "starting"):
            raise RuntimeError("stop live mode before enrolling")
        lines = []
        cfg = copy.copy(self.cfg)
        enroll(cfg, str(tgt), str(src) if src else None, name, assume_consent=True, log=lines.append)
        with self.lock:
            self.manager = None                                  # force reload with the new profile
        return {"ok": True, "log": lines, "profile": name}

    def do_convert(self, wav: bytes, profile: str):
        import soundfile as sf
        if self.status in ("live", "starting"):
            raise RuntimeError("stop live mode before using Try-it")
        mgr = self.get_manager(profile)
        x, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=False)
        x = resample(to_mono(x), sr, self.cfg.sample_rate)
        t0 = time.perf_counter()
        y, rtf = convert_array(self.cfg, mgr, x, self.cfg.sample_rate)
        buf = io.BytesIO()
        sf.write(buf, y, self.cfg.sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue(), {"backend": mgr.active.name, "rtf": round(rtf, 2),
                                "seconds": round(time.perf_counter() - t0, 2)}

    def start_live(self, b: dict):
        with self.lock:
            if self.status in ("live", "starting"):
                raise RuntimeError("already running")
            self.status, self.error = "starting", None
        threading.Thread(target=self._start_live, args=(b,), daemon=True).start()

    def _start_live(self, b: dict):
        from ..engine import Engine
        try:
            cfg = copy.copy(self.cfg)
            cfg.profile = b.get("profile") or cfg.profile
            cfg.input_device = str(b["input"]) if b.get("input") not in (None, "") else None
            cfg.output_device = str(b["output"]) if b.get("output") not in (None, "") else None
            cfg.monitor = bool(b.get("monitor"))
            if b.get("hop_ms"):
                cfg.hop_ms = int(b["hop_ms"])
            mgr = self.get_manager(cfg.profile)
            inp, out, mon = PlannerAgent(cfg, self.events).plan()
            self.plan = {"input": inp["name"], "output": out["name"], "monitor": mon["name"] if mon else None,
                         "call_app_mic": devices.call_app_mic_name(out["name"])}
            eng = Engine(cfg, mgr, inp, out, mon, self.events)
            eng.start()
            sup = Supervisor(cfg, eng, mgr, self.events)
            sup.start()
            with self.lock:
                self.engine, self.supervisor, self.status = eng, sup, "live"
        except BaseException as e:  # noqa: BLE001 - SystemExit from planner carries advice
            with self.lock:
                self.status, self.error = "error", str(e) or repr(e)

    def stop_live(self):
        with self.lock:
            sup, eng = self.supervisor, self.engine
            self.supervisor = self.engine = None
            self.status, self.error = "idle", None
        if sup: sup.stop()
        if eng: eng.stop()


def make_handler(app: App, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "Mimicry"

        def log_message(self, *a):  # quiet
            pass

        # -- plumbing
        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _authed(self, q):
            if self.headers.get("Host") not in hosts:
                return False
            tok = self.headers.get("X-Mimicry-Token") or (q.get("t") or [""])[0]
            return secrets.compare_digest(tok, app.token)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("upload too large")
            return self.rfile.read(n)

        def _route(self, method):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if self.headers.get("Host") not in hosts:
                return self._json({"error": "bad host"}, 403)
            if method == "GET" and u.path in ("/", "/index.html"):
                html = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if not u.path.startswith("/api/") or not self._authed(q):
                return self._json({"error": "forbidden"}, 403)
            try:
                if method == "GET" and u.path == "/api/state":
                    return self._json(app.state())
                if method == "GET" and u.path == "/api/recording":
                    p = app.rec_path(q.get("id", [""])[0])
                    return self._send(200, p.read_bytes(), "audio/wav")
                if method == "POST" and u.path == "/api/upload":
                    kind = q.get("kind", ["target"])[0]
                    if kind not in ("target", "source", "try"):
                        raise ValueError("bad kind")
                    return self._json(app.save_upload(kind, self._body()))
                if method == "POST" and u.path == "/api/enroll":
                    return self._json(app.do_enroll(json.loads(self._body() or b"{}")))
                if method == "POST" and u.path == "/api/convert":
                    wav, info = app.do_convert(self._body(), q.get("profile", [app.cfg.profile])[0])
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(wav)))
                    self.send_header("X-Mimicry-Info", json.dumps(info))
                    self.send_header("Access-Control-Expose-Headers", "X-Mimicry-Info")
                    self.end_headers()
                    self.wfile.write(wav)
                    return
                if method == "POST" and u.path == "/api/start":
                    app.start_live(json.loads(self._body() or b"{}"))
                    return self._json({"ok": True})
                if method == "POST" and u.path == "/api/stop":
                    app.stop_live()
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, 404)
            except (ValueError, RuntimeError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return H


def serve(cfg, port: int = 8765, open_browser: bool = True):
    app = App(cfg)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Mimicry UI running at {url}   (Ctrl+C to quit)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_live()
        httpd.server_close()
    return app
