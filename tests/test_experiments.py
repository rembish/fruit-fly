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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nALL PHASE 0 TESTS PASSED")
