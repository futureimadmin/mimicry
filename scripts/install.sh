#!/usr/bin/env bash
# Mimicry installer for macOS (Apple Silicon + Intel). Also works on Linux. NO Homebrew needed.
#   bash scripts/install.sh [--fresh] [--skip-neural]
#   --fresh        rebuild .venv from scratch      --skip-neural  app only (pitch-only voice, no big downloads)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs; exec > >(tee logs/install.log) 2>&1
say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nFAILED: %s\nFull log: %s/logs/install.log\n' "$*" "$(pwd)"; exit 1; }
FRESH=0; SKIP=0
for a in "$@"; do case $a in --fresh) FRESH=1;; --skip-neural) SKIP=1;; esac; done
OS=$(uname -s); ARCH=$(uname -m)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# ---- 1. macOS prerequisite: Apple command-line tools (gives git) -----------------------------
if [ "$OS" = Darwin ]; then
  say "macOS $(sw_vers -productVersion) on $ARCH"
  if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    die "Apple's Command Line Tools are installing (a pop-up appeared). When it finishes, run this setup again."
  fi
fi

# ---- 2. Python 3.10-3.12 (uses what you have; otherwise installs a private copy with 'uv') ---------
find_py() {
  local c p
  for c in python3.11 python3.10 python3.12 python3 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
    p=$(command -v "$c" 2>/dev/null || true)
    if [ -n "$p" ] && "$p" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then echo "$p"; return 0; fi
  done
  return 1
}
say "Looking for Python 3.10 - 3.12"
PY0=$(find_py || true)
if [ -z "$PY0" ]; then
  say "Not found - installing a private Python 3.11 with uv (no Homebrew, no admin password)"
  if ! command -v uv >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh || die "could not install uv (check your internet connection)"; fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  uv python install 3.11 || die "uv could not install Python 3.11"
  PY0=$(uv python find 3.11 || true)
fi
[ -n "$PY0" ] || die "Python 3.10-3.12 not found. Install Python 3.11 from https://www.python.org/downloads/macos/ and run again."
echo "Using $PY0 ($("$PY0" --version))"

# ---- 3. virtual environment -------------------------------------------------------------------------
[ "$FRESH" = 1 ] && rm -rf .venv
if ! { [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys' ; } 2>/dev/null; then rm -rf .venv; say "Creating .venv"; "$PY0" -m venv .venv; fi
PY=.venv/bin/python
say "Installing app packages"
$PY -m pip install --upgrade pip setuptools wheel
$PY -m pip install -r requirements.txt

# ---- 4. neural voice model ----------------------------------------------------------------------------
if [ "$SKIP" = 0 ]; then
  if [ "$OS" = Darwin ] && [ "$ARCH" = x86_64 ]; then TORCH="torch==2.2.2"; else TORCH="torch"; fi   # newest PyTorch has no Intel-Mac build
  say "Installing PyTorch ($TORCH) - Apple Silicon uses the GPU through MPS"
  $PY -m pip install "$TORCH"
  $PY -m pip install -r requirements-neural.txt

  say "Getting OpenVoice source"
  mkdir -p third_party
  [ -f third_party/OpenVoice/openvoice/api.py ] || { rm -rf third_party/OpenVoice; git clone --depth 1 https://github.com/myshell-ai/OpenVoice third_party/OpenVoice; }
  [ -f third_party/OpenVoice/openvoice/api.py ] || die "OpenVoice source is incomplete in third_party/OpenVoice"

  say "Downloading the voice model (131 MB) from Hugging Face"
  $PY scripts/fetch_models.py || die "model download failed - see the manual steps printed above"

  say "Self-test: loading the model and converting a test signal"
  $PY -m mimicry selftest || echo "WARNING: neural self-test failed; the app still works in pitch-only mode. Send logs/install.log to support."
fi

# ---- 5. virtual microphone: BlackHole 2ch (direct installer, no Homebrew) ---------------------------------
NEED_RESTART=0
if [ "$OS" = Darwin ]; then
  say "Virtual microphone (BlackHole 2ch)"
  if ls /Library/Audio/Plug-Ins/HAL 2>/dev/null | grep -qi blackhole; then
    echo "BlackHole already installed."
  else
    BH_URL="https://existential.audio/downloads/BlackHole2ch-0.6.1.pkg"
    TMPD=$(mktemp -d)
    if curl -fL --retry 2 -o "$TMPD/BlackHole2ch.pkg" "$BH_URL"; then
      echo "Installing BlackHole - macOS will ask for your password."
      if sudo installer -pkg "$TMPD/BlackHole2ch.pkg" -target /; then NEED_RESTART=1; else echo "WARNING: BlackHole installer failed."; fi
    else
      echo "Could not download BlackHole automatically. Opening the download page - install 'BlackHole 2ch' from it,"
      echo "then restart your Mac."
      open "https://existential.audio/blackhole/" || true
      NEED_RESTART=1
    fi
    rm -rf "$TMPD"
  fi
fi

chmod +x start.command doctor.command setup_mac.command 2>/dev/null || true
say "Environment check"
$PY -m mimicry doctor || true

echo; echo "DONE."
if [ "$OS" = Darwin ]; then
  [ "$NEED_RESTART" = 1 ] && echo "-> RESTART YOUR MAC once now (BlackHole is an audio driver)."
  echo "-> Then double-click start.command. The first time, macOS asks to let Terminal and your browser use the microphone: click Allow."
fi
