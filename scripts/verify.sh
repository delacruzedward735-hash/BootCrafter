#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Python compile check"
python3 -m compileall -q bootcrafter_linux tests

echo "==> Unit tests"
python3 -m unittest discover -s tests -v

echo "==> Helper CLI check"
python3 -m bootcrafter_linux.helper --help >/dev/null
python3 -m bootcrafter_linux.helper write --help >/dev/null
python3 -m bootcrafter_linux.helper windows --help >/dev/null
python3 -m bootcrafter_linux.helper format --help >/dev/null

echo "==> Import/version check"
python3 - <<'PY'
from bootcrafter_linux import APP_NAME, __version__
from bootcrafter_linux.app import BootCrafterApp
assert APP_NAME == "BootCrafter Linux"
assert __version__ == "1.0.3"
assert BootCrafterApp.__name__ == "BootCrafterApp"
print(f"  {APP_NAME} {__version__}")
PY


echo "==> GUI layout/mode smoke test"
if command -v xvfb-run >/dev/null 2>&1; then
  PYTHONPATH="$ROOT" xvfb-run -a -s "-screen 0 1366x768x24" python3 scripts/ui-smoke.py
else
  echo "  [INFO] xvfb-run not installed; skipping GUI smoke test"
fi

echo "==> Asset checks"
python3 - <<'PY'
from pathlib import Path
import struct

def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    assert data[12:16] == b"IHDR", path
    return struct.unpack(">II", data[16:24])

root=Path('assets')
for size in (16,24,32,48,64,96,128,256,512):
    p=root/f'bootcrafter-linux-{size}.png'
    assert p.is_file(), p
    assert png_size(p)==(size,size), (p, png_size(p))
print("  launcher icons OK")
PY

printf '\nRuntime command availability in this build environment:\n'
for c in lsblk findmnt umount wipefs sfdisk mkfs.vfat mkfs.ext4 mount sync blockdev udevadm wimlib-imagex pkexec zstd; do
  if command -v "$c" >/dev/null 2>&1; then printf '  [OK] %s\n' "$c"; else printf '  [INFO] %s not installed here\n' "$c"; fi
done
