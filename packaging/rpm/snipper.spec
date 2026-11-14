# Built by packaging/rpm/build-rpm.sh (pass --define "pkgversion X.Y.Z")
Name:           snipper
Version:        %{pkgversion}
Release:        1%{?dist}
Summary:        Screenshot & annotation tool
License:        MIT
URL:            https://github.com/FajriGoBimbel/sniping-tools-ubuntu
Source0:        snipper-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4
Requires:       libadwaita
Requires:       pango
Requires:       gdk-pixbuf2
Requires:       xdg-desktop-portal
Requires:       (xdg-desktop-portal-gnome or xdg-desktop-portal-gtk or xdg-desktop-portal-kde)
Recommends:     gnome-shell-extension-appindicator

%description
Capture an area, a window or the full screen, then annotate it with
rectangles, arrows, text, highlights, blur and step numbers before saving
or copying to the clipboard. Works on Wayland and X11.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/snipper/icons %{buildroot}%{_bindir}
cp -r snipper %{buildroot}%{_datadir}/snipper/snipper
find %{buildroot}%{_datadir}/snipper -name __pycache__ -prune -exec rm -rf {} +
cp -r data/icons/tools %{buildroot}%{_datadir}/snipper/icons/tools
cat > %{buildroot}%{_bindir}/snipper <<'PY'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/share/snipper")
from snipper.app import main
sys.exit(main())
PY
chmod 0755 %{buildroot}%{_bindir}/snipper
install -Dm0644 data/com.wahanacreative.Snipper.desktop %{buildroot}%{_datadir}/applications/com.wahanacreative.Snipper.desktop
install -Dm0644 data/icons/hicolor/scalable/apps/com.wahanacreative.Snipper.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/com.wahanacreative.Snipper.svg
install -Dm0644 data/com.wahanacreative.Snipper.metainfo.xml %{buildroot}%{_metainfodir}/com.wahanacreative.Snipper.metainfo.xml
%py_byte_compile %{python3} %{buildroot}%{_datadir}/snipper/snipper

%files
%license LICENSE
%{_bindir}/snipper
%{_datadir}/snipper/
%{_datadir}/applications/com.wahanacreative.Snipper.desktop
%{_datadir}/icons/hicolor/scalable/apps/com.wahanacreative.Snipper.svg
%{_metainfodir}/com.wahanacreative.Snipper.metainfo.xml

%changelog
* Sat Nov 14 2026 Wahana Creative - 0.1.0-1
- First RPM release
