#!/usr/bin/env bash
# Mimicry installer for macOS (Apple Silicon + Intel). Also works on Linux.
#   bash scripts/install.sh [--fresh] [--skip-neural] [--yes]
#   --fresh        rebuild .venv from scratch      --skip-neural  app only (pitch-only voice, no big downloads)
#   --yes          don't ask before installing Homebrew
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs; exec > >(tee logs/install.log) 2>&1
say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nFAILED: %s\nFull log: %s/logs/install.log\n' "$*" "$(pwd)"; exit 1; }
FRESH=0; SKIP=0; YES=0
for a in "$@"; do case $a in --fresh) FRESH=1;; --skip-neural) SKIP=1;; --yes) YES=1;; esac; done
OS=$(uname -s); ARCH=$(uname -m)
ask() { [ "$YES" = 1 ] && return 0; local r; read -r -p "$1 [y/N] " r </dev/tty; [[ $r =~ ^[Yy] ]]; }
brew_env() { for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do if [ -x "$b" ]; then eval "$("$b" shellenv)"; return 0; fi; done; return 0; }

# ---- 1. macOS prerequisites ---------------------------------------------------------
if [ "$OS" = Darwin ]; then
  say "macOS $(sw_vers -productVersion) on $ARCH"
  if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    die "Apple's Command Line Tools are installing (a pop-up appeared). When it finishes, run this setup again."
  fi
  brew_env
  if ! command -v brew >/dev/null 2>&1; then
    ask "Homebrew (the macOS package manager) is needed for Python and the virtual microphone. Install it now?" \
      || die "Install Homebrew from https://brew.sh, then run this setup again."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew_env
    command -v brew >/dev/null 2>&1 || die "Homebrew installed but not on PATH. Open a NEW Terminal window and run this setup again."
  fi
fi

# ---- 2. Python 3.10-3.12 --------------------------------------------------------------
find_py() {
  local c p
  for c in python3.11 python3.10 python3.12 python3; do
    p=$(command -v "$c" 2>/dev/null || true)
    if [ -n "$p" ] && "$p" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then echo "$p"; return 0; fi
  done
  return 1
}
say "Looking for Python 3.10 - 3.12"
PY0=$(find_py || true)
if [ -z "$PY0" ] && [ "$OS" = Darwin ]; then say "Installing Python 3.11 with Homebrew"; brew install python@3.11; PY0=$(find_py || true); fi
[ -n "$PY0" ] || die "Python 3.10-3.12 not found. Install it (macOS: brew install python@3.11) and run again."
echo "Using $PY0 ($("$PY0" --version))"

# ---- 3. virtual environment -----------------------------------------------------------
[ "$FRESH" = 1 ] && rm -rf .venv
if ! { [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys' ; } 2>/dev/null; then rm -rf .venv; say "Creating .venv"; "$PY0" -m venv .venv; fi
PY=.venv/bin/python
say "Installing app packages"
$PY -m pip install --upgrade pip setuptools wheel
$PY -m pip install -r requirements.txt

# ---- 4. neural voice model --------------------------------------------------------------
if [ "$SKIP" = 0 ]; then
  if [ "$OS" = Darwin ] && [ "$ARCH" = x86_64 ]; then TORCH="torch==2.2.2"; else TORCH="torch"; fi   # PyTorch has no newer Intel-Mac builds
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

# ---- 5. virtual microphone ---------------------------------------------------------------
NEED_RESTART=0
if [ "$OS" = Darwin ]; then
  say "Virtual microphone (BlackHole 2ch)"
  if ls /Library/Audio/Plug-Ins/HAL 2>/dev/null | grep -qi blackhole; then
    echo "BlackHole already installed."
  else
    echo "Installing BlackHole - macOS will ask for your password."
    brew install --cask blackhole-2ch || echo "WARNING: BlackHole install failed. Install it manually from https://existential.audio/blackhole/"
    NEED_RESTART=1
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
