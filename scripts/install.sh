#!/usr/bin/env bash
# Mimicry installer for macOS / Linux:  bash scripts/install.sh [--fresh] [--skip-neural]
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs; exec > >(tee logs/install.log) 2>&1
say() { printf '\n==> %s\n' "$*"; }
FRESH=0; SKIP=0
for a in "$@"; do case $a in --fresh) FRESH=1;; --skip-neural) SKIP=1;; esac; done

say "Looking for Python 3.10 - 3.12"
PY0=""
for c in python3.11 python3.10 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)'; then PY0=$(command -v "$c"); break; fi
done
[ -n "$PY0" ] || { echo "FAILED: need Python 3.10-3.12.  macOS: brew install python@3.11"; exit 1; }
echo "Using $PY0"

[ "$FRESH" = 1 ] && rm -rf .venv
{ [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys' ; } 2>/dev/null || { rm -rf .venv; "$PY0" -m venv .venv; }
PY=.venv/bin/python

say "Installing app packages"
$PY -m pip install --upgrade pip setuptools wheel
$PY -m pip install -r requirements.txt

if [ "$SKIP" = 0 ]; then
  say "Installing PyTorch (Apple Silicon uses the GPU via MPS)"
  $PY -m pip install torch
  $PY -m pip install -r requirements-neural.txt

  say "Getting OpenVoice source"
  mkdir -p third_party
  [ -f third_party/OpenVoice/openvoice/api.py ] || { rm -rf third_party/OpenVoice; git clone --depth 1 https://github.com/myshell-ai/OpenVoice third_party/OpenVoice; }

  say "Downloading the voice model (131 MB) from Hugging Face"
  $PY scripts/fetch_models.py

  say "Self-test: loading the model and converting a test signal"
  $PY -m mimicry selftest || echo "WARNING: neural self-test failed; the app still works in pitch-only mode. See logs/install.log"
fi

chmod +x start.command 2>/dev/null || true
if [ "$(uname)" = "Darwin" ]; then
  say "Virtual microphone"
  if command -v brew >/dev/null; then
    brew list blackhole-2ch >/dev/null 2>&1 || brew install blackhole-2ch
  else
    echo "Install Homebrew (https://brew.sh) then run: brew install blackhole-2ch"
  fi
  echo "Restart your Mac once after BlackHole installs, then double-click start.command."
  echo "First run: macOS asks to let your browser AND Terminal use the microphone - click Allow."
fi
say "Environment check"
$PY -m mimicry doctor
echo; echo "DONE."
