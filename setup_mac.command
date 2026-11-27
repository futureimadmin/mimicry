#!/bin/bash
# Mimicry - one-click Mac setup. Double-click in Finder (or: bash setup_mac.command [--fresh] [--skip-neural])
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine . 2>/dev/null || true      # allow files that came from a zip/download
chmod +x start.command doctor.command scripts/*.sh 2>/dev/null || true
bash scripts/install.sh "$@"
status=$?
echo
if [ $status -eq 0 ]; then echo "Setup finished."; else echo "Setup FAILED (exit $status). See logs/install.log"; fi
read -n 1 -s -r -p "Press any key to close this window"
exit $status
