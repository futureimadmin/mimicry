# Mimicry on Mac – quick start

Works on Apple Silicon (M1–M4) and Intel Macs, macOS 12+. Apple Silicon is much faster (uses the Apple GPU).

## 1. Install (once, ~15–30 min, mostly downloads)
1. Download/clone the repo and open the folder in Finder.
2. Double-click **`setup_mac.command`** (blocked? right-click → Open → Open).
3. Answer the prompts: Xcode command-line tools (a pop-up – click Install, then run setup again) and your Mac password (for the BlackHole driver). **No Homebrew needed** – Homebrew has largely dropped Intel Macs, so this setup doesn't use it.
4. When it prints `NEURAL SELFTEST OK … speed=… x realtime` and `DONE`, **restart your Mac**.

The script is safe to re-run. Rebuild from scratch with `bash scripts/install.sh --fresh`. App-only (no big downloads, pitch-only voice): `--skip-neural`.

## 2. Run
Double-click **`start.command`** → browser opens `http://127.0.0.1:8765`.
First run macOS asks **"Terminal would like to access the microphone"** and the browser asks too → **Allow** both.
(Missed it? System Settings → Privacy & Security → Microphone → switch on Terminal and your browser.)

## 3. Use (in the page)
1. Record the **target voice** (30–60 s, read the on-screen text) → 2. record **your voice** → 3. tick consent, **Create profile**
→ 4. **Try it** (headphones on) → 5. **Start**.

## 4. In your call app (Teams / Zoom / Meet / WhatsApp …)
Set **Microphone = BlackHole 2ch**. Keep **Speaker = your normal speakers/headphones** (never BlackHole).
Start Mimicry first, then open/refresh the call app's audio settings.

## 5. If something's wrong
| Problem | Fix |
|---|---|
| Double-click does nothing / "can't be opened" | Right-click → Open, or `cd` into the folder and run `bash setup_mac.command` |
| `doctor.command` shows `[--] virtual mic driver` | Restart the Mac after the install; or install "BlackHole 2ch" manually from https://existential.audio/blackhole/ |
| No sound to the other person | Call app mic must be **BlackHole 2ch**; check the Mimicry page says *You're live* and the output meter moves |
| Page says "Microphone blocked" | System Settings → Privacy & Security → Microphone → allow your browser and Terminal |
| Choppy / robotic | Close heavy apps; check **load < 1.0** on the page. Intel Macs are slow – expect pitch-only fallback |
| Echo | Use headphones; untick "monitor" |
| Anything else | Double-click **`doctor.command`** and send me the output + `logs/install.log` |

Intel Macs: PyTorch no longer ships newer Intel-Mac builds, so the installer uses torch 2.2.2 there. It works but is slow; use `--skip-neural` if it can't keep up.

## Uninstall
Delete the folder. To remove the driver, use the BlackHole 2ch uninstaller from https://existential.audio/blackhole/.
