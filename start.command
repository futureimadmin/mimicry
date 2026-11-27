#!/bin/bash
# macOS: double-click to start Mimicry (first time: chmod +x start.command)
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Run: bash scripts/install.sh first"; read -n1 -p "Press any key"; exit 1; }
. .venv/bin/activate
exec python -m mimicry ui
