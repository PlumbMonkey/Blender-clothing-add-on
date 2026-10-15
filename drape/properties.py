"""Drape scene settings."""

import bpy
from bpy.props import PointerProperty, StringProperty, EnumProperty

from .core.body_regions import REGIONS


def _mesh_only(self, obj):
    return obj.type == 'MESH'


REGION_ITEMS = [(r, r.title(), f"The {r.lower()} region") for r in REGIONS if r != 'NONE']


class DrapeSettings(bpy.types.PropertyGroup):
    target: PointerProperty(
        name="Body", type=bpy.types.Object, poll=_mesh_only,
        description="The body mesh garments are built on",
    )
    armature_name: StringProperty(name="Armature")
    pipeline: StringProperty(name="Pipeline")
    paint_region: EnumProperty(
        name="Region", items=REGION_ITEMS, default='TORSO',
        description="Region to repaint",
    )


def register():
    bpy.utils.register_class(DrapeSettings)
    bpy.types.Scene.drape = PointerProperty(type=DrapeSettings)


def unregister():
    del bpy.types.Scene.drape
    bpy.utils.unregister_class(DrapeSettings)
