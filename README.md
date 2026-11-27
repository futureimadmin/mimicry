# Mimicry – real-time agentic voice conversion

You speak in your own voice → Mimicry converts it to a **target voice** (taken from a sample you record or upload) → the result is sent to a **virtual microphone**. Any app that uses a microphone (Teams, Zoom, Google Meet, WhatsApp Desktop, Discord, a recorder …) selects that virtual microphone, so the other person only ever hears the target voice. Works on **macOS** and **Windows**.

```
 your mic ──► clean/gate ──► voice conversion ──► polish ──► VIRTUAL MIC ──► call app ──► other person
                              │                              (BlackHole / VB-CABLE)
                              └─ backend chain: openvoice (neural) → pitch (CPU fallback) → mute
 Agents watching it all: Planner · Performance · Reliability · Safety
```

> **Use responsibly.** Only use a target voice that is yours, or whose owner has explicitly agreed. Tell call participants when a voice is synthetic. Do not use this to impersonate, deceive or defraud anyone. Creating a profile requires a consent confirmation, which is stored with the profile.

---

## 1. What you need

| | macOS | Windows |
|---|---|---|
| OS | macOS 12+ (Apple Silicon or Intel) | Windows 10/11 |
| Python | 3.10 or 3.11 | 3.10 or 3.11 (`py -3.11`) |
| Git | included with Xcode CLT (`xcode-select --install`) | https://git-scm.com |
| Virtual microphone | **BlackHole 2ch** (free) | **VB-CABLE** (free) |
| GPU (strongly recommended) | Apple Silicon (uses MPS automatically) | NVIDIA GPU (CUDA) |
| Headphones | recommended (avoids echo) | recommended |

Without a GPU it still runs: the agent widens the chunk size and, if needed, falls back to a lighter pitch-only mode.

## 2. Install (one time)

### macOS
```bash
cd mimicry
bash scripts/install.sh        # creates .venv, installs packages, OpenVoice + model files, BlackHole via Homebrew
```
1. If Homebrew isn't installed, get it from https://brew.sh, then re-run the script (or run `brew install blackhole-2ch`).
2. **Restart your Mac once** after BlackHole installs (it's an audio driver).
3. Make the launcher runnable: `chmod +x start.command` (the script already tries this).

### Windows (PowerShell)
```powershell
cd C:\FutureIM\cleanup\products\mimicry
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Fresh
```
One command does everything and stops with a clear message if a step fails: finds Python 3.10-3.12, builds a clean `.venv`,
installs pinned packages, installs PyTorch (CUDA if you have an NVIDIA GPU, otherwise CPU), fetches OpenVoice, downloads the
model from Hugging Face, and runs a **self-test** that really converts audio. A full log is in `logs\install.log`.
Needs Python 3.10-3.12 (`winget install -e --id Python.Python.3.11` if missing). Then install **VB-CABLE**
(https://vb-audio.com/Cable/, run as administrator) and **reboot**.

### Check the install
```
.\.venv\Scripts\python -m mimicry doctor      # Windows        |   .venv/bin/python -m mimicry doctor   # macOS
.\.venv\Scripts\python -m mimicry selftest    # proves the neural model runs; prints its speed
```
`doctor` lists what's installed, whether a virtual mic was detected, and the exact microphone name to choose in your call app.
Fix anything marked `[--]` before continuing.

### Model files (131 MB OpenVoice voice model)
Downloaded automatically from Hugging Face (`myshell-ai/OpenVoiceV2`) into `third_party/OpenVoice/checkpoints_v2/converter/`.
MyShell's old S3 download links are dead - don't use them. If the automatic download fails, open
https://huggingface.co/myshell-ai/OpenVoiceV2/tree/main/converter, download `checkpoint.pth` and `config.json`, and put both in that folder.

**pip printed "dependency conflicts" for `myshell-openvoice`?** Those are warnings about OpenVoice's old pinned versions. The new installer
doesn't install that package at all; it uses the OpenVoice source directly.

## 3. Start the app

- **macOS:** double-click **`start.command`** (or `python -m mimicry ui` in the activated venv).
- **Windows:** double-click **`start.bat`** (or `python -m mimicry ui`).

Your browser opens at **http://127.0.0.1:8765**. The page only works on your own computer. Options: `--port 9000`, `--no-browser`.

**First run on macOS:** a permission pop-up appears – click **Allow** for the **browser** (recording in the page) and for **Terminal** (live audio). If you clicked "Don't Allow": System Settings → Privacy & Security → Microphone → switch it on, then restart the app.

## 4. Use it, step by step (in the UI)

The page has five cards. Work top to bottom the first time; afterwards you only need card 5.

### Step 1 – Record the target voice
1. Click **● Record** and read the on-screen text naturally (about 30–60 seconds; longer is better, up to 90 s). Speak at a normal pace and distance (15–20 cm from the mic).
2. Watch the **level bar**: green is good, yellow is loud, red means clipping – lower your input volume and redo.
3. Click **■ Stop**. A player appears so you can listen back, and a quality line shows duration, noise level (SNR) and peak. Warnings tell you if it's too short, too noisy or clipped – if so, record again.
4. Alternative: **Upload file…** and pick an existing recording (wav/mp3/m4a/flac). It must contain **only one speaker**, no music.

> The target must be your own voice, or someone's voice **with their permission**. If it's another person, they should be the one who speaks into the mic in this step.

### Step 2 – Record your own voice
Same as step 1, but it's **you** speaking in your normal voice (20–30 s is enough). The neural converter needs this to learn what "you" sound like. Skip it only if you accept the pitch-only fallback.

### Step 3 – Create the voice profile
1. Give the profile a name (letters, digits, `-`, `_`).
2. Read the consent statement and **tick the box** (the button stays disabled until you do).
3. Click **Create profile**. Your samples are cleaned automatically: low rumble removed, noise reduced, silences trimmed, level normalised. Building the voice embeddings can take up to a minute the first time.
4. A chip appears: **neural ready** (full voice conversion) or **pitch only** (neural model/your recording missing).

### Step 4 – Try it before going live
1. Choose the profile, click **● Record**, speak for ~8 seconds (say anything), click **■ Stop**.
2. After a moment the converted voice plays automatically. **Wear headphones** so the speakers don't feed back into the mic.
3. Read the result line: it shows the backend used and the **speed (× realtime)**. It must be **below 1.0×** for live use. If it's higher, you need a GPU or a larger chunk size (the agent handles this live, but expect more delay).
4. Not happy with the sound? Re-record step 1 with a quieter room / better mic / longer sample, and create the profile again.

### Step 5 – Go live and speak
1. **Your real microphone:** choose the mic you speak into (headset/laptop mic). Virtual devices are not offered here.
2. **Virtual microphone (output):** auto-selected (BlackHole 2ch / CABLE Input). Don't change it unless you know why.
3. **Profile:** the voice to produce.
4. *(Optional)* tick **Also play the converted voice to my speaker/headphones** to hear what the other person hears. Use headphones.
5. Click **Start**. The page shows "Loading the voice model…" for a few seconds, then **You're live**, with the exact microphone name for your call app, live meters, latency, load and the agent's activity log.
6. **Speak.** The "Your mic" meter moves with your voice and the "Converted output" meter follows about half a second later.

### Use it in a call (Teams, Zoom, Meet, WhatsApp, …)
Start Mimicry (step 5) **first**, then in the call app:

| | Microphone (input) | Speaker (output) |
|---|---|---|
| macOS | **BlackHole 2ch** | your normal speakers/headphones – **not** BlackHole |
| Windows | **CABLE Output (VB-Audio Virtual Cable)** | your normal speakers/headphones – **not** CABLE |

- Teams: Settings → Devices → Microphone. Zoom: Settings → Audio → Microphone. Meet: ⋮ → Settings → Audio.
- Turn **off** the call app's noise suppression / "automatic microphone adjustment" if the voice sounds thin; the converted audio is already clean.
- Check it works **before** an important call: use the call app's *mic test*, a *test call*, or join a call from your phone and listen. You should hear only the target voice.
- To stop: click **Stop** on the page (or close the app). Then set the call app's microphone back to your real mic.

## 5. What the agents do

| Agent | Job |
|---|---|
| **Planner** | Finds your real mic and the virtual mic; refuses a virtual device as input; tells you what to select in the call app. |
| **Performance** | Watches load. Overloaded → bigger chunks → lighter backend. Spare capacity → smaller chunks, tries the better backend again. |
| **Reliability** | Reopens audio streams after a device is unplugged/changed; adds buffer when audio glitches. Retries at other sample rates if a device refuses 48 kHz. |
| **Safety** | If every conversion backend fails, output is **muted** – your real voice is never sent. |

All runs locally (no cloud, no audio leaves your computer). Events are logged to `logs/session-*.jsonl`.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Page says **virtual mic driver missing** | Install BlackHole / VB-CABLE, restart/reboot, reload the page. |
| Recording says "Microphone blocked" | Allow the microphone for the browser (macOS: System Settings → Privacy & Security → Microphone). |
| **Start** fails with a device error | macOS: allow Terminal in Privacy → Microphone. Pick the mic explicitly in the dropdown. Close other apps using the mic. |
| Other person hears silence | Call app mic is not set to BlackHole / CABLE Output; or Mimicry is muted (check the agent log for `muted`) – the neural model failed to load, see `doctor`. |
| Other person hears **your real voice** | The call app is using your real mic. Mimicry never forwards your real voice. |
| You hear echo / feedback | Turn off *monitor* or wear headphones; keep call-app speaker ≠ virtual device. |
| Robotic or choppy voice | Load ≥ 1.0 → GPU needed or increase chunk size; close heavy apps. Check "glitches" counter. |
| Voice doesn't sound like the target | Re-record the target: 30–60 s, quiet room, no music, one speaker, no noise-cancelling during recording. |
| `doctor`: `openvoice.api import failed` | Re-run the installer with `-Fresh` (Windows) / `--fresh` (Mac). |
| "pitch only" chip | Neural model/checkpoints missing or you skipped step 2. Run `doctor`, re-run the install script, record your own voice, recreate the profile. |
| Delay feels long | Latency ≈ chunk size + processing. A GPU gets ~0.5 s. Lower `hop_ms` in `config.json` (min ~200) if load is < 0.5. |

## 7. Command line (optional)

```
python -m mimicry                # opens the UI (same as `ui`)
python -m mimicry doctor         # environment check
python -m mimicry devices        # list audio devices
python -m mimicry record --seconds 30 --out me.wav
python -m mimicry enroll --target target.wav --source me.wav --name default   # asks for consent
python -m mimicry convert me.wav --out test.wav        # offline test of the live pipeline
python -m mimicry run --monitor  # live without the UI
```
Settings live in `config.json` (copy `config.example.json`): `hop_ms`, `backends`, `fail_mode`, `polish`, `input_device`, `output_device`, `torch_device`, …

## 8. Project layout

```
mimicry/
  ui/server.py, index.html     local web UI (token-protected, 127.0.0.1 only)
  agent.py                     Planner / Performance / Reliability / Safety agents
  engine.py, stream.py         live audio engine, chunked conversion with crossfade
  backends/                    openvoice (neural), pitch (CPU fallback), mute
  audio_clean.py               sample cleanup + output polish
  profile.py                   enrollment, quality checks, consent record
scripts/install.sh|ps1         installers      start.command | start.bat   launchers
tests/                         python -m pytest -q tests
```

## 9. Honest limitations
- The neural backend (OpenVoice v2) is wired to its public API, but was **not run** in the build environment; run step 4 first and report problems.
- Zero-shot cloning is approximate: it captures timbre well enough for calls, not perfectly. It outputs 22 kHz speech audio (fine for calls, not studio quality).
- Live input is not denoised (that would hurt conversion): use a decent mic.
- The live audio path was tested with simulated audio only, not on real Mac/Windows hardware yet.
- Different languages/accents and singing are not supported well.
