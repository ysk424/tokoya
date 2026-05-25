"""Hair Simulation — Phase 6B.

First real solver architecture step. SolverInterface now owns a
stateful native solver instance (`NativeHairSolver`, a pybind11 class
in the native module) instead of calling a stateless C++ helper. The
native solver stores the baseline and a reusable output buffer; the
visible deformation (frame 800 baseline, 805/815/840 deterministic
offsets) matches Phase 6A exactly.

Canonical round-trip is still Phase 4D2's: original Curves baseline ->
NativeHairSolver -> result_buffer -> original Curves -> update_tag.
No PhysX, no CUDA, no collision yet.

Phase 1 invariants preserved: a single persistent frame_change_post
handler gated by WindowManager.hair_sim_running, Start/Stop/Reset
operators. Reset does NOT change running state (spec). Start failure
keeps hair_sim_running=False (no silent running-but-no-op state).
Restart behavior: each successful Start re-instantiates a fresh
NativeHairSolver and re-captures baseline from current original Curves
(so Stop -> Reset -> Start gives a clean cycle).
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
    """Phase 6B implementation. Holds a stateful native solver instance
    (`NativeHairSolver`, a pybind11 class) for the lifetime of the
    Python solver. step() delegates to `_native_solver.step(frame)`,
    which returns a `result_buffer` (py::bytes) computed from the
    baseline that the native solver captured at initialize time."""

    # Phase 6A hard-coded target (YOKO_EXT_TEST.blend).
    _TARGET_OBJECT_NAME  = "カーブ.001"
    _POINTS_PER_STRAND   = 8
    _ATTRIBUTE_NAME      = "position"
    _ATTRIBUTE_FIELD     = "vector"     # foreach key for FLOAT_VECTOR

    def __init__(self) -> None:
        self._native             = None    # native module ref (for hasattr checks)
        self._native_solver      = None    # NativeHairSolver instance
        self._n_points           = 0
        self._step_error_active  = False

    # ---- lifecycle ----

    def start(self) -> bool:
        """Acquire native module, capture baseline, and instantiate +
        initialize a fresh NativeHairSolver. Returns True only on
        success; on failure the operator must leave hair_sim_running
        as False so step() never gets called silently."""
        self._step_error_active = False
        self._native        = None
        self._native_solver = None
        self._n_points      = 0

        from . import _native_loader
        native = _native_loader.get_native()
        if native is None or not hasattr(native, "NativeHairSolver"):
            print("[hair_sim] start failed: native module / NativeHairSolver class unavailable")
            return False

        obj = bpy.data.objects.get(self._TARGET_OBJECT_NAME)
        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim] start failed: target '{self._TARGET_OBJECT_NAME}' missing or not Curves")
            return False

        attrs = obj.data.attributes
        pos = attrs.get(self._ATTRIBUTE_NAME)
        if pos is None:
            print(f"[hair_sim] start failed: attribute '{self._ATTRIBUTE_NAME}' missing on target")
            return False

        n_points = len(pos.data)
        if n_points == 0 or n_points % self._POINTS_PER_STRAND != 0:
            print(f"[hair_sim] start failed: unexpected point_count={n_points} "
                  f"(must be > 0 and multiple of {self._POINTS_PER_STRAND})")
            return False

        baseline = array.array('f', [0.0] * (n_points * 3))
        pos.data.foreach_get(self._ATTRIBUTE_FIELD, baseline)

        try:
            solver = native.NativeHairSolver()
            init_r = solver.initialize(
                point_count=n_points,
                points_per_strand=self._POINTS_PER_STRAND,
                baseline_buf=baseline,
            )
        except Exception as exc:
            print(f"[hair_sim] start failed: NativeHairSolver construct/initialize raised: {exc!r}")
            return False

        if not init_r.get("accepted") or not init_r.get("initialized"):
            print(f"[hair_sim] start failed: NativeHairSolver.initialize rejected: "
                  f"{init_r.get('message')!r}")
            return False

        self._native        = native
        self._native_solver = solver
        self._n_points      = n_points
        print(f"[hair_sim] start: NativeHairSolver init ok "
              f"(point_count={init_r.get('point_count')}, "
              f"strand_count={init_r.get('strand_count')}, "
              f"points_per_strand={init_r.get('points_per_strand')})")
        return True

    def stop(self) -> None:
        """Spec: Stop does not destroy the native solver and does not flip
        hair_sim_running (the operator owns that). The native solver
        keeps its baseline so Reset-after-Stop still restores cleanly."""
        return None

    def reset(self) -> None:
        """Spec: Reset restores original Curves to the captured baseline.
        Does NOT change hair_sim_running. If no solver is initialized
        this is a no-op."""
        if self._native_solver is None:
            return
        try:
            r = self._native_solver.reset()
        except Exception as exc:
            print(f"[hair_sim] reset error: {exc!r}")
            return
        if not r.get("accepted"):
            return
        result_bytes = r.get("result_buffer")
        if not result_bytes:
            return
        buf = array.array('f')
        buf.frombytes(result_bytes)
        if len(buf) != self._n_points * 3:
            return
        obj = bpy.data.objects.get(self._TARGET_OBJECT_NAME)
        if obj is None:
            return
        attr = obj.data.attributes.get(self._ATTRIBUTE_NAME)
        if attr is None or len(attr.data) != self._n_points:
            return
        attr.data.foreach_set(self._ATTRIBUTE_FIELD, buf)
        obj.data.update_tag()

    # ---- per-frame ----

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        if self._step_error_active:
            return
        if self._native_solver is None:
            return
        try:
            r = self._native_solver.step(frame_current=int(scene.frame_current))
            if not r.get("accepted"):
                return
            result_bytes = r.get("result_buffer")
            if not result_bytes:
                return

            result_buf = array.array('f')
            result_buf.frombytes(result_bytes)
            if len(result_buf) != self._n_points * 3:
                return  # length mismatch; refuse to write

            obj = bpy.data.objects.get(self._TARGET_OBJECT_NAME)
            if obj is None:
                return
            attr = obj.data.attributes.get(self._ATTRIBUTE_NAME)
            if attr is None or len(attr.data) != self._n_points:
                return  # target changed under us; skip

            attr.data.foreach_set(self._ATTRIBUTE_FIELD, result_buf)
            obj.data.update_tag()
        except Exception as exc:
            # One-shot error report; further steps become no-ops until next start().
            self._step_error_active = True
            print(f"[hair_sim] step error (suppressing further steps): {exc!r}")


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
    _uninstall_handler()
    ui.unregister()
    del WindowManager.hair_sim_running
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
