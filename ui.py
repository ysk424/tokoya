"""3D View N-panel for hair simulation."""
from __future__ import annotations

import bpy
from bpy.types import Panel


class HAIR_SIM_PT_main(Panel):
    bl_idname      = "HAIR_SIM_PT_main"
    bl_label       = "Hair Simulation"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "HairSim"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        wm     = context.window_manager
        mode   = getattr(wm, "hair_sim_mode", "BYPASS")

        layout.label(text=f"Mode: {mode}")

        row = layout.row(align=True)
        row.operator("hair_sim.start",  text="Start",  icon="PLAY",         depress=(mode == "SIMULATING"))
        row.operator("hair_sim.stop",   text="Stop",   icon="PAUSE",        depress=(mode == "PLAYBACK"))
        row.operator("hair_sim.bypass", text="Bypass", icon="FILE_REFRESH", depress=(mode == "BYPASS"))

        # ---- Simulation parameters (applied at next Start) ----
        box = layout.box()
        box.label(text="Params (applied at next Start)")
        for attr in (
            "hair_sim_param_spring_ke",
            "hair_sim_param_spring_kd",
            "hair_sim_param_particle_mass",
            "hair_sim_param_gravity",
            "hair_sim_param_iterations",
            "hair_sim_param_substeps",
            "hair_sim_param_bending_enabled",
            "hair_sim_param_bending_ke",
            "hair_sim_param_bending_kd",
            "hair_sim_param_body_collision_enabled",
            "hair_sim_param_body_collision_target",
        ):
            if hasattr(wm, attr):
                box.prop(wm, attr)


_classes = (HAIR_SIM_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
