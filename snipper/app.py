"""Application: command line, capture orchestration, launcher window, tray."""
from __future__ import annotations

import os
import shlex
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import capture, shortcuts  # noqa: E402
from .document import crop_surface, load_image  # noqa: E402
from .settings import APP_ID, APP_NAME, VERSION, Settings  # noqa: E402

CSS = b"""
.snipper-stage { background-color: alpha(currentColor, 0.07); }
.snipper-overlay { background: black; }
.snipper-big-button { padding: 14px 18px; }
.snipper-big-button image { -gtk-icon-size: 32px; }
"""


def data_dir():
    candidates = [
        os.environ.get("SNIPPER_DATA_DIR"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
        "/app/share/snipper",
        "/usr/local/share/snipper",
        "/usr/share/snipper",
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "icons")):
            return c
    return None


class LauncherWindow(Adw.ApplicationWindow):
    """Small window shown when Snipper is started without a capture flag."""

    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_default_size(460, -1)
        self.set_resizable(False)

        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Buka gambar…", "app.open")
        menu.append("Preferensi", "app.preferences")
        menu.append("Tentang Snipper", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=18,
                       margin_start=18, margin_end=18)

        self.perm_box = self._permission_box()
        body.append(self.perm_box)

        buttons = Gtk.Box(spacing=8, homogeneous=True)
        for mode, icon, label in (
            ("area", "snipper-crop-symbolic", "Area"),
            ("full", "snipper-screen-symbolic", "Layar penuh"),
            ("window", "snipper-window-symbolic", "Jendela"),
        ):
            b = Gtk.Button()
            b.add_css_class("snipper-big-button")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            inner.append(Gtk.Image(icon_name=icon))
            inner.append(Gtk.Label(label=label))
            b.set_child(inner)
            b.connect("clicked", lambda _b, m=mode: self.app.capture(m, self.delay()))
            buttons.append(b)
        body.append(buttons)

        delay_row = Gtk.Box(spacing=8)
        delay_row.append(Gtk.Label(label="Delay", xalign=0, hexpand=True))
        self.delay_dd = Gtk.DropDown.new_from_strings(["Tanpa delay", "3 detik", "5 detik", "10 detik"])
        d = app.settings["default_delay"]
        self.delay_dd.set_selected([0, 3, 5, 10].index(d) if d in (0, 3, 5, 10) else 0)
        delay_row.append(self.delay_dd)
        body.append(delay_row)

        acc = app.settings["shortcuts"]
        if shortcuts.installed():
            hint = (f"Shortcut: {self._fmt(acc.get('area'))} area · {self._fmt(acc.get('full'))} layar penuh · "
                    f"{self._fmt(acc.get('window'))} jendela")
        else:
            hint = "Tip: pasang shortcut Print Screen di Preferensi."
        hl = Gtk.Label(label=hint, wrap=True, xalign=0)
        hl.add_css_class("dim-label")
        hl.add_css_class("caption")
        body.append(hl)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(body)
        self.set_content(box)

    @staticmethod
    def _fmt(accel):
        if not accel:
            return "—"
        res = Gtk.accelerator_parse(accel)
        key, mods = (res[1], res[2]) if len(res) == 3 else res
        return Gtk.accelerator_get_label(key, mods) if key else accel

    def delay(self):
        return [0, 3, 5, 10][self.delay_dd.get_selected()]

    def _permission_box(self):
        box = Gtk.Box(spacing=8)
        box.add_css_class("card")
        box.set_visible(False)
        inner = Gtk.Box(spacing=10, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        lbl = Gtk.Label(
            label="Izinkan Snipper mengambil screenshot langsung tanpa dialog GNOME setiap kali.",
            wrap=True, xalign=0, hexpand=True,
        )
        btn = Gtk.Button(label="Izinkan", valign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self.app.request_permission(self))
        inner.append(lbl)
        inner.append(btn)
        box.append(inner)
        if self.app.use_portal and capture.has_screenshot_permission(APP_ID) is not True:
            box.set_visible(True)
        return box


class SnipperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name(APP_NAME)
        self.settings = Settings()
        self.use_portal = True
        self._busy = False
        self._hidden = []
        self._clip_hold = False
        self._clip_timer = 0
        self._background = False
        self.tray = None
        self._add_options()

    # ------------------------------------------------------------ startup
    def _add_options(self):
        O = GLib.OptionFlags.NONE
        A = GLib.OptionArg
        opts = [
            ("area", ord("a"), A.NONE, "Capture area (pilih dengan drag)", None),
            ("full", ord("f"), A.NONE, "Capture layar penuh", None),
            ("window", ord("w"), A.NONE, "Capture jendela", None),
            ("delay", ord("d"), A.INT, "Tunda capture N detik", "N"),
            ("monitor", ord("m"), A.INT, "Layar penuh: hanya monitor N (mulai dari 1, 0 = semua)", "N"),
            ("open", ord("o"), A.FILENAME, "Buka gambar di editor", "FILE"),
            ("background", ord("b"), A.NONE, "Tetap berjalan di latar dengan ikon tray", None),
            ("install-shortcuts", 0, A.NONE, "Pasang shortcut global (Print Screen)", None),
            ("remove-shortcuts", 0, A.NONE, "Lepas shortcut global dan pulihkan bawaan GNOME", None),
            ("version", ord("v"), A.NONE, "Tampilkan versi", None),
        ]
        for long, short, arg, desc, arg_desc in opts:
            self.add_main_option(long, short, O, arg, desc, arg_desc)

    def do_handle_local_options(self, options):
        if options.contains("version"):
            print(f"{APP_NAME} {VERSION}")
            return 0
        if options.contains("install-shortcuts"):
            try:
                shortcuts.install(self.launch_command(), self.settings["shortcuts"])
                print("Shortcut global terpasang:", self.settings["shortcuts"])
                return 0
            except Exception as e:  # noqa: BLE001
                print("Gagal memasang shortcut:", e, file=sys.stderr)
                return 1
        if options.contains("remove-shortcuts"):
            shortcuts.remove()
            print("Shortcut global dilepas, shortcut bawaan GNOME dipulihkan.")
            return 0
        return -1

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        ddir = data_dir()
        theme = Gtk.IconTheme.get_for_display(display)
        if ddir:
            theme.add_search_path(os.path.join(ddir, "icons", "tools"))
            theme.add_search_path(os.path.join(ddir, "icons"))
        css = Gtk.CssProvider()
        try:
            css.load_from_data(CSS, -1)
        except TypeError:
            css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name(APP_ID)

        self.use_portal = capture.portal_available()

        def act(name, cb, param=None):
            a = Gio.SimpleAction.new(name, param)
            a.connect("activate", cb)
            self.add_action(a)

        act("capture-area", lambda *_: self.capture("area"))
        act("capture-full", lambda *_: self.capture("full"))
        act("capture-window", lambda *_: self.capture("window"))
        act("open", lambda *_: self._open_dialog())
        act("preferences", lambda *_: self.show_preferences())
        act("about", lambda *_: self.show_about())
        act("quit", lambda *_: self.quit())

        accels = {
            "win.save": ["<Control>s"], "win.save-as": ["<Control><Shift>s"], "win.copy": ["<Control>c"],
            "win.undo": ["<Control>z"], "win.redo": ["<Control><Shift>z", "<Control>y"],
            "win.zoom-in": ["<Control>plus", "<Control>equal", "<Control>KP_Add"],
            "win.zoom-out": ["<Control>minus", "<Control>KP_Subtract"],
            "win.zoom-fit": ["<Control>0"], "win.zoom-100": ["<Control>1"],
            "win.close": ["<Control>w"], "app.quit": ["<Control>q"],
        }
        for action, keys in accels.items():
            self.set_accels_for_action(action, keys)

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        delay = opts.get("delay")
        monitor = opts.get("monitor")
        path = opts.get("open")
        if isinstance(path, (bytes, bytearray)):
            path = path.decode()
        args = [a for a in cmdline.get_arguments()[1:]]
        if not path and args:
            path = args[0]
        if path:
            f = cmdline.create_file_for_arg(path)
            self.open_file(f.get_path())
        elif "area" in opts:
            self.capture("area", delay)
        elif "full" in opts:
            self.capture("full", delay, monitor=monitor)
        elif "window" in opts:
            self.capture("window", delay)
        elif "background" in opts:
            self.start_background()
        else:
            self.show_launcher()
        return 0

    def do_activate(self):
        self.show_launcher()

    # ------------------------------------------------------------ helpers
    def launch_command(self):
        """Command line other processes (shortcuts, autostart) use to start Snipper."""
        if os.environ.get("FLATPAK_ID"):
            return f"flatpak run {APP_ID}"
        argv0 = os.path.realpath(sys.argv[0])
        if os.path.basename(argv0) in ("snipper", "snipper-run") and os.access(argv0, os.X_OK):
            # absolute: gnome-settings-daemon's PATH may not include ~/.local/bin
            return shlex.quote(argv0)
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return f"{shlex.quote(sys.executable)} {shlex.quote(os.path.join(pkg_parent, 'snipper-run'))}"

    def show_launcher(self):
        for w in self.get_windows():
            if isinstance(w, LauncherWindow):
                w.present()
                return
        LauncherWindow(self).present()

    def start_background(self):
        if self._background:
            return
        self._background = True
        self.hold()
        from .tray import Tray

        ddir = data_dir()
        theme_path = os.path.join(ddir, "icons") if ddir else ""
        self.tray = Tray(
            APP_ID, APP_ID, theme_path,
            [
                ("Capture area", lambda: self.capture("area")),
                ("Capture layar penuh", lambda: self.capture("full")),
                ("Capture jendela", lambda: self.capture("window")),
                None,
                ("Capture area (delay 3 detik)", lambda: self.capture("area", 3)),
                ("Capture area (delay 5 detik)", lambda: self.capture("area", 5)),
                ("Capture area (delay 10 detik)", lambda: self.capture("area", 10)),
                None,
                ("Buka gambar…", self._open_dialog),
                ("Preferensi", self.show_preferences),
                ("Keluar", self.quit),
            ],
            on_activate=lambda: self.capture("area"),
        )
        self.tray.start()

    def keep_alive_for_clipboard(self):
        """On Wayland the clipboard content disappears with its owner, so stay alive a while."""
        if self._clip_timer:
            GLib.source_remove(self._clip_timer)
        self._clip_timer = GLib.timeout_add_seconds(30 * 60, self._release_clipboard)
        if not self._clip_hold:
            self._clip_hold = True
            self.hold()
            clip = Gdk.Display.get_default().get_clipboard()
            self._clip_handler = clip.connect("changed", self._on_clipboard_changed)

    def _on_clipboard_changed(self, clip):
        if not clip.is_local():
            self._release_clipboard()

    def _release_clipboard(self):
        if self._clip_timer:
            GLib.source_remove(self._clip_timer)
        self._clip_timer = 0
        if self._clip_hold:
            self._clip_hold = False
            Gdk.Display.get_default().get_clipboard().disconnect(self._clip_handler)
            self.release()
        return False

    def _active_window(self):
        return self.get_active_window() or next(iter(self.get_windows()), None)

    def show_preferences(self):
        from .prefs import build_preferences

        parent = self._active_window()
        if parent is None:
            self.show_launcher()
            parent = self._active_window()
        build_preferences(self, parent)

    def show_about(self):
        kw = dict(application_name=APP_NAME, application_icon=APP_ID, version=VERSION,
                  developer_name="Wahana Creative", license_type=Gtk.License.MIT_X11,
                  comments="Screenshot & anotasi untuk Ubuntu")
        parent = self._active_window()
        if hasattr(Adw, "AboutDialog"):
            Adw.AboutDialog(**kw).present(parent)
        elif hasattr(Adw, "AboutWindow"):
            Adw.AboutWindow(transient_for=parent, **kw).present()
        else:
            Gtk.AboutDialog(transient_for=parent, program_name=APP_NAME, logo_icon_name=APP_ID,
                            version=VERSION, comments=kw["comments"]).present()

    def _open_dialog(self):
        from . import compat

        parent = self._active_window()
        compat.open_file(parent, self.open_file)

    def open_file(self, path):
        try:
            surface = load_image(path)
        except Exception as e:  # noqa: BLE001
            self.error(f"Tidak bisa membuka {path}: {e}")
            return
        self.open_editor(surface)

    def open_editor(self, surface):
        from .editor import EditorWindow

        win = EditorWindow(self, surface)
        win.present()
        for w in list(self.get_windows()):
            if isinstance(w, LauncherWindow):
                w.destroy()
        return win

    def error(self, message):
        print("snipper:", message, file=sys.stderr)
        n = Gio.Notification.new(APP_NAME)
        n.set_body(message)
        self.send_notification("error", n)

    # ------------------------------------------------------------ capture
    def capture(self, mode, delay=None, monitor=None):
        if self._busy:
            return
        self._busy = True
        self.hold()
        if delay is None:
            delay = 0
        # hide our own windows so they don't end up in the screenshot
        self._hidden = [w for w in self.get_windows() if w.get_visible()]
        for w in self._hidden:
            w.set_visible(False)
        wait = max(0, int(delay)) * 1000 + (350 if self._hidden else 0)
        if delay:
            self._countdown_notify(int(delay))
        GLib.timeout_add(max(1, wait), self._do_capture, mode, monitor)

    def _countdown_notify(self, seconds):
        n = Gio.Notification.new(APP_NAME)
        n.set_body(f"Capture dalam {seconds} detik…")
        self.send_notification("countdown", n)

    def _do_capture(self, mode, monitor):
        self.withdraw_notification("countdown")
        if self.use_portal:
            interactive = mode == "window"
            capture.PortalScreenshot(
                interactive, lambda p, e, c: self._on_shot(mode, monitor, interactive, p, e, c))
        else:
            self._capture_with_tools(mode, monitor)
        return False

    def _capture_with_tools(self, mode, monitor):
        try:
            path = capture.capture_with_tools("window" if mode == "window" else "full")
        except RuntimeError as e:
            self.error(str(e))
            self._capture_done(None)
            return
        self._on_shot(mode, monitor, mode == "window", path, None, False)

    def _on_shot(self, mode, monitor, interactive, path, err, cancelled):
        if cancelled:
            self._capture_done(None)
            return
        if err:
            if not interactive and self.use_portal:
                if err == "denied":
                    # no stored permission: fall back to GNOME's own interactive screenshot UI
                    print("snipper: portal denied silent capture; using interactive dialog. "
                          "Click 'Izinkan' in the Snipper window to allow silent captures.", file=sys.stderr)
                    capture.PortalScreenshot(
                        True, lambda p, e, c: self._on_shot(mode, monitor, True, p, e, c))
                    return
                self._capture_with_tools(mode, monitor)
                return
            self.error(f"Screenshot gagal: {err}")
            self._capture_done(None)
            return
        try:
            surface = load_image(path)
        except Exception as e:  # noqa: BLE001
            self.error(f"Tidak bisa membaca hasil screenshot: {e}")
            self._capture_done(None)
            return
        finally:
            self._discard_temp(path)

        if interactive:
            # the user already chose the region in the system dialog
            self._capture_done(surface)
        elif mode == "area":
            from .selector import AreaSelector

            AreaSelector(self, surface, self._capture_done)
        elif mode == "full":
            idx = (monitor - 1) if monitor else self.settings["fullscreen_monitor"]
            if monitor == 0:
                idx = -1
            if idx is not None and idx >= 0:
                regions = capture.monitor_regions(surface.get_width(), surface.get_height())
                if idx < len(regions):
                    surface = crop_surface(surface, *regions[idx][1])
            self._capture_done(surface)
        else:
            self._capture_done(surface)

    def _discard_temp(self, path):
        """The portal/CLI wrote this file just for us; we keep the image in memory instead."""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def _capture_done(self, surface):
        self._busy = False
        if surface is not None:
            self.open_editor(surface)
        for w in self._hidden:
            try:
                if surface is None or not isinstance(w, LauncherWindow):
                    w.set_visible(True)
            except Exception:  # window may be gone
                pass
        self._hidden = []
        self.release()

    def request_permission(self, launcher):
        """Ask the portal once while our window is focused, so GNOME can show its permission prompt."""

        def done(path, err, cancelled):
            self._discard_temp(path)
            ok = capture.has_screenshot_permission(APP_ID) is True or path is not None
            launcher.perm_box.set_visible(not ok)
            if not ok:
                self.error("Izin screenshot belum diberikan. Snipper akan memakai dialog GNOME.")

        capture.PortalScreenshot(False, done)


def main(argv=None):
    # must happen before GTK touches the portal (e.g. to read the color scheme)
    capture.register_host_app(APP_ID)
    app = SnipperApp()
    return app.run(argv if argv is not None else sys.argv)
