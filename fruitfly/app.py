"""The desktop overlay: a click-through window where the fly lives.

Threads:
  GTK main loop  — draws the fly, samples cursor + screen luminance,
                   integrates motor kinematics at ~60 fps
  brain thread   — steps the connectome LIF simulation continuously,
                   paced to real time when the hardware allows
"""

from __future__ import annotations

import math
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

import cairo  # noqa: E402
import numpy as np  # noqa: E402

from .brain import Brain, RateMonitor
from .senses import Senses, SensoryFrame, Retina, PATCH, EYE_RADIUS
from .motor import MotorMap, FLYING, ESCAPE
from .sprite import draw_fly

MOTOR_POPS = ["GF", "DNa02_L", "DNa02_R", "DNp09", "MDN", "descending",
              "LC4_L", "LC4_R"]


class Shared:
    """State exchanged between the brain thread and the GTK thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stim: list = []
        self.rates: dict[str, float] = {}
        self.gf_count = 0
        self.sim_speed = 0.0
        self.spikes_per_s = 0.0
        self.stop = False


class BrainThread(threading.Thread):
    def __init__(self, brain: Brain, shared: Shared):
        super().__init__(daemon=True, name="fly-brain")
        self.brain = brain
        self.shared = shared
        self.monitor = RateMonitor(brain, MOTOR_POPS)
        gf = brain.pops["GF"]
        self.gf_mask = np.zeros(brain.n, dtype=bool)
        self.gf_mask[gf] = True

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
                    self.shared.spikes_per_s = spikes_window / (now - window_t0)
                window_t0, window_sim0, spikes_window = now, b.t, 0


class FlyWindow(Gtk.Window):
    def __init__(self, brain: Brain, senses: Senses, size: float = 34.0,
                 hud: bool = False, vision: bool = True, verbose: bool = True):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.hud = hud
        self.vision = vision
        self.verbose = verbose
        self.size = size

        screen = self.get_screen()
        self.scr_w, self.scr_h = screen.get_width(), screen.get_height()
        self.set_default_size(self.scr_w, self.scr_h)
        self.move(0, 0)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        visual = screen.get_rgba_visual()
        if visual is None:
            raise RuntimeError(
                "No RGBA visual — is the MATE compositor enabled? "
                "(System > Preferences > Windows > enable software compositing)")
        self.set_visual(visual)
        self.connect("draw", self.on_draw)
        self.connect("realize", self.on_realize)

        self.shared = Shared()
        self.senses = senses
        self.motor = MotorMap(self.scr_w, self.scr_h)
        self.brain_thread = BrainThread(brain, self.shared)
        self.frame = SensoryFrame()
        self._threat = 0.0
        self._bearing = 0.0
        self._last_tick = time.perf_counter()
        self._lum_tick = 0
        self._last_patch_t = time.perf_counter()
        self._t0 = time.perf_counter()

        self.brain_thread.start()
        GLib.timeout_add(16, self.tick)          # ~60 fps
        self.show_all()

    # ------------------------------------------------------------ window
    def on_realize(self, *_):
        # completely click-through: empty input shape
        self.get_window().input_shape_combine_region(
            cairo.Region(), 0, 0)

    # ------------------------------------------------------------ senses
    def sample_senses(self):
        st = self.motor.st
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        _, px, py = seat.get_pointer().get_position()
        self.frame.cursor_x, self.frame.cursor_y = float(px), float(py)

        # eye patches: what each retina actually sees (~20 Hz; an X trip)
        self._lum_tick += 1
        if self.vision and self._lum_tick % 3 == 0:
            root = Gdk.get_default_root_window()
            side_px = int(2 * EYE_RADIUS)
            for attr, eye in (("patch_L", "L"), ("patch_R", "R")):
                cx, cy = Senses.eye_center(st.x, st.y, st.heading, eye)
                sx = max(0, min(self.scr_w - side_px, int(cx - EYE_RADIUS)))
                sy = max(0, min(self.scr_h - side_px, int(cy - EYE_RADIUS)))
                pb = Gdk.pixbuf_get_from_window(root, sx, sy, side_px, side_px)
                if pb is None:
                    continue
                pb = pb.scale_simple(PATCH, PATCH, 2)  # BILINEAR
                ch, rs = pb.get_n_channels(), pb.get_rowstride()
                buf = np.frombuffer(pb.get_pixels(), dtype=np.uint8)
                buf = np.pad(buf, (0, rs * PATCH - len(buf)))  # last-row pad
                arr = buf.reshape(PATCH, rs)[:, : PATCH * ch]
                arr = arr.reshape(PATCH, PATCH, ch)[..., :3]
                setattr(self.frame, attr,
                        arr.mean(axis=2).astype(np.float32) / 255.0)
            now = time.perf_counter()
            self.frame.patch_dt = min(0.5, now - self._last_patch_t)
            self._last_patch_t = now

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

        with self.shared.lock:
            self.shared.stim = stim
            rates = dict(self.shared.rates)
            gf = self.shared.gf_count
            self.shared.gf_count = 0

        prev_event = st.last_event
        self.motor.update(dt, t, rates, gf, self._bearing, self._threat)
        if self.verbose and st.last_event != prev_event:
            speed = self.shared.sim_speed
            print(f"[fly t={t:7.1f}s sim {speed:.2f}x] {st.last_event}",
                  flush=True)

        self.queue_draw()
        return True

    # -------------------------------------------------------------- draw
    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        st = self.motor.st
        draw_fly(cr, st.x, st.y, st.heading, self.size,
                 flying=st.state in (FLYING, ESCAPE),
                 wing_phase=st.wing_phase,
                 escaping=st.state == ESCAPE)

        if self.hud:
            self.draw_hud(cr)
        return False

    def draw_hud(self, cr):
        with self.shared.lock:
            rates = dict(self.shared.rates)
            speed = self.shared.sim_speed
            sps = self.shared.spikes_per_s
        lines = [
            f"sim {speed:4.2f}x real time   {sps/1000:6.1f}k spikes/s",
            f"threat {self._threat:4.2f}   state {self.motor.st.state}",
            "  ".join(f"{k} {rates.get(k, 0):5.1f}Hz"
                      for k in ("GF", "DNa02_L", "DNa02_R", "descending")),
            "  ".join(f"{k} {rates.get(k, 0):5.1f}Hz"
                      for k in ("LC4_L", "LC4_R")) + "   (loom detectors)",
            f"last: {self.motor.st.last_event}",
        ]
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(13)
        y = 28
        for line in lines:
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.rectangle(12, y - 14, 560, 19)
            cr.fill()
            cr.set_source_rgba(0.6, 1.0, 0.6, 0.95)
            cr.move_to(16, y)
            cr.show_text(line)
            y += 19

    def shutdown(self):
        self.shared.stop = True


def run(noise_rate: float = 100.0, noise_weight: float = 3.0,
        inh_gain: float = 1.5, dt: float = 2.0, size: float = 34.0,
        hud: bool = False, vision: bool = True, pure_retina: bool = False,
        seed: int | None = None):
    from . import data

    print("[app] loading connectome ...")
    indptr, indices, weights, pops, retina_data = data.load()
    brain = Brain(indptr, indices, weights, pops, dt=dt,
                  noise_rate=noise_rate, noise_weight=noise_weight,
                  inh_gain=inh_gain, seed=seed)
    retina = Retina(retina_data) if vision else None
    senses = Senses(retina=retina,
                    loom_injection=0.0 if pure_retina else 0.4)
    n_photo = (len(retina_data["L_idx"]) + len(retina_data["R_idx"])
               if vision else 0)
    print(f"[app] brain ready: {brain.n} neurons, {len(indices)} connections, "
          f"{n_photo} retinotopic photoreceptors — releasing the fly")

    win = FlyWindow(brain, senses, size=size, hud=hud, vision=vision)
    win.connect("destroy", Gtk.main_quit)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    finally:
        win.shutdown()
