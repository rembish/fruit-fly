"""Smoke tests: speed, silence at rest, and the escape circuit.

Run:  python3 tests/test_brain.py
"""

import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from fruitfly import data
from fruitfly.brain import Brain, RateMonitor


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
    for i in range(500):
        s = b.step()
        total += len(s)
        mon.update(s)
        gf_spikes += b.pop_count(s, "GF")
    wall = time.perf_counter() - t0
    print(f"[loom]  500 ms of looming: total spikes {total}, "
          f"GF spikes {gf_spikes} (expect > 0)")
    print(f"[loom]  descending rate {mon.rates['descending']:.2f} Hz, "
          f"DNa02 L/R {mon.rates['DNa02_L']:.1f}/{mon.rates['DNa02_R']:.1f} Hz")
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
              f"{hz:.3f} Hz/neuron, {total} spikes/0.5s, {0.5/wall:.2f}x real time")

    # ---- 4. photoreceptor drive cost ------------------------------------
    b = Brain(indptr, indices, weights, pops, dt=1.0,
              noise_rate=50.0, noise_weight=3.0, seed=1)
    b.set_stimulus({"photoreceptor_L": 10.0, "photoreceptor_R": 10.0})
    t0 = time.perf_counter()
    total = sum(len(b.step()) for _ in range(500))
    wall = time.perf_counter() - t0
    print(f"[light] photoreceptors at 10 Hz + noise: {total} spikes/0.5s, "
          f"{0.5/wall:.2f}x real time")


if __name__ == "__main__":
    main()
