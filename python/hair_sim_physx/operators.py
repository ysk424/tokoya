from __future__ import annotations

import bpy
from bpy.types import Operator

from ._core_loader import get_core, status


class HAIRSIM_OT_status(Operator):
    bl_idname = "hair_sim_physx.status"
    bl_label  = "PhysX Hair: Status"

    def execute(self, context: bpy.types.Context) -> set[str]:
        self.report({"INFO"}, f"hair_sim_physx native: {status()}")
        return {"FINISHED"}


class HAIRSIM_OT_step(Operator):
    bl_idname = "hair_sim_physx.step"
    bl_label  = "PhysX Hair: Step Once"

    def execute(self, context: bpy.types.Context) -> set[str]:
        core = get_core()
        if core is None:
            self.report({"ERROR"}, "Native module not built. Run scripts/build_wheel.ps1.")
            return {"CANCELLED"}
        s = context.scene.hair_sim_physx
        solver = core.HairSolver()
        cfg = core.SolverConfig()
        cfg.use_gpu  = bool(s.use_gpu)
        cfg.substeps = int(s.substeps)
        cfg.gravity  = (0.0, 0.0, float(s.gravity_z))
        solver.initialize(cfg)
        self.report({"INFO"}, f"Stepped (gpu={cfg.use_gpu}, substeps={cfg.substeps})")
        return {"FINISHED"}


_classes = (HAIRSIM_OT_status, HAIRSIM_OT_step)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
