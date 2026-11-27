"""The agent layer.

A small multi-role supervisor that observes the pipeline and acts on it.
It is a deterministic control loop (no cloud LLM, so no extra latency and no
audio leaving the machine). Roles:

  PlannerAgent    - picks devices / routing at start-up and refuses unsafe routing
  PerformanceAgent- watches real-time factor, grows hop size, demotes/promotes backends
  ReliabilityAgent- watches streams, restarts them after device loss, tracks underruns
  SafetyAgent     - guarantees the real voice never reaches the virtual mic
"""
from __future__ import annotations

import json
import threading
from collections import deque
import time
from pathlib import Path
from typing import Optional

from . import devices


class EventLog:
    def __init__(self, logs_dir: str):
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        self.path = Path(logs_dir) / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self.lock = threading.Lock()
        self.echo = True
        self.recent = deque(maxlen=60)

    def __call__(self, kind: str, data: dict):
        rec = {"t": round(time.time(), 2), "event": kind, **data}
        if kind != "tick":
            self.recent.append(rec)
        with self.lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        if self.echo and kind not in ("tick",):
            print(f"\n[agent] {kind}: {data}")


class PlannerAgent:
    """Decides routing. Returns (in_dev, out_dev, mon_dev) or raises SystemExit with advice."""

    def __init__(self, cfg, emit):
        self.cfg, self.emit = cfg, emit

    def plan(self):
        out = (devices.find(self.cfg.output_device, "out") if self.cfg.output_device
               else devices.auto_virtual_output())
        if not out:
            raise SystemExit(devices.virtual_driver_help())
        d_in, d_out = devices.default_devices()
        inp = devices.find(self.cfg.input_device, "in") if self.cfg.input_device else d_in
        if not inp:
            raise SystemExit("No microphone found. Pass --input <name or index>. See `mimicry devices`.")
        if devices.is_virtual_input(inp):
            raise SystemExit(f"Input '{inp['name']}' is a virtual device; choose your real microphone.")
        mon = None
        if self.cfg.monitor:
            mon = devices.find(self.cfg.monitor_device, "out") if self.cfg.monitor_device else d_out
            if mon and mon["index"] == out["index"]:
                mon = None
        self.emit("plan", {"input": inp["name"], "virtual_mic_sink": out["name"],
                           "monitor": mon["name"] if mon else None,
                           "select_in_call_app": devices.call_app_mic_name(out["name"])})
        return inp, out, mon


class PerformanceAgent:
    def __init__(self, cfg, engine, manager, emit):
        self.cfg, self.engine, self.mgr, self.emit = cfg, engine, manager, emit
        self.high = self.low = 0
        self.base_hop = cfg.hop_ms
        self.cooldown_until = 0.0
        self.promote_wait = 120.0

    def tick(self):
        c = self.engine.conv
        if c.rtf == 0:
            return
        if c.rtf > self.cfg.rtf_high:
            self.high += 1; self.low = 0
        elif c.rtf < self.cfg.rtf_low:
            self.low += 1; self.high = 0
        else:
            self.high = self.low = 0

        if self.high >= 3:                                   # sustained overload
            self.high = 0
            if c.hop_ms < self.cfg.max_hop_ms:
                new = min(self.cfg.max_hop_ms, int(c.hop_ms * 1.25 // 20 * 20))
                c.set_hop(new)
                self.emit("hop_increased", {"hop_ms": new, "rtf": round(c.rtf, 2)})
            elif self.mgr.demote(f"rtf {c.rtf:.2f} at max hop"):
                c.rtf = 0.0
                self.cooldown_until = time.time() + self.promote_wait
        elif self.low >= 30 and time.time() > self.cooldown_until:   # headroom
            self.low = 0
            if c.hop_ms > self.base_hop:
                c.set_hop(max(self.base_hop, int(c.hop_ms * 0.8 // 20 * 20)))
                self.emit("hop_decreased", {"hop_ms": c.hop_ms})
            elif self.mgr.degraded and self.mgr.active.name != "mute":
                # a lighter backend has headroom; try the better one again, back off if it fails
                if self.mgr.promote():
                    c.rtf = 0.0
                    self.promote_wait *= 2
                    self.cooldown_until = time.time() + self.promote_wait


class ReliabilityAgent:
    def __init__(self, engine, emit):
        self.engine, self.emit = engine, emit
        self.last_under = 0
        self.fails = 0

    def tick(self):
        e = self.engine
        if e.running and not e.streams_alive():
            self.fails += 1
            self.emit("streams_down", {"attempt": self.fails})
            time.sleep(min(5, self.fails))
            if e.restart_streams():
                self.fails = 0
        u = e.out_ring.underruns
        if u - self.last_under > 5:
            self.emit("underruns", {"count": u - self.last_under})
            e.prebuffer = min(e.prebuffer + int(e.sr * 0.04), int(e.sr * 0.5))
        self.last_under = u


class SafetyAgent:
    """Static guarantee: when every backend failed, fail_mode=mute outputs silence."""

    def __init__(self, cfg, manager, emit):
        self.cfg, self.mgr, self.emit = cfg, manager, emit
        self.warned = False

    def tick(self):
        if self.mgr.active.name == "mute" and not self.warned:
            self.warned = True
            self.emit("muted", {"reason": "no working backend; real voice is NOT being sent"})
        elif self.mgr.active.name != "mute":
            self.warned = False


class Supervisor:
    def __init__(self, cfg, engine, manager, emit, period=1.0):
        self.agents = [PerformanceAgent(cfg, engine, manager, emit),
                       ReliabilityAgent(engine, emit), SafetyAgent(cfg, manager, emit)]
        self.engine, self.emit, self.period = engine, emit, period
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="mimicry-supervisor")

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.period):
            for a in self.agents:
                try:
                    a.tick()
                except Exception as e:  # noqa: BLE001
                    self.emit("agent_error", {"agent": type(a).__name__, "error": repr(e)})
            self.emit("tick", self.engine.stats())
