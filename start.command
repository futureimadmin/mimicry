#!/bin/bash
# macOS: double-click to start Mimicry (opens the UI in your browser)
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then echo "Not installed yet. Double-click setup_mac.command first."; read -n 1 -s -r -p "Press any key"; exit 1; fi
export PYTORCH_ENABLE_MPS_FALLBACK=1
.venv/bin/python -m mimicry ui
status=$?
[ $status -ne 0 ] && { echo "Mimicry stopped with an error (exit $status)."; read -n 1 -s -r -p "Press any key to close"; }
exit $status
