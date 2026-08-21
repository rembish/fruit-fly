"""CLI:  python3 -m fruitfly [command] [options]

Commands:
  run        (default) release the fly onto the desktop
  benchmark  measure what timestep this machine can sustain
  calibrate  re-derive the motor thresholds for a changed brain
  fetch      download the FlyWire connectome data (~50 MB)
  prepare    compile the raw tables into data/brain.npz
  test       headless behavioral test (no window)
  phototaxis does luminance asymmetry steer the fly? (web plan M0.1)
  padstats   where does the fly go, and how often would it hit a pad?
             (web plan M0.2)
  pipes      does a scrolling game world reach the escape circuit
             through the eyes alone? (web plan M0.3)
"""

from __future__ import annotations

import argparse
import os
import sys

from . import data


def _dt(value: str):
    """--dt takes milliseconds, or 'auto' to measure this machine."""
    if value.strip().lower() == "auto":
        return "auto"
    return float(value)


#: The web plan's Phase 0 measurements. They share a preamble (load the
#: connectome, settle on a dt) and none of them opens a window.
PHASE0 = ("phototaxis", "padstats", "pipes")


def _phase0(args):
    """Run one of the Phase 0 experiments and print its report."""
    from . import experiments as ex  # noqa: PLC0415
    dt = 2.0 if args.dt == "auto" else args.dt
    print("[phase0] loading connectome ...")
    indptr, indices, weights, pops, retina = data.load()
    common = {"seeds": tuple(args.seeds), "dt": dt,
              "noise_rate": args.noise, "inh_gain": args.inh}

    if args.command == "phototaxis":
        print(f"[phase0] M0.1: {len(args.seeds)} brains x 30 "
              f"simulated seconds ...")
        print(ex.format_phototaxis(ex.phototaxis(
            indptr, indices, weights, pops, retina, **common)))
        return

    if args.command == "pipes":
        print(f"[phase0] M0.3: {len(args.seeds)} brains x "
              f"{ex.world_seconds():.0f} simulated seconds, eyes only ...")
        print(ex.format_world(ex.world_drive(
            indptr, indices, weights, pops, retina, **common)))
        return

    print(f"[phase0] M0.2: capturing {args.calib_seconds:.0f} "
          f"simulated seconds of descending drive ...")
    trace = ex.capture_rates(
        indptr, indices, weights, pops, dt=dt,
        seconds=args.calib_seconds, noise_rate=args.noise,
        inh_gain=args.inh, seed=7 if args.seed is None else args.seed)
    w, h = args.canvas or ex.CANVAS
    traj = ex.replay(trace, w, h)
    print(ex.format_padstats(traj, ex.pad_statistics(traj)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fruitfly", description=__doc__)
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "fetch", "prepare", "test",
                             "benchmark", "calibrate", *PHASE0])
    ap.add_argument("--hud", action="store_true",
                    help="show neural activity HUD overlay")
    ap.add_argument("--no-vision", action="store_true",
                    help="don't sample the screen into the retina")
    ap.add_argument("--pure-retina", action="store_true",
                    help="no direct looming injection: trust the eyes only")
    ap.add_argument("--backend", default=None,
                    help="force a window backend (gtk, cocoa); "
                         "default: auto-detect for this platform")
    ap.add_argument("--size", type=float, default=34.0, help="fly size, px")
    ap.add_argument("--dt", type=_dt, default=2.0,
                    help="simulation timestep, ms (smaller = finer + "
                         "slower), or 'auto' to benchmark this machine "
                         "and pick the finest it can sustain")
    ap.add_argument("--noise", type=float, default=100.0,
                    help="background noise rate, Hz (spontaneity)")
    ap.add_argument("--inh", type=float, default=1.5,
                    help="inhibition gain")
    ap.add_argument("--recordable", action="store_true",
                    help="let screen recorders see the fly (Windows hides "
                         "it from capture so it cannot see itself); the "
                         "fly may then react to its own image")
    ap.add_argument("--calib-seconds", type=float, default=120.0,
                    help="simulated seconds per trace for `calibrate`")
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 13],
                    help="brains to run for `phototaxis` and `pipes`")
    ap.add_argument("--canvas", type=int, nargs=2, default=None,
                    metavar=("W", "H"),
                    help="play field for `padstats` (default 960x540)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)

    if args.command == "fetch":
        data.fetch()
        return
    if args.command == "prepare":
        data.fetch()
        data.prepare()
        return

    # run/test need the compiled brain; build it if missing
    brain_path = os.path.join(data.data_dir(), "brain.npz")
    if not os.path.exists(brain_path):
        print("[app] compiled brain not found — fetching & preparing "
              "(one-time, ~50 MB download)")
        data.fetch()
        data.prepare()

    if args.command == "benchmark":
        from .bench import format_table, measure  # noqa: PLC0415
        print("[bench] loading connectome ...")
        indptr, indices, weights, pops, _retina = data.load()
        print(format_table(measure(indptr, indices, weights, pops)))
        return

    if args.command == "calibrate":
        from .calibrate import format_result, recalibrate  # noqa: PLC0415
        dt = 2.0 if args.dt == "auto" else args.dt
        print(f"[calib] capturing descending traces "
              f"({args.calib_seconds:.0f} simulated seconds each) ...")
        indptr, indices, weights, pops, _retina = data.load()
        print(format_result(recalibrate(
            indptr, indices, weights, pops, dt=dt,
            seconds=args.calib_seconds, noise_rate=args.noise,
            inh_gain=args.inh)))
        return

    if args.command in PHASE0:
        _phase0(args)
        return

    if args.command == "test":
        os.execv(sys.executable, [sys.executable, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tests", "test_behavior.py")])

    # imported late so `fetch`, `prepare` and `--help` work with no
    # display toolkit installed (importing app pulls in a backend)
    from .app import run  # noqa: PLC0415
    run(noise_rate=args.noise, inh_gain=args.inh, dt=args.dt,
        size=args.size, hud=args.hud, vision=not args.no_vision,
        pure_retina=args.pure_retina, backend=args.backend, seed=args.seed,
        recordable=args.recordable)


if __name__ == "__main__":
    main()
