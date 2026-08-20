"""CLI:  python3 -m fruitfly [command] [options]

Commands:
  run        (default) release the fly onto the desktop
  fetch      download the FlyWire connectome data (~50 MB)
  prepare    compile the raw tables into data/brain.npz
  test       headless behavioral test (no window)
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fruitfly", description=__doc__)
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "fetch", "prepare", "test"])
    ap.add_argument("--hud", action="store_true",
                    help="show neural activity HUD overlay")
    ap.add_argument("--no-vision", action="store_true",
                    help="don't sample screen luminance into photoreceptors")
    ap.add_argument("--size", type=float, default=34.0, help="fly size, px")
    ap.add_argument("--dt", type=float, default=2.0,
                    help="simulation timestep, ms (smaller = finer + slower)")
    ap.add_argument("--noise", type=float, default=100.0,
                    help="background noise rate, Hz (spontaneity)")
    ap.add_argument("--inh", type=float, default=1.5,
                    help="inhibition gain")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)

    if args.command == "fetch":
        from . import data
        data.fetch()
        return
    if args.command == "prepare":
        from . import data
        data.fetch()
        data.prepare()
        return

    # run/test need the compiled brain; build it if missing
    from . import data
    brain_path = os.path.join(data.data_dir(), "brain.npz")
    if not os.path.exists(brain_path):
        print("[app] compiled brain not found — fetching & preparing "
              "(one-time, ~50 MB download)")
        data.fetch()
        data.prepare()

    if args.command == "test":
        os.execv(sys.executable, [sys.executable, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tests", "test_behavior.py")])

    from .app import run
    run(noise_rate=args.noise, inh_gain=args.inh, dt=args.dt,
        size=args.size, hud=args.hud, vision=not args.no_vision,
        seed=args.seed)


if __name__ == "__main__":
    main()
