"""The contract every window-system backend implements.

A Host owns the platform side of the fly: a small always-on-top window
that follows it, an optional telemetry panel, the global pointer, and
grabs of the screen the fly is looking at. Everything else — brain,
senses, motor, and the cairo drawing of the sprite itself — lives in
`fruitfly.core` and is shared by all backends.

Coordinates are **logical pixels with a top-left origin and y growing
down**, matching the fly's own world. Backends whose native coordinates
differ (Cocoa's bottom-left origin) convert at their boundary, so the
controller never learns which platform it is on.

Lifecycle:

    host = SomeHost(hud=True)
    controller = Controller(brain, senses, host, ...)
    host.attach(controller)     # wire draw/click callbacks
    controller.start()          # brain thread
    host.run()                  # blocks in the platform event loop
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass


class Host(abc.ABC):
    """Platform window-system backend."""

    #: short identifier used by --backend and in messages
    name: str = "host"
    #: human-readable, for error messages
    description: str = ""

    def __init__(self, hud: bool = False) -> None:  # noqa: B027
        """Create the fly window, plus the telemetry panel if `hud`.

        Not abstract: a backend needing no setup may inherit this.
        """

    # ------------------------------------------------------- capabilities
    @classmethod
    def available(cls) -> tuple[bool, str]:
        """Can this backend run here? Returns (ok, reason_if_not)."""
        return True, ""

    # ---------------------------------------------------------- geometry
    @abc.abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Screen size in logical pixels."""

    @abc.abstractmethod
    def pointer(self) -> tuple[float, float]:
        """Global cursor position, top-left origin, y down."""

    @abc.abstractmethod
    def move_window(self, x: int, y: int) -> None:
        """Move the fly window so its top-left corner sits at (x, y)."""

    # ----------------------------------------------------------- capture
    @abc.abstractmethod
    def grab(self, x: int, y: int, side: int, out: int) -> np.ndarray | None:
        """Grab a `side`x`side` screen square at (x, y), top-left origin.

        Returns an (out, out) float32 luminance array in [0, 1], or None
        if screen capture is unavailable (e.g. permission not granted) —
        the fly then flies blind rather than the app dying. Backends
        should exclude the fly's own window if they can, so it does not
        see itself.
        """

    # ------------------------------------------------------------ paint
    @abc.abstractmethod
    def request_redraw(self) -> None:
        """Schedule a repaint of the fly window (and HUD, if shown)."""

    # ------------------------------------------------------- wiring/loop
    @abc.abstractmethod
    def attach(self, controller) -> None:
        """Wire the controller's draw/click callbacks into the toolkit.

        The backend must call `controller.draw(cr)` with a WIN x WIN
        cairo context, `controller.draw_hud(cr)` for the panel, and
        `controller.on_swat()` when a click lands within
        `controller.hit_radius()` of the window centre. Clicks outside
        that radius must pass through to whatever is underneath.
        """

    @abc.abstractmethod
    def run(self) -> None:
        """Show the windows and run the platform event loop until quit.

        Must drive `controller.tick()` at roughly 60 Hz and return on
        Ctrl-C or window close.
        """

    def shutdown(self) -> None:  # noqa: B027 - optional hook, not abstract
        """Optional teardown after `run` returns; backends may skip it."""


# ------------------------------------------------------------- helpers
def rgb_to_luminance(arr: np.ndarray) -> np.ndarray:
    """(h, w, >=3) uint8 -> (h, w) float32 luminance in [0, 1]."""
    return arr[..., :3].mean(axis=2).astype(np.float32) / 255.0
