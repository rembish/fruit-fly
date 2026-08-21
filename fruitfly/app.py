"""Wire the brain, the senses and a window backend together, then run."""

from __future__ import annotations

import sys
import threading

from . import bench, data
from .brain import Brain
from .core import Controller
from .senses import Retina, Senses
from .ui import create_host


def _poke_console(controller) -> None:
    """Read poke commands from the terminal that launched the fly.

    The terminal is the one input channel that costs nothing: the fly's
    windows are deliberately non-activating, so they never hold keyboard
    focus, and reading stdin needs no permission on any platform.
    """
    usage = ("[poke] <population> [hz] [seconds]   e.g. `GF`, `MDN 150`, "
             "`DNa02_L 120 1.0`;  `?` lists populations")
    for raw in sys.stdin:
        parts = raw.split()
        if not parts:
            continue
        head = parts[0].lower()
        if head in ("?", "h", "help", "list"):
            print(f"[poke] {len(controller.pops)} populations: "
                  f"{', '.join(controller.pops)}\n{usage}", flush=True)
            continue
        name = next((n for n in controller.pops if n.lower() == head), None)
        if name is None:
            print(f"[poke] no population {parts[0]!r}; `?` lists them",
                  flush=True)
            continue
        try:
            hz = float(parts[1]) if len(parts) > 1 else 120.0
            secs = float(parts[2]) if len(parts) > 2 else 0.4
        except ValueError:
            print("[poke] rate and duration must be numbers", flush=True)
            continue
        print(f"[poke] {controller.poke(name, hz, secs)}", flush=True)


def _autodetect_dt(indptr, indices, weights, pops, host, *,
                   vision: bool, **brain_kw) -> float:
    """Benchmark this machine, then pick a timestep it can actually hold."""
    print("[bench] measuring this machine ...")
    rows = bench.measure(indptr, indices, weights, pops,
                         dts=bench.AUTO_MENU, vision=vision, **brain_kw)
    overhead = bench.grab_overhead(host) if vision else 0.0
    pick = bench.choose(rows, overhead)
    verdict = "sustains real time" if pick["sustainable"] else (
        "cannot sustain real time — no coarser timestep is on offer")
    print(f"[bench] {pick['hz_per_neuron']:.2f} Hz/neuron, vision costs "
          f"{100 * overhead:.0f}% of the wall clock on {host.name}; "
          f"dt={pick['dt']} ms at {pick['realtime']:.2f}x brain-only "
          f"({verdict})")
    return float(pick["dt"])


def run(noise_rate: float = 100.0, noise_weight: float = 3.0,
        inh_gain: float = 1.5, dt: float = 2.0, size: float = 34.0,
        hud: bool = False, vision: bool = True, pure_retina: bool = False,
        backend: str | None = None, seed: int | None = None,
        recordable: bool = False):
    print("[app] loading connectome ...")
    indptr, indices, weights, pops, retina_data = data.load()

    # The host comes first when dt is being measured: the cost that
    # actually decides the timestep is this backend's screen grab, and
    # that is only measurable once there is a backend to ask.
    host = create_host(hud=hud, backend=backend, recordable=recordable)
    if dt == "auto":
        dt = _autodetect_dt(indptr, indices, weights, pops, host,
                            vision=vision, noise_rate=noise_rate,
                            noise_weight=noise_weight, inh_gain=inh_gain)

    brain = Brain(indptr, indices, weights, pops, dt=dt,
                  noise_rate=noise_rate, noise_weight=noise_weight,
                  inh_gain=inh_gain, seed=seed)
    retina = Retina(retina_data) if vision else None
    senses = Senses(retina=retina,
                    loom_injection=0.0 if pure_retina else 0.4)
    n_photo = (len(retina_data["L_idx"]) + len(retina_data["R_idx"])
               if vision else 0)

    controller = Controller(brain, senses, host, size=size, vision=vision)
    host.attach(controller)

    print(f"[app] brain ready: {brain.n} neurons, {len(indices)} connections, "
          f"{n_photo} retinotopic photoreceptors — releasing the fly "
          f"({host.name})")

    if sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=_poke_console, args=(controller,),
                         daemon=True, name="fly-poke").start()
        print("[app] type a population name here to stimulate it "
              "(`?` for the list) — the fly's reaction is not scripted")

    controller.start()
    try:
        host.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
        host.shutdown()
