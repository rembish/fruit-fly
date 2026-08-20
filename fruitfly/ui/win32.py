"""Win32 backend — Windows, via ctypes. No extra Python dependency.

UNTESTED ON HARDWARE: written against the documented Win32 APIs but
developed on Linux. Please report what breaks.

Design notes:
  * the fly lives in a WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE
    popup, painted with UpdateLayeredWindow
  * UpdateLayeredWindow takes a premultiplied-BGRA bitmap, which is
    byte-for-byte what cairo's FORMAT_ARGB32 produces on little-endian,
    so cairo draws *directly into* the DIB memory — no pixel copy
  * click-through is free: hit testing of a layered window is per-pixel
    alpha, so clicks land only where the fly actually is, and pass
    through everywhere else. WM_NCHITTEST additionally enforces the same
    hit radius the other backends use
  * screen grabs are BitBlt/StretchBlt from the screen DC, with
    SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) on our own windows
    (Windows 10 2004+) so the fly cannot see itself
"""

from __future__ import annotations

import contextlib
import ctypes
import time
from typing import TYPE_CHECKING

import cairo
import numpy as np

from ..core import HUD_H, HUD_W, WIN
from .base import Host

if TYPE_CHECKING:
    from ..core import Controller

try:
    from ctypes import wintypes

    # these ctypes members exist only on Windows, so type checkers on
    # other platforms cannot see them
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)  # type: ignore[attr-defined]
    _IMPORT_ERROR: Exception | None = None
except Exception as _e:                    # non-Windows, or no ctypes.WinDLL
    wintypes = user32 = gdi32 = None  # type: ignore[assignment]
    _IMPORT_ERROR = _e


# --------------------------------------------------------------- constants
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020

SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
HALFTONE = 4

PM_REMOVE = 0x0001
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_NCHITTEST = 0x0084
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
HTCLIENT = 1
HTTRANSPARENT = -1

SM_CXSCREEN, SM_CYSCREEN = 0, 1
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


if _IMPORT_ERROR is None:                  # pragma: no cover - Windows only

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,  # type: ignore[attr-defined]
                                 wintypes.WPARAM, wintypes.LPARAM)

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte),
                    ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte)]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR)]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD), ("pt", POINT)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.restype = LRESULT
    user32.GetDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.restype = wintypes.HGDIOBJ


def _top_down_dib(hdc, w, h):
    """32bpp top-down DIB section; returns (hbitmap, writable buffer)."""
    bmi = BITMAPINFO()
    hdr = bmi.bmiHeader
    hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    hdr.biWidth = w
    hdr.biHeight = -h                      # negative: rows top-down, as cairo
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = 0                  # BI_RGB
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                  ctypes.byref(bits), None, 0)
    if not hbmp or not bits.value:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    buf = (ctypes.c_char * (w * h * 4)).from_address(bits.value)
    return hbmp, buf


class _LayeredWindow:
    """One transparent, always-on-top, cairo-painted window."""

    def __init__(self, host, w, h, clickable: bool):
        self.host = host
        self.w, self.h = w, h
        self.clickable = clickable
        self.origin = [0, 0]

        ex = (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
              | WS_EX_NOACTIVATE)
        if not clickable:
            ex |= WS_EX_TRANSPARENT
        self.hwnd = user32.CreateWindowExW(
            ex, host.class_name, "fruitfly", WS_POPUP,
            0, 0, w, h, None, None, host.hinstance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]  # type: ignore[attr-defined]
        host.windows[self.hwnd] = self

        # keep the fly out of its own eyes (Windows 10 2004+; ignore if old)
        with contextlib.suppress(Exception):
            user32.SetWindowDisplayAffinity(self.hwnd,
                                            WDA_EXCLUDEFROMCAPTURE)

        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        self.hbmp, buf = _top_down_dib(self.screen_dc, w, h)
        self.old_bmp = gdi32.SelectObject(self.mem_dc, self.hbmp)
        # cairo draws straight into the DIB: ARGB32 premultiplied ==
        # the premultiplied BGRA that UpdateLayeredWindow expects
        self.surface = cairo.ImageSurface.create_for_data(
            memoryview(buf), cairo.FORMAT_ARGB32, w, h, w * 4)

    def show(self):
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def paint(self, draw_fn):
        cr = cairo.Context(self.surface)
        draw_fn(cr)
        self.surface.flush()
        pt_dst = POINT(int(self.origin[0]), int(self.origin[1]))
        size = SIZE(self.w, self.h)
        pt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            self.hwnd, self.screen_dc, ctypes.byref(pt_dst),
            ctypes.byref(size), self.mem_dc, ctypes.byref(pt_src), 0,
            ctypes.byref(blend), ULW_ALPHA)

    def destroy(self):
        with contextlib.suppress(Exception):
            gdi32.SelectObject(self.mem_dc, self.old_bmp)
            gdi32.DeleteObject(self.hbmp)
            gdi32.DeleteDC(self.mem_dc)
            user32.ReleaseDC(None, self.screen_dc)
            user32.DestroyWindow(self.hwnd)


class Win32Host(Host):
    name = "win32"
    description = "Win32 layered windows (Windows 10+); no extra deps"

    @classmethod
    def available(cls):
        if _IMPORT_ERROR is not None:
            return False, f"not a Windows system ({_IMPORT_ERROR})"
        return True, ""

    def __init__(self, hud: bool = False):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(self.available()[1])
        self.controller: Controller | None = None
        self.windows: dict = {}
        self._quit = False
        self._capture: tuple | None = None

        self._set_dpi_aware()
        self.hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)  # type: ignore[attr-defined]
        self.class_name = "FruitflyWindow"
        self._wndproc = WNDPROC(self._on_message)   # keep alive!
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinstance
        wc.lpszClassName = self.class_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()  # type: ignore[attr-defined]
            if err not in (0, 1410):                # 1410: already registered
                raise ctypes.WinError(err)  # type: ignore[attr-defined]

        self.scr_w = user32.GetSystemMetrics(SM_CXSCREEN)
        self.scr_h = user32.GetSystemMetrics(SM_CYSCREEN)
        self.fly = _LayeredWindow(self, WIN, WIN, clickable=True)
        self.hud = (_LayeredWindow(self, HUD_W, HUD_H, clickable=False)
                    if hud else None)
        if self.hud is not None:
            self.hud.origin = [10, 10]

    @staticmethod
    def _set_dpi_aware():
        """Work in real pixels, so our coords match the cursor's."""
        try:                                    # Windows 10 1703+
            ctx = ctypes.c_void_p(-4)           # PER_MONITOR_AWARE_V2
            if user32.SetProcessDpiAwarenessContext(ctx):
                return
        except Exception:
            pass
        with contextlib.suppress(Exception):
            user32.SetProcessDPIAware()

    # ------------------------------------------------------- window proc
    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            win = self.windows.get(hwnd)
            if win is not None and win.clickable and self.controller:
                # screen coords -> window-local
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                dx = x - (win.origin[0] + WIN / 2.0)
                dy = y - (win.origin[1] + WIN / 2.0)
                r = self.controller.hit_radius()
                return HTCLIENT if dx * dx + dy * dy <= r * r \
                    else HTTRANSPARENT
            return HTTRANSPARENT
        if msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            if self.controller is not None:
                self.controller.on_swat()
            return 0
        if msg in (WM_CLOSE, WM_DESTROY):
            self._quit = True
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------------------------------------------------- host interface
    def screen_size(self):
        return self.scr_w, self.scr_h

    def pointer(self):
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return float(pt.x), float(pt.y)

    def move_window(self, x, y):
        self.fly.origin = [x, y]      # applied by the next UpdateLayeredWindow

    def request_redraw(self):
        if self.controller is None:
            return
        self.fly.paint(self.controller.draw)
        if self.hud is not None:
            self.hud.paint(self.controller.draw_hud)

    def grab(self, x, y, side, out):
        cap = self._capture
        if cap is None or cap[0] != out:
            if cap is not None:
                gdi32.SelectObject(cap[2], cap[4])
                gdi32.DeleteObject(cap[3])
                gdi32.DeleteDC(cap[2])
            screen_dc = user32.GetDC(None)
            mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            hbmp, buf = _top_down_dib(screen_dc, out, out)
            old = gdi32.SelectObject(mem_dc, hbmp)
            gdi32.SetStretchBltMode(mem_dc, HALFTONE)
            cap = self._capture = (out, screen_dc, mem_dc, hbmp, old, buf)
        _out, screen_dc, mem_dc, _hbmp, _old, buf = cap
        ok = gdi32.StretchBlt(mem_dc, 0, 0, out, out,
                              screen_dc, x, y, side, side,
                              SRCCOPY | CAPTUREBLT)
        if not ok:
            return None
        arr = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(out, out, 4)
        return arr[..., :3].mean(axis=2).astype(np.float32) / 255.0

    # -------------------------------------------------------------- loop
    def attach(self, controller: Controller) -> None:
        self.controller = controller

    def run(self):
        self.fly.show()
        if self.hud is not None:
            self.hud.show()
        msg = MSG()
        frame = 1.0 / 60.0
        try:
            while not self._quit:
                t0 = time.perf_counter()
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0,
                                          PM_REMOVE):
                    if msg.message == WM_QUIT:
                        self._quit = True
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                if self._quit:
                    break
                assert self.controller is not None, "attach() before run()"
                self.controller.tick()
                left = frame - (time.perf_counter() - t0)
                if left > 0:
                    time.sleep(left)      # keeps Ctrl-C responsive
        except KeyboardInterrupt:
            pass

    def shutdown(self):
        for win in list(self.windows.values()):
            win.destroy()
        self.windows.clear()
        cap = self._capture
        if cap is not None:
            gdi32.SelectObject(cap[2], cap[4])
            gdi32.DeleteObject(cap[3])
            gdi32.DeleteDC(cap[2])
            user32.ReleaseDC(None, cap[1])
            self._capture = None
