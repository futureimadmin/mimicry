"""Live audio engine: mic -> StreamConverter -> virtual mic (+ optional monitor)."""
from __future__ import annotations

import platform
import queue
import threading
import time
from typing import Optional

import numpy as np

from . import devices
from .audio_clean import Polish
from .dsp import rms_db
from .ring import Ring
from .stream import StreamConverter


class Engine:
    def __init__(self, cfg, manager, in_dev: dict, out_dev: dict, mon_dev: Optional[dict], emit):
        self.cfg, self.mgr, self.emit = cfg, manager, emit
        self.in_dev, self.out_dev, self.mon_dev = in_dev, out_dev, mon_dev
        self.in_db = self.out_db = -120.0
        self._build(cfg.sample_rate)
        self._primed_out = self._primed_mon = False
        self.streams = []
        self.running = False
        self.stream_errors = 0
        self.input_drops = 0
        self.worker: Optional[threading.Thread] = None

    def _build(self, sr: int):
        cfg = self.cfg
        self.sr = sr
        self.conv = StreamConverter(sr, self.mgr, cfg.hop_ms, cfg.ctx_ms, cfg.xfade_ms, cfg.gate_db)
        self.polish = Polish(sr, cfg.polish_shelf_db) if cfg.polish else None
        self.inq: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=200)
        self.out_ring = Ring(sr * 4)
        self.mon_ring = Ring(sr * 4) if self.mon_dev else None
        self.prebuffer = int(sr * cfg.prebuffer_ms / 1000)
        self._primed_out = self._primed_mon = False

    # ---- audio callbacks -------------------------------------------------
    def _in_cb(self, indata, frames, t, status):
        if status:
            self.stream_errors += 1
        try:
            blk = indata[:, 0].copy()
            self.in_db = 0.8 * self.in_db + 0.2 * rms_db(blk)
            self.inq.put_nowait(blk)
        except queue.Full:
            self.input_drops += 1

    def _make_out_cb(self, ring: Ring, which: str):
        def cb(outdata, frames, t, status):
            if status:
                self.stream_errors += 1
            primed = getattr(self, f"_primed_{which}")
            if not primed:
                if len(ring) < self.prebuffer:
                    outdata.fill(0)
                    return
                setattr(self, f"_primed_{which}", True)
            outdata[:] = ring.read(frames)[:, None]
        return cb

    # ---- lifecycle --------------------------------------------------------
    def _extra(self, dev):
        import sounddevice as sd
        if platform.system() == "Windows" and "WASAPI" in dev["api"]:
            return sd.WasapiSettings(auto_convert=True)
        return None

    def start(self):
        import sounddevice as sd
        tried, last = [], None
        for sr in dict.fromkeys([self.cfg.sample_rate, int(self.in_dev["sr"]), int(self.out_dev["sr"]), 48000, 44100]):
            if sr != self.sr or tried:
                self._build(sr)
            tried.append(sr)
            try:
                self._open(sd)
                return
            except Exception as e:  # noqa: BLE001 - e.g. device doesn't support this rate
                last = e
                self.emit("open_failed", {"sr": sr, "error": repr(e)})
                for s_ in self.streams:
                    try: s_.close()
                    except Exception: pass  # noqa: BLE001
                self.streams = []
        raise RuntimeError(f"could not open audio devices at any sample rate {tried}: {last!r}")

    def _open(self, sd):
        self.running = True
        if not (self.worker and self.worker.is_alive()):
            self.worker = threading.Thread(target=self._work, daemon=True, name="mimicry-worker")
            self.worker.start()
        blk = int(self.sr * 0.02)
        self.streams = [
            sd.InputStream(device=self.in_dev["index"], samplerate=self.sr, channels=1, blocksize=blk,
                           dtype="float32", callback=self._in_cb, extra_settings=self._extra(self.in_dev)),
            sd.OutputStream(device=self.out_dev["index"], samplerate=self.sr, channels=1, blocksize=blk,
                            dtype="float32", callback=self._make_out_cb(self.out_ring, "out"),
                            extra_settings=self._extra(self.out_dev)),
        ]
        if self.mon_dev:
            self.streams.append(sd.OutputStream(
                device=self.mon_dev["index"], samplerate=self.sr, channels=1, blocksize=blk, dtype="float32",
                callback=self._make_out_cb(self.mon_ring, "mon"), extra_settings=self._extra(self.mon_dev)))
        for s_ in self.streams:
            s_.start()
        self.emit("engine_started", {"in": self.in_dev["name"], "out": self.out_dev["name"],
                                     "monitor": self.mon_dev["name"] if self.mon_dev else None, "sr": self.sr})

    def stop(self):
        self.running = False
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=1.0)
        for s in self.streams:
            try:
                s.stop(); s.close()
            except Exception:  # noqa: BLE001
                pass
        self.streams = []

    def restart_streams(self) -> bool:
        """Used by the supervisor after a device error/unplug."""
        self.stop()
        try:
            self.start()
            return True
        except Exception as e:  # noqa: BLE001
            self.emit("restart_failed", {"error": repr(e)})
            return False

    def streams_alive(self) -> bool:
        return bool(self.streams) and all(s.active for s in self.streams)

    # ---- worker -----------------------------------------------------------
    def _work(self):
        while self.running:
            try:
                x = self.inq.get(timeout=0.2)
            except queue.Empty:
                continue
            y = self.conv.process(x)
            if len(y):
                if self.polish is not None:
                    y = self.polish.process(y)
                self.out_db = 0.7 * self.out_db + 0.3 * rms_db(y)
                self.out_ring.write(y)
                if self.mon_ring is not None:
                    self.mon_ring.write(y)

    def stats(self) -> dict:
        c = self.conv
        return {"backend": self.mgr.active.name, "degraded": self.mgr.degraded,
                "rtf": round(c.rtf, 2), "hop_ms": c.hop_ms,
                "latency_ms": int(c.hop_ms + self.cfg.xfade_ms + c.last_proc_s * 1000),
                "underruns": self.out_ring.underruns, "overflows": self.out_ring.overflows,
                "input_drops": self.input_drops, "stream_errors": self.stream_errors,
                "voiced": f"{c.voiced_hops}/{c.total_hops}", "in_db": round(self.in_db), "out_db": round(self.out_db), "sr": self.sr}
