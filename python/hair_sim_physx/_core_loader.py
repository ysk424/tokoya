"""Lazy import of the compiled `_core` pybind11 module.

Isolated so the rest of the add-on can be loaded even before the
native wheel is built — useful during early development.
"""
from __future__ import annotations

from types import ModuleType

_core: ModuleType | None = None
_error: Exception | None = None


def get_core() -> ModuleType | None:
    global _core, _error
    if _core is not None or _error is not None:
        return _core
    try:
        from . import _core as native  # type: ignore[attr-defined]
    except ImportError as exc:
        _error = exc
        return None
    _core = native
    return _core


def status() -> str:
    core = get_core()
    if core is None:
        return f"native module not built ({_error})"
    flags = []
    if getattr(core, "HAVE_PHYSX", False):
        flags.append("PhysX")
    if getattr(core, "ENABLE_GPU", False):
        flags.append("GPU")
    return "loaded" + (f" ({', '.join(flags)})" if flags else " (stub)")
