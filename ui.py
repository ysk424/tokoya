"""Tokoya N-panel (VIEW_3D sidebar, tab 'Tokoya')."""
from __future__ import annotations
import os, tomllib
import bpy
from bpy.types import Panel


def _version():
    try:
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(path, "rb") as f:
            return tomllib.load(f).get("version", "?")
    except Exception:
        return "?"


class TOKOYA_PT_main(Panel):
    bl_idname      = "TOKOYA_PT_main"
    bl_label       = "Tokoya"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "Tokoya"

    def draw(self, context):
        layout = self.layout
        wm     = context.window_manager

        # Header
        layout.label(text=f"Tokoya  v{_version()}")
        layout.separator(factor=0.3)

        # Plant parameters
        box = layout.box()
        box.label(text="Plant")
        col = box.column(align=True)
        col.prop(wm, "tokoya_alpha")
        col.prop(wm, "tokoya_beta")

        # General N + Ref Object
        box = layout.box()
        box.label(text="N  /  Ref Object")
        col = box.column(align=True)
        col.prop(wm, "tokoya_n")
        row = col.row(align=True)
        row.prop_search(wm, "tokoya_ref_obj", bpy.data, "objects", text="")
        ref = bpy.data.objects.get(wm.tokoya_ref_obj.strip())
        row.label(text=ref.type if ref else "--")

        layout.separator(factor=0.3)

        # Main buttons
        col = layout.column(align=True)
        col.operator("tokoya.plant_hair",  icon="OUTLINER_OB_CURVES")
        col.operator("tokoya.extend",       icon="ARROW_LEFTRIGHT")
        col.operator("tokoya.simulate",     icon="PLAY")
        col.separator()
        col.operator("tokoya.mesh_shrink",  icon="MOD_SOLIDIFY")
        col.operator("tokoya.mesh_extend",  icon="MESH_UVSPHERE")
        col.separator()
        col.operator("tokoya.urchin_reset", icon="FORCE_FORCE")

        # Physics params
        layout.separator(factor=0.3)
        box = layout.box()
        box.label(text="Physics (applied at Simulate)")
        col = box.column(align=True)
        col.prop(wm, "tokoya_spring_ke")
        col.prop(wm, "tokoya_damping")
        col.prop(wm, "tokoya_particle_mass")
        col.prop(wm, "tokoya_gravity")
        col.separator()
        col.prop(wm, "tokoya_iterations")
        col.prop(wm, "tokoya_substeps")
        col.separator()
        col.prop(wm, "tokoya_bending_enabled")
        if getattr(wm, "tokoya_bending_enabled", False):
            col.prop(wm, "tokoya_root_bending_ke")
            col.prop(wm, "tokoya_bending_ke")


_classes = (TOKOYA_PT_main,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
