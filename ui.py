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


def _label(layout, text: str) -> None:
    layout.label(text=text, translate=False)


def _prop(layout, wm, name: str, *, text: str | None = None) -> None:
    kwargs = {"translate": False}
    if text is not None:
        kwargs["text"] = text
    layout.prop(wm, name, **kwargs)


def _operator(layout, op_id: str, *, text: str | None = None, icon: str = "NONE"):
    kwargs = {"icon": icon, "translate": False}
    if text is not None:
        kwargs["text"] = text
    return layout.operator(op_id, **kwargs)


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
        _label(layout, f"Tokoya  v{_version()}")
        layout.separator(factor=0.3)

        # Plant parameters
        box = layout.box()
        _label(box, "Mask Plant")
        col = box.column(align=True)
        _operator(col, "tokoya.create_head_mask", icon="MESH_DATA")
        _prop(col, wm, "tokoya_strand_count")
        _prop(col, wm, "tokoya_max_length_cm")

        # Persistent hair/body/clothes targets and temporary cutter target
        box = layout.box()
        _label(box, "Objects")
        col = box.column(align=True)
        row = col.row(align=True)
        _prop(row, wm, "tokoya_hair_obj", text="Hair")
        _operator(row, "tokoya.pick_hair", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        _prop(row, wm, "tokoya_body_obj", text="Body")
        _operator(row, "tokoya.pick_body", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        _prop(row, wm, "tokoya_clothes_obj", text="Clothes")
        _operator(row, "tokoya.pick_clothes", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        _prop(row, wm, "tokoya_cutter_obj", text="Cutter")
        _operator(row, "tokoya.pick_cutter", text="", icon="EYEDROPPER")

        layout.separator(factor=0.3)

        # Main buttons
        col = layout.column(align=True)
        row = col.row(align=True)
        _operator(row, "tokoya.plant_hair", icon="OUTLINER_OB_CURVES")
        _operator(row, "tokoya.plant_z_axe", icon="MOD_ARRAY")

        box = layout.box()
        _label(box, "Settle Hair Back")
        col = box.column(align=True)
        _prop(col, wm, "tokoya_groom_radius_mm")
        _prop(col, wm, "tokoya_groom_follow_mm")
        _prop(col, wm, "tokoya_groom_release_mm")
        _operator(col, "tokoya.settle_with_guide", icon="MOD_CLOTH")
        _operator(col, "tokoya.simulate", icon="MOD_CLOTH")

        box = layout.box()
        _label(box, "Cut / Reset")

        col = box.column(align=True)
        col.separator()
        _operator(col, "tokoya.mesh_shrink", icon="MOD_SOLIDIFY")
        row = col.row(align=True)
        _prop(row, wm, "tokoya_bangs_side_extra_cm", text="Side +cm")
        _prop(row, wm, "tokoya_bangs_z_extra_cm", text="Z +cm")
        _operator(col, "tokoya.trim_bangs", icon="MOD_SOLIDIFY")
        col.separator()
        _operator(col, "tokoya.urchin_reset", icon="FORCE_FORCE")

        box = layout.box()
        _label(box, "ZOZO Hand-off")
        col = box.column(align=True)
        _operator(col, "tokoya.prepare_zozo", icon="EXPORT")
        _label(box, getattr(wm, "tokoya_zozo_status", "Ready"))


_classes = (TOKOYA_PT_main,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
