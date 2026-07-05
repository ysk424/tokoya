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
        box.label(text="Mask Plant")
        col = box.column(align=True)
        col.operator("tokoya.create_head_mask", icon="MESH_DATA")
        col.prop(wm, "tokoya_strand_count")
        col.prop(wm, "tokoya_max_length_cm")

        # Persistent hair/body/clothes targets and temporary cutter target
        box = layout.box()
        box.label(text="Objects")
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(wm, "tokoya_hair_obj", text="Hair")
        row.operator("tokoya.pick_hair", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        row.prop(wm, "tokoya_body_obj", text="Body")
        row.operator("tokoya.pick_body", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        row.prop(wm, "tokoya_clothes_obj", text="Clothes")
        row.operator("tokoya.pick_clothes", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        row.prop(wm, "tokoya_cutter_obj", text="Cutter")
        row.operator("tokoya.pick_cutter", text="", icon="EYEDROPPER")

        layout.separator(factor=0.3)

        # Main buttons
        col = layout.column(align=True)
        col.operator("tokoya.plant_hair",  icon="OUTLINER_OB_CURVES")
        col.operator("tokoya.simulate",     icon="MOD_CLOTH")

        box = layout.box()
        box.label(text="Settle Hair Back")
        col = box.column(align=True)
        col.prop(wm, "tokoya_groom_radius_mm")
        col.prop(wm, "tokoya_groom_follow_mm")
        col.prop(wm, "tokoya_groom_release_mm")

        box = layout.box()
        box.label(text="Cut / Reset")

        col = box.column(align=True)
        col.separator()
        col.operator("tokoya.mesh_shrink",  icon="MOD_SOLIDIFY")
        col.separator()
        col.operator("tokoya.urchin_reset", icon="FORCE_FORCE")


_classes = (TOKOYA_PT_main,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
