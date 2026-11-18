"""GPU drawing helpers: turn Cairo surfaces into GdkTextures and append simple nodes to a GtkSnapshot.

Big images are uploaded to the GPU once as a texture and scaled there, instead of being
re-rasterized by Cairo on every frame (which is what made the overlay and editor feel heavy).
"""
from __future__ import annotations

import sys

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

_HAS_SCALED = hasattr(Gtk.Snapshot, "append_scaled_texture")  # GTK >= 4.10
_FORMAT = (
    Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED if sys.byteorder == "little"
    else Gdk.MemoryFormat.A8R8G8B8_PREMULTIPLIED
)


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, max(0, w), max(0, h))


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def device_scale(widget) -> float:
    """Device pixels per logical pixel, fractional on GTK >= 4.12 with fractional scaling."""
    native = widget.get_native()
    surface = native.get_surface() if native is not None else None
    if surface is not None and hasattr(surface, "get_scale"):
        try:
            return max(1.0, surface.get_scale())
        except Exception:
            pass
    return max(1, widget.get_scale_factor())


def texture_from_surface(surface: cairo.ImageSurface) -> Gdk.Texture:
    """Copy a Cairo image surface into an immutable GdkTexture (uploaded to the GPU on first use)."""
    if surface.get_format() != cairo.FORMAT_ARGB32:
        # RGB24's padding byte is undefined; normalise to ARGB32 so alpha is opaque
        conv = cairo.ImageSurface(cairo.FORMAT_ARGB32, surface.get_width(), surface.get_height())
        cr = cairo.Context(conv)
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        surface = conv
    surface.flush()
    data = GLib.Bytes.new(bytes(surface.get_data()))
    return Gdk.MemoryTexture.new(surface.get_width(), surface.get_height(), _FORMAT, data, surface.get_stride())


def append_texture(snapshot, texture, bounds, device_ratio=1.0):
    """Draw `texture` stretched over `bounds`. device_ratio = device pixels per texture pixel."""
    if _HAS_SCALED:
        if device_ratio >= 2:
            filt = Gsk.ScalingFilter.NEAREST  # crisp pixels when zoomed in
        elif device_ratio < 0.99:
            filt = Gsk.ScalingFilter.TRILINEAR  # mipmapped downscale, no aliasing
        else:
            filt = Gsk.ScalingFilter.LINEAR
        snapshot.append_scaled_texture(texture, filt, bounds)
    else:
        snapshot.append_texture(texture, bounds)


def fill(snapshot, color, x, y, w, h):
    if w > 0 and h > 0:
        snapshot.append_color(color, rect(x, y, w, h))


def dim_outside(snapshot, color, width, height, hole=None):
    """Cover the widget with `color`, leaving `hole` (x, y, w, h) clear."""
    if hole is None:
        fill(snapshot, color, 0, 0, width, height)
        return
    x, y, w, h = hole
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        fill(snapshot, color, 0, 0, width, height)
        return
    fill(snapshot, color, 0, 0, width, y0)
    fill(snapshot, color, 0, y1, width, height - y1)
    fill(snapshot, color, 0, y0, x0, y1 - y0)
    fill(snapshot, color, x1, y0, width - x1, y1 - y0)


def outline(snapshot, color, x, y, w, h, line=1.0):
    """Solid rectangle outline made of four colour nodes (no Cairo)."""
    fill(snapshot, color, x, y, w, line)
    fill(snapshot, color, x, y + h - line, w, line)
    fill(snapshot, color, x, y + line, line, h - 2 * line)
    fill(snapshot, color, x + w - line, y + line, line, h - 2 * line)


def dashed_outline(snapshot, rgb, x, y, w, h, dash=(4, 3)):
    """1px dashed rectangle. Each edge is its own thin Cairo node, so nothing large is rasterized."""
    x, y, w, h = int(x), int(y), int(w), int(h)
    strips = ((x - 1, y - 1, w + 3, 3), (x - 1, y + h - 1, w + 3, 3),
              (x - 1, y + 2, 3, h - 3), (x + w - 1, y + 2, 3, h - 3))
    for sx, sy, sw, sh in strips:
        if sw <= 0 or sh <= 0:
            continue
        cr = snapshot.append_cairo(rect(sx, sy, sw, sh))
        cr.set_line_width(1)
        cr.set_dash(list(dash))
        cr.set_source_rgb(*rgb)
        cr.rectangle(x + 0.5, y + 0.5, w, h)
        cr.stroke()


def pill(snapshot, layout, x, y, pad=6, radius=6):
    """Rounded dark label with white text. Returns (w, h)."""
    _ink, log = layout.get_pixel_extents()
    w, h = log.width + 2 * pad, log.height + 2 * pad
    bounds = rect(x, y, w, h)
    snapshot.push_rounded_clip(Gsk.RoundedRect().init_from_rect(bounds, radius))
    snapshot.append_color(rgba(0.1, 0.1, 0.12, 0.85), bounds)
    snapshot.pop()
    snapshot.save()
    snapshot.translate(Graphene.Point().init(x + pad, y + pad))
    snapshot.append_layout(layout, rgba(1, 1, 1, 1))
    snapshot.restore()
    return w, h
