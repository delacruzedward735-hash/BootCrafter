#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
VERSION="$(PYTHONPATH="$ROOT" python3 -c 'from bootcrafter_linux import __version__; print(__version__)')"
./scripts/verify.sh
./scripts/build-deb.sh
printf '\nInstall or upgrade with:\n  sudo apt install ./dist/bootcrafter-linux_%s_all.deb\n' "$VERSION"
