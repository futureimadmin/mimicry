"""Cross-platform audio device discovery (Windows / macOS / Linux)."""
from __future__ import annotations

import platform
from typing import Optional, Tuple

# Names of virtual-microphone drivers the other party's call app will see as a mic.
VIRTUAL_OUT_HINTS = ["cable input", "blackhole", "loopback audio", "voicemeeter input",
                     "vb-audio", "virtual", "pulse_sink"]
# Devices that are virtual *captures*: never use as our real mic (would loop audio).
VIRTUAL_IN_HINTS = ["cable output", "blackhole", "loopback", "voicemeeter out", "virtual", "stereo mix"]


def _sd():
    import sounddevice as sd
    return sd


def list_devices():
    sd = _sd()
    apis = sd.query_hostapis()
    rows = []
    for i, d in enumerate(sd.query_devices()):
        rows.append({"index": i, "name": d["name"], "in": d["max_input_channels"],
                     "out": d["max_output_channels"], "sr": d["default_samplerate"],
                     "api": apis[d["hostapi"]]["name"]})
    return rows


def _api_rank(api: str) -> int:
    # prefer low-latency, shared-mode APIs per OS
    order = {"Windows": ["Windows WASAPI", "MME", "Windows DirectSound"],
             "Darwin": ["Core Audio"], "Linux": ["ALSA", "PulseAudio", "JACK Audio Connection Kit"]}
    lst = order.get(platform.system(), [])
    return lst.index(api) if api in lst else len(lst)


def find(name: Optional[str], kind: str) -> Optional[dict]:
    """kind: 'in' or 'out'. name: case-insensitive substring or numeric index."""
    rows = [r for r in list_devices() if r[kind] > 0]
    if name is None:
        return None
    if str(name).isdigit():
        return next((r for r in rows if r["index"] == int(name)), None)
    hits = [r for r in rows if name.lower() in r["name"].lower()]
    return sorted(hits, key=lambda r: _api_rank(r["api"]))[0] if hits else None


def auto_virtual_output() -> Optional[dict]:
    rows = [r for r in list_devices() if r["out"] > 0
            and any(h in r["name"].lower() for h in VIRTUAL_OUT_HINTS)]
    return sorted(rows, key=lambda r: _api_rank(r["api"]))[0] if rows else None


def default_devices() -> Tuple[Optional[dict], Optional[dict]]:
    sd = _sd()
    rows = {r["index"]: r for r in list_devices()}
    i, o = sd.default.device
    return rows.get(i if i is not None and i >= 0 else -1), rows.get(o if o is not None and o >= 0 else -1)


def is_virtual_input(dev: dict) -> bool:
    return any(h in dev["name"].lower() for h in VIRTUAL_IN_HINTS)


def virtual_driver_help() -> str:
    if platform.system() == "Darwin":
        return ("No virtual microphone found. Install BlackHole 2ch (brew install blackhole-2ch), "
                "then restart. In your call app choose 'BlackHole 2ch' as the microphone.")
    if platform.system() == "Windows":
        return ("No virtual microphone found. Install VB-CABLE (https://vb-audio.com/Cable/), reboot. "
                "In your call app choose 'CABLE Output (VB-Audio Virtual Cable)' as the microphone.")
    return "Create a virtual source (e.g. `pactl load-module module-null-sink`) and select its monitor as the mic."


def call_app_mic_name(out_dev_name: str) -> str:
    n = out_dev_name.lower()
    if "cable input" in n:
        return "CABLE Output (VB-Audio Virtual Cable)"
    return out_dev_name   # BlackHole etc. show the same name as input and output
