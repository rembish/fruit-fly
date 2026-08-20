"""Pure-retina looming test: does the escape circuit fire from PIXELS?

No injection into LC4/LPLC2 — the only input is luminance patches fed
through the retinotopic photoreceptors. An expanding dark disc is drawn
into the left eye. If the real optic lobe works even crudely, the loom
detectors (LC4/LPLC2) and giant fiber should respond; a full-field
dimming control tells us how loom-selective the response is.

Run:  python3 tests/test_retina.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from fruitfly import data
from fruitfly.brain import Brain, RateMonitor
from fruitfly.senses import PATCH, Retina, Senses, SensoryFrame

POPS = ["GF", "LC4_L", "LC4_R", "LPLC2_L", "LPLC2_R",
        "DNa02_L", "DNa02_R", "descending"]
TICK = 0.05  # sensory frame every 50 ms


def run_epoch(brain, mon, senses, frame, seconds, describe):
    steps = int(TICK * 1000 / brain.dt)
    gf = 0
    gf_mask = np.zeros(brain.n, dtype=bool)
    gf_mask[brain.pops["GF"]] = True
    t0 = time.perf_counter()
    for _ in range(int(seconds / TICK)):
        stim, _, _ = senses.rates(frame, 500, 500, 0.0, brain.t / 1000.0)
        brain.set_stimulus(stim)
        for _ in range(steps):
            s = brain.step()
            mon.update(s)
            if len(s):
                gf += int(gf_mask[s].sum())
    wall = time.perf_counter() - t0
    r = mon.rates
    print(f"{describe:26s} GF {gf/seconds:5.1f} Hz | "
          f"LC4 L/R {r['LC4_L']:5.1f}/{r['LC4_R']:5.1f} | "
          f"LPLC2 L/R {r['LPLC2_L']:5.1f}/{r['LPLC2_R']:5.1f} | "
          f"DNa02 L/R {r['DNa02_L']:4.1f}/{r['DNa02_R']:4.1f} | "
          f"{seconds/wall:.2f}x rt")
    return gf / seconds, r["LC4_L"], r["LPLC2_L"]


def main():
    indptr, indices, weights, pops, retina_data = data.load()
    brain = Brain(indptr, indices, weights, pops, dt=2.0,
                  noise_rate=100.0, noise_weight=3.0, seed=7)
    mon = RateMonitor(brain, POPS)
    retina = Retina(retina_data)
    senses = Senses(retina=retina, loom_injection=0.0)  # eyes only!

    frame = SensoryFrame(cursor_x=1e9, cursor_y=1e9, patch_dt=TICK)
    frame.patch_L = np.full((PATCH, PATCH), 0.55, dtype=np.float32)
    frame.patch_R = np.full((PATCH, PATCH), 0.55, dtype=np.float32)

    print("== settling with uniform gray (adaptation) ==")
    run_epoch(brain, mon, senses, frame, 3.0, "settle")
    gf0, lc0, lp0 = run_epoch(brain, mon, senses, frame, 3.0, "baseline")

    print("== expanding dark disc, left eye (0.6 s) ==")
    yy, xx = np.mgrid[0:PATCH, 0:PATCH]
    center = PATCH / 2
    gf_max, lc_max, lp_max = 0.0, 0.0, 0.0
    n_frames = int(0.6 / TICK)
    for i in range(n_frames):
        r = 4 + (48 - 4) * i / (n_frames - 1)
        disc = ((xx - center) ** 2 + (yy - center) ** 2) <= r * r
        frame.patch_L = np.where(disc, 0.06, 0.55).astype(np.float32)
        g, lc, lp = run_epoch(brain, mon, senses, frame, TICK,
                              f"  loom r={r:4.1f}px")
        gf_max = max(gf_max, g)
        lc_max, lp_max = max(lc_max, lc), max(lp_max, lp)

    print("== recovery ==")
    frame.patch_L = np.full((PATCH, PATCH), 0.55, dtype=np.float32)
    run_epoch(brain, mon, senses, frame, 2.0, "recovery")

    print("== control: full-field dimming both eyes (0.6 s) ==")
    gf_dim = 0.0
    for i in range(n_frames):
        lum = 0.55 - (0.55 - 0.10) * i / (n_frames - 1)
        frame.patch_L = np.full((PATCH, PATCH), lum, dtype=np.float32)
        frame.patch_R = np.full((PATCH, PATCH), lum, dtype=np.float32)
        g, _, _ = run_epoch(brain, mon, senses, frame, TICK,
                            f"  dim lum={lum:4.2f}")
        gf_dim = max(gf_dim, g)

    print()
    print(f"baseline GF {gf0:.1f} Hz, LC4_L {lc0:.1f} Hz, "
          f"LPLC2_L {lp0:.1f} Hz")
    print(f"loom     GF {gf_max:.1f} Hz, LC4_L {lc_max:.1f} Hz, "
          f"LPLC2_L {lp_max:.1f} Hz")
    print(f"dimming  GF {gf_dim:.1f} Hz (loom-selectivity check)")
    ok = lc_max > 3 * max(lc0, 1.0) and gf_max > gf0 + 10
    print("PASS: loom emerges from pixels through the real retina" if ok
          else "FAIL: retina pathway did not drive the loom circuit")
    return 0 if ok else 1


def test_retina_and_looming():
    """Retinotopy, and whether a looming cursor reaches the giant fiber."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
