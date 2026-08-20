"""Cocoa backend — macOS, via PyObjC. No X11, no GTK.

Developed on Linux against the documented AppKit/Quartz APIs, and since
run on a Mac, where the fly does appear and fly. Most of it is still
lightly exercised, so please report what breaks -- the first thing that
did was Ctrl-C, see stop_event_loop.

Design notes:
  * the fly lives in a borderless, transparent, non-activating NSWindow
    at status level, joining all Spaces
  * click-through is `NSView.hitTest_` returning nil outside the fly's
    body — the same semantics as the X11 input shape, and it needs no
    Accessibility permission
  * the sprite is still drawn by the shared cairo code; the ARGB32
    surface is wrapped as a CGImage each frame (cairo's little-endian
    ARGB32 is exactly premultiplied-first / 32-little for CoreGraphics)
  * screen grabs use CGWindowListCreateImage restricted to windows
    *below* ours, so the fly never sees itself. This needs the Screen
    Recording permission; without it the fly simply flies blind
"""

from __future__ import annotations

import contextlib
import signal
from typing import TYPE_CHECKING

import cairo
import numpy as np

from ..core import HUD_H, HUD_W, WIN
from .base import Host, rgb_to_luminance

if TYPE_CHECKING:
    from ..core import Controller

try:
    import AppKit
    import objc
    import Quartz
    from PyObjCTools import AppHelper
    _IMPORT_ERROR = None
except Exception as _e:                      # pragma: no cover - macOS only
    objc = AppKit = Quartz = AppHelper = None
    _IMPORT_ERROR = _e


#: NSEvent constructor for the synthetic event that wakes the run loop.
#: Kept as a string because the selector is 74 characters and will not
#: fit the line limit written as an attribute access.
_WAKE_SELECTOR = ("otherEventWithType_location_modifierFlags_timestamp_"
                  "windowNumber_context_subtype_data1_data2_")


def _cairo_surface_to_cgimage(surface, w, h):
    """Wrap a cairo ARGB32 ImageSurface as a CGImage (no pixel copy loop)."""
    surface.flush()
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    bitmap_info = (Quartz.kCGImageAlphaPremultipliedFirst
                   | Quartz.kCGBitmapByteOrder32Little)
    return Quartz.CGImageCreate(w, h, 8, 32, stride, cs, bitmap_info,
                                provider, None, False,
                                Quartz.kCGRenderingIntentDefault)


if AppKit is not None:                       # pragma: no cover - macOS only

    class _NonActivatingWindow(AppKit.NSWindow):
        """Never steals focus: clicks reach the fly without activating us."""

        def canBecomeKeyWindow(self):
            return False

        def canBecomeMainWindow(self):
            return False

    class _FlyView(AppKit.NSView):
        """Draws the sprite; only its body accepts clicks."""

        def drawRect_(self, _rect):
            host = getattr(self, "host", None)
            if host is None or host.controller is None:
                return
            img = host.render(hud=bool(getattr(self, "is_hud", False)))
            if img is None:
                return
            ns_ctx = AppKit.NSGraphicsContext.currentContext()
            if ns_ctx is None:
                return
            ctx = ns_ctx.CGContext()
            b = self.bounds()
            Quartz.CGContextSaveGState(ctx)
            # cairo is y-down, CoreGraphics is y-up
            Quartz.CGContextTranslateCTM(ctx, 0, b.size.height)
            Quartz.CGContextScaleCTM(ctx, 1.0, -1.0)
            Quartz.CGContextDrawImage(
                ctx, Quartz.CGRectMake(0, 0, b.size.width, b.size.height), img)
            Quartz.CGContextRestoreGState(ctx)

        def hitTest_(self, point):
            if getattr(self, "is_hud", False):
                return None                   # HUD is fully click-through
            host = getattr(self, "host", None)
            if host is None or host.controller is None:
                return None
            local = self.convertPoint_fromView_(point, None)
            dx = local.x - WIN / 2.0
            dy = local.y - WIN / 2.0
            r = host.controller.hit_radius()
            return self if dx * dx + dy * dy <= r * r else None

        def mouseDown_(self, _event):
            host = getattr(self, "host", None)
            if host is not None and host.controller is not None:
                host.controller.on_swat()

        def rightMouseDown_(self, event):
            self.mouseDown_(event)

    class _Ticker(AppKit.NSObject):
        """NSTimer target driving Controller.tick at ~60 Hz."""

        def tick_(self, _timer):
            host = getattr(self, "host", None)
            if host is None:
                return
            if host.interrupted:          # Ctrl-C arrived; leave the loop
                host.stop_event_loop()
                return
            if host.controller is not None:
                host.controller.tick()


class CocoaHost(Host):
    name = "cocoa"
    description = "Cocoa/AppKit (macOS); needs PyObjC"

    @classmethod
    def available(cls):
        if _IMPORT_ERROR is not None:
            return False, (f"PyObjC not importable ({_IMPORT_ERROR}). "
                           f"Install: pip install "
                           f"pyobjc-framework-Cocoa pyobjc-framework-Quartz")
        return True, ""

    interrupted = False

    def __init__(self, hud: bool = False,
                 recordable: bool = False):  # noqa: ARG002 - never hides
        if _IMPORT_ERROR is not None:
            raise RuntimeError(self.available()[1])
        self._cairo = cairo
        self.controller: Controller | None = None
        self._capture_ok: bool | None = None

        self.app = AppKit.NSApplication.sharedApplication()
        # accessory: no Dock icon, no menu bar takeover
        self.app.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)

        frame = AppKit.NSScreen.mainScreen().frame()
        self.scr_w = int(frame.size.width)
        self.scr_h = int(frame.size.height)

        self.fly_win, self.fly_view = self._make_window(WIN, WIN, hud=False)
        if hud:
            self.hud_win, self.hud_view = self._make_window(HUD_W, HUD_H,
                                                            hud=True)
            self.hud_win.setFrameOrigin_(
                Quartz.CGPointMake(10, self.scr_h - HUD_H - 10))
        else:
            self.hud_win = self.hud_view = None

        # cairo surfaces reused every frame
        self._fly_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIN, WIN)
        self._hud_surface = (cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                                HUD_W, HUD_H) if hud else None)

    def _make_window(self, w, h, hud: bool):
        win = _NonActivatingWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(
                Quartz.CGRectMake(0, 0, w, h),
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(AppKit.NSColor.clearColor())
        win.setLevel_(AppKit.NSStatusWindowLevel)
        win.setHasShadow_(False)
        win.setIgnoresMouseEvents_(hud)
        win.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        view = _FlyView.alloc().initWithFrame_(Quartz.CGRectMake(0, 0, w, h))
        view.host = self
        view.is_hud = hud
        win.setContentView_(view)
        return win, view

    # ---------------------------------------------------- host interface
    def screen_size(self):
        return self.scr_w, self.scr_h

    def pointer(self):
        p = AppKit.NSEvent.mouseLocation()
        return float(p.x), float(self.scr_h - p.y)   # -> y down

    def move_window(self, x, y):
        # NSWindow origin is bottom-left of the main screen
        self.fly_win.setFrameOrigin_(
            Quartz.CGPointMake(x, self.scr_h - y - WIN))

    def request_redraw(self):
        self.fly_view.setNeedsDisplay_(True)
        if self.hud_view is not None:
            self.hud_view.setNeedsDisplay_(True)

    def grab(self, x, y, side, out):
        if self._capture_ok is False:
            return None
        if self._capture_ok is None:
            self._capture_ok = self._check_capture_permission()
            if not self._capture_ok:
                return None
        # capture only what is *below* our window, so the fly can't see
        # its own sprite (or the HUD) in its retina
        try:
            img = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(x, y, side, side),
                Quartz.kCGWindowListOptionOnScreenBelowWindow,
                self.fly_win.windowNumber(),
                Quartz.kCGWindowImageNominalResolution
                | Quartz.kCGWindowImageBoundsIgnoreFraming)
        except Exception:
            return None
        if img is None or Quartz.CGImageGetWidth(img) == 0:
            return None
        buf = bytearray(out * out * 4)
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(
            buf, out, out, 8, out * 4, cs,
            Quartz.kCGImageAlphaPremultipliedLast)
        if ctx is None:
            return None
        Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, out, out), img)
        arr = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(out, out, 4)
        return rgb_to_luminance(arr[::-1])   # CG bitmaps are bottom-up

    def _check_capture_permission(self) -> bool:
        pre = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
        req = getattr(Quartz, "CGRequestScreenCaptureAccess", None)
        if pre is None:
            return True                       # pre-10.15: no permission model
        if pre():
            return True
        if req is not None and req():
            return True
        print("[fly] macOS Screen Recording permission not granted — the "
              "fly is blind (its brain still runs). Grant it in System "
              "Settings > Privacy & Security > Screen Recording, then "
              "restart.", flush=True)
        return False

    # ------------------------------------------------------------ render
    def render(self, hud: bool = False):
        """Draw the current frame with cairo, return it as a CGImage."""
        assert self.controller is not None, "attach() before run()"
        if hud:
            if self._hud_surface is None:
                return None
            cr = self._cairo.Context(self._hud_surface)
            self.controller.draw_hud(cr)
            return _cairo_surface_to_cgimage(self._hud_surface, HUD_W, HUD_H)
        cr = self._cairo.Context(self._fly_surface)
        self.controller.draw(cr)
        return _cairo_surface_to_cgimage(self._fly_surface, WIN, WIN)

    # ------------------------------------------------------- wiring/loop
    def attach(self, controller: Controller) -> None:
        self.controller = controller

    def run(self):
        self.fly_win.orderFrontRegardless()
        if self.hud_win is not None:
            self.hud_win.orderFrontRegardless()

        ticker = _Ticker.alloc().init()
        ticker.host = self
        self._ticker = ticker                 # keep alive
        self._timer = (AppKit.NSTimer
                       .scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                           1.0 / 60.0, ticker, objc.selector(
                               ticker.tick_, signature=b"v@:@"), None, True))
        # Handle SIGINT ourselves rather than letting PyObjC install its
        # own: a Python signal handler cannot run while the process is
        # blocked in AppKit, so the flag is only seen when the timer next
        # runs Python — and a KeyboardInterrupt raised there is swallowed
        # by PyObjC's callback machinery instead of leaving runEventLoop.
        # Latching a flag the tick checks avoids both problems.
        self.interrupted = False
        previous = signal.signal(signal.SIGINT, self._on_interrupt)
        try:
            with contextlib.suppress(KeyboardInterrupt):
                AppHelper.runEventLoop(installInterrupt=False)
        finally:
            with contextlib.suppress(Exception):
                signal.signal(signal.SIGINT, previous)

    def _on_interrupt(self, _signum, _frame) -> None:
        """Ctrl-C: latch it. The 60Hz tick acts on it a frame later."""
        self.interrupted = True

    def stop_event_loop(self) -> None:
        """Leave runEventLoop so app.py can shut the fly down cleanly.

        NSApp.stop_ does not end the loop by itself: it only takes effect
        once the loop processes another *event*, and timers are not
        events. This app is non-activating and click-through, so it can
        run for ever without receiving one -- which is exactly why Ctrl-C
        looked like it did nothing. Post a dummy event to wake it.

        stop_ rather than terminate_ on purpose: terminate_ would end the
        process here and skip the brain-thread shutdown in app.py.
        """
        app = AppKit.NSApp()
        if app is None:
            return
        app.stop_(None)
        kind = getattr(AppKit, "NSEventTypeApplicationDefined",
                       getattr(AppKit, "NSApplicationDefined", 15))
        with contextlib.suppress(Exception):
            make = getattr(AppKit.NSEvent, _WAKE_SELECTOR)
            wake = make(kind, (0.0, 0.0), 0, 0.0, 0, None, 0, 0, 0)
            app.postEvent_atStart_(wake, True)

    def shutdown(self):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.invalidate()
