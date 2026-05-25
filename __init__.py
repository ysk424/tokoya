"""Hair Simulation — Phase 6A.

First implementation phase: the Phase 1 SolverInterface stub is now
wired to the C++ deterministic deformation path (Phase 4C's
deform_position_buffer). Canonical round-trip is Phase 4D2's:
original Curves baseline -> Python buffer -> C++ deform -> result ->
original Curves -> update_tag. No PhysX, no CUDA, no collision yet.

Phase 1 invariants preserved: a single persistent frame_change_post
handler gated by WindowManager.hair_sim_running, Start/Stop/Reset
operators. Reset does NOT change running state (spec). Start failure
keeps hair_sim_running=False (no silent running-but-no-op state).
"""
from __future__ import annotations

import array
import math

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty
from bpy.types import Operator, WindowManager

from . import ui


# --------------------------------------------------------------------------- #
# Solver boundary
# --------------------------------------------------------------------------- #

class SolverInterface:
    """Phase 6A implementation. Drives a deterministic, non-cumulative
    C++ deformation of one hard-coded Curves object's ORIGINAL position
    attribute every frame_change_post.

    Hard-coded target is acceptable for Phase 6A; object discovery is
    a later phase. The deformation is computed from a baseline that is
    captured exactly once per Start, so step() is independent of any
    previously written result (non-cumulative)."""

    # Phase 6A hard-coded target (YOKO_EXT_TEST.blend).
    _TARGET_OBJECT_NAME  = "カーブ.001"  # "カーブ.001"
    _POINTS_PER_STRAND   = 8
    _ATTRIBUTE_NAME      = "position"
    _ATTRIBUTE_FIELD     = "vector"     # foreach key for FLOAT_VECTOR
    _ANIM_FRAME_ORIGIN   = 800
    _ANIM_FREQ_PER_FRAME = 0.15         # radians per frame
    _ANIM_AMPLITUDE      = 0.25         # in baseline units (Blender world ~m)

    def __init__(self) -> None:
        self._native             = None
        self._baseline           = None   # array.array('f') length = n_points * 3
        self._n_points           = 0
        self._step_error_active  = False

    # ---- lifecycle ----

    def start(self) -> bool:
        """Acquire native module and capture baseline. Returns True only
        on success; on failure the operator must leave hair_sim_running
        as False so step() never gets called silently."""
        self._step_error_active = False
        self._native   = None
        self._baseline = None
        self._n_points = 0

        from . import _native_loader
        native = _native_loader.get_native()
        if native is None or not hasattr(native, "deform_position_buffer"):
            print("[hair_sim] start failed: native module / deform_position_buffer unavailable")
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

        self._native   = native
        self._baseline = baseline
        self._n_points = n_points
        print(f"[hair_sim] start: captured baseline "
              f"({n_points} points / {n_points // self._POINTS_PER_STRAND} strands)")
        return True

    def stop(self) -> None:
        """Spec: Stop does not touch baseline (so Reset-after-Stop still
        works) and does not flip hair_sim_running (the operator owns
        that). Step() naturally stops being called once running=False."""
        return None

    def reset(self) -> None:
        """Spec: Reset restores original Curves to the captured baseline
        when one exists. Does NOT change hair_sim_running. Without a
        captured baseline this is a no-op."""
        if self._baseline is None:
            return
        obj = bpy.data.objects.get(self._TARGET_OBJECT_NAME)
        if obj is None or obj.type != "CURVES":
            return
        attr = obj.data.attributes.get(self._ATTRIBUTE_NAME)
        if attr is None or len(attr.data) != self._n_points:
            return
        attr.data.foreach_set(self._ATTRIBUTE_FIELD, self._baseline)
        obj.data.update_tag()

    # ---- per-frame ----

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        if self._step_error_active:
            return
        if self._native is None or self._baseline is None:
            return
        try:
            frame = scene.frame_current
            amp = math.sin((frame - self._ANIM_FRAME_ORIGIN)
                            * self._ANIM_FREQ_PER_FRAME) * self._ANIM_AMPLITUDE

            r = self._native.deform_position_buffer(
                expected_point_count=self._n_points,
                expected_float_count=self._n_points * 3,
                points_per_strand=self._POINTS_PER_STRAND,
                frame_current=frame,
                amplitude=float(amp),
                input_buf=self._baseline,        # non-cumulative input every step
            )
            if not r.get("accepted"):
                return  # C++ validation rejected; do not corrupt curves
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
