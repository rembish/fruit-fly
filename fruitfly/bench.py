"""Measure what this machine sustains, so the timestep is chosen not guessed.

The paper integrates at dt = 0.1 ms. Whether that is reachable in real
time is a property of the machine, not of the model, so ask the machine.

Cost per simulated millisecond decomposes cleanly:

    wall(dt) = D(dt)/dt + rate * n * k

D is the dense per-step cost — the fused numpy update over all 139k
neurons, paid every step whatever happens — and k is the marginal cost of
one spike propagating through the CSR. Halving dt doubles how often D is
paid but does not change how many spikes there are per simulated second,
which is why smaller dt costs so much and buys so little.

Measuring the two separately matters. The obvious approach — run each
candidate dt for a moment and time it — is measuring a transient:
adaptation equilibrates over tau_adapt = 500 ms and the noise-floor
governor has a 500 ms EMA on top, so a short burst samples an arbitrary
point of each candidate's own ramp-up, and the candidates are not
comparable to each other. D is measured on a silenced brain where there is no transient
to be caught by, and the firing rate is measured once, warm.
"""

from __future__ import annotations

import time

import numpy as np

from .brain import Brain

#: Timesteps the printed ladder covers, so the speed picture is visible.
LADDER = (2.0, 1.0, 0.5)

#: Timesteps auto-select may actually pick — only the tuned one.
#:
#: dt is not a free knob for this toy, which the headless behaviour test
#: settles empirically. Over the same 30 simulated seconds:
#:
#:     dt=2.0   12.4M spikes   flying 12.7s   landed 15.4s   PASS
#:     dt=1.0   14.5M spikes   flying 25.4s   landed  2.8s   PASS, barely
#:     dt=0.5   16.1M spikes   flying 27.6s   landed  0.6s   FAIL
#:
#: Finer dt resolves spike timing the coarse step used to merge, the
#: network fires more, and the motor map's thresholds were calibrated
#: against the coarse rate — so the "more accurate" fly never lands.
#: Auto-selecting per machine would hand fast machines a broken fly.
#: `python3 -m fruitfly calibrate --dt 0.5` derives the retune, which
#: does rescue the finer steps (dt=0.5 goes from landed 0.6s and FAIL to
#: landed 6.9s and PASS with recalibrated thresholds). Auto-select still
#: will not pick them, because it cannot edit motor.py for you.
AUTO_MENU = (2.0,)

#: core.py grabs two eye patches on every third 60 Hz tick.
GRAB_HZ = 40.0

#: What auto-select aims for, over and above the measured UI cost.
TARGET_REALTIME = 1.05


def _median_us_per_step(brain: Brain, steps: int, repeats: int) -> float:
    """Median wall microseconds per step, to blunt turbo/throttle drift."""
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(steps):
            brain.step()
        runs.append(1e6 * (time.perf_counter() - t0) / steps)
    return float(np.median(runs))


def dense_cost(indptr, indices, weights, pops, dt: float, *,
               steps: int = 40, repeats: int = 3) -> float:
    """D(dt): microseconds per step with the brain silenced.

    No noise and no stimulus means no spikes, so nothing propagates and
    this isolates the per-step floor. It is also the one measurement with
    no transient to be fooled by: a silent network stays silent.
    """
    b = Brain(indptr, indices, weights, pops, dt=dt, seed=1)
    b.step()                      # fault in the lazily-allocated pages
    return _median_us_per_step(b, steps, repeats)


#: Photoreceptor drive standing in for "a fly with its eyes open". The
#: real rate depends on what is on screen, but a blind fly is measurably
#: cheaper -- noise alone settles near 1.8 Hz/neuron where the closed-loop
#: behaviour test with vision runs near 3.0 -- so benchmarking without it
#: would promise a dt the seeing fly cannot hold.
PHOTORECEPTOR_HZ = 10.0


def warm_rate(indptr, indices, weights, pops, *, dt: float = 2.0,
              sim_ms: float = 1500.0, noise_rate: float = 100.0,
              noise_weight: float = 3.0, inh_gain: float = 1.5,
              vision: bool = True, seed: int = 1) -> tuple[float, float]:
    """Steady-state firing rate and per-step cost, measured once, warm.

    Returns (hz_per_neuron, us_per_step). Runs long enough to get past
    adaptation and the noise-floor governor rather than sampling the ramp.
    """
    b = Brain(indptr, indices, weights, pops, dt=dt, noise_rate=noise_rate,
              noise_weight=noise_weight, inh_gain=inh_gain, seed=seed)
    if vision:
        b.set_stimulus({"photoreceptor_L": PHOTORECEPTOR_HZ,
                        "photoreceptor_R": PHOTORECEPTOR_HZ})
    warm = int(0.6 * sim_ms / dt)
    for _ in range(warm):
        b.step()
    n_steps = max(10, int(0.4 * sim_ms / dt))
    spikes = 0
    t0 = time.perf_counter()
    for _ in range(n_steps):
        spikes += len(b.step())
    el = time.perf_counter() - t0
    hz = spikes / (n_steps * dt * 1e-3) / b.n
    return hz, 1e6 * el / n_steps


def measure(indptr, indices, weights, pops, dts=LADDER,
            **run_kw) -> list[dict]:
    """Predicted real-time factor for each candidate dt.

    One warm run fixes the firing rate and the cost of a spike; a silenced
    run per candidate fixes that candidate's dense cost. Everything else
    is arithmetic.
    """
    n = len(indptr) - 1
    hz, warm_us = warm_rate(indptr, indices, weights, pops, **run_kw)
    warm_dt = run_kw.get("dt", 2.0)
    spikes_per_step = hz * n * warm_dt * 1e-3
    d_warm = dense_cost(indptr, indices, weights, pops, warm_dt)
    # marginal microseconds per propagated spike: whatever the warm run
    # cost above the silent floor, divided by the spikes that caused it
    k = 0.0
    if spikes_per_step > 0.0:
        k = max(0.0, (warm_us - d_warm) / spikes_per_step)
    event_us_per_sim_ms = hz * n * k * 1e-3

    rows = []
    for dt in dts:
        d = dense_cost(indptr, indices, weights, pops, dt)
        us_per_sim_ms = d / dt + event_us_per_sim_ms
        rows.append({
            "dt": dt,
            "dense_us": d,
            "event_us_per_ms": event_us_per_sim_ms,
            "us_per_sim_ms": us_per_sim_ms,
            "realtime": 1000.0 / us_per_sim_ms,
        })
    for r in rows:
        r["hz_per_neuron"] = hz
        r["us_per_spike"] = k
    return rows


def grab_overhead(host, side: int = 240, out: int = 96,
                  samples: int = 12) -> float:
    """Fraction of each wall second the vision path spends grabbing.

    This is the honest way to size the headroom auto-select needs, and it
    is very much not a constant: the same dt=2 brain runs at 0.99x under
    GTK and 0.64-0.73x under Win32, because BitBlt costs far more than a
    pixbuf fetch. Returns 0.0 if the host cannot grab at all.
    """
    try:
        host.grab(0, 0, side, out)
    except Exception:
        return 0.0
    t0 = time.perf_counter()
    ok = 0
    for _ in range(samples):
        if host.grab(0, 0, side, out) is not None:
            ok += 1
    if not ok:
        return 0.0
    per_grab = (time.perf_counter() - t0) / samples
    return min(0.9, per_grab * GRAB_HZ)


def choose(rows: list[dict], overhead: float = 0.0,
           target: float = TARGET_REALTIME) -> dict:
    """Finest dt whose predicted speed survives the UI overhead.

    Falls back to the coarsest candidate when nothing qualifies, which is
    the honest answer on a machine that cannot keep up at all: there is no
    dt in the menu that fixes it, because the coarsest is already the
    cheapest.
    """
    budget = target / max(0.05, 1.0 - overhead)
    ok = [r for r in rows if r["realtime"] >= budget]
    best = min(ok, key=lambda r: r["dt"]) if ok else max(
        rows, key=lambda r: r["realtime"])
    return {**best, "needed": budget, "overhead": overhead,
            "sustainable": best["realtime"] >= budget}


def format_table(rows: list[dict], paper_dt: float = 0.1) -> str:
    """Human-readable ladder, including how far it is from the paper."""
    hz = rows[0]["hz_per_neuron"]
    k = rows[0]["us_per_spike"]
    out = [f"measured: {hz:.2f} Hz/neuron steady state, "
           f"{k:.3f} us per propagated spike",
           f"{'dt (ms)':>8} {'dense us/step':>14} {'us/sim ms':>11} "
           f"{'real time':>10}"]
    for r in rows:
        out.append(f"{r['dt']:8.2f} {r['dense_us']:14.1f} "
                   f"{r['us_per_sim_ms']:11.1f} {r['realtime']:9.2f}x")
    finest = min(rows, key=lambda r: r["dt"])
    factor = finest["dt"] / paper_dt
    if factor > 1.0:
        out.append(f"the paper integrates at dt={paper_dt} ms, {factor:.0f}x "
                   f"finer than the finest candidate here.")
    out.append("closing that gap means cutting the dense per-step cost "
               "(a compiled kernel), not picking a smaller dt: the dense "
               "cost is paid every step and barely falls as dt shrinks.")
    out.append(f"note: only dt={AUTO_MENU[0]} ms is behaviourally "
               f"validated. Finer steps make the network fire more than "
               f"the motor map was tuned for and the fly stops landing "
               f"(landed 15.4s at dt=2.0, 2.8s at 1.0, 0.6s at 0.5) — "
               f"they are reachable with an explicit --dt, but auto will "
               f"not choose them.")
    return "\n".join(out)
