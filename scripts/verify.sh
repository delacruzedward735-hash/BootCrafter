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

echo "==> Broken progress-pipe resilience check"
set +e
PYTHONPATH="$ROOT" python3 -c 'from bootcrafter_linux.operations import emit; [emit("progress", bytes=i) for i in range(10000)]' | head -n0
pipe_codes=("${PIPESTATUS[@]}")
set -e
test "${pipe_codes[0]}" -eq 0
echo "  helper progress pipe can disappear without changing operation exit status"

echo "==> Import/version check"
python3 - <<'PY'
from bootcrafter_linux import APP_NAME, __version__
from bootcrafter_linux.app import BootCrafterApp
assert APP_NAME == "BootCrafter Linux"
assert __version__ == "1.0.5"
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

echo "==> PolicyKit policy check"
python3 - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
p=Path('assets/io.bootcrafter.Linux.policy')
root=ET.parse(p).getroot()
action=root.find("./action[@id='io.bootcrafter.Linux.helper']")
assert action is not None
annotations={a.attrib.get('key'): (a.text or '').strip() for a in action.findall('annotate')}
assert annotations.get('org.freedesktop.policykit.exec.path') == '/usr/lib/bootcrafter-linux/bootcrafter-helper'
print('  PolicyKit action/path OK')
PY

echo "==> Privilege-boundary static checks"
python3 - <<'PY'
from pathlib import Path
source='\n'.join(p.read_text(errors='ignore') for p in Path('bootcrafter_linux').glob('*.py'))
for forbidden in ('shell=True', 'os.system(', 'subprocess.call(', 'eval(', 'exec('):
    assert forbidden not in source, forbidden
assert 'shutil.which' not in source, 'user PATH lookup remains in privileged/runtime code'
assert 'TemporaryDirectory(prefix="bootcrafter-")' not in source, 'recursive mount cleanup pattern returned'
build=Path('scripts/build-deb.sh').read_text(errors='ignore')
assert '/usr/bin/python3 -I -S -c' in build, 'privileged Python is not isolated from cwd/site imports'
control_line=next(line for line in build.splitlines() if line.startswith('Depends:'))
assert 'pkexec' in control_line, 'modern pkexec package dependency missing'
assert 'policykit-1' not in control_line, 'obsolete/transitional policykit-1 dependency remains'
print('  no shell execution, PATH lookup, dynamic eval/exec, recursive mount cleanup, or privileged cwd imports')
PY

if [ "$(id -u)" -eq 0 ]; then
  echo "==> Root GUI refusal check"
  set +e
  PYTHONPATH="$ROOT" python3 -m bootcrafter_linux >/tmp/bootcrafter-root-gui.out 2>&1
  code=$?
  set -e
  test "$code" -eq 2
  grep -q 'must be launched as a normal desktop user' /tmp/bootcrafter-root-gui.out
  rm -f /tmp/bootcrafter-root-gui.out
  echo "  root GUI refused as designed"
fi

printf '\nRuntime command availability in this build environment:\n'
for c in lsblk findmnt umount wipefs sfdisk mkfs.vfat mkfs.ext4 mount sync blockdev udevadm wimlib-imagex pkexec zstd; do
  if command -v "$c" >/dev/null 2>&1; then printf '  [OK] %s\n' "$c"; else printf '  [INFO] %s not installed here\n' "$c"; fi
done
