"""Smoke tests: speed, silence at rest, and the escape circuit.

The two integration tests at the bottom need no connectome and so run
under pytest on any machine; `main()` is the full smoke run.

Run:  python3 tests/test_brain.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fruitfly import data
from fruitfly.brain import (
    Brain,
    Params,
    RateMonitor,
    _decays,
    _psp_calibration,
)


def main():
    indptr, indices, weights, pops, _retina = data.load()
    n = len(indptr) - 1
    print(f"loaded brain: {n} neurons, {len(indices)} connections")

    # ---- 1. silence at rest (no noise, no stimulus) ----------------------
    b = Brain(indptr, indices, weights, pops, dt=1.0, seed=1)
    spikes = sum(len(b.step()) for _ in range(200))
    print(f"[rest]  spikes in 200 ms with no input: {spikes} (expect 0)")

    # ---- 2. escape circuit: looming detectors -> giant fiber -------------
    b = Brain(indptr, indices, weights, pops, dt=1.0, seed=1)
    mon = RateMonitor(b, ["GF", "DNa02_L", "DNa02_R", "descending"])
    b.set_stimulus({"LC4_L": 100.0, "LPLC2_L": 100.0})
    gf_spikes = 0
    t0 = time.perf_counter()
    total = 0
    for _ in range(500):
        s = b.step()
        total += len(s)
        mon.update(s)
        gf_spikes += b.pop_count(s, "GF")
    wall = time.perf_counter() - t0
    print(f"[loom]  500 ms of looming: total spikes {total}, "
          f"GF spikes {gf_spikes} (expect > 0)")
    d_l, d_r = mon.rates["DNa02_L"], mon.rates["DNa02_R"]
    print(f"[loom]  descending rate {mon.rates['descending']:.2f} Hz, "
          f"DNa02 L/R {d_l:.1f}/{d_r:.1f} Hz")
    print(f"[speed] {wall:.2f} s wall for 0.5 s biological "
          f"({0.5 / wall:.2f}x real time)")

    # ---- 3. spontaneous activity under background noise ------------------
    for rate, w in [(20.0, 3.0), (50.0, 3.0), (100.0, 3.0), (50.0, 5.0)]:
        b = Brain(indptr, indices, weights, pops, dt=1.0,
                  noise_rate=rate, noise_weight=w, seed=1)
        t0 = time.perf_counter()
        total = sum(len(b.step()) for _ in range(500))
        wall = time.perf_counter() - t0
        hz = total / (n * 0.5)
        print(f"[noise] rate={rate:>5} Hz w={w} synapses -> mean activity "
              f"{hz:.3f} Hz/neuron, {total} spikes/0.5s, "
              f"{0.5/wall:.2f}x real time")

    # ---- 4. photoreceptor drive cost ------------------------------------
    b = Brain(indptr, indices, weights, pops, dt=1.0,
              noise_rate=50.0, noise_weight=3.0, seed=1)
    b.set_stimulus({"photoreceptor_L": 10.0, "photoreceptor_R": 10.0})
    t0 = time.perf_counter()
    total = sum(len(b.step()) for _ in range(500))
    wall = time.perf_counter() - t0
    print(f"[light] photoreceptors at 10 Hz + noise: {total} spikes/0.5s, "
          f"{0.5/wall:.2f}x real time")


def test_decays_are_exact_not_euler():
    """Decay factors must be exp(-dt/tau), never forward Euler.

    Forward Euler does not merely add error here, it rescales the model:
    1 - dt/tau at dt=2ms turns tau_syn=5.5 into an effective 4.42ms,
    -19.5%, and tau_m=20 into 18.98. The network was quietly running
    with time constants nobody chose.
    """
    p = Params()
    for dt in (2.0, 1.0, 0.5, 0.1):
        d_s, d_m, d_a = _decays(dt, p)
        for got, tau, name in ((d_s, p.tau_syn, "tau_syn"),
                               (d_m, p.tau_m, "tau_m"),
                               (d_a, p.tau_adapt, "tau_adapt")):
            exact = math.exp(-dt / tau)
            euler = 1.0 - dt / tau
            assert abs(got - exact) < 1e-12, \
                f"{name} at dt={dt} is not exp(-dt/tau)"
            if abs(exact - euler) > 1e-6:      # dt/tau big enough to tell
                assert abs(got - euler) > 1e-9, \
                    f"{name} at dt={dt} regressed to forward Euler"
    print("decay factors are exact exponentials at every dt")


def test_psp_calibration_converges_to_analytic():
    """As dt shrinks, the calibrated weight must approach the real answer.

    For an exponential synapse driving a leaky membrane, the impulse
    response is analytic, so the discretisation has a ground truth to
    converge to. This is what catches a calibration that silently stops
    matching the integration scheme it is supposed to mirror.
    """
    p = Params()
    ts, tm = p.tau_syn, p.tau_m
    t_peak = math.log(tm / ts) / (1 / ts - 1 / tm)
    peak = ts / (ts - tm) * (math.exp(-t_peak / ts) - math.exp(-t_peak / tm))
    want = p.psp_peak / peak
    err = [abs(_psp_calibration(dt, p) - want) / want
           for dt in (1.0, 0.1, 0.01)]
    assert err[0] > err[1] > err[2], f"not converging: {err}"
    assert err[2] < 0.005, f"dt=0.01 still {100*err[2]:.2f}% off analytic"
    print(f"PSP calibration converges to analytic "
          f"({100*err[2]:.2f}% at dt=0.01)")


def test_brain_smoke():
    """The full smoke run. Needs the compiled connectome; conftest skips
    it when there is none, and marks it slow either way."""
    main()


if __name__ == "__main__":
    test_decays_are_exact_not_euler()
    test_psp_calibration_converges_to_analytic()
    main()
