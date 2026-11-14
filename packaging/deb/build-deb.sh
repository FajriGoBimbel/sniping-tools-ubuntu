#!/usr/bin/env bash
# Build dist/snipper_<version>_all.deb with dpkg-deb (no debhelper needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$ROOT/snipper/settings.py').read()).group(1))")"
APP=com.wahanacreative.Snipper
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
PKG="$BUILD/snipper_${VERSION}_all"

install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/snipper/icons" \
  "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/usr/share/metainfo"
cp -r "$ROOT/snipper" "$PKG/usr/share/snipper/snipper"
find "$PKG/usr/share/snipper" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$ROOT/data/icons/tools" "$PKG/usr/share/snipper/icons/tools"
cat > "$PKG/usr/bin/snipper" <<'SH'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/share/snipper")
from snipper.app import main
sys.exit(main())
SH
chmod 755 "$PKG/usr/bin/snipper"
install -m644 "$ROOT/data/$APP.desktop" "$PKG/usr/share/applications/"
install -m644 "$ROOT/data/icons/hicolor/scalable/apps/$APP.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/"
install -m644 "$ROOT/data/$APP.metainfo.xml" "$PKG/usr/share/metainfo/"

chmod -R u=rwX,go=rX "$PKG/usr"
SIZE="$(du -sk "$PKG/usr" | cut -f1)"
cat > "$PKG/DEBIAN/control" <<CTRL
Package: snipper
Version: $VERSION
Section: graphics
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-pango-1.0, gir1.2-gdkpixbuf-2.0, xdg-desktop-portal, xdg-desktop-portal-gnome | xdg-desktop-portal-gtk
Recommends: gnome-shell-extension-appindicator
Suggests: gnome-screenshot
Maintainer: Wahana Creative <dev@wahanacreative.example>
Description: Screenshot & annotation tool for Ubuntu
 Capture an area, a window or the full screen, then annotate it with
 rectangles, arrows, text, highlights, blur and step numbers before saving
 or copying to the clipboard. Works on Wayland and X11.
CTRL
cat > "$PKG/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
SH
cp "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/snipper_${VERSION}_all.deb" >/dev/null
echo "$ROOT/dist/snipper_${VERSION}_all.deb"
