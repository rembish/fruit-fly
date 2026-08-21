"""The two measurements the web port is not allowed to guess at.

`docs/web-plan.md` Phase 0. Both are headless, both answer a question the
layout of a game screen depends on, and both were mandated before any
canvas exists precisely so the layout follows the fly rather than the
other way round.

M0.1 phototaxis — does luminance asymmetry steer this connectome? The
loom pathway needed a scaled-down direct LC4/LPLC2 injection because the
emergent signal was weak, and nothing in the repo shows that a bright
patch on one side produces DNa02 asymmetry. If it does, a game pad can
be a beacon the fly is drawn to. If it does not, pads are hit by drift
and the site says so.

  The design is mirrored, and that is the whole point. The reconstruction
  itself is lopsided — 5790 left photoreceptors against 5361 right, 54
  LC4 against 50 — so a single "bright on the left" run showing more
  right-side drive measures the connectome's own asymmetry, not
  phototaxis. Both mirror images are run and the difference of the two
  asymmetries is the result: any fixed structural bias appears in both
  and cancels. A sham pair of identical gray epochs, put through exactly
  the same arithmetic, gives the noise floor to compare it against.

M0.2 pad statistics — where does the fly actually go, and how often
would it hit a pad? Not by re-simulating per candidate rectangle: the
brain is captured once as a per-frame rate trace, replayed through the
real `MotorMap` to get one trajectory, and every candidate pad is then a
geometry query on that trajectory. Pads do not feed back into the fly in
v1, so one capture answers every layout question, including canvas size.

Both measurements are blind and unthreatened: no retina, no cursor. That
is the same operating point `calibrate.py` captures at, and it is the
fly's *undisturbed* behaviour — the numbers are a floor for a fly that
will later have pipes scrolling through its optic lobe.
"""

from __future__ import annotations

import math

import numpy as np

from .brain import Brain, RateMonitor
from .motor import LANDED, MotorMap
from .senses import PATCH, Retina, Senses, SensoryFrame

# ---------------------------------------------------------------- M0.1

#: Sensory frames per second, as `test_retina.py` drives them.
TICK = 0.05

#: Luminance of the lit and the unlit eye. Kept off both ends of the
#: photoreceptor range on purpose: R_MAX clips at 70 Hz, and a stimulus
#: that saturates would compress the very asymmetry being measured.
BRIGHT, DIM, GRAY = 0.85, 0.15, 0.5

#: Read out the one-neuron-per-side steering pair the plan names, and the
#: 1305-neuron descending pool as a high-SNR corroboration: if luminance
#: lateralizes descending drive at all, the pool shows it while a pair of
#: single neurons is still counting coincidences.
LATERAL = [("DNa02", "DNa02_L", "DNa02_R"),
           ("descending", "descending_L", "descending_R")]
READOUTS = ["DNa02_L", "DNa02_R", "descending_L", "descending_R", "GF"]

#: Transient (contrast, which decays over Retina.TAU_ADAPT = 1.5 s) and
#: sustained (absolute luminance, which does not) are different circuits
#: reaching the same neurons, so they get different windows.
TRANSIENT_S = (0.0, 0.5)
SUSTAINED_S = (2.0, 5.0)

#: The plan's own parity rule, reused: an effect counts only if it clears
#: 1.5x the spread of the measurement that has nothing in it.
NULL_MARGIN = 1.5


def _epochs(condition_first: str) -> list[tuple[str, float, float, float]]:
    """(label, left luminance, right luminance, seconds).

    The sham pair comes first and is two gray epochs treated exactly like
    the two real ones. Rest epochs let adaptation wash out between
    stimuli; they are not measured.
    """
    other = "bright_R" if condition_first == "bright_L" else "bright_L"

    def lit(name):
        return (BRIGHT, DIM) if name == "bright_L" else (DIM, BRIGHT)

    a_l, a_r = lit(condition_first)
    b_l, b_r = lit(other)
    return [
        ("settle", GRAY, GRAY, 3.0),
        ("sham_A", GRAY, GRAY, 5.0),
        ("rest", GRAY, GRAY, 2.0),
        ("sham_B", GRAY, GRAY, 5.0),
        ("rest", GRAY, GRAY, 2.0),
        (condition_first, a_l, a_r, 5.0),
        ("rest", GRAY, GRAY, 3.0),
        (other, b_l, b_r, 5.0),
    ]


def _run_epoch(brain, mon, senses, frame, lum_l, lum_r, seconds):
    """Hold one luminance pair; return per-tick rate samples per readout."""
    frame.patch_L = np.full((PATCH, PATCH), lum_l, dtype=np.float32)
    frame.patch_R = np.full((PATCH, PATCH), lum_r, dtype=np.float32)
    steps = int(round(TICK * 1000 / brain.dt))
    ticks = int(round(seconds / TICK))
    out = {k: np.empty(ticks, dtype=np.float32) for k in READOUTS}
    for i in range(ticks):
        # The fly is stationary at an arbitrary spot with the cursor
        # effectively at infinity: the eyes are the only input.
        stim, _, _ = senses.rates(frame, 500.0, 500.0, 0.0,
                                  brain.t / 1000.0)
        brain.set_stimulus(stim)
        for _ in range(steps):
            mon.update(brain.step())
        for k in READOUTS:
            out[k][i] = mon.rates[k]
    return out


def _window(samples: dict, span: tuple[float, float]) -> dict[str, float]:
    lo = int(round(span[0] / TICK))
    hi = int(round(span[1] / TICK))
    return {k: float(v[lo:hi].mean()) for k, v in samples.items()}


def asymmetry(rates: dict[str, float], left: str, right: str) -> float:
    """Lateral asymmetry index, (R - L) / (R + L), unitless.

    Normalized so a change in overall excitability cannot masquerade as
    a change in sidedness.
    """
    total = rates[left] + rates[right]
    if total <= 0.0:
        return 0.0
    return (rates[right] - rates[left]) / total


def steering_effect(runs: list[dict]) -> dict:
    """Difference of asymmetries across the mirror, and the sham floor.

    `runs` is one dict per seed, mapping epoch label -> window ->
    readout -> Hz. The returned effect for each lateral pair is
    asym(bright_L) - asym(bright_R): a phototactic circuit drives those
    two opposite ways, while any structural bias sits in both and
    subtracts out. The sham is the same subtraction over two identical
    gray epochs.
    """
    out: dict[str, dict] = {}
    for name, left, right in LATERAL:
        for window in ("transient", "sustained"):
            real, sham = [], []
            for run in runs:
                real.append(asymmetry(run["bright_L"][window], left, right)
                            - asymmetry(run["bright_R"][window],
                                        left, right))
                sham.append(asymmetry(run["sham_A"][window], left, right)
                            - asymmetry(run["sham_B"][window], left, right))
            real_a = np.array(real, dtype=np.float64)
            sham_a = np.array(sham, dtype=np.float64)
            # ddof=1: this is the spread of a sample of seeds, and with
            # three of them the difference from ddof=0 is not cosmetic.
            floor = float(sham_a.std(ddof=1)) if len(sham_a) > 1 else 0.0
            effect = float(real_a.mean())
            same_sign = bool(np.all(real_a > 0) or np.all(real_a < 0))
            out[f"{name}/{window}"] = {
                "effect": effect,
                "per_seed": real_a.tolist(),
                "sham_per_seed": sham_a.tolist(),
                "sham_sd": floor,
                "threshold": NULL_MARGIN * floor,
                "steers": bool(abs(effect) > NULL_MARGIN * floor
                               and same_sign),
                "consistent_sign": same_sign,
            }
    return out


def phototaxis(indptr, indices, weights, pops, retina_data, *,
               seeds=(7, 11, 13), dt=2.0, noise_rate=100.0,
               noise_weight=3.0, inh_gain=1.5) -> dict:
    """M0.1: run the mirrored stimulus over several brains."""
    runs = []
    for i, seed in enumerate(seeds):
        brain = Brain(indptr, indices, weights, pops, dt=dt,
                      noise_rate=noise_rate, noise_weight=noise_weight,
                      inh_gain=inh_gain, seed=seed)
        mon = RateMonitor(brain, READOUTS)
        # A fresh Retina per seed so the adaptation baselines start
        # where reset_state cannot put them back: they live in the
        # retina, not in the brain.
        senses = Senses(retina=Retina(retina_data), loom_injection=0.0)
        frame = SensoryFrame(cursor_x=1e9, cursor_y=1e9, patch_dt=TICK)
        # Counterbalanced: half the seeds see the mirror image first, so
        # a slow drift over the session cannot look like a side effect.
        first = "bright_L" if i % 2 == 0 else "bright_R"
        run: dict[str, dict] = {}
        for label, lum_l, lum_r, seconds in _epochs(first):
            samples = _run_epoch(brain, mon, senses, frame,
                                 lum_l, lum_r, seconds)
            if label in ("rest", "settle"):
                continue
            run[label] = {"transient": _window(samples, TRANSIENT_S),
                          "sustained": _window(samples, SUSTAINED_S)}
        runs.append(run)
    return {"seeds": list(seeds), "dt": dt, "runs": runs,
            "effects": steering_effect(runs)}


def format_phototaxis(result: dict) -> str:
    lines = [f"M0.1 phototaxis — {len(result['seeds'])} seeds "
             f"{result['seeds']}, dt={result['dt']}, eyes only "
             f"(no loom injection, no cursor)",
             f"stimulus: one eye at {BRIGHT} luminance, the other at "
             f"{DIM}; then mirrored", ""]
    for run, seed in zip(result["runs"], result["seeds"], strict=True):
        for window in ("transient", "sustained"):
            bits = []
            for cond in ("bright_L", "bright_R"):
                r = run[cond][window]
                bits.append(f"{cond} DNa02 L/R "
                            f"{r['DNa02_L']:5.1f}/{r['DNa02_R']:5.1f}"
                            f" desc L/R "
                            f"{r['descending_L']:4.1f}/"
                            f"{r['descending_R']:4.1f}")
            lines.append(f"seed {seed:3d} {window:9s} " + " | ".join(bits))
    lines.append("")
    lines.append("difference of asymmetries across the mirror "
                 "(structural bias cancels); asym = (R-L)/(R+L), and")
    lines.append("DNa02 turns the fly toward its own side, so a positive "
                 "effect is light AVOIDANCE and a negative one attraction:")
    for key, e in result["effects"].items():
        verdict = "STEERS" if e["steers"] else "null"
        lines.append(
            f"  {key:22s} effect {e['effect']:+.4f}  "
            f"sham sd {e['sham_sd']:.4f}  "
            f"needs |effect| > {e['threshold']:.4f}  -> {verdict}")
    steering = [k for k, e in result["effects"].items() if e["steers"]]
    lines.append("")
    if steering:
        toward = result["effects"][steering[0]]["effect"] < 0
        lines.append(
            f"PASS: luminance asymmetry steers ({', '.join(steering)}) — "
            f"the fly turns {'toward' if toward else 'away from'} the "
            f"lit side, so a bright pad "
            f"{'can be a beacon' if toward else 'would repel it'}")
    else:
        lines.append(
            "NULL: luminance asymmetry does not steer this connectome — "
            "pads get hit by drift, and the site should say so")
    return "\n".join(lines)


# ---------------------------------------------------------------- M0.2

#: One captured frame is this many brain steps. At dt=2.0 that is 16 ms,
#: the nearest exact multiple to the ~60 fps the desktop controller ticks
#: `MotorMap.update` at.
FRAME_STEPS = 8

#: Populations the motor map reads. Same list the controller uses, minus
#: the loom detectors it does not consult.
MOTOR_POPS = ["GF", "DNa02_L", "DNa02_R", "DNp09", "MDN", "descending"]

#: Discarded before recording, as in `calibrate.capture`: adaptation and
#: the noise governor both settle over ~500 ms and an early sample
#: measures the ramp.
WARMUP_S = 3.0

#: Canvas the fff play field is measured at. Every number below moves
#: with it — the motor map's speeds (260-500 px/s cruise, 1400 px/s
#: escape) and its 24 px edge margin are absolute pixels, so a fly on a
#: 1920x1080 field crosses less of it per second and sits in the middle
#: of a larger empty area. Phase 3 must build at this size or re-measure.
CANVAS = (960, 540)

#: "Landed or slow" is the press predicate, and presses per minute swing
#: hard on where slow stops. Reported at several so the choice is made
#: with the numbers in view. 0.0 is landed-only.
SLOW_PX_S = (0.0, 60.0, 120.0)


def capture_rates(indptr, indices, weights, pops, *, dt=2.0, seconds=120.0,
                  noise_rate=100.0, noise_weight=3.0, inh_gain=1.5,
                  seed=7, frame_steps=FRAME_STEPS) -> dict:
    """Per-frame motor rates + giant fiber spike counts, blind and calm.

    This is the expensive half and it is done once. Everything downstream
    — the trajectory, the occupancy map, every candidate pad at every
    canvas size — is a replay of this array.
    """
    brain = Brain(indptr, indices, weights, pops, dt=dt,
                  noise_rate=noise_rate, noise_weight=noise_weight,
                  inh_gain=inh_gain, seed=seed)
    mon = RateMonitor(brain, MOTOR_POPS)
    gf_mask = np.zeros(brain.n, dtype=bool)
    gf_mask[brain.pops["GF"]] = True

    frame_dt = frame_steps * dt * 1e-3
    warm = int(WARMUP_S / frame_dt)
    frames = int(seconds / frame_dt)
    rates = {k: np.empty(frames, dtype=np.float32) for k in MOTOR_POPS}
    gf = np.empty(frames, dtype=np.int32)
    for i in range(warm + frames):
        fired = 0
        for _ in range(frame_steps):
            spiked = brain.step()
            mon.update(spiked)
            if len(spiked):
                fired += int(gf_mask[spiked].sum())
        if i >= warm:
            j = i - warm
            gf[j] = fired
            for k in MOTOR_POPS:
                rates[k][j] = mon.rates[k]
    return {"frame_dt": frame_dt, "dt": dt, "seed": seed,
            "seconds": frames * frame_dt, "rates": rates, "gf": gf}


def replay(trace: dict, width: int, height: int) -> dict:
    """Drive the real MotorMap with a captured trace -> one trajectory.

    Threat is zero throughout: the capture is of a fly nobody is chasing,
    so this is the undisturbed flight path. Cheap enough (a few thousand
    frames of arithmetic) to redo per canvas size.
    """
    motor = MotorMap(width, height)
    frame_dt = trace["frame_dt"]
    n = len(trace["gf"])
    x = np.empty(n, dtype=np.float32)
    y = np.empty(n, dtype=np.float32)
    speed = np.empty(n, dtype=np.float32)
    landed = np.zeros(n, dtype=bool)
    for i in range(n):
        rates = {k: float(v[i]) for k, v in trace["rates"].items()}
        st = motor.update(frame_dt, i * frame_dt, rates,
                          int(trace["gf"][i]), 0.0, 0.0)
        x[i], y[i], speed[i] = st.x, st.y, st.speed
        landed[i] = st.state == LANDED
    return {"frame_dt": frame_dt, "width": width, "height": height,
            "x": x, "y": y, "speed": speed, "landed": landed,
            "seconds": n * frame_dt}


def press_times(traj: dict, pad: tuple[float, float, float, float],
                slow_px_s: float) -> np.ndarray:
    """Edge-triggered presses: seconds at which the fly arrives on a pad.

    A press fires on the rising edge of "inside the pad and landed or
    slow", which is the same predicate the web runtime must use. Holding
    still on the pad is one press, not thousands; a 1400 px/s escape dart
    crossing the pad in a single frame is none.

    `pad` is (x0, y0, x1, y1) in fractions of the canvas.
    """
    w, h = traj["width"], traj["height"]
    x0, y0, x1, y1 = pad[0] * w, pad[1] * h, pad[2] * w, pad[3] * h
    inside = ((traj["x"] >= x0) & (traj["x"] <= x1)
              & (traj["y"] >= y0) & (traj["y"] <= y1))
    eligible = inside & (traj["landed"] | (traj["speed"] <= slow_px_s))
    rising = eligible & ~np.concatenate(([False], eligible[:-1]))
    return np.flatnonzero(rising) * traj["frame_dt"]


def press_stats(traj: dict, pad, slow_px_s: float) -> dict:
    """Presses per minute and the inter-press interval distribution."""
    t = press_times(traj, pad, slow_px_s)
    minutes = traj["seconds"] / 60.0
    gaps = np.diff(t)
    out = {"presses": int(len(t)), "per_minute": len(t) / minutes,
           "mean_gap_s": float(gaps.mean()) if len(gaps) else math.nan}
    if len(gaps) >= 3:
        p10, p50, p90 = np.percentile(gaps, [10, 50, 90])
        out.update(gap_p10=float(p10), gap_p50=float(p50),
                   gap_p90=float(p90))
    return out


def occupancy(traj: dict, cols: int = 24, rows: int = 12) -> np.ndarray:
    """Fraction of time spent in each cell of a coarse grid.

    The edge avoidance in `motor.py` turns the fly back toward the middle
    whenever it touches a margin, so this is not uniform and a pad in the
    wrong place waits a long time.
    """
    cx = np.clip((traj["x"] / traj["width"] * cols).astype(np.int32),
                 0, cols - 1)
    cy = np.clip((traj["y"] / traj["height"] * rows).astype(np.int32),
                 0, rows - 1)
    grid = np.bincount(cy * cols + cx, minlength=cols * rows)
    return (grid / grid.sum()).reshape(rows, cols)


def render_occupancy(grid: np.ndarray) -> str:
    ramp = " .:-=+*#%@"
    top = grid.max()
    lines = []
    for row in grid:
        lines.append("|" + "".join(
            ramp[min(len(ramp) - 1, int(v / top * len(ramp)))]
            for v in row) + "|")
    return "\n".join(lines)


def band_occupancy(traj: dict, bands: int = 5) -> list[float]:
    """Time fraction in each horizontal band, top to bottom.

    The one number a bottom-edge FLAP pad lives or dies by.
    """
    cy = np.clip((traj["y"] / traj["height"] * bands).astype(np.int32),
                 0, bands - 1)
    counts = np.bincount(cy, minlength=bands)
    return (counts / counts.sum()).tolist()


#: Candidates swept for the fff FLAP pad, in canvas fractions. The plan
#: asks for "one big FLAP pad at the bottom"; the centre band is not a
#: candidate but a control, showing what the traffic looks like where the
#: fly actually is.
PAD_CANDIDATES = [
    ("bottom full, h=10%", (0.00, 0.90, 1.00, 1.00)),
    ("bottom full, h=20%", (0.00, 0.80, 1.00, 1.00)),
    ("bottom full, h=30%", (0.00, 0.70, 1.00, 1.00)),
    ("bottom mid-60%, h=20%", (0.20, 0.80, 0.80, 1.00)),
    ("centre band, h=20% (control)", (0.00, 0.40, 1.00, 0.60)),
]


def pad_statistics(traj: dict, candidates=PAD_CANDIDATES,
                   slows=SLOW_PX_S) -> dict:
    return {
        "landed_fraction": float(traj["landed"].mean()),
        "mean_speed_px_s": float(traj["speed"].mean()),
        "bands": band_occupancy(traj),
        "pads": {name: {slow: press_stats(traj, pad, slow)
                        for slow in slows}
                 for name, pad in candidates},
    }


def format_padstats(traj: dict, stats: dict) -> str:
    lines = [f"M0.2 pad statistics — {traj['seconds']:.0f} simulated "
             f"seconds on a {traj['width']}x{traj['height']} canvas, "
             f"blind and unthreatened",
             f"landed {stats['landed_fraction'] * 100:.0f}% of the time, "
             f"mean speed {stats['mean_speed_px_s']:.0f} px/s", "",
             "occupancy (time per cell; edge avoidance biases to centre):",
             render_occupancy(occupancy(traj)), "",
             "time per horizontal band, top to bottom: "
             + "  ".join(f"{b * 100:4.1f}%" for b in stats["bands"]), "",
             "presses per minute, by pad and by where 'slow' stops:"]
    header = "  " + " " * 30 + "".join(
        f"{('landed only' if s == 0.0 else f'<={s:.0f} px/s'):>14s}"
        for s in SLOW_PX_S)
    lines.append(header)
    for name, by_slow in stats["pads"].items():
        cells = "".join(f"{by_slow[s]['per_minute']:>14.1f}"
                        for s in SLOW_PX_S)
        lines.append(f"  {name:30s}{cells}")
    lines.append("")
    lines.append("inter-press interval (s) at the widest predicate:")
    widest = SLOW_PX_S[-1]
    for name, by_slow in stats["pads"].items():
        s = by_slow[widest]
        if "gap_p50" in s:
            lines.append(f"  {name:30s} p10/50/90 = {s['gap_p10']:5.1f}/"
                         f"{s['gap_p50']:5.1f}/{s['gap_p90']:5.1f}  "
                         f"({s['presses']} presses)")
        else:
            lines.append(f"  {name:30s} too few presses to describe "
                         f"({s['presses']})")
    return "\n".join(lines)
