from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup


class HairSimSettings(PropertyGroup):
    use_gpu: BoolProperty(
        name="Use GPU",
        description="Run PhysX hair solver on CUDA",
        default=True,
    )
    substeps: IntProperty(
        name="Substeps",
        default=4, min=1, max=32,
    )
    gravity_z: FloatProperty(
        name="Gravity Z",
        default=-9.81,
    )


_classes = (HairSimSettings,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hair_sim_physx = PointerProperty(type=HairSimSettings)


def unregister() -> None:
    del bpy.types.Scene.hair_sim_physx
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
