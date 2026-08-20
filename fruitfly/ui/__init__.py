"""Window-system backends.

Each backend implements `fruitfly.ui.base.Host`. Pick one automatically
for the running platform, or force one with `--backend`.
"""

from __future__ import annotations

import sys

from .base import Host

#: backend name -> (module, class); imported lazily so a backend's
#: toolkit is only required on the platform that uses it
REGISTRY = {
    "gtk": ("fruitfly.ui.gtk", "GtkHost"),
    "cocoa": ("fruitfly.ui.cocoa", "CocoaHost"),
    "win32": ("fruitfly.ui.win32", "Win32Host"),
}

#: preference order per platform, most native first
PLATFORM_ORDER = {
    "linux": ["gtk"],
    "darwin": ["cocoa", "gtk"],   # GTK/quartz works if someone insists
    "win32": ["win32", "gtk"],    # GTK via MSYS2 as a fallback
    "cygwin": ["win32", "gtk"],
}


def load(name: str) -> type[Host]:
    """Import and return a backend class by name."""
    import importlib

    if name not in REGISTRY:
        raise ValueError(f"unknown backend {name!r}; "
                         f"known: {', '.join(sorted(REGISTRY))}")
    module, cls = REGISTRY[name]
    return getattr(importlib.import_module(module), cls)


def create_host(hud: bool = False, backend: str | None = None) -> Host:
    """Instantiate the best available backend for this platform."""
    if backend:
        cls = load(backend)
        ok, why = cls.available()
        if not ok:
            raise RuntimeError(f"backend {backend!r} unavailable: {why}")
        return cls(hud=hud)

    order = PLATFORM_ORDER.get(sys.platform, [])
    if not order:
        raise RuntimeError(
            f"no backend for platform {sys.platform!r}. Supported: Linux "
            f"(GTK3/X11), macOS (Cocoa), Windows. Contributions welcome — "
            f"see fruitfly/ui/base.py for the interface.")

    problems = []
    for name in order:
        try:
            cls = load(name)
        except Exception as e:
            problems.append(f"{name}: import failed ({e})")
            continue
        ok, why = cls.available()
        if ok:
            return cls(hud=hud)
        problems.append(f"{name}: {why}")
    raise RuntimeError("no usable window backend:\n  "
                       + "\n  ".join(problems))
