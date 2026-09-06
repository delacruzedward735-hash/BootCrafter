#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(PYTHONPATH="$ROOT" python3 -c 'from bootcrafter_linux import __version__; print(__version__)')"
DEB="${1:-$ROOT/dist/bootcrafter-linux_${VERSION}_all.deb}"
[ -f "$DEB" ] || { echo "Package not found: $DEB" >&2; exit 2; }
TMP="$(mktemp -d /tmp/bootcrafter-package-audit.XXXXXX)"
trap 'rm -rf "$TMP" /tmp/bootcrafter-audit-cwd-marker' EXIT
mkdir -p "$TMP/root/DEBIAN"
dpkg-deb -x "$DEB" "$TMP/root"
dpkg-deb -e "$DEB" "$TMP/root/DEBIAN"

echo "==> Control metadata"
grep -q '^Package: bootcrafter-linux$' "$TMP/root/DEBIAN/control"
grep -q "^Version: ${VERSION}$" "$TMP/root/DEBIAN/control"
depends="$(sed -n 's/^Depends: //p' "$TMP/root/DEBIAN/control")"
case ",$depends," in *", pkexec,"*|*",pkexec,"*) ;; *) echo "pkexec dependency missing" >&2; exit 1;; esac
if grep -q 'policykit-1' "$TMP/root/DEBIAN/control"; then echo "obsolete policykit-1 dependency remains" >&2; exit 1; fi

echo "==> Permissions"
if find "$TMP/root" \( -perm -0002 -o -perm -4000 -o -perm -2000 \) -print | grep -q .; then
  echo "Unsafe world-writable/setuid/setgid package path" >&2
  exit 1
fi

echo "==> Shell syntax"
for f in "$TMP/root/usr/bin/bootcrafter-linux" "$TMP/root/usr/lib/bootcrafter-linux/bootcrafter-helper" "$TMP/root/DEBIAN/postinst" "$TMP/root/DEBIAN/postrm"; do
  sh -n "$f"
done

echo "==> Isolated Python wrappers"
grep -q '/usr/bin/python3 -I -S -c' "$TMP/root/usr/bin/bootcrafter-linux"
grep -q '/usr/bin/python3 -I -S -c' "$TMP/root/usr/lib/bootcrafter-linux/bootcrafter-helper"

# Simulate the helper import path from an attacker-writable cwd. The installed
# wrapper uses /usr/lib; for extraction-only auditing we substitute the staged
# package path while keeping the same isolated Python flags.
ATTACK="$TMP/attacker"
mkdir -p "$ATTACK"
cat > "$ATTACK/argparse.py" <<'PY'
from pathlib import Path
Path('/tmp/bootcrafter-audit-cwd-marker').write_text('executed')
raise RuntimeError('cwd import hijack')
PY
rm -f /tmp/bootcrafter-audit-cwd-marker
(
  cd "$ATTACK"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8 PKEXEC_UID=1000 \
    /usr/bin/python3 -I -S -c "import sys; sys.path.insert(0,'$TMP/root/usr/lib/bootcrafter-linux'); from bootcrafter_linux.helper import main; raise SystemExit(main(sys.argv[1:]))" --help >/dev/null
)
[ ! -e /tmp/bootcrafter-audit-cwd-marker ] || { echo "cwd Python import hijack detected" >&2; exit 1; }

echo "==> Installed-layout Python"
/usr/bin/python3 -I -S -c "import sys; sys.path.insert(0,'$TMP/root/usr/lib/bootcrafter-linux'); import bootcrafter_linux; from bootcrafter_linux.helper import parser; assert bootcrafter_linux.__version__ == '$VERSION'; parser()"

echo "==> PolicyKit action"
python3 - "$TMP/root/usr/share/polkit-1/actions/io.bootcrafter.Linux.policy" <<'PY'
import sys, xml.etree.ElementTree as ET
root=ET.parse(sys.argv[1]).getroot()
a=root.find("./action[@id='io.bootcrafter.Linux.helper']")
assert a is not None
ann={x.attrib.get('key'):(x.text or '').strip() for x in a.findall('annotate')}
assert ann.get('org.freedesktop.policykit.exec.path') == '/usr/lib/bootcrafter-linux/bootcrafter-helper'
PY

echo "Package audit: PASS"
