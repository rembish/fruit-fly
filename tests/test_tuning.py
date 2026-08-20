"""Decision logic of the benchmark and the motor recalibration.

Neither needs the connectome: the expensive half of those modules is
measurement, and the half worth pinning is what they decide once the
measuring is done. Synthetic traces and synthetic ladders exercise that
in milliseconds.

Run:  python3 tests/test_tuning.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from fruitfly import bench, calibrate
from fruitfly.motor import MotorMap


def _ladder(*pairs):
    """Synthetic measure() output: (dt, realtime) pairs."""
    return [{"dt": dt, "dense_us": 200.0, "event_us_per_ms": 250.0,
             "us_per_sim_ms": 1000.0 / rt, "realtime": rt,
             "hz_per_neuron": 2.15, "us_per_spike": 0.95}
            for dt, rt in pairs]


def test_auto_select_offers_only_the_tuned_timestep():
    """Auto must never hand a machine an unvalidated dt.

    dt is not a free knob here: at 0.5 the network fires enough more that
    the motor thresholds stop matching and the fly never lands. The whole
    point of AUTO_MENU is that it cannot pick one of those.
    """
    assert bench.AUTO_MENU == (2.0,), bench.AUTO_MENU
    assert set(bench.AUTO_MENU) <= set(bench.LADDER)
    print(f"auto-select menu is {bench.AUTO_MENU}, ladder is {bench.LADDER}")


def test_choose_takes_the_finest_that_survives_the_overhead():
    rows = _ladder((2.0, 3.0), (1.0, 2.0), (0.5, 1.2))
    free = bench.choose(rows, overhead=0.0)
    assert free["dt"] == 0.5 and free["sustainable"], free
    # vision eating half the wall clock doubles what the brain must hit
    busy = bench.choose(rows, overhead=0.5)
    assert busy["dt"] == 2.0 and busy["sustainable"], busy
    print(f"overhead 0% picks dt={free['dt']}, 50% picks dt={busy['dt']}")


def test_choose_admits_defeat_rather_than_lying():
    """A machine that cannot keep up must be told, not given a fake dt."""
    rows = _ladder((2.0, 1.1), (1.0, 0.8))
    pick = bench.choose(rows, overhead=0.9)
    assert not pick["sustainable"], pick
    assert pick["dt"] == 2.0, "should fall back to the fastest candidate"
    print(f"unsustainable machine reports dt={pick['dt']}, sustainable=False")


def test_format_table_names_the_behavioural_limit():
    text = bench.format_table(_ladder((2.0, 3.0), (1.0, 2.0), (0.5, 1.2)))
    assert "2.0" in text and "behaviourally validated" in text, text
    print("benchmark table warns that only the tuned dt is validated")


def test_thresholds_and_quantiles_are_inverses():
    """calibrate reads Hz off a trace at a quantile; that must round-trip."""
    trace = np.linspace(0.0, 100.0, 5001, dtype=np.float32)
    got = calibrate.thresholds_at(trace, 70.0, 97.6)
    assert abs(calibrate.quantile_of(trace, got["LAND_REF"]) - 70.0) < 0.5
    assert abs(calibrate.quantile_of(trace, got["TAKEOFF_REF"]) - 97.6) < 0.5
    print(f"quantile round-trip holds: {got['LAND_REF']:.1f} Hz is p70")


def test_anchors_locate_the_current_motor_constants():
    """The tuned constants must sit somewhere sane on a plausible trace."""
    rng = np.random.default_rng(3)
    trace = rng.normal(5.6, 1.5, 20000).astype(np.float32)
    anc = calibrate.anchors(trace)
    assert 0.0 < anc["land_q"] < anc["takeoff_q"] < 100.0, anc
    assert calibrate.thresholds_at(trace, **anc)["LAND_REF"] < \
        calibrate.thresholds_at(trace, **anc)["TAKEOFF_REF"]
    print(f"LAND_REF={MotorMap.LAND_REF} sits at p{anc['land_q']:.0f}, "
          f"TAKEOFF_REF={MotorMap.TAKEOFF_REF} at p{anc['takeoff_q']:.0f}")


if __name__ == "__main__":
    test_auto_select_offers_only_the_tuned_timestep()
    test_choose_takes_the_finest_that_survives_the_overhead()
    test_choose_admits_defeat_rather_than_lying()
    test_format_table_names_the_behavioural_limit()
    test_thresholds_and_quantiles_are_inverses()
    test_anchors_locate_the_current_motor_constants()
    print("\nALL TUNING TESTS PASSED")
