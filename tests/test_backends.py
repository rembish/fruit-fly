"""Backend contract tests — run these on every platform.

A FakeHost stands in for a window system, so the whole controller path
(senses -> brain -> motor -> draw -> click) is exercised without a
display. Also checks that each registered backend conforms to the Host
interface and reports its availability instead of crashing.

Run:  python3 tests/test_backends.py
"""

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cairo
import numpy as np

from fruitfly import data, ui
from fruitfly.brain import Brain
from fruitfly.core import HUD_H, HUD_W, WIN, Controller
from fruitfly.motor import LANDED, SQUASHED, TAKEOFF
from fruitfly.senses import Retina, Senses
from fruitfly.ui.base import Host


class FakeHost(Host):
    name = "fake"
    description = "headless test double"

    def __init__(self, hud: bool = False, w=1920, h=1200):
        self.hud = hud
        self.w, self.h = w, h
        self.controller = None
        self.moves, self.redraws, self.grabs = [], 0, 0
        self.cursor = (5000.0, 5000.0)
        self.blind = False

    def screen_size(self):
        return self.w, self.h

    def pointer(self):
        return self.cursor

    def grab(self, x, y, side, out):
        self.grabs += 1
        assert 0 <= x <= self.w - side and 0 <= y <= self.h - side, \
            f"grab out of bounds: {x},{y} side {side}"
        if self.blind:
            return None
        return np.full((out, out), 0.5, dtype=np.float32)

    def move_window(self, x, y):
        self.moves.append((x, y))

    def request_redraw(self):
        self.redraws += 1

    def attach(self, controller):
        self.controller = controller

    def run(self):
        raise NotImplementedError("driven manually in tests")


def build(hud=False, vision=True):
    indptr, indices, weights, pops, retina_data = data.load()
    brain = Brain(indptr, indices, weights, pops, dt=2.0,
                  noise_rate=100.0, noise_weight=3.0, seed=3)
    senses = Senses(retina=Retina(retina_data))
    host = FakeHost(hud=hud)
    ctl = Controller(brain, senses, host, vision=vision, verbose=False)
    host.attach(ctl)
    return host, ctl


def test_registry():
    assert set(ui.REGISTRY) >= {"gtk", "cocoa", "win32"}
    for name in sorted(ui.REGISTRY):
        cls = ui.load(name)                     # must import on any platform
        assert issubclass(cls, Host), name
        ok, why = cls.available()               # must not raise
        assert isinstance(ok, bool) and isinstance(why, str)
        missing = {m for m in Host.__abstractmethods__
                   if getattr(cls, m) is getattr(Host, m, None)}
        assert not missing, f"{name} leaves abstract: {missing}"
        print(f"  backend {name:6s} available={ok} {why[:60]}")
    print("registry + interface conformance OK")


def test_native_backend_is_usable():
    """The backend for THIS platform must actually work, not just import.

    Without this, a backend that breaks at import time still 'passes' —
    available() catches the exception and returns False, which the
    conformance check above happily accepts. That is exactly how a
    toolkit-version regression slipped through once.
    """
    order = ui.PLATFORM_ORDER.get(sys.platform, [])
    if not order:
        print(f"no native backend for {sys.platform!r} — skipped")
        return
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        print("no DISPLAY (headless) — native backend check skipped")
        return
    native = order[0]
    ok, why = ui.load(native).available()
    assert ok, (f"native backend {native!r} is unusable on {sys.platform}: "
                f"{why}")
    print(f"native backend {native!r} reports usable OK")


def test_controller_loop():
    host, ctl = build()
    for _ in range(12):
        ctl.tick()
    assert host.redraws == 12
    assert host.moves, "window never followed the fly"
    assert host.grabs > 0, "retina never sampled"
    x, y = host.moves[-1]
    assert x == int(ctl.motor.st.x) - WIN // 2
    assert y == int(ctl.motor.st.y) - WIN // 2
    print(f"controller loop OK ({host.grabs} grabs, {len(host.moves)} moves)")


def test_grab_bounds_at_screen_edges():
    """The fly at a corner must not ask for an off-screen rectangle."""
    host, ctl = build()
    for pos in ((0, 0), (host.w, host.h), (0, host.h), (host.w, 0)):
        ctl.motor.st.x, ctl.motor.st.y = float(pos[0]), float(pos[1])
        for _ in range(3):
            ctl.tick()          # asserts inside FakeHost.grab
    print("edge-clamped grabs OK")


def test_blind_host_survives():
    host, ctl = build()
    host.blind = True           # e.g. macOS Screen Recording denied
    for _ in range(6):
        ctl.tick()
    print("blind host (capture denied) OK — fly still runs")


def test_drawing_surfaces():
    _host, ctl = build(hud=True)
    ctl.tick()
    for surf, w, fn in (
            (cairo.ImageSurface(cairo.FORMAT_ARGB32, WIN, WIN), WIN, "draw"),
            (cairo.ImageSurface(cairo.FORMAT_ARGB32, HUD_W, HUD_H),
             HUD_W, "draw_hud")):
        getattr(ctl, fn)(cairo.Context(surf))
        surf.flush()
        buf = np.frombuffer(surf.get_data(), dtype=np.uint8)
        assert buf.any(), f"{fn} produced an empty surface"
        # ARGB32 is what the Cocoa backend hands to CGImageCreate
        assert surf.get_format() == cairo.FORMAT_ARGB32
        assert surf.get_stride() == w * 4
    # and the splat sprite renders too
    ctl.motor.st.state = SQUASHED
    ctl.draw(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, WIN, WIN)))
    print("cairo surfaces OK (ARGB32, tight stride — CGImage-compatible)")


def test_layered_window_pixel_contract():
    """What Win32's UpdateLayeredWindow and Cocoa's CGImageCreate assume.

    Both take the cairo surface's memory verbatim: premultiplied BGRA on
    little-endian. This is checkable anywhere, so the riskiest part of
    those two (untested) backends is pinned down here.
    """
    assert sys.byteorder == "little", (
        "backends assume little-endian ARGB32 == BGRA bytes")
    w = h = 8
    buf = (ctypes.c_char * (w * h * 4))()     # stands in for the Win32 DIB
    surf = cairo.ImageSurface.create_for_data(
        memoryview(buf), cairo.FORMAT_ARGB32, w, h, w * 4)
    cr = cairo.Context(surf)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    cr.set_source_rgba(1.0, 0.0, 0.0, 0.5)    # half-transparent red
    cr.rectangle(0, 0, w, h)
    cr.fill()
    surf.flush()

    b, g, r, a = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(
        h, w, 4)[0, 0].tolist()
    assert (b, g) == (0, 0) and a == 128, f"unexpected layout {(b, g, r, a)}"
    assert r == 128, f"not premultiplied (expected 128, got {r})"
    print("layered-window pixel contract OK (premultiplied BGRA, zero-copy)")


def test_swat_semantics():
    _host, ctl = build()
    ctl.motor.st.state = LANDED
    ctl.on_swat()
    assert ctl.motor.st.state == SQUASHED and ctl.flies_swatted == 1
    ctl.on_swat()                       # already dead: no double count
    assert ctl.flies_swatted == 1
    _host2, ctl2 = build()
    ctl2.motor.st.state = "flying"
    ctl2.on_swat()
    assert ctl2.swats_dodged == 1 and ctl2.motor.st.state == "escape"
    ctl3 = build()[1]
    ctl3.motor.st.state = TAKEOFF
    ctl3.on_swat()
    assert ctl3.motor.st.state == SQUASHED, "startle window must be killable"
    print("swat semantics OK (ground=kill, air=dodge, takeoff=kill)")


def test_hit_radius():
    _host, ctl = build()
    r = ctl.hit_radius()
    assert 0 < r < WIN / 2, f"hit radius {r} must fit inside the window"
    print(f"hit radius {r:.1f}px fits in {WIN}px window OK")


if __name__ == "__main__":
    test_registry()
    test_native_backend_is_usable()
    test_controller_loop()
    test_grab_bounds_at_screen_edges()
    test_blind_host_survives()
    test_drawing_surfaces()
    test_layered_window_pixel_contract()
    test_swat_semantics()
    test_hit_radius()
    print("\nALL BACKEND CONTRACT TESTS PASSED")
