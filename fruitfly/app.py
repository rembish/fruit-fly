"""Wire the brain, the senses and a window backend together, then run."""

from __future__ import annotations

from .brain import Brain
from .core import Controller
from .senses import Senses, Retina
from .ui import create_host


def run(noise_rate: float = 100.0, noise_weight: float = 3.0,
        inh_gain: float = 1.5, dt: float = 2.0, size: float = 34.0,
        hud: bool = False, vision: bool = True, pure_retina: bool = False,
        backend: str | None = None, seed: int | None = None):
    from . import data

    print("[app] loading connectome ...")
    indptr, indices, weights, pops, retina_data = data.load()
    brain = Brain(indptr, indices, weights, pops, dt=dt,
                  noise_rate=noise_rate, noise_weight=noise_weight,
                  inh_gain=inh_gain, seed=seed)
    retina = Retina(retina_data) if vision else None
    senses = Senses(retina=retina,
                    loom_injection=0.0 if pure_retina else 0.4)
    n_photo = (len(retina_data["L_idx"]) + len(retina_data["R_idx"])
               if vision else 0)

    host = create_host(hud=hud, backend=backend)
    controller = Controller(brain, senses, host, size=size, vision=vision)
    host.attach(controller)

    print(f"[app] brain ready: {brain.n} neurons, {len(indices)} connections, "
          f"{n_photo} retinotopic photoreceptors — releasing the fly "
          f"({host.name})")

    controller.start()
    try:
        host.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
        host.shutdown()
