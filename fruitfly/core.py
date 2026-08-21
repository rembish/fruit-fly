"""Platform-independent fly logic: brain thread, senses, motor, drawing.

Everything here is shared by every window backend (GTK on Linux, Cocoa
on macOS, Win32 on Windows). A backend supplies a small host interface:

    host.screen_size()              -> (w, h) in logical pixels
    host.pointer()                  -> (x, y), top-left origin, y down
    host.grab(x, y, side, out)      -> (out, out) float32 luminance in [0,1]
                                       or None if screen capture is denied
    host.move_window(x, y)          -> move the fly window (top-left origin)
    host.request_redraw()           -> schedule a repaint of fly (+ HUD)

and drives `Controller.tick()` at ~60 fps, painting via `Controller.draw`.
"""

from __future__ import annotations

import threading
import time

import cairo
import numpy as np

from .brain import Brain, RateMonitor
from .motor import ESCAPE, FLYING, LANDED, SQUASHED, TAKEOFF, MotorMap
from .senses import EYE_RADIUS, PATCH, Senses, SensoryFrame
from .sprite import draw_fly, draw_splat

MOTOR_POPS = ["GF", "DNa02_L", "DNa02_R", "DNp09", "MDN", "descending",
              "LC4_L", "LC4_R"]

WIN = 150           # px, the little travelling window around the fly
HUD_W, HUD_H = 620, 116
SWAT_S = 0.25       # s of mechanosensory drive after a click lands
JO_SWAT_HZ = 150.0  # firing rate forced on JO neurons by a swat


class Shared:
    """State exchanged between the brain thread and the UI thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stim: list = []
        self.rates: dict[str, float] = {}
        self.gf_count = 0
        self.sim_speed = 0.0
        self.spikes_per_s = 0.0
        self.reset = False
        self.stop = False


class BrainThread(threading.Thread):
    def __init__(self, brain: Brain, shared: Shared):
        super().__init__(daemon=True, name="fly-brain")
        self.brain = brain
        self.shared = shared
        self.monitor = RateMonitor(brain, MOTOR_POPS)
        self.gf_mask = np.zeros(brain.n, dtype=bool)
        self.gf_mask[brain.pops["GF"]] = True

    def run(self):
        b = self.brain
        chunk = max(1, int(round(10.0 / b.dt)))   # ~10 ms sim per chunk
        spikes_window = 0
        window_t0 = time.perf_counter()
        window_sim0 = b.t
        while not self.shared.stop:
            t0 = time.perf_counter()
            with self.shared.lock:
                stim = list(self.shared.stim)
                do_reset = self.shared.reset
                self.shared.reset = False
            if do_reset:
                b.reset_state()
            b.set_stimulus(stim)

            gf_fired = 0
            for _ in range(chunk):
                spiked = b.step()
                self.monitor.update(spiked)
                spikes_window += len(spiked)
                if len(spiked):
                    gf_fired += int(self.gf_mask[spiked].sum())

            with self.shared.lock:
                self.shared.rates = dict(self.monitor.rates)
                self.shared.gf_count += gf_fired

            # pace toward real time; report achieved speed once a second
            sim_elapsed = chunk * b.dt * 1e-3
            wall_elapsed = time.perf_counter() - t0
            if wall_elapsed < sim_elapsed:
                time.sleep(sim_elapsed - wall_elapsed)
            now = time.perf_counter()
            if now - window_t0 >= 1.0:
                with self.shared.lock:
                    self.shared.sim_speed = ((b.t - window_sim0) * 1e-3
                                             / (now - window_t0))
                    self.shared.spikes_per_s = (spikes_window
                                                / (now - window_t0))
                window_t0, window_sim0, spikes_window = now, b.t, 0


class Controller:
    """The fly itself: senses in, motor out, sprite drawn. Host-agnostic."""

    def __init__(self, brain: Brain, senses: Senses, host,
                 size: float = 34.0, vision: bool = True,
                 verbose: bool = True):
        self.host = host
        self.pops = list(brain.pops)      # what poke() may drive
        self._poke: tuple[str, float, float] | None = None
        self.size = size
        self.vision = vision
        self.verbose = verbose

        self.scr_w, self.scr_h = host.screen_size()
        self.shared = Shared()
        self.senses = senses
        self.motor = MotorMap(self.scr_w, self.scr_h)
        self.brain_thread = BrainThread(brain, self.shared)
        self.frame = SensoryFrame()

        self._threat = 0.0
        self._bearing = 0.0
        self._swat_until = 0.0
        self.swats_dodged = 0
        self.flies_swatted = 0
        self._last_tick = time.perf_counter()
        self._lum_tick = 0
        self._last_patch_t = time.perf_counter()
        self._t0 = time.perf_counter()
        self._origin = (-10_000, -10_000)
        self._vision_warned = False

    def start(self):
        self.brain_thread.start()

    def shutdown(self):
        self.shared.stop = True

    # -------------------------------------------------------------- swat
    def hit_radius(self) -> float:
        return self.size * 0.5 + 4

    def on_swat(self) -> None:
        """A click landed on the fly's body."""
        t = time.perf_counter() - self._t0
        st = self.motor.st
        if st.state == SQUASHED:
            return
        if st.state in (LANDED, TAKEOFF):
            # caught on the ground — sitting, or mid-startle with its
            # wings up but feet still down (the flyswatter window)
            self.flies_swatted += 1
            self.motor.squash(t)
            with self.shared.lock:
                self.shared.reset = True  # this brain is done
            if self.verbose:
                print(f"[fly] SPLAT. flies swatted: {self.flies_swatted}, "
                      f"swats dodged: {self.swats_dodged} — a new fly "
                      f"arrives shortly", flush=True)
        else:
            # airborne: a glancing blow, felt through the JO mechanosensors
            self.swats_dodged += 1
            self._swat_until = t + SWAT_S
            self.motor.glancing_blow(t)
            if self.verbose:
                print(f"[fly] swat dodged (#{self.swats_dodged}) — "
                      f"JO mechanosensors firing", flush=True)

    # ------------------------------------------------------------ senses
    def sample_senses(self):
        st = self.motor.st
        px, py = self.host.pointer()
        self.frame.cursor_x, self.frame.cursor_y = float(px), float(py)

        # eye patches: what each retina actually sees (~20 Hz; a costly trip
        # through the display server, so not every frame)
        self._lum_tick += 1
        if not self.vision or self._lum_tick % 3:
            return
        side = int(2 * EYE_RADIUS)
        for attr, eye in (("patch_L", "L"), ("patch_R", "R")):
            cx, cy = Senses.eye_center(st.x, st.y, st.heading, eye)
            sx = max(0, min(self.scr_w - side, int(cx - EYE_RADIUS)))
            sy = max(0, min(self.scr_h - side, int(cy - EYE_RADIUS)))
            patch = self.host.grab(sx, sy, side, PATCH)
            if patch is None:
                if not self._vision_warned:
                    self._vision_warned = True
                    print("[fly] screen capture unavailable — the fly is "
                          "blind (its brain still runs). On macOS grant "
                          "Screen Recording permission; see README.",
                          flush=True)
                continue
            setattr(self.frame, attr, patch)
        now = time.perf_counter()
        self.frame.patch_dt = min(0.5, now - self._last_patch_t)
        self._last_patch_t = now

    # -------------------------------------------------------------- poke
    def poke(self, target: str, hz: float = 120.0,
             seconds: float = 0.4) -> str:
        """Drive one real population, then watch what the body does.

        The optogenetics knob: the fly has no scripted response to this.
        Whatever happens next is the rest of the connectome reacting --
        drive GF and it should escape, drive one side's DNa02 and it
        should turn that way, drive MDN and it should scoot backwards.
        """
        if target not in self.pops:
            return f"no population {target!r}"
        if hz <= 0.0 or seconds <= 0.0:
            return "rate and duration must both be positive"
        now = time.perf_counter() - self._t0
        self._poke = (target, float(hz), now + float(seconds))
        return f"poking {target} at {hz:.0f} Hz for {seconds:.2f}s"

    # -------------------------------------------------------------- tick
    def tick(self):
        now = time.perf_counter()
        dt = min(0.1, now - self._last_tick)
        self._last_tick = now
        t = now - self._t0

        self.sample_senses()
        st = self.motor.st
        stim, self._threat, self._bearing = self.senses.rates(
            self.frame, st.x, st.y, st.heading, t)
        if t < self._swat_until:   # being touched: maximal alarm
            stim.append(("JO", JO_SWAT_HZ))
            self._threat = 1.0

        poke = self._poke                 # see poke(); one at a time
        if poke is not None:
            name, hz, until = poke
            if t < until:
                stim.append((name, hz))
            else:
                self._poke = None
                if self.verbose:
                    print(f"[poke] {name} released", flush=True)

        with self.shared.lock:
            self.shared.stim = stim
            rates = dict(self.shared.rates)
            gf = self.shared.gf_count
            self.shared.gf_count = 0

        prev_event = st.last_event
        self.motor.update(dt, t, rates, gf, self._bearing, self._threat)
        if self.verbose and st.last_event != prev_event:
            print(f"[fly t={t:7.1f}s sim {self.shared.sim_speed:.2f}x] "
                  f"{st.last_event}", flush=True)

        # the little window follows the fly
        origin = (int(st.x) - WIN // 2, int(st.y) - WIN // 2)
        if origin != self._origin:
            self._origin = origin
            self.host.move_window(*origin)
        self.host.request_redraw()

    # -------------------------------------------------------------- draw
    def draw(self, cr):
        """Paint the fly, centred, into a WIN x WIN cairo context."""
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        st = self.motor.st
        if st.state == SQUASHED:
            draw_splat(cr, WIN / 2, WIN / 2, st.heading, self.size)
        else:
            draw_fly(cr, WIN / 2, WIN / 2, st.heading, self.size,
                     flying=st.state in (FLYING, ESCAPE, TAKEOFF),
                     wing_phase=st.wing_phase,
                     escaping=st.state in (ESCAPE, TAKEOFF))

    def draw_hud(self, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        with self.shared.lock:
            rates = dict(self.shared.rates)
            speed = self.shared.sim_speed
            sps = self.shared.spikes_per_s
        poke = self._poke
        lines = [
            (f"sim {speed:4.2f}x real time   {sps/1000:6.1f}k spikes/s"
             + (f"   POKE {poke[0]} {poke[1]:.0f}Hz" if poke else "")),
            f"threat {self._threat:4.2f}   state {self.motor.st.state}   "
            f"dodged {self.swats_dodged}   swatted {self.flies_swatted}",
            "  ".join(f"{k} {rates.get(k, 0):5.1f}Hz"
                      for k in ("GF", "DNa02_L", "DNa02_R", "descending")),
            "  ".join(f"{k} {rates.get(k, 0):5.1f}Hz"
                      for k in ("LC4_L", "LC4_R")) + "   (loom detectors)",
            f"last: {self.motor.st.last_event}",
        ]
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(13)
        y = 18
        for line in lines:
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.rectangle(2, y - 14, HUD_W - 14, 19)
            cr.fill()
            cr.set_source_rgba(0.6, 1.0, 0.6, 0.95)
            cr.move_to(6, y)
            cr.show_text(line)
            y += 19
