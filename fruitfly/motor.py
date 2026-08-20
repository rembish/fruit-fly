"""Read out descending neurons and turn spikes into desktop flight.

The mapping is grounded in what these neurons actually do in the fly:

  GF (DNp01, the giant fiber)  -> escape. The GF fires sporadically even at
                                  rest in this model (it integrates from the
                                  whole brain), but looming drives it ~10x
                                  harder, so the readout thresholds its
                                  *rate* like real downstream motor circuits:
                                  lone spikes -> twitchy jinks and startles,
                                  a sustained GF burst -> directed escape.
  DNa02 left/right             -> steering: rate asymmetry yaws the fly
                                  toward the more active side's direction
                                  (DNa02 drives ipsilateral turns).
  DNp09                        -> forward drive.
  MDN                          -> backward drive (moonwalker neurons).
  all descending neurons       -> arousal: overall descending activity
                                  decides whether the fly flies or sits.

Kinematics are fly-like: forward thrust along the heading, drag, and
body-saccade turns rather than smooth arcs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

FLYING, LANDED, ESCAPE, SQUASHED = "flying", "landed", "escape", "squashed"
TAKEOFF = "takeoff"   # startled: wings up, feet still down — squashable!

SPLAT_S = 4.0   # how long the remains stay on screen


@dataclass
class MotorState:
    x: float = 400.0
    y: float = 300.0
    heading: float = 0.0          # radians, screen coords (y down)
    speed: float = 0.0            # px/s
    state: str = LANDED
    wing_phase: float = 0.0
    last_event: str = ""          # human-readable, for the HUD/log


class MotorMap:
    # Idle GF hums at ~6 Hz in clustered doublets; looming drives ~50 Hz
    # sustained. A slow rate estimate + high threshold separates the two.
    ESCAPE_GF_HZ = 30.0   # summed GF rate (2 neurons) for a full escape
    GF_TAU = 0.30         # s, GF rate estimator time constant
    ESCAPE_REFRACT = 0.7  # s after an escape before the next one
    JINK_COOLDOWN = 1.2   # s between spontaneous startle jinks

    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.st = MotorState(x=width * 0.5, y=height * 0.4)
        self._escape_until = 0.0
        self._escape_dir = 0.0
        self._calm_since = 0.0
        self._takeoff_drive = 0.0
        self._land_drive = 0.0
        self._land_thresh = 2.0
        self._gf_rate = 0.0
        self._last_jink = -10.0
        self._squash_t = 0.0
        self._takeoff_until = 0.0     # end of the vulnerable takeoff window
        self._escape_on_takeoff = False
        self.rng = random.Random(4)

    def _startle(self, t: float, event: str, escape: bool) -> None:
        """Begin takeoff: a real fly needs ~100-200 ms to get airborne
        after its escape circuit fires, and it can be swatted until then.
        (This latency is the entire reason flyswatters work.)"""
        self.st.state = TAKEOFF
        self.st.speed = 0.0
        self.st.last_event = event
        self._takeoff_until = t + self.rng.uniform(0.10, 0.22)
        self._escape_on_takeoff = escape

    def squash(self, t: float) -> None:
        """A swat landed on a sitting fly. It's over."""
        self.st.state = SQUASHED
        self.st.speed = 0.0
        self.st.last_event = "SPLAT."
        self._squash_t = t

    def glancing_blow(self, t: float) -> None:
        """A swat clipped a flying fly: tumble and bolt."""
        st = self.st
        st.state = ESCAPE
        st.last_event = "glancing blow -> tumbling away"
        self._escape_until = t + 0.3
        self._escape_dir = self.rng.uniform(0, 2 * math.pi)

    def _respawn(self) -> None:
        st = self.st
        edge = self.rng.randrange(4)
        m = 30.0
        if edge == 0:
            st.x, st.y = m, self.rng.uniform(m, self.h - m)
        elif edge == 1:
            st.x, st.y = self.w - m, self.rng.uniform(m, self.h - m)
        elif edge == 2:
            st.x, st.y = self.rng.uniform(m, self.w - m), m
        else:
            st.x, st.y = self.rng.uniform(m, self.w - m), self.h - m
        st.heading = math.atan2(self.h / 2 - st.y, self.w / 2 - st.x) \
            + self.rng.uniform(-0.5, 0.5)
        st.state = FLYING
        st.speed = 320.0
        st.last_event = "another fly got in through the window"
        self._gf_rate = 0.0
        self._takeoff_drive = 0.0
        self._land_drive = 0.0

    def update(self, dt: float, t: float, rates: dict[str, float],
               gf_count: int, threat_bearing: float, threat: float) -> MotorState:
        st = self.st

        if st.state == SQUASHED:
            if t - self._squash_t > SPLAT_S:
                self._respawn()
            return st

        # --- giant fiber rate: jinks on lone spikes, escape on bursts -----
        self._gf_rate += (gf_count / max(dt, 1e-3) - self._gf_rate) \
            * min(1.0, dt / self.GF_TAU)
        if self._gf_rate > self.ESCAPE_GF_HZ and st.state != ESCAPE \
                and t - self._escape_until > self.ESCAPE_REFRACT:
            self._gf_rate = 0.0
            if threat > 0.05:  # dart away from the threat, with scatter
                self._escape_dir = threat_bearing + math.pi \
                    + self.rng.uniform(-0.7, 0.7)
            else:
                self._escape_dir = self.rng.uniform(0, 2 * math.pi)
            if st.state == LANDED:
                # grounded: the escape must physically get airborne first
                self._startle(t, "giant fiber burst -> scrambling to "
                              "take off!", escape=True)
            elif st.state == TAKEOFF:
                self._escape_on_takeoff = True
            else:
                st.state = ESCAPE
                st.last_event = "giant fiber burst -> ESCAPE!"
                self._escape_until = t + 0.22
        elif gf_count and st.state == FLYING \
                and t - self._last_jink > self.JINK_COOLDOWN:
            st.heading += self.rng.choice((-1, 1)) * self.rng.uniform(0.6, 1.4)
            st.speed += 180.0
            st.last_event = "giant fiber spike -> jink"
            self._last_jink = t
        elif gf_count and st.state == LANDED and threat < 0.05 \
                and t - self._last_jink > self.JINK_COOLDOWN:
            # startle hop in place: reposition slightly, stay landed
            ang = self.rng.uniform(0, 2 * math.pi)
            st.x += math.cos(ang) * 14.0
            st.y += math.sin(ang) * 14.0
            st.heading = self.rng.uniform(0, 2 * math.pi)
            st.last_event = "giant fiber spike -> startle hop"
            self._last_jink = t

        dna_l = rates.get("DNa02_L", 0.0)
        dna_r = rates.get("DNa02_R", 0.0)
        desc = rates.get("descending", 0.0)
        fwd = rates.get("DNp09", 0.0)
        back = rates.get("MDN", 0.0)

        if st.state == TAKEOFF:
            st.speed = 0.0
            st.wing_phase += dt * 200.0 * 2 * math.pi  # revving up
            if t > self._takeoff_until:  # airborne at last
                if self._escape_on_takeoff:
                    st.state = ESCAPE
                    self._escape_until = t + 0.22
                    st.heading = self._escape_dir
                else:
                    st.state = FLYING
                    st.heading = self.rng.uniform(0, 2 * math.pi)
                st.speed = 260.0
        elif st.state == ESCAPE:
            st.heading = self._escape_dir
            st.speed = 1400.0
            if t > self._escape_until:
                st.state = FLYING
                st.speed = 500.0
        elif st.state == FLYING:
            # steering: DNa02 asymmetry (ipsilateral turns) + saccades.
            # Rate scales below match the tuned brain: DNa02 idles ~5-15 Hz
            # per side, bursts to ~40+ Hz; descending pool idles ~3-6 Hz.
            turn = (dna_r - dna_l) * 0.12
            st.heading += max(-5.0, min(5.0, turn)) * dt
            # body saccade: descending bursts kick the heading
            if self.rng.random() < min(0.9, max(0.0, desc - 4.0) * 0.10) * dt * 10:
                st.heading += self.rng.choice((-1, 1)) * self.rng.uniform(0.5, 1.6)
                st.last_event = "descending burst -> saccade"
            target = 90.0 + 45.0 * min(10.0, desc) + 60.0 * min(5.0, fwd) \
                - 40.0 * min(5.0, back)
            target = max(60.0, target)
            st.speed += (target - st.speed) * min(1.0, 5.0 * dt)
            # landing drive: a leaky accumulator of calm. Grows while the
            # descending pool is below its ~median (5.2 Hz), drains when
            # aroused or threatened, lands when it wins. Gives naturally
            # variable flight bouts without needing unbroken quiet.
            if threat > 0.05:
                self._land_drive = 0.0
            else:
                self._land_drive = max(0.0, self._land_drive
                                       + max(-1.0, min(1.0, 5.8 - desc)) * dt)
            if self._land_drive > self._land_thresh:
                st.state = LANDED
                st.speed = 0.0
                st.last_event = "descending activity low -> landing"
                self._land_drive = 0.0
        else:  # LANDED: sitting, until the brain stirs
            st.speed = 0.0
            # descending bursts above the ~90th pct accumulate takeoff drive
            self._takeoff_drive += max(0.0, desc - 7.5 + fwd) * dt
            self._takeoff_drive *= (1.0 - 0.1 * dt)
            if threat > 0.5:
                self._escape_dir = threat_bearing + math.pi \
                    + self.rng.uniform(-0.7, 0.7)
                self._startle(t, "looming! -> scrambling to take off",
                              escape=True)
                self._takeoff_drive = 0.0
                self._land_drive = 0.0
                self._land_thresh = self.rng.uniform(1.0, 3.0)
            elif self._takeoff_drive > self.rng.uniform(0.5, 2.0):
                self._startle(t, "descending activity -> takeoff",
                              escape=False)
                self._takeoff_drive = 0.0
                self._land_drive = 0.0
                self._land_thresh = self.rng.uniform(1.0, 3.0)

        # --- integrate position ------------------------------------------
        if st.speed > 0.0:
            st.x += math.cos(st.heading) * st.speed * dt
            st.y += math.sin(st.heading) * st.speed * dt
            st.wing_phase += dt * 200.0 * 2 * math.pi  # ~200 Hz wingbeat

        # keep on screen: turn away from edges like a fly in a bottle
        margin = 24.0
        bounced = False
        if st.x < margin:
            st.x, bounced = margin, True
        elif st.x > self.w - margin:
            st.x, bounced = self.w - margin, True
        if st.y < margin:
            st.y, bounced = margin, True
        elif st.y > self.h - margin:
            st.y, bounced = self.h - margin, True
        if bounced and st.speed > 0.0:
            cx, cy = self.w / 2 - st.x, self.h / 2 - st.y
            st.heading = math.atan2(cy, cx) + self.rng.uniform(-0.6, 0.6)

        return st
