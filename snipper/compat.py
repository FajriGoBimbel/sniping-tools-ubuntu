"""Small wrappers so the app runs on GTK 4.6 / libadwaita 1.1 (Ubuntu 22.04) as well as newer stacks."""
from __future__ import annotations

from gi.repository import Adw, Gdk, Gio, GLib, Gtk


def confirm(parent, heading, body, ok_label, callback, destructive=True):
    """Ask a yes/no question; callback(bool)."""
    if hasattr(Adw, "AlertDialog"):  # libadwaita >= 1.5
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("cancel", "Batal")
        dlg.add_response("ok", ok_label)
        dlg.set_response_appearance(
            "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
        )
        dlg.set_default_response("cancel")
        dlg.connect("response", lambda d, r: callback(r == "ok"))
        dlg.present(parent)
        return
    if hasattr(Adw, "MessageDialog"):  # libadwaita 1.2 - 1.4
        dlg = Adw.MessageDialog(transient_for=parent, heading=heading, body=body)
        dlg.add_response("cancel", "Batal")
        dlg.add_response("ok", ok_label)
        dlg.set_response_appearance(
            "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
        )
        dlg.connect("response", lambda d, r: callback(r == "ok"))
        dlg.present()
        return
    dlg = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE, text=heading, secondary_text=body,
    )
    dlg.add_button("Batal", Gtk.ResponseType.CANCEL)
    dlg.add_button(ok_label, Gtk.ResponseType.OK)

    def on_resp(d, r):
        d.destroy()
        callback(r == Gtk.ResponseType.OK)

    dlg.connect("response", on_resp)
    dlg.present()


def choose_color(parent, initial: Gdk.RGBA, callback):
    """callback(Gdk.RGBA) only when the user picked a color."""
    if hasattr(Gtk, "ColorDialog"):  # GTK >= 4.10
        dlg = Gtk.ColorDialog(with_alpha=True)

        def done(d, res):
            try:
                callback(d.choose_rgba_finish(res))
            except GLib.Error:
                pass

        dlg.choose_rgba(parent, initial, None, done)
        return
    dlg = Gtk.ColorChooserDialog(transient_for=parent, modal=True, use_alpha=True)
    dlg.set_rgba(initial)

    def on_resp(d, r):
        if r == Gtk.ResponseType.OK:
            callback(d.get_rgba())
        d.destroy()

    dlg.connect("response", on_resp)
    dlg.present()


def save_file(parent, folder: str, name: str, callback):
    """callback(path) when the user picked a destination."""
    if hasattr(Gtk, "FileDialog"):  # GTK >= 4.10
        dlg = Gtk.FileDialog(title="Simpan screenshot", initial_name=name)
        dlg.set_initial_folder(Gio.File.new_for_path(folder))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        for label, pats in (("Gambar PNG", ["*.png"]), ("Gambar JPEG", ["*.jpg", "*.jpeg"])):
            f = Gtk.FileFilter(name=label)
            for p in pats:
                f.add_pattern(p)
            filters.append(f)
        dlg.set_filters(filters)

        def done(d, res):
            try:
                gfile = d.save_finish(res)
            except GLib.Error:
                return
            if gfile:
                callback(gfile.get_path())

        dlg.save(parent, None, done)
        return
    dlg = Gtk.FileChooserNative(title="Simpan screenshot", transient_for=parent, action=Gtk.FileChooserAction.SAVE)
    dlg.set_current_name(name)
    try:
        dlg.set_current_folder(Gio.File.new_for_path(folder))
    except GLib.Error:
        pass

    def on_resp(d, r):
        if r == Gtk.ResponseType.ACCEPT:
            callback(d.get_file().get_path())
        d.destroy()

    dlg.connect("response", on_resp)
    dlg.show()
    parent._snipper_native = dlg  # keep a reference alive


def choose_folder(parent, folder: str, callback):
    if hasattr(Gtk, "FileDialog"):
        dlg = Gtk.FileDialog(title="Pilih folder")
        dlg.set_initial_folder(Gio.File.new_for_path(folder))

        def done(d, res):
            try:
                gfile = d.select_folder_finish(res)
            except GLib.Error:
                return
            if gfile:
                callback(gfile.get_path())

        dlg.select_folder(parent, None, done)
        return
    dlg = Gtk.FileChooserNative(
        title="Pilih folder", transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER
    )

    def on_resp(d, r):
        if r == Gtk.ResponseType.ACCEPT:
            callback(d.get_file().get_path())
        d.destroy()

    dlg.connect("response", on_resp)
    dlg.show()
    parent._snipper_native = dlg


def open_file(parent, callback):
    """Pick an image to open; callback(path)."""
    if hasattr(Gtk, "FileDialog"):
        dlg = Gtk.FileDialog(title="Buka gambar")
        f = Gtk.FileFilter(name="Gambar")
        f.add_pixbuf_formats()
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg.set_filters(filters)

        def done(d, res):
            try:
                gfile = d.open_finish(res)
            except GLib.Error:
                return
            if gfile:
                callback(gfile.get_path())

        dlg.open(parent, None, done)
        return
    dlg = Gtk.FileChooserNative(title="Buka gambar", transient_for=parent, action=Gtk.FileChooserAction.OPEN)
    f = Gtk.FileFilter()
    f.set_name("Gambar")
    f.add_pixbuf_formats()
    dlg.add_filter(f)

    def on_resp(d, r):
        if r == Gtk.ResponseType.ACCEPT:
            callback(d.get_file().get_path())
        d.destroy()

    dlg.connect("response", on_resp)
    dlg.show()
    parent._snipper_native = dlg


def open_folder(path: str):
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except GLib.Error:
        pass


def texture_from_png(data: bytes) -> Gdk.Texture:
    if hasattr(Gdk.Texture, "new_from_bytes"):
        return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
    from gi.repository import GdkPixbuf

    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data)
    loader.close()
    return Gdk.Texture.new_for_pixbuf(loader.get_pixbuf())


def set_clipboard_image(clipboard, png: bytes):
    """Offer the image as a texture (all image formats GTK knows) plus raw image/png bytes."""
    texture = texture_from_png(png)
    providers = [
        Gdk.ContentProvider.new_for_value(texture),
        Gdk.ContentProvider.new_for_bytes("image/png", GLib.Bytes.new(png)),
    ]
    clipboard.set_content(Gdk.ContentProvider.new_union(providers))
