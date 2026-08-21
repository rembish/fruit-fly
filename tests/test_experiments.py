"""What the Phase 0 measurements decide, once the measuring is done.

Same split as `test_tuning.py`: the expensive half of `experiments.py` is
simulation and needs the connectome, but the half worth pinning is the
arithmetic that turns rate traces into an answer. Synthetic runs and
synthetic trajectories exercise that in milliseconds — and the two
properties that matter most (a mirrored design cancels the
reconstruction's own lopsidedness; a press is an arrival, not a dwell)
are exactly the ones a synthetic case can prove and a real one cannot.

Run:  python3 tests/test_experiments.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from fruitfly import experiments as ex
from fruitfly.senses import Retina

BASE = 10.0     # Hz on each side of a synthetic readout pair


def _rates(l_hz, r_hz):
    return {"DNa02_L": l_hz, "DNa02_R": r_hz,
            "descending_L": l_hz, "descending_R": r_hz, "GF": 1.0}


def _run(bias=0.0, light=0.0, jitter=0.0, rng=None):
    """One synthetic seed's worth of epochs.

    `bias` is a fixed structural lopsidedness (always favours the right,
    the way 5790 left photoreceptors against 5361 right would);
    `light` is a genuine phototactic pull toward the lit eye; `jitter`
    is measurement noise, which lands in the sham epochs too.
    """
    rng = rng or np.random.default_rng(0)

    def pair(pull):
        n_l, n_r = rng.normal(0, jitter, 2) if jitter else (0.0, 0.0)
        return _rates(BASE + n_l - pull, BASE + bias + n_r + pull)

    run = {}
    # bright_L pulls drive toward the right side; bright_R mirrors it.
    for label, pull in (("sham_A", 0.0), ("sham_B", 0.0),
                        ("bright_L", light), ("bright_R", -light)):
        r = pair(pull)
        run[label] = {"transient": r, "sustained": r}
    return run


def test_asymmetry_index_is_normalised_and_signed():
    assert ex.asymmetry(_rates(10, 10), "DNa02_L", "DNa02_R") == 0.0
    right = ex.asymmetry(_rates(5, 15), "DNa02_L", "DNa02_R")
    left = ex.asymmetry(_rates(15, 5), "DNa02_L", "DNa02_R")
    assert right == -left and right > 0
    # doubling both sides is not a change in sidedness
    assert ex.asymmetry(_rates(10, 30), "DNa02_L", "DNa02_R") == right
    assert ex.asymmetry(_rates(0, 0), "DNa02_L", "DNa02_R") == 0.0
    print(f"asymmetry(5,15) = {right:+.2f}, and scale-free")


def test_mirrored_design_cancels_structural_bias():
    """The measurement this whole experiment exists to be: a lopsided
    reconstruction with no phototaxis at all must read as null."""
    runs = [_run(bias=3.0, light=0.0) for _ in range(3)]
    eff = ex.steering_effect(runs)["DNa02/sustained"]
    assert abs(eff["effect"]) < 1e-9, eff
    assert not eff["steers"]
    # ... and the bias really was there, in each single condition
    single = ex.asymmetry(runs[0]["bright_L"]["sustained"],
                          "DNa02_L", "DNa02_R")
    assert single > 0.1, single
    print(f"a {single:+.2f} one-sided asymmetry cancels to "
          f"{eff['effect']:+.4f} across the mirror")


def test_a_real_pull_survives_the_cancellation():
    runs = [_run(bias=3.0, light=2.0) for _ in range(3)]
    eff = ex.steering_effect(runs)["DNa02/sustained"]
    assert eff["steers"], eff
    assert eff["effect"] > 0 and eff["consistent_sign"]
    print(f"a real pull reads {eff['effect']:+.3f} through the same "
          f"structural bias")


def test_noise_alone_does_not_read_as_steering():
    """The sham pair is the noise floor, so a wobble the size of the
    wobble must not clear it."""
    rng = np.random.default_rng(11)
    runs = [_run(bias=3.0, light=0.0, jitter=1.5, rng=rng)
            for _ in range(3)]
    eff = ex.steering_effect(runs)["DNa02/sustained"]
    assert not eff["steers"], eff
    assert eff["sham_sd"] > 0.0
    print(f"jitter gives effect {eff['effect']:+.4f} against a "
          f"{eff['threshold']:.4f} threshold -> null, correctly")


def test_the_schedule_is_mirrored_and_counterbalanced():
    first = [lbl for lbl, *_ in ex._epochs("bright_L")]
    second = [lbl for lbl, *_ in ex._epochs("bright_R")]
    for schedule in (first, second):
        assert schedule.index("sham_A") < schedule.index("bright_L")
        assert {"bright_L", "bright_R", "sham_A", "sham_B"} <= set(schedule)
    assert first.index("bright_L") < first.index("bright_R")
    assert second.index("bright_R") < second.index("bright_L")
    # the mirror really is a mirror: swap the eyes and you get the other
    lum = {lbl: (a, b) for lbl, a, b, _ in ex._epochs("bright_L")}
    assert lum["bright_L"] == (ex.BRIGHT, ex.DIM)
    assert lum["bright_R"] == (ex.DIM, ex.BRIGHT)
    print("both orders run both conditions; the sham pair comes first")


# ------------------------------------------------------------------ M0.2

def _traj(n=200, width=960, height=540, x=None, y=None, speed=0.0,
          landed=False):
    return {"frame_dt": 0.016, "width": width, "height": height,
            "seconds": n * 0.016,
            "x": np.full(n, x if x is not None else width * 0.5,
                         dtype=np.float32),
            "y": np.full(n, y if y is not None else height * 0.5,
                         dtype=np.float32),
            "speed": np.full(n, speed, dtype=np.float32),
            "landed": np.full(n, landed, dtype=bool)}


PAD = (0.0, 0.9, 1.0, 1.0)   # bottom strip


def test_a_dwelling_fly_presses_once():
    """A fly sits ~4 seconds. A held button would fire every frame."""
    t = _traj(n=300, y=520.0, landed=True)
    presses = ex.press_times(t, PAD, 0.0)
    assert len(presses) == 1 and presses[0] == 0.0, presses
    print(f"{len(t['x'])} frames of sitting on the pad = "
          f"{len(presses)} press")


def test_leaving_and_returning_presses_again():
    t = _traj(n=300, y=520.0, landed=True)
    t["y"][100:200] = 100.0          # takes off, comes back
    presses = ex.press_times(t, PAD, 0.0)
    assert len(presses) == 2, presses
    assert abs(presses[1] - 200 * 0.016) < 1e-6
    print(f"leaving and returning gives {len(presses)} presses")


def test_an_escape_dart_registers_nothing():
    """1400 px/s crosses the pad inside a frame; that is a startle, not
    a decision, and it must not chord the game."""
    t = _traj(n=300, y=520.0, speed=1400.0, landed=False)
    assert len(ex.press_times(t, PAD, 120.0)) == 0
    # the same geometry at cruising speed is still not a press ...
    t["speed"][:] = 300.0
    assert len(ex.press_times(t, PAD, 120.0)) == 0
    # ... until it slows to the predicate
    t["speed"][:] = 90.0
    assert len(ex.press_times(t, PAD, 120.0)) == 1
    print("darts and cruises ignored; a slow arrival counts")


def test_slowing_down_on_the_pad_is_an_arrival():
    """Deceleration over a pad is a rising edge even without crossing
    the boundary — the same predicate the web runtime will use."""
    t = _traj(n=300, y=520.0, speed=800.0)
    t["speed"][150:] = 50.0
    presses = ex.press_times(t, PAD, 120.0)
    assert len(presses) == 1 and abs(presses[0] - 150 * 0.016) < 1e-6
    print("a fly that slows to a stop over the pad presses it once")


def test_pad_geometry_is_in_canvas_fractions():
    """Fractions, so one capture answers every canvas size."""
    small = _traj(n=10, width=960, height=540, y=530.0, landed=True)
    big = _traj(n=10, width=1920, height=1080, y=530.0, landed=True)
    assert len(ex.press_times(small, PAD, 0.0)) == 1
    # the same absolute y is mid-screen on the bigger canvas
    assert len(ex.press_times(big, PAD, 0.0)) == 0
    print("pad fractions scale; absolute positions do not")


def test_occupancy_is_a_time_distribution():
    t = _traj(n=100, x=100.0, y=100.0)
    grid = ex.occupancy(t, cols=10, rows=5)
    assert grid.shape == (5, 10)
    assert abs(grid.sum() - 1.0) < 1e-9
    assert grid[0, 1] == 1.0, grid       # x=100/960*10 -> 1, y -> 0
    bands = ex.band_occupancy(t, bands=5)
    assert abs(sum(bands) - 1.0) < 1e-9 and bands[0] == 1.0
    print(f"occupancy sums to {grid.sum():.1f} and lands in the right cell")


def test_press_stats_survives_a_pad_nothing_touches():
    stats = ex.press_stats(_traj(n=100, y=10.0), PAD, 0.0)
    assert stats["presses"] == 0 and stats["per_minute"] == 0.0
    assert "gap_p50" not in stats
    print("an untouched pad reports zero rather than dividing by it")


# ------------------------------------------------------------------ M0.3

def _dark_columns(patch):
    """Which patch columns contain any pipe, as a boolean mask."""
    return (patch < 0.5).any(axis=0)


def test_a_pipe_is_a_wall_with_a_gap_in_it():
    p = ex.render_pipes(1.0)
    assert p.shape == (ex.PATCH, ex.PATCH)
    mid = ex.PATCH // 2
    assert np.isclose(p[2, mid], ex.PIPE_DARK)    # wall, top of the frame
    assert np.isclose(p[mid, mid], ex.WORLD_GRAY)  # the gap it flies through
    assert np.isclose(p[2, 2], ex.WORLD_GRAY)     # open sky beside the pipe
    print(f"a pipe is {int(_dark_columns(p).sum())} dark columns "
          f"with a gap punched through them")


def test_approaching_expands_the_pipe_and_holds_it_centred():
    """Looming is expansion: both edges move apart, neither drifts."""
    near, far = ex.render_pipes(2.0), ex.render_pipes(1.0)
    n_cols, f_cols = _dark_columns(near), _dark_columns(far)
    assert n_cols.sum() > f_cols.sum()
    # the far pipe's columns are a subset of the near one's: it grew
    # around itself rather than sliding
    assert bool((f_cols & ~n_cols).sum() == 0)
    # ... and the gap opened up too, which a flat zoom-free pipe cannot do
    assert (near < 0.5).sum() > 0
    gap_near = int((near[:, ex.PATCH // 2] > 0.5).sum())
    gap_far = int((far[:, ex.PATCH // 2] > 0.5).sum())
    assert gap_near > gap_far, (gap_near, gap_far)
    print(f"approach widens the wall and opens the gap "
          f"{gap_far} -> {gap_near} px")


def test_scrolling_moves_the_pipe_without_resizing_it():
    """The flat renderer's pipe is the same object in a new place."""
    left = ex.render_pipes(ex.SCALE_FLAT, offset=-20.0)
    right = ex.render_pipes(ex.SCALE_FLAT, offset=+20.0)
    l_cols, r_cols = _dark_columns(left), _dark_columns(right)
    assert l_cols.sum() == r_cols.sum()           # same size ...
    assert int(np.argmax(r_cols)) - int(np.argmax(l_cols)) == 40  # ... moved
    print(f"a scrolled pipe keeps its {int(l_cols.sum())} columns "
          f"and moves 40 px")


def test_every_condition_is_measured_over_the_same_many_ticks():
    """Not the same wall clock — the same sample count. A 0.8 s approach
    and a 2.1 s crossing are different events, but an average over 16
    ticks and one over 43 are differently noisy, and the blank floor has
    to be as noisy as whatever it is judging."""
    measured = {k: sum(b - a for a, b in ex.condition_frames(k)[1])
                for k in [*ex.WORLD_CONDITIONS, "blank"]}
    assert max(measured.values()) - min(measured.values()) <= 2, measured
    assert all(n >= ex.TARGET_EVENT_TICKS - 2 for n in measured.values())
    print(f"measured ticks per condition: {measured}")


def test_blank_is_gray_and_static_does_not_move():
    blank, blank_events = ex.condition_frames("blank")
    assert all(np.allclose(p, ex.WORLD_GRAY) for p in blank)
    assert blank_events        # gray, but still the floor for real events
    static, _ = ex.condition_frames("static")
    n_event = ex.event_shape("static")[0]
    assert all(np.array_equal(static[0], p) for p in static[:n_event])
    assert np.isclose(static[0].min(), ex.PIPE_DARK)
    print("blank is gray throughout; the static control never moves")


def test_the_scroll_speed_is_derived_from_the_game_not_chosen():
    """A motion pathway is tuned to a velocity range: a pipe stepping
    half its own width per tick is a slideshow, and a null against one
    would say nothing about the circuit."""
    per_tick = ex.SCROLL_PX_S * ex.PATCH_PER_SCREEN * ex.TICK
    assert 1.5 < per_tick < 5.0, per_tick
    assert per_tick < ex.PIPE_HALF_W * ex.SCALE_FLAT   # overlaps itself
    print(f"a {ex.SCROLL_PX_S:.0f} px/s game moves the pipe "
          f"{per_tick:.1f} patch px per tick")


def test_the_schedule_measures_the_floor_before_the_conditions():
    sched = [label for label, _, _ in ex._world_schedule()]
    assert sched[0] == "settle"
    for cond in ex.WORLD_CONDITIONS:
        assert sched.index("blank_A") < sched.index(cond)
        assert sched.index("blank_B") < sched.index(cond)
    # rests separate every measured epoch, so adaptation starts level
    measured = [i for i, s in enumerate(sched) if s != "rest"]
    assert all(b - a == 2 for a, b in zip(measured[1:], measured[2:],
                                          strict=False))
    print(f"{ex.world_seconds():.1f} s per brain: " + " ".join(sched))


def _world_run(gf=0.0, lc4=0.0, jitter=0.0, rng=None):
    """One synthetic seed. `gf`/`lc4` are drive the loom condition alone
    gets; everything else differs only by noise."""
    rng = rng or np.random.default_rng(0)

    # Each condition's event shape gives its burst maximum a different
    # number of chances, so an unstimulated brain reads a different burst
    # per condition. The fixture models that, because a floor that
    # ignored it is the bug `_blank_bursts` exists to prevent.
    def shape_floor(cond):
        return 40.0 + 3.0 * ex.WORLD_CONDITIONS.index(cond)

    def metrics(cond, extra_gf=0.0, extra_lc4=0.0):
        n = rng.normal(0, jitter, 2) if jitter else (0.0, 0.0)
        # LPLC2 sits below QUIET_HZ on purpose: the real population does,
        # and a readout that quiet must be refused rather than judged.
        return {"GF": 5.0 + extra_gf + n[0],
                "GF_burst": shape_floor(cond) + 4.0 * extra_gf,
                "LC4": 2.0 + extra_lc4 + n[1],
                "LPLC2": 0.05, "DNa02": 20.0, "descending": 6.0,
                "LC4_peak": 0.0}

    def blank():
        m = metrics("static")
        for cond in ex.WORLD_CONDITIONS:
            m[f"GF_burst@{cond}"] = shape_floor(cond)
        return m

    return {"blank_A": blank(), "blank_B": blank(),
            "static": metrics("static"), "scroll": metrics("scroll"),
            "loom": metrics("loom", gf, lc4)}


def test_a_world_that_does_nothing_reads_null():
    runs = [_world_run() for _ in range(3)]
    eff = ex.drive_effect(runs)
    assert not any(e["drives"] for e in eff.values()), eff
    assert "NULL" in ex._world_verdict(eff)
    print("a world the brain ignores reads null, and says pipes are scenery")


def test_a_looming_pipe_that_fires_the_giant_fiber_reads_pass():
    runs = [_world_run(gf=30.0, lc4=15.0) for _ in range(3)]
    eff = ex.drive_effect(runs)
    assert eff["loom/GF"]["drives"] and eff["loom/LC4"]["drives"]
    assert not eff["scroll/GF"]["drives"]
    verdict = ex._world_verdict(eff)
    assert verdict.startswith("PASS") and "perspective" in verdict
    print("loom-only GF drive -> render pipes with perspective")


def test_detectors_without_escape_read_partial_not_pass():
    """The honest middle: the injection exists because the emergent loom
    signal is weak, so 'the eyes stir LC4 but never command escape' is a
    real outcome and must not be reported as either success or nothing."""
    runs = [_world_run(gf=0.0, lc4=15.0) for _ in range(3)]
    eff = ex.drive_effect(runs)
    assert eff["loom/LC4"]["drives"] and not eff["loom/GF"]["drives"]
    verdict = ex._world_verdict(eff)
    assert verdict.startswith("PARTIAL") and "injection" in verdict
    print("LC4 without GF -> partial: fff would ride the injection")


def test_conditions_do_not_always_run_in_the_same_order():
    """The confound this rotation exists for: run one fixed order and a
    slow drift in excitability rises across the session, which looks
    exactly like a stimulus that gets stronger — and the condition that
    always runs last is the one that always looks strongest."""
    n = len(ex.WORLD_CONDITIONS)
    orders = [ex.condition_order(i) for i in range(n)]
    for slot in range(n):
        assert len({o[slot] for o in orders}) == n, orders
    for order in orders:
        assert sorted(order) == sorted(ex.WORLD_CONDITIONS)
    print(f"over {n} brains every condition runs in every slot: "
          f"{[o[0] for o in orders]} lead")


def test_a_burst_is_scored_per_event_not_per_epoch():
    """An escape is a burst at one moment, and a mean over a whole
    approach divides it away. But the epoch maximum is no good either —
    it just finds the loudest spontaneous moment and grows with epoch
    length, and blank epochs here burst to 200 Hz unprovoked."""
    quiet = np.zeros(60, dtype=np.float32)
    events = [(0, 20), (20, 40), (40, 60)]
    assert ex._burst(quiet, events) == 0.0
    # one loud tick in one event: scored, but only as one event in three
    one = quiet.copy()
    one[5] = 10.0
    every = quiet.copy()
    every[[5, 25, 45]] = 10.0
    assert ex._burst(every, events) > ex._burst(one, events) > 0.0
    assert abs(ex._burst(every, events) - 3 * ex._burst(one, events)) < 1e-6
    # and a burst is found wherever in the event it happens
    late = quiet.copy()
    late[[18, 38, 58]] = 10.0
    assert abs(ex._burst(late, events) - ex._burst(every, events)) < 1e-6
    print(f"a burst on every approach reads "
          f"{ex._burst(every, events):.0f} Hz against "
          f"{ex._burst(one, events):.0f} for one")


def test_the_gap_between_repeats_outlasts_adaptation():
    """Too short a gap and every repeat is weaker than the one before,
    which biases toward the null — the answer that would be believed."""
    assert ex.GAP_S >= Retina.TAU_ADAPT, (ex.GAP_S, Retina.TAU_ADAPT)
    print(f"{ex.GAP_S}s gap against a {Retina.TAU_ADAPT}s adaptation "
          f"constant")


def test_the_burst_floor_is_measured_per_condition_shape():
    """A maximum over 40 windows beats one over 13 under the identical
    null, so one blank burst number would be a floor too high for the
    short events and too low for the long ones — and being systematic,
    every brain would shift the same way and agreeing on sign would
    prove nothing."""
    gf = np.zeros(200, dtype=np.float32)
    rng = np.random.default_rng(3)
    gf[:] = rng.integers(0, 3, size=200)      # pure noise, no stimulus
    floors = ex._blank_bursts(gf)
    assert set(floors) == {f"GF_burst@{c}" for c in ex.WORLD_CONDITIONS}
    long_ev, short_ev = floors["GF_burst@scroll"], floors["GF_burst@loom"]
    assert long_ev > short_ev, floors
    print(f"on noise alone, scroll-shaped events read "
          f"{long_ev:.0f} Hz and loom-shaped {short_ev:.0f} Hz — "
          f"which is why they get separate floors")


def test_a_suppressed_burst_is_never_a_pass():
    """Escape is more giant fiber, never less. A shape artefact that
    lowered bursts during approaches must not print a pass."""
    runs = [_world_run() for _ in range(3)]
    for run in runs:
        run["loom"]["GF_burst"] = run["blank_A"]["GF_burst@loom"] - 12.0
    eff = ex.drive_effect(runs)["loom/GF_burst"]
    assert eff["drives"] and eff["effect"] < 0      # it does clear the bar
    verdict = ex._world_verdict(ex.drive_effect(runs))
    assert not verdict.startswith("PASS"), verdict
    print(f"a {eff['effect']:+.0f} Hz burst *drop* reads "
          f"'{verdict.split(':')[0]}', not PASS")


def test_a_silent_population_is_refused_rather_than_judged():
    """The trap this guard exists for: a population that fires almost
    never has almost no sham spread, so an arithmetic wobble clears the
    margin and reads as biology. LPLC2 really does sit at ~0.05 Hz."""
    runs = []
    for i in range(3):
        run = _world_run()
        # a wobble far below anything meaningful, in one direction
        run["loom"]["LPLC2"] = 0.05 + 0.001 * (i + 1)
        runs.append(run)
    eff = ex.drive_effect(runs)["loom/LPLC2"]
    assert eff["quiet"] and not eff["drives"]
    assert eff["consistent_sign"]          # it would have passed on sign
    assert abs(eff["effect"]) > eff["threshold"]   # ... and on the margin
    print(f"a {eff['effect']:+.4f} Hz wobble on a "
          f"{eff['baseline']:.2f} Hz population is refused, not reported")


def test_world_noise_alone_does_not_read_as_drive():
    rng = np.random.default_rng(5)
    runs = [_world_run(jitter=2.0, rng=rng) for _ in range(3)]
    eff = ex.drive_effect(runs)
    assert not eff["loom/GF"]["drives"], eff["loom/GF"]
    assert eff["loom/GF"]["sham_sd"] > 0.0
    print(f"jitter gives {eff['loom/GF']['effect']:+.2f} Hz against a "
          f"{eff['loom/GF']['threshold']:.2f} threshold -> null, correctly")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nALL PHASE 0 TESTS PASSED")
