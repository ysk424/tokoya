"""Hair Simulation — VBD-direction Phase 0: world-coord passthrough.

`SolverInterface` is wired to `WorldPassthrough` (in `_world_passthrough`).
The passthrough reads all Curves positions in world coordinates each
frame_change_post, passes them through a dummy identity function, and
writes them back. No physics yet — this exists to nail the data path
that a real VBD solver will plug into.

The Surface Deform Geometry Nodes modifier "サーフェス変形" is muted
while the passthrough is running so that the round-trip is bit-exact
between what the dummy returns and what the viewport shows. Stop
restores the modifier's prior `show_viewport`. `unregister()` also
restores it as a safety net.

The C++ `NativeHairSolver` from Phase 6C and the Warp `_warp_kernels`
infra (Phase 7W-B) remain in place for historical reference and are
not called from this code path.

Phase 1 invariants preserved: a single persistent frame_change_post
handler gated by WindowManager.hair_sim_running; Start/Stop/Reset
operators with idempotent semantics. Reset does NOT change running
state. Start failure keeps `hair_sim_running=False` so the handler
can never enter a silent running-but-no-op state.
"""
from __future__ import annotations

import array

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty
from bpy.types import Operator, WindowManager

from . import ui


# --------------------------------------------------------------------------- #
# Solver boundary
# --------------------------------------------------------------------------- #

class SolverInterface:
    """VBD-prep: thin delegator to `WorldPassthrough`. Owns a single
    passthrough instance for the lifetime of the running session;
    `start()` re-instantiates it. The C++ `NativeHairSolver` path
    from Phase 6C is intentionally NOT called from here."""

    _TARGET_OBJECT_NAME = "カーブ.001"

    def __init__(self) -> None:
        self._passthrough = None  # WorldPassthrough instance set by start()

    # ---- lifecycle ----

    def start(self) -> bool:
        """Instantiate a fresh `WorldPassthrough`. Returns True only on
        success; on failure the operator must leave
        `hair_sim_running=False` so the handler never enters a silent
        running-but-no-op state."""
        self._passthrough = None

        try:
            from . import _world_passthrough
        except Exception as exc:
            print(f"[hair_sim] start failed: import _world_passthrough: {exc!r}")
            return False

        obj = bpy.data.objects.get(_world_passthrough.TARGET_NAME)
        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim] start failed: target "
                  f"'{_world_passthrough.TARGET_NAME}' missing or not Curves")
            return False

        pt = _world_passthrough.WorldPassthrough()
        if not pt.start(obj):
            return False

        self._passthrough = pt
        return True

    def stop(self) -> None:
        """Spec: Stop restores the GN modifier's prior `show_viewport`
        and does NOT flip `hair_sim_running` (the operator owns that).
        The passthrough does not retain Curves history, so there is
        nothing else to preserve."""
        if self._passthrough is not None:
            self._passthrough.stop()

    def reset(self) -> None:
        """Spec: Reset is a no-op for the identity passthrough. Does
        NOT change `hair_sim_running`. Does NOT touch the GN modifier
        mute state (Reset is not Stop)."""
        if self._passthrough is None:
            return
        self._passthrough.reset()

    # ---- per-frame ----

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        if self._passthrough is None:
            return
        # WorldPassthrough swallows its own exceptions and disables
        # itself via _step_error_active. We never raise out of the
        # handler.
        self._passthrough.step()


_solver = SolverInterface()


# --------------------------------------------------------------------------- #
# Frame handler
# --------------------------------------------------------------------------- #

@persistent
def _on_frame_change_post(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
    wm = bpy.context.window_manager
    if wm is None or not getattr(wm, "hair_sim_running", False):
        return
    _solver.step(scene, depsgraph)


def _install_handler() -> None:
    handlers = bpy.app.handlers.frame_change_post
    if _on_frame_change_post not in handlers:
        handlers.append(_on_frame_change_post)


def _uninstall_handler() -> None:
    handlers = bpy.app.handlers.frame_change_post
    if _on_frame_change_post in handlers:
        handlers.remove(_on_frame_change_post)


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #

class HAIR_SIM_OT_start(Operator):
    bl_idname = "hair_sim.start"
    bl_label = "Start"
    bl_description = "Begin advancing the hair simulation on frame change"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        if wm.hair_sim_running:
            return {"FINISHED"}
        # Phase 6A: only flip running when the solver actually started.
        # If start() returns False (native unavailable, target missing,
        # bad point count, ...), we leave hair_sim_running=False so the
        # handler never enters a silent running-but-no-op state.
        if not _solver.start():
            self.report({"ERROR"}, "Hair sim start failed (see system console)")
            return {"CANCELLED"}
        wm.hair_sim_running = True
        self.report({"INFO"}, "Hair sim running")
        return {"FINISHED"}


class HAIR_SIM_OT_stop(Operator):
    bl_idname = "hair_sim.stop"
    bl_label = "Stop"
    bl_description = "Stop advancing the hair simulation on frame change"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        if not wm.hair_sim_running:
            return {"FINISHED"}
        _solver.stop()
        wm.hair_sim_running = False
        return {"FINISHED"}


class HAIR_SIM_OT_reset(Operator):
    bl_idname = "hair_sim.reset"
    bl_label = "Reset"
    bl_description = "Request the solver to reinitialize its internal state"

    def execute(self, context: bpy.types.Context) -> set[str]:
        _solver.reset()
        return {"FINISHED"}


# Phase 2C experimental probe. INTERNAL = hidden from operator search
# and not bound to any UI button; triggered only via bpy.ops or MCP.
# Independent of SolverInterface and frame_change_post by design.
class HAIR_SIM_OT_probe_native(Operator):
    bl_idname      = "hair_sim.probe_native"
    bl_label       = "Probe Native (Phase 2C)"
    bl_description = "Probe the experimental native module via the loader"
    bl_options     = {"INTERNAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        from . import _native_loader
        native = _native_loader.get_native()
        if native is None:
            self.report({"ERROR"}, "Native module not available")
            return {"CANCELLED"}
        try:
            value = native.add(2, 3)
            phase = native.phase
        except Exception as exc:
            self.report({"ERROR"}, f"Native call failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Native probe ok: phase={phase} add(2,3)={value}")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Register
# --------------------------------------------------------------------------- #

_classes = (
    HAIR_SIM_OT_start,
    HAIR_SIM_OT_stop,
    HAIR_SIM_OT_reset,
    HAIR_SIM_OT_probe_native,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    # SKIP_SAVE keeps the running flag out of the .blend file.
    WindowManager.hair_sim_running = BoolProperty(
        name="Hair Sim Running",
        default=False,
        options={"SKIP_SAVE"},
    )
    ui.register()
    _install_handler()


def unregister() -> None:
    # Safety net: if the user disables the extension while the
    # passthrough is still running, the Surface Deform GN modifier
    # would otherwise stay muted in the scene. Stop the solver first
    # so its saved show_viewport value is restored.
    try:
        _solver.stop()
    except Exception:
        pass
    _uninstall_handler()
    ui.unregister()
    del WindowManager.hair_sim_running
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
