"""Headless closed-loop test: brain + senses + motor, no GTK.

Simulates 30 wall-seconds of desktop life on a virtual 1920x1200 screen,
including a scripted "cursor attack" at t=10s, and logs what the fly does.

Run:  python3 tests/test_behavior.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from fruitfly import data
from fruitfly.brain import Brain, RateMonitor
from fruitfly.senses import Senses, SensoryFrame
from fruitfly.motor import MotorMap

W, H = 1920, 1200
MOTOR_POPS = ["GF", "DNa02_L", "DNa02_R", "DNp09", "MDN", "descending"]


def main():
    indptr, indices, weights, pops = data.load()
    brain = Brain(indptr, indices, weights, pops, dt=2.0,
                  noise_rate=100.0, noise_weight=3.0, seed=7)
    mon = RateMonitor(brain, MOTOR_POPS)
    gf_mask = np.zeros(brain.n, dtype=bool)
    gf_mask[pops["GF"]] = True

    senses = Senses()
    motor = MotorMap(W, H)
    frame = SensoryFrame(cursor_x=1e9, cursor_y=1e9)

    tick = 1 / 30.0  # motor updates at 30 fps equivalent
    steps_per_tick = int(tick * 1000 / brain.dt)
    events, states = [], {"flying": 0.0, "landed": 0.0, "escape": 0.0}
    gf_total = 0
    wall0 = time.perf_counter()

    t = 0.0
    while t < 30.0:
        # scripted cursor: swoops onto the fly during t=[10,13] and [20,23]
        if 10.0 <= t <= 13.0 or 20.0 <= t <= 23.0:
            phase = (t - 10.0 if t <= 13.0 else t - 20.0) / 3.0
            frame.cursor_x = motor.st.x + (1.0 - phase) * 500.0
            frame.cursor_y = motor.st.y + (1.0 - phase) * 300.0
        else:
            frame.cursor_x, frame.cursor_y = 1e9, 1e9

        stim = senses.rates(frame, motor.st.x, motor.st.y, motor.st.heading, t)
        threat, bearing = stim.pop("_threat"), stim.pop("_bearing")
        brain.set_stimulus(stim)

        gf_fired = 0
        for _ in range(steps_per_tick):
            s = brain.step()
            mon.update(s)
            if len(s):
                k = int(gf_mask[s].sum())
                gf_fired += k
                gf_total += k

        prev = motor.st.last_event
        motor.update(tick, t, mon.rates, gf_fired, bearing, threat)
        states[motor.st.state] += tick
        if motor.st.last_event != prev:
            events.append((t, motor.st.last_event))
        t += tick

    wall = time.perf_counter() - wall0
    print(f"30 bio-seconds in {wall:.1f} wall-seconds "
          f"({30/wall:.2f}x real time, {brain.total_spikes} spikes)")
    print(f"time flying {states['flying']:.1f}s / landed {states['landed']:.1f}s"
          f" / escaping {states['escape']:.1f}s;  GF spikes: {gf_total}")
    print("events:")
    for et, e in events:
        print(f"  t={et:5.1f}s  {e}")

    ok = gf_total > 0 and states["flying"] > 1.0 and states["landed"] > 1.0
    print("PASS" if ok else "FAIL: expected escapes + both flying and landed time")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
