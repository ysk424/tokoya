from __future__ import annotations

import bpy
from bpy.types import Panel


class HAIRSIM_PT_main(Panel):
    bl_label       = "PhysX Hair"
    bl_idname      = "HAIRSIM_PT_main"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "physics"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        s = context.scene.hair_sim_physx
        col = layout.column(align=True)
        col.prop(s, "use_gpu")
        col.prop(s, "substeps")
        col.prop(s, "gravity_z")
        layout.separator()
        row = layout.row(align=True)
        row.operator("hair_sim_physx.status",  icon="INFO")
        row.operator("hair_sim_physx.step",    icon="PLAY")


_classes = (HAIRSIM_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
