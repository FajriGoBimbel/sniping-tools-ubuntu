"""The annotation editor window."""
from __future__ import annotations

import os

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import compat
from . import shapes as S
from .canvas import Canvas, Style
from .document import Document

TOOL_INFO = [
    # tool, icon, tooltip, key
    ("select", "snipper-select-symbolic", "Pilih & geser (V)", "v"),
    ("rect", "snipper-rect-symbolic", "Kotak (R)", "r"),
    ("ellipse", "snipper-ellipse-symbolic", "Elips (E)", "e"),
    ("line", "snipper-line-symbolic", "Garis (L)", "l"),
    ("arrow", "snipper-arrow-symbolic", "Panah (A)", "a"),
    ("text", "snipper-text-symbolic", "Teks (T)", "t"),
    ("highlight", "snipper-highlight-symbolic", "Highlighter (H)", "h"),
    ("blur", "snipper-blur-symbolic", "Blur / pixelate (B)", "b"),
    ("step", "snipper-step-symbolic", "Nomor langkah (N)", "n"),
    ("pen", "snipper-pen-symbolic", "Pensil bebas (P)", "p"),
    ("crop", "snipper-crop-symbolic", "Crop (C)", "c"),
]

PALETTE = [
    ("Merah", (0.88, 0.11, 0.14, 1)),
    ("Oranye", (1.0, 0.47, 0.0, 1)),
    ("Kuning", (0.96, 0.83, 0.18, 1)),
    ("Hijau", (0.2, 0.82, 0.48, 1)),
    ("Biru", (0.21, 0.52, 0.89, 1)),
    ("Ungu", (0.57, 0.25, 0.67, 1)),
    ("Hitam", (0.0, 0.0, 0.0, 1)),
    ("Putih", (1.0, 1.0, 1.0, 1)),
]


def _swatch(color_getter, size=18):
    area = Gtk.DrawingArea()
    area.set_content_width(size)
    area.set_content_height(size)

    def draw(_a, cr, w, h):
        import math

        r = min(w, h) / 2 - 1
        cr.arc(w / 2, h / 2, r, 0, 2 * math.pi)
        cr.set_source_rgba(*color_getter())
        cr.fill_preserve()
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.6)
        cr.set_line_width(1)
        cr.stroke()

    area.set_draw_func(draw)
    return area


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app, surface):
        super().__init__(application=app)
        self.app = app
        self.settings = app.settings
        st = self.settings
        self.doc = Document(surface)
        self.style = Style(st["color"], st["width"], st["fill"], st["font_size"], st["bold"])
        self.saved_path = None
        self._syncing = False

        self.canvas = Canvas(self.doc, self.style)
        self.canvas.set_halign(Gtk.Align.CENTER)
        self.canvas.set_valign(Gtk.Align.CENTER)
        self.canvas.connect("changed", self._on_doc_changed)
        self.canvas.connect("selection-changed", self._on_selection_changed)
        self.canvas.connect("zoom-changed", self._on_zoom_changed)
        self.canvas.connect("request-text", self._on_request_text)

        self._build_actions()
        self._build_ui()
        self.set_tool("arrow")
        self._update_history_buttons()
        self._update_title()

        self.connect("close-request", self._on_close_request)
        self.connect("destroy", lambda *_: self.text_popover.unparent())
        self._fitted = False
        self.connect("map", lambda *_: GLib.timeout_add(60, self._initial_zoom))

        if st["copy_after_capture"]:
            GLib.idle_add(lambda: (self.copy_to_clipboard(toast=False), False)[1])

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        sw, sh = self.doc.width, self.doc.height
        display = Gdk.Display.get_default()
        mons = display.get_monitors()
        mw, mh = 1600, 1000
        if mons.get_n_items():
            g = mons.get_item(0).get_geometry()
            mw, mh = g.width, g.height
        self.set_default_size(
            int(min(max(sw + 40, 720), mw * 0.85)), int(min(max(sh + 150, 480), mh * 0.85))
        )

        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title="Snipper")
        header.set_title_widget(self.title_widget)

        self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo (Ctrl+Z)")
        self.undo_btn.set_action_name("win.undo")
        self.redo_btn = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text="Redo (Ctrl+Shift+Z)")
        self.redo_btn.set_action_name("win.redo")
        header.pack_start(self.undo_btn)
        header.pack_start(self.redo_btn)

        menu = Gio.Menu()
        cap = Gio.Menu()
        cap.append("Capture area baru", "app.capture-area")
        cap.append("Capture layar penuh", "app.capture-full")
        cap.append("Capture jendela", "app.capture-window")
        menu.append_section(None, cap)
        files = Gio.Menu()
        files.append("Buka gambar…", "app.open")
        files.append("Simpan sebagai…", "win.save-as")
        files.append("Buka folder screenshot", "win.open-folder")
        menu.append_section(None, files)
        other = Gio.Menu()
        other.append("Preferensi", "app.preferences")
        other.append("Pintasan keyboard", "win.show-help")
        other.append("Tentang Snipper", "app.about")
        menu.append_section(None, other)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu")
        header.pack_end(menu_btn)

        save_menu = Gio.Menu()
        save_menu.append("Simpan sebagai…", "win.save-as")
        save_btn = Adw.SplitButton(label="Simpan", menu_model=save_menu, tooltip_text="Simpan (Ctrl+S)")
        save_btn.set_action_name("win.save")
        save_btn.add_css_class("suggested-action")
        header.pack_end(save_btn)
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Salin ke clipboard (Ctrl+C)")
        copy_btn.set_action_name("win.copy")
        header.pack_end(copy_btn)

        toolbar = self._build_toolbar()

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.add_css_class("snipper-stage")
        scrolled.set_child(self.canvas)
        self.scrolled = scrolled
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll.connect("scroll", self._on_scroll)
        scrolled.add_controller(scroll)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(scrolled)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(toolbar)
        box.append(self.toasts)
        self.set_content(box)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self._build_text_popover()

    def _build_toolbar(self):
        bar = Gtk.Box(spacing=4, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        bar.add_css_class("snipper-toolbar")

        tools_box = Gtk.Box(spacing=2)
        self.tool_buttons = {}
        group = None
        for tool, icon, tip, _key in TOOL_INFO:
            b = Gtk.ToggleButton(icon_name=icon, tooltip_text=tip)
            b.add_css_class("flat")
            b.set_focusable(False)
            if group:
                b.set_group(group)
            else:
                group = b
            b.connect("toggled", self._on_tool_toggled, tool)
            self.tool_buttons[tool] = b
            tools_box.append(b)
            if tool in ("select", "pen"):
                tools_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4))
        bar.append(tools_box)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))

        # color picker
        self.color_swatch = _swatch(lambda: self.style.color)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6, margin_bottom=6,
                          margin_start=6, margin_end=6)
        grid = Gtk.Grid(column_spacing=4, row_spacing=4)
        self.color_popover = Gtk.Popover()
        for i, (name, rgba) in enumerate(PALETTE):
            btn = Gtk.Button(tooltip_text=name)
            btn.add_css_class("flat")
            btn.set_child(_swatch(lambda c=rgba: c, 22))
            btn.connect("clicked", self._on_palette, rgba)
            grid.attach(btn, i % 4, i // 4, 1, 1)
        pop_box.append(grid)
        more = Gtk.Button(label="Warna lain…")
        more.add_css_class("flat")
        more.connect("clicked", self._on_custom_color)
        pop_box.append(more)
        self.color_popover.set_child(pop_box)
        color_btn = Gtk.MenuButton(popover=self.color_popover, tooltip_text="Warna")
        color_btn.set_child(self.color_swatch)
        color_btn.set_focusable(False)
        bar.append(color_btn)

        # line width
        self.width_box = Gtk.Box(spacing=4)
        self.width_box.append(Gtk.Image(icon_name="snipper-line-symbolic", tooltip_text="Ketebalan garis"))
        self.width_spin = Gtk.SpinButton.new_with_range(1, 40, 1)
        self.width_spin.set_value(self.style.width)
        self.width_spin.set_tooltip_text("Ketebalan garis")
        self.width_spin.connect("value-changed", self._on_width)
        self.width_box.append(self.width_spin)
        bar.append(self.width_box)

        self.fill_btn = Gtk.ToggleButton(icon_name="snipper-fill-symbolic", tooltip_text="Isi bentuk (outline / isi)")
        self.fill_btn.set_active(self.style.fill)
        self.fill_btn.set_focusable(False)
        self.fill_btn.connect("toggled", self._on_fill)
        bar.append(self.fill_btn)

        # text options
        self.text_box = Gtk.Box(spacing=4)
        self.text_box.append(Gtk.Image(icon_name="snipper-text-symbolic", tooltip_text="Ukuran font"))
        self.font_spin = Gtk.SpinButton.new_with_range(8, 160, 2)
        self.font_spin.set_value(self.style.font_size)
        self.font_spin.set_tooltip_text("Ukuran font (px)")
        self.font_spin.connect("value-changed", self._on_font_size)
        self.text_box.append(self.font_spin)
        self.bold_btn = Gtk.ToggleButton(icon_name="snipper-bold-symbolic", tooltip_text="Tebal (bold)")
        self.bold_btn.set_active(self.style.bold)
        self.bold_btn.set_focusable(False)
        self.bold_btn.connect("toggled", self._on_bold)
        self.text_box.append(self.bold_btn)
        bar.append(self.text_box)

        bar.append(Gtk.Box(hexpand=True))

        zoom_box = Gtk.Box()
        zoom_box.add_css_class("linked")
        zo = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text="Perkecil (Ctrl+-)")
        zo.set_action_name("win.zoom-out")
        self.zoom_label = Gtk.Button(label="100%", tooltip_text="Sesuaikan ke jendela (Ctrl+0)")
        self.zoom_label.set_action_name("win.zoom-fit")
        zi = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text="Perbesar (Ctrl++)")
        zi.set_action_name("win.zoom-in")
        for w in (zo, self.zoom_label, zi):
            w.set_focusable(False)
            zoom_box.append(w)
        bar.append(zoom_box)
        return bar

    def _build_text_popover(self):
        self.text_popover = Gtk.Popover()
        self.text_popover.set_parent(self.canvas)
        self.text_popover.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=4, margin_bottom=4,
                      margin_start=4, margin_end=4)
        self.text_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        self.text_view.set_size_request(260, 60)
        frame = Gtk.Frame()
        frame.set_child(self.text_view)
        box.append(frame)
        hint = Gtk.Label(label="Enter = selesai · Shift+Enter = baris baru · Esc = batal", xalign=0)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        box.append(hint)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_text_key)
        box.add_controller(keys)
        self.text_popover.set_child(box)
        self.text_popover.connect("closed", self._on_text_closed)
        self._text_target = None
        self._text_active = False
        self._text_cancel = False

    def _run_action(self, name, cb):
        """Never let one failing action crash the app; tell the user instead."""
        try:
            cb()
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            self.toast(f"Gagal ({name}): {e}")

    def _build_actions(self):
        def add(name, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: self._run_action(name, cb))
            self.add_action(a)
            return a

        self.undo_action = add("undo", self.undo)
        self.redo_action = add("redo", self.redo)
        add("save", self.save)
        add("save-as", self.save_as)
        add("copy", self.copy_to_clipboard)
        add("delete", self.canvas.delete_selected)
        add("zoom-in", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25))
        add("zoom-out", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25))
        add("zoom-fit", self.zoom_fit)
        add("zoom-100", lambda: self.canvas.set_zoom(1 / self._device_scale()))
        add("open-folder", lambda: compat.open_folder(
            os.path.dirname(self.saved_path) if self.saved_path else self.settings.save_dir))
        add("show-help", self._show_help)
        add("close", self.close)

    # ------------------------------------------------------------- tools/style
    def set_tool(self, tool):
        btn = self.tool_buttons[tool]
        if not btn.get_active():
            btn.set_active(True)
        else:
            self._apply_tool(tool)

    def _on_tool_toggled(self, btn, tool):
        if btn.get_active():
            self._apply_tool(tool)

    def _apply_tool(self, tool):
        self.canvas.set_tool(tool)
        self._update_option_visibility()

    def _update_option_visibility(self):
        tool = self.canvas.tool
        sel = self.canvas.selected
        kind = sel.kind if sel is not None else tool
        self.text_box.set_visible(kind == "text")
        self.fill_btn.set_visible(kind in ("rect", "ellipse"))
        self.width_box.set_visible(kind not in ("text", "crop", "select"))

    def _style_changed(self, attr):
        if self._syncing:
            return
        key = {"color": "color", "width": "width", "fill": "fill", "font_size": "font_size", "bold": "bold"}[attr]
        value = getattr(self.style, attr)
        self.settings[key] = list(value) if attr == "color" else value
        self.canvas.apply_style_to_selection(attr)

    def _on_palette(self, _btn, rgba):
        self.color_popover.popdown()
        self._set_color(rgba)

    def _on_custom_color(self, _btn):
        self.color_popover.popdown()
        c = self.style.color
        compat.choose_color(self, Gdk.RGBA(red=c[0], green=c[1], blue=c[2], alpha=c[3]),
                            lambda rgba: self._set_color((rgba.red, rgba.green, rgba.blue, rgba.alpha)))

    def _set_color(self, rgba):
        self.style.color = tuple(rgba)
        self.color_swatch.queue_draw()
        self._style_changed("color")

    def _on_width(self, spin):
        self.style.width = spin.get_value_as_int()
        self._style_changed("width")

    def _on_fill(self, btn):
        self.style.fill = btn.get_active()
        self._style_changed("fill")

    def _on_font_size(self, spin):
        self.style.font_size = spin.get_value_as_int()
        self._style_changed("font_size")

    def _on_bold(self, btn):
        self.style.bold = btn.get_active()
        self._style_changed("bold")

    def _on_selection_changed(self, _canvas):
        sel = self.canvas.selected
        if sel is not None:
            # reflect the selected object's properties in the toolbar
            self._syncing = True
            self.style.color = tuple(sel.color)
            self.color_swatch.queue_draw()
            if not isinstance(sel, S.TextShape):
                self.width_spin.set_value(sel.width)
            if hasattr(sel, "fill"):
                self.fill_btn.set_active(sel.fill)
            if isinstance(sel, S.TextShape):
                self.font_spin.set_value(sel.size)
                self.bold_btn.set_active(sel.bold)
            self.style.width = self.width_spin.get_value_as_int()
            self._syncing = False
        self._update_option_visibility()

    # ------------------------------------------------------------- text
    def _on_request_text(self, _canvas, shape, wx, wy):
        self._text_target = shape
        self._text_cancel = False
        self._text_active = True
        buf = self.text_view.get_buffer()
        buf.set_text(shape.text if shape else "")
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(wx), int(wy), 1, 1
        self.text_popover.set_pointing_to(rect)
        self.text_popover.popup()
        self.text_view.grab_focus()
        buf.select_range(buf.get_start_iter(), buf.get_end_iter())

    def _on_text_key(self, _ctrl, keyval, _code, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.SHIFT_MASK):
            self.text_popover.popdown()
            return True
        if keyval == Gdk.KEY_Escape:
            self._text_cancel = True
            self.text_popover.popdown()
            return True
        return False

    def _on_text_closed(self, _pop):
        if not self._text_active:
            return
        self._text_active = False
        if not self._text_cancel:
            buf = self.text_view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            self.canvas.commit_text(self._text_target, text)
        self.canvas.grab_focus()

    # ------------------------------------------------------------- history
    def undo(self):
        if self.doc.undo():
            self.canvas.document_changed()
            self._on_doc_changed()

    def redo(self):
        if self.doc.redo():
            self.canvas.document_changed()
            self._on_doc_changed()

    def _on_doc_changed(self, *_):
        self._update_history_buttons()
        self._update_title()

    def _update_history_buttons(self):
        self.undo_action.set_enabled(self.doc.can_undo())
        self.redo_action.set_enabled(self.doc.can_redo())

    def _update_title(self):
        mark = "• " if self.doc.dirty else ""
        self.title_widget.set_subtitle(f"{mark}{self.doc.width} × {self.doc.height} px")

    # ------------------------------------------------------------- zoom
    def _device_scale(self):
        surface = self.get_surface()
        if surface is not None and hasattr(surface, "get_scale"):
            try:
                return max(1.0, surface.get_scale())
            except Exception:
                pass
        return max(1, self.get_scale_factor())

    def _initial_zoom(self):
        if self._fitted:
            return False
        if self.scrolled.get_width() < 2:
            return True  # not allocated yet, try again shortly
        self._fitted = True
        one_to_one = 1 / self._device_scale()
        fit = self._fit_zoom()
        self.canvas.set_zoom(min(one_to_one, fit))
        self._on_zoom_changed()
        self.canvas.grab_focus()
        return False

    def _fit_zoom(self):
        aw = max(50, self.scrolled.get_width() - 24)
        ah = max(50, self.scrolled.get_height() - 24)
        return min(aw / self.doc.width, ah / self.doc.height)

    def zoom_fit(self):
        self.canvas.set_zoom(min(self._fit_zoom(), 1 / self._device_scale() * 4))

    def _on_zoom_changed(self, *_):
        pct = round(self.canvas.zoom * self._device_scale() * 100)
        self.zoom_label.set_label(f"{pct}%")

    def _on_scroll(self, ctrl, dx, dy):
        state = ctrl.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            factor = 1.15 if dy < 0 else 1 / 1.15
            self.canvas.set_zoom(self.canvas.zoom * factor)
            return True
        return False

    # ------------------------------------------------------------- keys
    def _on_key(self, _ctrl, keyval, _code, state):
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK)
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Text, Gtk.TextView, Gtk.SpinButton)):
            return False
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace, Gdk.KEY_KP_Delete):
            return self.canvas.delete_selected()
        if keyval == Gdk.KEY_Escape:
            if self.canvas.selected is not None:
                self.canvas.select(None)
                return True
            return False
        step = 10 if state & Gdk.ModifierType.SHIFT_MASK else 1
        arrows = {Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0), Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step)}
        if keyval in arrows and self.canvas.selected is not None:
            self.canvas.nudge_selected(*arrows[keyval])
            self._on_doc_changed()
            return True
        if not mods:
            ch = chr(Gdk.keyval_to_unicode(keyval) or 0).lower()
            for tool, _i, _t, key in TOOL_INFO:
                if ch == key:
                    self.set_tool(tool)
                    return True
        return False

    def _show_help(self):
        rows = [
            ("Ctrl+S", "Simpan"), ("Ctrl+Shift+S", "Simpan sebagai"), ("Ctrl+C", "Salin ke clipboard"),
            ("Ctrl+Z / Ctrl+Shift+Z", "Undo / Redo"), ("Delete", "Hapus objek terpilih"),
            ("Panah (+Shift)", "Geser objek 1px (10px)"), ("Shift saat menggambar", "Kotak sama sisi / sudut 45°"),
            ("Ctrl+scroll, Ctrl+± / Ctrl+0", "Zoom / sesuaikan"), ("Dobel-klik teks", "Edit teks"),
        ] + [(k.upper(), t.split(" (")[0]) for _tool, _i, t, k in TOOL_INFO]
        grid = Gtk.Grid(column_spacing=24, row_spacing=6, margin_top=18, margin_bottom=18,
                        margin_start=18, margin_end=18)
        for i, (k, d) in enumerate(rows):
            kl = Gtk.Label(label=k, xalign=1)
            kl.add_css_class("monospace")
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(Gtk.Label(label=d, xalign=0), 1, i, 1, 1)
        win = Adw.Window(transient_for=self, modal=True, title="Pintasan keyboard")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar())
        box.append(grid)
        win.set_content(box)
        win.present()

    # ------------------------------------------------------------- output
    def toast(self, text, action=None, label=None):
        t = Adw.Toast(title=text, timeout=4)
        if action:
            t.set_button_label(label)
            t.set_action_name(action)
        self.toasts.add_toast(t)

    def _write(self, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.doc.save(path, quality=self.settings["jpg_quality"])
        except Exception as e:  # noqa: BLE001 - show any failure to the user
            self.toast(f"Gagal menyimpan: {e}")
            return False
        self.saved_path = path
        self._update_title()
        if self.settings["close_after_save"]:
            self.destroy()
        else:
            self.toast(f"Tersimpan: {os.path.basename(path)}", "win.open-folder", "Buka folder")
        return True

    def save(self):
        self._write(self.saved_path or self.settings.new_filename())

    def save_as(self):
        name = os.path.basename(self.saved_path or self.settings.new_filename())
        folder = os.path.dirname(self.saved_path) if self.saved_path else self.settings.save_dir
        os.makedirs(folder, exist_ok=True)

        def chosen(path):
            if not os.path.splitext(path)[1]:
                path += "." + self.settings["format"]
            self._write(path)

        compat.save_file(self, folder, name, chosen)

    def copy_to_clipboard(self, toast=True):
        compat.set_clipboard_image(self.get_clipboard(), self.doc.to_png_bytes())
        self.doc.dirty = False
        self._update_title()
        self.app.keep_alive_for_clipboard()
        if toast:
            self.toast("Disalin ke clipboard")

    def _on_close_request(self, _win):
        if not self.doc.dirty or not self.doc.can_undo():
            return False
        compat.confirm(
            self, "Tutup tanpa menyimpan?", "Anotasi belum disimpan atau disalin dan akan hilang.",
            "Tutup", lambda ok: ok and self.destroy(),
        )
        return True
