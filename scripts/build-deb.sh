#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(PYTHONPATH="$ROOT" python3 -c 'from bootcrafter_linux import __version__; print(__version__)')"
ARCH="all"
PKG="bootcrafter-linux"
BUILD="$(mktemp -d /tmp/${PKG}_${VERSION}_${ARCH}.XXXXXX)"
OUT="$ROOT/dist"
trap 'rm -rf "$BUILD"' EXIT
chmod 0755 "$BUILD"
mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/bin" "$BUILD/usr/lib/bootcrafter-linux/bootcrafter_linux" \
         "$BUILD/usr/share/applications" "$BUILD/usr/share/polkit-1/actions" \
         "$BUILD/usr/share/doc/$PKG" "$OUT"
chmod 0755 "$BUILD/DEBIAN"
cp -a "$ROOT/bootcrafter_linux/." "$BUILD/usr/lib/bootcrafter-linux/bootcrafter_linux/"
find "$BUILD/usr/lib/bootcrafter-linux/bootcrafter_linux" -type d -name __pycache__ -prune -exec rm -rf {} +

cat > "$BUILD/usr/bin/bootcrafter-linux" <<'EOS'
#!/bin/sh
# Isolated Python startup prevents current-directory/user-site modules from
# shadowing the installed application or standard library. Desktop session
# variables (DISPLAY, DBUS, XAUTHORITY, theme settings) remain available.
exec /usr/bin/python3 -I -S -c 'import sys; sys.path.insert(0,"/usr/lib/bootcrafter-linux"); from bootcrafter_linux.app import main; raise SystemExit(main())' "$@"
EOS
cat > "$BUILD/usr/lib/bootcrafter-linux/bootcrafter-helper" <<'EOS'
#!/bin/sh
# Run the privileged helper with a minimal environment so user-controlled
# PYTHONPATH/PYTHONHOME/PATH values cannot affect root code execution.
exec /usr/bin/env -i \
  PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  LC_ALL=C.UTF-8 \
  PKEXEC_UID="${PKEXEC_UID:-}" \
  /usr/bin/python3 -I -S -c 'import sys; sys.path.insert(0,"/usr/lib/bootcrafter-linux"); from bootcrafter_linux.helper import main; raise SystemExit(main(sys.argv[1:]))' "$@"
EOS
chmod 0755 "$BUILD/usr/bin/bootcrafter-linux" "$BUILD/usr/lib/bootcrafter-linux/bootcrafter-helper"

cp "$ROOT/assets/bootcrafter-linux.desktop" "$BUILD/usr/share/applications/"
cp "$ROOT/assets/io.bootcrafter.Linux.policy" "$BUILD/usr/share/polkit-1/actions/"
for size in 16 24 32 48 64 96 128 256 512; do
  dir="$BUILD/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dir"
  cp "$ROOT/assets/bootcrafter-linux-${size}.png" "$dir/bootcrafter-linux.png"
done
cp "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/NOTICE.md" "$ROOT/CHANGELOG.md" "$BUILD/usr/share/doc/$PKG/"

cat > "$BUILD/DEBIAN/control" <<EOF2
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: CodeDev by Edward
Homepage: https://bootcrafter-linux.vercel.app
Vcs-Browser: https://github.com/delacruzedward735-hash/BootCrafter
Vcs-Git: https://github.com/delacruzedward735-hash/BootCrafter.git
Depends: python3 (>= 3.10), python3-tk, util-linux, fdisk, pkexec, dosfstools, e2fsprogs, mount, coreutils
Recommends: wimtools, exfatprogs, ntfs-3g, zstd
Description: Linux bootable USB creator with verification and Windows UEFI support
 BootCrafter Linux safely writes ISO/IMG/raw images to removable USB drives,
 verifies written bytes, creates Windows UEFI installer media, and can
 repartition/format removable drives.
EOF2
cat > "$BUILD/DEBIAN/postinst" <<'EOS'
#!/bin/sh
set -e
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q /usr/share/icons/hicolor || true; fi
exit 0
EOS
cat > "$BUILD/DEBIAN/postrm" <<'EOS'
#!/bin/sh
set -e
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q /usr/share/icons/hicolor || true; fi
exit 0
EOS
chmod 0755 "$BUILD/DEBIAN/postinst" "$BUILD/DEBIAN/postrm"
find "$BUILD" -type d -exec chmod g-s {} +
find "$BUILD" -type d -exec chmod 0755 {} +
find "$BUILD" -type f -exec chmod 0644 {} +
chmod 0755 "$BUILD/DEBIAN/postinst" "$BUILD/DEBIAN/postrm" "$BUILD/usr/bin/bootcrafter-linux" "$BUILD/usr/lib/bootcrafter-linux/bootcrafter-helper"

dpkg-deb --build --root-owner-group "$BUILD" "$OUT/${PKG}_${VERSION}_${ARCH}.deb"
echo "Built: $OUT/${PKG}_${VERSION}_${ARCH}.deb"
