"""Turn the desktop into sensory input for the fly brain.

Two channels, both mapped onto real sensory populations of the connectome:

  Looming (your cursor): flies detect approaching objects with dedicated
  visual projection neurons (LC4, LPLC2, LC6) that drive the giant fiber
  escape circuit. The cursor's proximity and approach speed toward the fly
  set the Poisson firing rate of those neurons on the eye facing the cursor.

  Light (the screen): mean luminance sampled around the fly modulates a
  low baseline drive of the photoreceptors of each eye, so the optic lobe
  is doing *something* with your actual desktop content.

This module only computes {population: rate_hz} dictionaries; the brain
thread applies them with Brain.set_stimulus().
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SensoryFrame:
    """Raw percepts gathered on the GTK thread (X11 calls live there)."""
    cursor_x: float = -1e9
    cursor_y: float = -1e9
    lum_left: float = 0.5    # 0..1 luminance to the fly's left
    lum_right: float = 0.5   # 0..1 luminance to the fly's right


@dataclass
class Senses:
    # tuning
    loom_radius: float = 260.0     # px: cursor closer than this is "seen"
    panic_radius: float = 110.0    # px: strong looming zone
    loom_rate_max: float = 120.0   # Hz on LC4/LPLC2 at full threat
    photo_rate_max: float = 15.0   # Hz baseline photoreceptor drive
    approach_gain: float = 0.12    # extra threat per px/s of approach speed

    _last_dist: float = field(default=1e9, repr=False)
    _last_t: float = field(default=0.0, repr=False)

    def rates(self, frame: SensoryFrame, fly_x: float, fly_y: float,
              heading: float, t: float) -> dict[str, float]:
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
                threat += min(1.0, self.approach_gain * approach / 100.0) * prox
            if dist < self.panic_radius:
                threat = max(threat, 0.85)
        threat = min(1.0, threat)

        # which eye sees the cursor: angle of cursor relative to heading
        bearing = math.atan2(dy, dx) - heading
        left_side = math.sin(bearing) < 0  # screen y grows downward

        loom = self.loom_rate_max * threat
        out = {
            "LC4_L": loom if left_side else loom * 0.15,
            "LC4_R": loom if not left_side else loom * 0.15,
            "LPLC2_L": loom if left_side else loom * 0.15,
            "LPLC2_R": loom if not left_side else loom * 0.15,
            "photoreceptor_L": self.photo_rate_max * frame.lum_left,
            "photoreceptor_R": self.photo_rate_max * frame.lum_right,
        }
        out["_threat"] = threat  # consumed by motor for escape direction
        out["_bearing"] = math.atan2(dy, dx)
        return out
