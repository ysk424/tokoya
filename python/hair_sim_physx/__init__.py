"""PhysX Hair Simulation — Blender 5.1 extension entry point."""
from __future__ import annotations

import bpy

from . import operators, panels, properties

_REGISTERED = (
    properties,
    operators,
    panels,
)


def register() -> None:
    for mod in _REGISTERED:
        mod.register()


def unregister() -> None:
    for mod in reversed(_REGISTERED):
        mod.unregister()
