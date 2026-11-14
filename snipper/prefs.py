"""Preferences window."""
from __future__ import annotations

import os

from gi.repository import Adw, Gtk

from . import compat, shortcuts
from .settings import APP_ID

DELAYS = [0, 3, 5, 10]


def _combo(title, labels, selected, on_change, subtitle=None):
    row = Adw.ComboRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_model(Gtk.StringList.new(labels))
    row.set_selected(selected)
    row.connect("notify::selected", lambda r, _p: on_change(r.get_selected()))
    return row


def _switch(title, active, on_change, subtitle=None):
    row = Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    sw.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    row.add_suffix(sw)
    row.set_activatable_widget(sw)
    return row, sw


def autostart_path():
    from gi.repository import GLib

    return os.path.join(GLib.get_user_config_dir(), "autostart", f"{APP_ID}.desktop")


def set_autostart(enabled, command):
    path = autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(
                "[Desktop Entry]\nType=Application\nName=Snipper\n"
                f"Exec={command} --background\nIcon={APP_ID}\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
    elif os.path.exists(path):
        os.remove(path)


def build_preferences(app, parent):
    st = app.settings
    use_dialog = hasattr(Adw, "PreferencesDialog")
    win = Adw.PreferencesDialog() if use_dialog else Adw.PreferencesWindow(transient_for=parent, modal=True)
    win.set_title("Preferensi")
    page = Adw.PreferencesPage(title="Umum", icon_name="preferences-system-symbolic")
    win.add(page)

    # --- output
    out = Adw.PreferencesGroup(title="Simpan")
    folder_row = Adw.ActionRow(title="Folder default", subtitle=st.save_dir)
    pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Pilih folder")
    pick.add_css_class("flat")

    def on_folder(path):
        st["save_dir"] = path
        folder_row.set_subtitle(path)

    pick.connect("clicked", lambda *_: compat.choose_folder(
        win if not use_dialog else parent, st.save_dir if os.path.isdir(st.save_dir) else os.path.expanduser("~"),
        on_folder))
    folder_row.add_suffix(pick)
    out.add(folder_row)
    out.add(_combo("Format file", ["PNG", "JPG"], 0 if st["format"] == "png" else 1,
                   lambda i: st.__setitem__("format", "png" if i == 0 else "jpg")))
    row, _ = _switch("Salin otomatis ke clipboard", st["copy_after_capture"],
                     lambda v: st.__setitem__("copy_after_capture", v), "Setiap capture langsung ada di clipboard")
    out.add(row)
    row, _ = _switch("Tutup editor setelah menyimpan", st["close_after_save"],
                     lambda v: st.__setitem__("close_after_save", v))
    out.add(row)
    page.add(out)

    # --- capture
    cap = Adw.PreferencesGroup(title="Capture")
    from gi.repository import Gdk

    mons = Gdk.Display.get_default().get_monitors()
    labels = ["Semua layar"]
    for i in range(mons.get_n_items()):
        m = mons.get_item(i)
        name = m.get_model() or m.get_connector() or ""
        g = m.get_geometry()
        labels.append(f"Layar {i + 1} — {name} ({g.width}×{g.height})".replace(" —  (", " ("))
    sel = st["fullscreen_monitor"] + 1
    cap.add(_combo("Capture layar penuh", labels, sel if sel < len(labels) else 0,
                   lambda i: st.__setitem__("fullscreen_monitor", i - 1)))
    cap.add(_combo("Delay default", ["Tanpa delay", "3 detik", "5 detik", "10 detik"],
                   DELAYS.index(st["default_delay"]) if st["default_delay"] in DELAYS else 0,
                   lambda i: st.__setitem__("default_delay", DELAYS[i])))
    page.add(cap)

    # --- shortcuts
    sc = Adw.PreferencesGroup(
        title="Shortcut global",
        description="Menggantikan shortcut screenshot bawaan GNOME. Kosongkan untuk menonaktifkan satu aksi.",
    )
    entries = {}
    for action, label in (("area", "Capture area"), ("full", "Capture layar penuh"), ("window", "Capture jendela")):
        r = Adw.ActionRow(title=label)
        e = Gtk.Entry(text=st["shortcuts"].get(action, ""), valign=Gtk.Align.CENTER, width_chars=16)
        e.set_placeholder_text("mis. <Shift>Print")
        r.add_suffix(e)
        entries[action] = e
        sc.add(r)
    status = Adw.ActionRow(title="Status")
    status_label = Gtk.Label()
    status.add_suffix(status_label)
    btns = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
    apply_btn = Gtk.Button(label="Pasang")
    apply_btn.add_css_class("suggested-action")
    remove_btn = Gtk.Button(label="Lepas")
    btns.append(remove_btn)
    btns.append(apply_btn)
    status.add_suffix(btns)
    sc.add(status)

    def refresh():
        if not shortcuts.supported():
            status_label.set_label("Tidak didukung di desktop ini")
            apply_btn.set_sensitive(False)
            remove_btn.set_sensitive(False)
            return
        on = shortcuts.installed()
        status_label.set_label("Aktif" if on else "Belum dipasang")
        remove_btn.set_sensitive(on)

    def do_apply(*_):
        accels = {a: e.get_text().strip() for a, e in entries.items()}
        for a, acc in accels.items():
            if not shortcuts.valid_accel(acc):
                entries[a].add_css_class("error")
                return
            entries[a].remove_css_class("error")
        st["shortcuts"] = accels
        try:
            shortcuts.install(app.launch_command(), accels)
        except Exception as e:  # noqa: BLE001
            status_label.set_label(str(e))
            return
        refresh()

    def do_remove(*_):
        shortcuts.remove()
        refresh()

    apply_btn.connect("clicked", do_apply)
    remove_btn.connect("clicked", do_remove)
    refresh()
    page.add(sc)

    # --- background
    bg = Adw.PreferencesGroup(title="Latar belakang")
    row, _ = _switch(
        "Jalankan saat login (ikon tray)", os.path.exists(autostart_path()),
        lambda v: set_autostart(v, app.launch_command()),
        "Snipper tetap aktif di tray sehingga capture lebih cepat",
    )
    bg.add(row)
    page.add(bg)

    if use_dialog:
        win.present(parent)
    else:
        win.present()
    return win
