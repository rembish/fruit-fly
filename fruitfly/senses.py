"""Turn the desktop into sensory input for the fly brain.

Vision is retinotopic and real: each eye is the actual hexagonal lattice of
~790 columns from the FlyWire column assignments, and every photoreceptor
neuron is driven at its own rate from the luminance its column sees in a
screen patch beside the fly. Phototransduction adapts (photoreceptors
respond to contrast against a slowly-updated baseline, not absolute light),
and photoreceptor output is histaminergic (inhibitory) in the compiled
connectome, so ON/OFF processing downstream is the real circuit's job.

The cursor is rendered INTO the retina with angular size growing as it
nears the fly (the desktop has no depth, so perspective is simulated at
the renderer; the detection itself happens in the fly's optic lobe).

A scaled-down direct injection into LC4/LPLC2 remains as a safety net for
escape reliability — disable it with pure_retina=True to trust the eyes
completely.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

PATCH = 96          # retina sampling grid, pixels (per eye)
EYE_OFFSET = 80.0   # px from fly to each eye's gaze center
EYE_RADIUS = 120.0  # px of screen each eye sees (half-width of patch)


class Retina:
    """Maps screen patches onto photoreceptor firing rates, per column."""

    # Photoreceptors release continuously in the light; their tonic rate
    # must be high enough that the (histaminergic, inhibitory) drive holds
    # the biased lamina cells quiet — darkness then disinhibits (OFF).
    R_TONIC = 5.0     # Hz in darkness
    GAIN = 40.0       # Hz per unit of contrast (lum - baseline)
    LUM_GAIN = 45.0   # Hz per unit of absolute luminance
    R_MAX = 70.0      # Hz ceiling
    TAU_ADAPT = 1.5   # s, baseline adaptation time constant

    # Lamina OFF response (computed here because L cells are graded,
    # non-spiking neurons; this is their textbook transfer function):
    # transient firing on local darkening against the adapted baseline.
    L_R0 = 1.0        # Hz at steady state
    L_GAIN = 90.0     # Hz per unit of darkening (baseline - lum)
    L_MAX = 100.0     # Hz ceiling

    def __init__(self, retina_data: dict[str, np.ndarray]):
        self.eyes = {}
        for e in ("L", "R"):
            xy = retina_data[f"{e}_xy"]          # (ncols, 2) unit disc
            px = np.clip(((xy * 0.5 + 0.5) * (PATCH - 1)).astype(np.int32),
                         0, PATCH - 1)
            self.eyes[e] = {
                "idx": retina_data[f"{e}_idx"],  # photoreceptor neuron ids
                "col": retina_data[f"{e}_col"],  # column ordinal per photorec.
                "lam_idx": retina_data[f"{e}_lam_idx"],  # L1/L2/L3 ids
                "lam_col": retina_data[f"{e}_lam_col"],
                "px": px,                        # column -> patch pixel
                "xy": xy,
                "baseline": np.full(len(xy), 0.5, dtype=np.float32),
            }

    def process(self, eye: str, patch: np.ndarray | None,
                cursor_px: tuple[float, float] | None, cursor_r: float,
                dt: float):
        """One eye: patch (PATCH x PATCH luminance in [0,1]) -> (idx, rates).

        cursor_px: cursor position in patch pixel coords (None if not seen);
        cursor_r: its rendered radius in patch pixels (perspective-scaled).
        """
        E = self.eyes[eye]
        if patch is None:
            return []
        lum = patch[E["px"][:, 1], E["px"][:, 0]].astype(np.float32)

        if cursor_px is not None and cursor_r > 0:
            d2 = ((E["px"][:, 0] - cursor_px[0]) ** 2
                  + (E["px"][:, 1] - cursor_px[1]) ** 2)
            lum = np.where(d2 <= cursor_r * cursor_r, lum * 0.1, lum)

        base = E["baseline"]
        darkening = np.clip(base - lum, 0.0, None)  # before baseline update
        base += (lum - base) * min(1.0, dt / self.TAU_ADAPT)
        contrast = lum - base
        col_rates = np.clip(
            self.R_TONIC + self.GAIN * contrast + self.LUM_GAIN * lum,
            0.0, self.R_MAX)
        lam_rates = np.clip(self.L_R0 + self.L_GAIN * darkening,
                            0.0, self.L_MAX)
        return [(E["idx"], col_rates[E["col"]]),
                (E["lam_idx"], lam_rates[E["lam_col"]])]


@dataclass
class SensoryFrame:
    """Raw percepts gathered on the GTK thread (X11 calls live there)."""
    cursor_x: float = -1e9
    cursor_y: float = -1e9
    patch_L: np.ndarray | None = None   # PATCH x PATCH luminance, left eye
    patch_R: np.ndarray | None = None
    patch_dt: float = 0.1               # s since previous patches


@dataclass
class Senses:
    retina: Retina | None = None
    # direct LC4/LPLC2 injection safety net; 0.0 = pure retina
    loom_injection: float = 0.4
    loom_radius: float = 260.0     # px: cursor closer than this is "seen"
    panic_radius: float = 110.0    # px: strong looming zone
    loom_rate_max: float = 120.0   # Hz on LC4/LPLC2 at full threat
    approach_gain: float = 0.12    # extra threat per px/s of approach speed

    _last_dist: float = field(default=1e9, repr=False)
    _last_t: float = field(default=0.0, repr=False)

    @staticmethod
    def eye_center(fly_x: float, fly_y: float, heading: float, eye: str):
        side = -1.0 if eye == "L" else 1.0
        ang = heading + side * math.pi / 2
        return (fly_x + math.cos(ang) * EYE_OFFSET,
                fly_y + math.sin(ang) * EYE_OFFSET)

    def cursor_in_eye(self, frame: SensoryFrame, fly_x, fly_y, heading, eye):
        """Cursor position in an eye's patch coords + perspective radius."""
        cx, cy = self.eye_center(fly_x, fly_y, heading, eye)
        rel_x, rel_y = frame.cursor_x - cx, frame.cursor_y - cy
        if abs(rel_x) > EYE_RADIUS * 1.3 or abs(rel_y) > EYE_RADIUS * 1.3:
            return None, 0.0
        scale = PATCH / (2 * EYE_RADIUS)
        px = (rel_x + EYE_RADIUS) * scale
        py = (rel_y + EYE_RADIUS) * scale
        dist = math.hypot(frame.cursor_x - fly_x, frame.cursor_y - fly_y)
        r_screen = min(70.0, 2600.0 / max(dist, 30.0))
        return (px, py), r_screen * scale

    def rates(self, frame: SensoryFrame, fly_x: float, fly_y: float,
              heading: float, t: float
              ) -> tuple[list, float, float]:
        """Sense the world -> (brain stimuli, threat 0-1, cursor bearing).

        Stimuli are (neuron_indices_or_population_name, rate_hz) pairs
        ready for `Brain.set_stimulus`.
        """
        dx = frame.cursor_x - fly_x
        dy = frame.cursor_y - fly_y
        dist = math.hypot(dx, dy)

        # approach speed (px/s), positive when cursor is closing in
        dt = max(1e-3, t - self._last_t)
        approach = (self._last_dist - dist) / dt if self._last_t else 0.0
        self._last_dist, self._last_t = dist, t

        threat = 0.0
        if dist < self.loom_radius:
            prox = 1.0 - dist / self.loom_radius
            threat = prox * prox
            if approach > 0:
                threat += prox * min(
                    1.0, self.approach_gain * approach / 100.0)
            if dist < self.panic_radius:
                threat = max(threat, 0.85)
        threat = min(1.0, threat)

        bearing = math.atan2(dy, dx) - heading
        left_side = math.sin(bearing) < 0  # screen y grows downward

        out: list = []
        # the eyes: actual pixels through the actual retina
        if self.retina is not None:
            for eye, patch in (("L", frame.patch_L), ("R", frame.patch_R)):
                cur, cur_r = self.cursor_in_eye(frame, fly_x, fly_y,
                                                heading, eye)
                out += self.retina.process(eye, patch, cur, cur_r,
                                           frame.patch_dt)

        # safety-net loom injection (scaled; 0 in pure-retina mode)
        loom = self.loom_rate_max * threat * self.loom_injection
        if loom > 0:
            out += [
                ("LC4_L", loom if left_side else loom * 0.15),
                ("LC4_R", loom if not left_side else loom * 0.15),
                ("LPLC2_L", loom if left_side else loom * 0.15),
                ("LPLC2_R", loom if not left_side else loom * 0.15),
            ]

        return out, threat, math.atan2(dy, dx)
