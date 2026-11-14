#!/usr/bin/env bash
# Install Snipper for the current user (no root): ~/.local/{bin,share}
# Usage: ./install.sh            install
#        ./install.sh --uninstall
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP=com.wahanacreative.Snipper
LIB="$PREFIX/share/snipper"

if [[ "${1:-}" == "--uninstall" ]]; then
  "$PREFIX/bin/snipper" --remove-shortcuts 2>/dev/null || true
  rm -rf "$LIB" "$PREFIX/bin/snipper" \
    "$PREFIX/share/applications/$APP.desktop" \
    "$PREFIX/share/icons/hicolor/scalable/apps/$APP.svg" \
    "$PREFIX/share/metainfo/$APP.metainfo.xml"
  gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true
  update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
  echo "Snipper dihapus."
  exit 0
fi

python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa
PY

mkdir -p "$LIB" "$PREFIX/bin" "$PREFIX/share/applications" \
  "$PREFIX/share/icons/hicolor/scalable/apps" "$PREFIX/share/metainfo"
rm -rf "$LIB/snipper" "$LIB/icons"
cp -r "$SRC/snipper" "$LIB/snipper"
find "$LIB/snipper" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$LIB/icons"
cp -r "$SRC/data/icons/tools" "$LIB/icons/tools"
cat > "$PREFIX/bin/snipper" <<SH
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$LIB")
from snipper.app import main
sys.exit(main())
SH
chmod +x "$PREFIX/bin/snipper"
sed "s|^Exec=snipper|Exec=$PREFIX/bin/snipper|" "$SRC/data/$APP.desktop" > "$PREFIX/share/applications/$APP.desktop"
cp "$SRC/data/icons/hicolor/scalable/apps/$APP.svg" "$PREFIX/share/icons/hicolor/scalable/apps/"
cp "$SRC/data/$APP.metainfo.xml" "$PREFIX/share/metainfo/"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

echo "Snipper terpasang di $PREFIX/bin/snipper"
echo "Pasang shortcut Print Screen:  snipper --install-shortcuts"
