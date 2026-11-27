#!/bin/bash
# macOS: double-click to check the install (devices, virtual mic, neural model speed)
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { echo "Not installed yet. Double-click setup_mac.command first."; read -n 1 -s -r -p "Press any key"; exit 1; }
export PYTORCH_ENABLE_MPS_FALLBACK=1
.venv/bin/python -m mimicry doctor
echo; echo "--- neural self-test ---"
.venv/bin/python -m mimicry selftest
echo; read -n 1 -s -r -p "Press any key to close"
