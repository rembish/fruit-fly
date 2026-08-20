"""GTK3 backend — Linux/X11 (and Wayland via XWayland).

Click-through is an X11 input shape: the fly window accepts pointer
events only inside a square around the fly's body.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import cairo
import numpy as np

from ..core import HUD_H, HUD_W, WIN
from .base import Host, rgb_to_luminance

if TYPE_CHECKING:
    from ..core import Controller

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    _IMPORT_ERROR: Exception | None = None
except Exception as _e:                      # no PyGObject, or no GTK3
    Gdk = GLib = Gtk = None                  # type: ignore[assignment]
    _IMPORT_ERROR = _e


class GtkHost(Host):
    name = "gtk"
    description = "GTK3 on X11 (Linux); needs a compositing window manager"

    @classmethod
    def available(cls) -> tuple[bool, str]:
        if _IMPORT_ERROR is not None:
            return False, (f"PyGObject/GTK3 not importable ({_IMPORT_ERROR}). "
                           f"Install python3-gi python3-gi-cairo "
                           f"gir1.2-gtk-3.0")
        if Gdk.Screen.get_default() is None:
            return False, "no display (is DISPLAY set?)"
        return True, ""

    def __init__(self, hud: bool = False):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(self.available()[1])
        self.screen = Gdk.Screen.get_default()
        if self.screen is None:
            raise RuntimeError("no display — is DISPLAY set?")
        self.fly_win = self._layer_window(WIN, WIN)
        self.fly_win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.hud_win = self._layer_window(HUD_W, HUD_H) if hud else None
        self._root = Gdk.get_default_root_window()
        self.controller: Controller | None = None

    def _layer_window(self, w: int, h: int):
        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_default_size(w, h)
        win.set_app_paintable(True)
        win.set_keep_above(True)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_accept_focus(False)
        visual = self.screen.get_rgba_visual()
        if visual is None:
            raise RuntimeError(
                "No RGBA visual — is the compositor enabled? "
                "(MATE: System > Preferences > Windows > enable compositing)")
        win.set_visual(visual)
        return win

    # ---------------------------------------------------- host interface
    def screen_size(self) -> tuple[int, int]:
        return self.screen.get_width(), self.screen.get_height()

    def pointer(self) -> tuple[float, float]:
        seat = Gdk.Display.get_default().get_default_seat()
        _screen, px, py = seat.get_pointer().get_position()
        return float(px), float(py)

    def grab(self, x: int, y: int, side: int, out: int):
        pb = Gdk.pixbuf_get_from_window(self._root, x, y, side, side)
        if pb is None:
            return None
        pb = pb.scale_simple(out, out, 2)  # BILINEAR
        ch, rs = pb.get_n_channels(), pb.get_rowstride()
        buf = np.frombuffer(pb.get_pixels(), dtype=np.uint8)
        buf = np.pad(buf, (0, rs * out - len(buf)))  # last row may be short
        arr = buf.reshape(out, rs)[:, : out * ch].reshape(out, out, ch)
        return rgb_to_luminance(arr)

    def move_window(self, x: int, y: int) -> None:
        self.fly_win.move(x, y)

    def request_redraw(self) -> None:
        self.fly_win.queue_draw()
        if self.hud_win is not None:
            self.hud_win.queue_draw()

    # ------------------------------------------------------------- setup
    def attach(self, controller: Controller) -> None:
        self.controller = controller
        self.fly_win.connect("draw", lambda _w, cr: controller.draw(cr))
        self.fly_win.connect("realize", lambda _w: self._shape_fly())
        self.fly_win.connect("button-press-event", self._on_click)
        if self.hud_win is not None:
            self.hud_win.connect("draw",
                                 lambda _w, cr: controller.draw_hud(cr))
            self.hud_win.connect(
                "realize", lambda w: w.get_window()
                .input_shape_combine_region(
                    cairo.Region(),  # type: ignore[call-arg]  # empty region
                    0, 0))
            self.hud_win.move(10, 10)

    def _shape_fly(self) -> None:
        assert self.controller is not None, "attach() before run()"
        r = int(self.controller.hit_radius())
        rect = cairo.RectangleInt(x=WIN // 2 - r, y=WIN // 2 - r,
                                  width=2 * r, height=2 * r)
        self.fly_win.get_window().input_shape_combine_region(
            cairo.Region(rect), 0, 0)

    def _on_click(self, _widget, _event) -> bool:
        assert self.controller is not None
        self.controller.on_swat()
        return True

    # -------------------------------------------------------------- loop
    def run(self) -> None:
        self.fly_win.show_all()
        if self.hud_win is not None:
            self.hud_win.show_all()
        self.fly_win.connect("destroy", Gtk.main_quit)
        GLib.timeout_add(16, self._tick)   # ~60 fps
        with contextlib.suppress(KeyboardInterrupt):
            Gtk.main()

    def _tick(self) -> bool:
        assert self.controller is not None
        self.controller.tick()
        return True
