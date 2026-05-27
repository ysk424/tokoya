from __future__ import annotations
import json, math, os
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, WindowManager
from . import ui


def _load_defaults():
    path = os.path.join(os.path.dirname(__file__), "tokoya_defaults.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _snapshot_sim_params(wm):
    from . import _world_passthrough as _wp
    _wp.SPRING_KE       = 10.0 ** wm.tokoya_spring_ke
    _wp.DAMPING         = wm.tokoya_damping       / 100.0
    _wp.PARTICLE_MASS   = wm.tokoya_particle_mass / 1000.0
    _wp.GRAVITY         = wm.tokoya_gravity
    _wp.ITERATIONS      = wm.tokoya_iterations
    _wp.SUBSTEPS        = wm.tokoya_substeps
    _wp.BENDING_ENABLED = wm.tokoya_bending_enabled
    _wp.ROOT_BENDING_KE = 10.0 ** wm.tokoya_root_bending_ke
    _wp.BENDING_KE      = 10.0 ** wm.tokoya_bending_ke


def _find_curves_obj():
    objs = [o for o in bpy.data.objects if o.type == "CURVES"]
    return objs[0] if len(objs) == 1 else None


class TOKOYA_OT_plant_hair(Operator):
    bl_idname      = "tokoya.plant_hair"
    bl_label       = "Plant Hair"
    bl_description = "Plant strands via Vogel spiral seeded from Ref Object (Empty)"

    def execute(self, context):
        wm       = context.window_manager
        ref_name = wm.tokoya_ref_obj.strip()
        if not ref_name:
            self.report({"ERROR"}, "Ref Object is empty"); return {"CANCELLED"}
        ref_obj = bpy.data.objects.get(ref_name)
        if ref_obj is None:
            self.report({"ERROR"}, f"Object {ref_name!r} not found"); return {"CANCELLED"}
        if ref_obj.type != "EMPTY":
            self.report({"WARNING"}, f"{ref_name!r} is {ref_obj.type}, not EMPTY")
        from . import _spiral_plant
        try:
            r = _spiral_plant.plant_hair(ref_obj, alpha_cm=wm.tokoya_alpha, beta_cm=wm.tokoya_beta)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc)); return {"CANCELLED"}
        self.report({"INFO"},
            f"Planted {r['n_added']} strands (total {r['total_curves']}). "
            f"Root-surface max {r['root_to_surface_max_um']:.1f} um")
        return {"FINISHED"}


class TOKOYA_OT_extend(Operator):
    bl_idname      = "tokoya.extend"
    bl_label       = "Extend"
    bl_description = "Scale all strands from root to N cm (N = number field)"

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.extend_length(obj, target_m=context.window_manager.tokoya_n / 100.0)
        self.report({"INFO"}, f"Extended {n} strands to {context.window_manager.tokoya_n:.1f} cm")
        return {"FINISHED"}


class TOKOYA_OT_simulate(Operator):
    bl_idname      = "tokoya.simulate"
    bl_label       = "Simulate"
    bl_description = "Run N steps of Taichi XPBD. Body vs CC_Base_Body. N = number field"

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        wm = context.window_manager
        _snapshot_sim_params(wm)
        from . import _world_passthrough as _wp
        status = _wp.run_simulation(obj.name, int(wm.tokoya_n), context.scene)
        if status.startswith("ERROR"):
            self.report({"ERROR"}, status); return {"CANCELLED"}
        self.report({"INFO"}, status)
        return {"FINISHED"}


class TOKOYA_OT_mesh_shrink(Operator):
    bl_idname      = "tokoya.mesh_shrink"
    bl_label       = "Mesh Shrink"
    bl_description = ("Shrink strands to first intersection with Ref mesh. "
                      "Plane=height-cut, half-sphere=round-cut.")

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        ref_name = context.window_manager.tokoya_ref_obj.strip()
        ref = bpy.data.objects.get(ref_name)
        if ref is None or ref.type != "MESH":
            self.report({"ERROR"}, f"{ref_name!r} not found or not MESH"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.mesh_shrink(obj, ref)
        self.report({"INFO"}, f"Shrunk {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_mesh_extend(Operator):
    bl_idname      = "tokoya.mesh_extend"
    bl_label       = "Mesh Extend"
    bl_description = "Extend strand tips to reach Ref mesh surface"

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        ref_name = context.window_manager.tokoya_ref_obj.strip()
        ref = bpy.data.objects.get(ref_name)
        if ref is None or ref.type != "MESH":
            self.report({"ERROR"}, f"{ref_name!r} not found or not MESH"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.mesh_extend(obj, ref)
        self.report({"INFO"}, f"Extended {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_urchin_reset(Operator):
    bl_idname      = "tokoya.urchin_reset"
    bl_label       = "Urchin Reset"
    bl_description = "Reset all strands to straight radial lines (arc-length preserved)"

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.urchin_reset(obj)
        self.report({"INFO"}, f"Urchin reset: {n} strands")
        return {"FINISHED"}


_classes = (
    TOKOYA_OT_plant_hair,
    TOKOYA_OT_extend,
    TOKOYA_OT_simulate,
    TOKOYA_OT_mesh_shrink,
    TOKOYA_OT_mesh_extend,
    TOKOYA_OT_urchin_reset,
)


def register():
    defaults = _load_defaults()
    for cls in _classes:
        bpy.utils.register_class(cls)

    WindowManager.tokoya_alpha = FloatProperty(
        name="Radius a cm", description="Spiral radius for Plant Hair (cm)",
        default=27.0, min=0.5, max=35.0, step=10, precision=1, options={"SKIP_SAVE"})
    WindowManager.tokoya_beta = FloatProperty(
        name="Spacing b cm", description="Root spacing for Plant Hair (cm)",
        default=0.3, min=0.2, max=5.0, step=5, precision=2, options={"SKIP_SAVE"})
    WindowManager.tokoya_n = FloatProperty(
        name="N", description="Length cm (Extend) or Step count (Simulate)",
        default=30.0, min=0.1, max=500.0, step=100, precision=1, options={"SKIP_SAVE"})
    WindowManager.tokoya_ref_obj = StringProperty(
        name="Ref Object", description="Empty (Plant) or Mesh (Shrink/Extend)",
        default="", options={"SKIP_SAVE"})
    WindowManager.tokoya_spring_ke = FloatProperty(
        name="Stiffness 10^N", default=math.log10(defaults["SPRING_KE"]),
        min=1.0, max=9.0, step=10, precision=2, options={"SKIP_SAVE"})
    WindowManager.tokoya_damping = FloatProperty(
        name="Damping /100", default=defaults["DAMPING"] * 100.0,
        min=0.0, max=50.0, step=10, precision=1, options={"SKIP_SAVE"})
    WindowManager.tokoya_particle_mass = FloatProperty(
        name="Mass /1000", default=defaults["PARTICLE_MASS"] * 1000.0,
        min=1.0, max=10000.0, step=100, precision=1, options={"SKIP_SAVE"})
    WindowManager.tokoya_gravity = FloatProperty(
        name="Gravity m/s2", default=defaults["GRAVITY"],
        min=-20.0, max=0.0, step=10, precision=2, options={"SKIP_SAVE"})
    WindowManager.tokoya_iterations = IntProperty(
        name="Iterations", default=int(defaults["ITERATIONS"]),
        min=1, max=64, options={"SKIP_SAVE"})
    WindowManager.tokoya_substeps = IntProperty(
        name="Substeps", default=int(defaults["SUBSTEPS"]),
        min=1, max=16, options={"SKIP_SAVE"})
    WindowManager.tokoya_bending_enabled = BoolProperty(
        name="Bending", default=bool(defaults["BENDING_ENABLED"]),
        options={"SKIP_SAVE"})
    WindowManager.tokoya_root_bending_ke = FloatProperty(
        name="Root Stiff 10^N", default=math.log10(defaults["ROOT_BENDING_KE"]),
        min=0.0, max=7.0, step=10, precision=2, options={"SKIP_SAVE"})
    WindowManager.tokoya_bending_ke = FloatProperty(
        name="Strand Stiff 10^N", default=math.log10(defaults["BENDING_KE"]),
        min=0.0, max=6.0, step=10, precision=2, options={"SKIP_SAVE"})
    ui.register()


def unregister():
    ui.unregister()
    for name in (
        "tokoya_alpha", "tokoya_beta", "tokoya_n", "tokoya_ref_obj",
        "tokoya_spring_ke", "tokoya_damping", "tokoya_particle_mass",
        "tokoya_gravity", "tokoya_iterations", "tokoya_substeps",
        "tokoya_bending_enabled", "tokoya_root_bending_ke", "tokoya_bending_ke",
    ):
        try: delattr(WindowManager, name)
        except Exception: pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
