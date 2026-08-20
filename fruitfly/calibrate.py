"""Re-derive the motor thresholds when the brain's excitability moves.

The fly/land balance is set by two constants in `motor.MotorMap`, LAND_REF
and TAKEOFF_REF, compared against the descending pool's firing rate. They
were tuned by hand against a captured 120 s trace, which means they are
tied to one operating point — and anything that shifts how much the
network fires silently un-tunes the fly. Measured at three timesteps over
the same 30 simulated seconds:

    dt=2.0   12.4M spikes   flying 12.7s   landed 15.4s   PASS
    dt=1.0   14.5M spikes   flying 25.4s   landed  2.8s   PASS, barely
    dt=0.5   16.1M spikes   flying 27.6s   landed  0.6s   FAIL, never lands

The thresholds are absolute (Hz) but the thing they are really expressing
is relative: "calm for this brain" and "a burst for this brain". So store
the intent as quantiles of the descending trace instead of as Hz. Capture
a trace under the tuned reference brain, ask which quantiles the hand-tuned
constants sit at, then capture a trace under whatever new brain you have
and read the Hz off at those same quantiles.

That makes a retune mechanical rather than a matter of taste, which is
what any future change to excitability needs — a finer dt, dropping
monoamines out of fast excitation, adding neuromodulatory gain.
"""

from __future__ import annotations

import numpy as np

from .brain import Brain, RateMonitor
from .motor import MotorMap

#: The population the fly/land decision is thresholded against.
POOL = "descending"

#: Simulated seconds to discard before sampling. Adaptation settles over
#: tau_adapt=500ms and the noise-floor governor has a 500ms EMA on top, so
#: an early sample measures the ramp rather than the operating point.
WARMUP_S = 3.0

#: The reference brain: the configuration the constants were tuned at.
REFERENCE_DT = 2.0


def capture(indptr, indices, weights, pops, *, dt=REFERENCE_DT,
            seconds=120.0, noise_rate=100.0, noise_weight=3.0,
            inh_gain=1.5, seed=7) -> np.ndarray:
    """Descending-pool rate trace in Hz, as the motor map would see it.

    Sampled through the same RateMonitor the controller uses, so the
    smoothing matches; sampling every step rather than every frame only
    changes how densely the same distribution is covered.
    """
    brain = Brain(indptr, indices, weights, pops, dt=dt,
                  noise_rate=noise_rate, noise_weight=noise_weight,
                  inh_gain=inh_gain, seed=seed)
    mon = RateMonitor(brain, [POOL])
    warm = int(WARMUP_S * 1000.0 / dt)
    steps = int(seconds * 1000.0 / dt)
    out = np.empty(max(0, steps - warm), dtype=np.float32)
    for i in range(steps):
        mon.update(brain.step())
        if i >= warm:
            out[i - warm] = mon.rates[POOL]
    return out


def quantile_of(trace: np.ndarray, value: float) -> float:
    """Which quantile (0-100) of the trace this rate sits at."""
    return float(100.0 * np.mean(trace < value))


def anchors(trace: np.ndarray,
            land: float | None = None,
            takeoff: float | None = None) -> dict[str, float]:
    """Express the current hand-tuned thresholds as quantiles of a trace."""
    land = MotorMap.LAND_REF if land is None else land
    takeoff = MotorMap.TAKEOFF_REF if takeoff is None else takeoff
    return {"land_q": quantile_of(trace, land),
            "takeoff_q": quantile_of(trace, takeoff)}


def thresholds_at(trace: np.ndarray, land_q: float,
                  takeoff_q: float) -> dict[str, float]:
    """Read the Hz values off a trace at the given quantiles."""
    return {"LAND_REF": float(np.percentile(trace, land_q)),
            "TAKEOFF_REF": float(np.percentile(trace, takeoff_q))}


def describe(trace: np.ndarray, label: str) -> str:
    p10, p50, p90 = np.percentile(trace, [10, 50, 90])
    return (f"{label}: p10/50/90 = {p10:.1f}/{p50:.1f}/{p90:.1f} Hz "
            f"(mean {trace.mean():.1f}, {len(trace)} samples)")


def recalibrate(indptr, indices, weights, pops, *, dt: float,
                seconds: float = 120.0, **brain_kw) -> dict:
    """What LAND_REF and TAKEOFF_REF should be for a brain running at `dt`.

    Captures the reference brain too, rather than trusting the numbers in
    the motor.py comment, so the anchors describe the code as it is now.
    """
    ref = capture(indptr, indices, weights, pops, dt=REFERENCE_DT,
                  seconds=seconds, **brain_kw)
    anc = anchors(ref)
    result = {"reference": ref, "anchors": anc, "dt": dt}
    if abs(dt - REFERENCE_DT) < 1e-9:
        result["target"] = ref
        result["thresholds"] = thresholds_at(ref, **{
            "land_q": anc["land_q"], "takeoff_q": anc["takeoff_q"]})
        return result
    tgt = capture(indptr, indices, weights, pops, dt=dt, seconds=seconds,
                  **brain_kw)
    result["target"] = tgt
    result["thresholds"] = thresholds_at(tgt, anc["land_q"],
                                         anc["takeoff_q"])
    return result


def format_result(r: dict) -> str:
    anc = r["anchors"]
    th = r["thresholds"]
    out = [describe(r["reference"], f"reference brain (dt={REFERENCE_DT})"),
           f"hand-tuned LAND_REF={MotorMap.LAND_REF} Hz sits at the "
           f"{anc['land_q']:.1f}th percentile of that trace; "
           f"TAKEOFF_REF={MotorMap.TAKEOFF_REF} Hz at the "
           f"{anc['takeoff_q']:.1f}th"]
    if r["dt"] != REFERENCE_DT:
        out.append(describe(r["target"], f"target brain    (dt={r['dt']})"))
    out.append(f"to keep the same intent at dt={r['dt']}, set in "
               f"fruitfly/motor.py:")
    out.append(f"    LAND_REF    = {th['LAND_REF']:.1f}")
    out.append(f"    TAKEOFF_REF = {th['TAKEOFF_REF']:.1f}")
    out.append("then confirm with: python3 tests/test_behavior.py "
               f"{r['dt']}")
    return "\n".join(out)
