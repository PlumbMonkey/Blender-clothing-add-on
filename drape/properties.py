"""Drape settings: per scene (body setup) and per garment object."""

import bpy
from bpy.props import (
    PointerProperty, StringProperty, EnumProperty, FloatProperty,
    IntProperty, BoolProperty, FloatVectorProperty,
)

from .core.body_regions import REGIONS
from .core.coverage import TEMPLATES, CoverageParams, compute_coverage, write_coverage
from .core.fabric import STYLES, apply_fabric
from .core import garment as garment_core
from .core.nodes import set_input


def _mesh_only(self, obj):
    return obj.type == 'MESH'


REGION_ITEMS = [(r, r.title(), f"The {r.lower()} region") for r in REGIONS if r != 'NONE']
TEMPLATE_ITEMS = [(k, v, f"Start from a {v.lower()} coverage") for k, v in TEMPLATES.items()]


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
    new_template: EnumProperty(
        name="Garment", items=TEMPLATE_ITEMS, default='TSHIRT',
        description="Kind of garment to add",
    )
    painting_garment: PointerProperty(
        name="Painting", type=bpy.types.Object,
        description="Garment whose coverage is being painted",
    )


# --- per-garment live updates ------------------------------------------------

def _live(g):
    return g.is_garment and g.body is not None


def rebuild_coverage(g):
    """Rewrite a garment's coverage group from its template and lengths."""
    if not _live(g):
        return
    arm = bpy.data.objects.get(g.armature_name)
    params = CoverageParams(
        sleeve_length=g.sleeve_length, body_length=g.body_length,
        leg_length=g.leg_length, rise=g.rise, sock_height=g.sock_height,
    )
    write_coverage(g.body, g.coverage_group,
                   compute_coverage(g.body, arm, g.template, params))
    g.body.data.update()


def _update_coverage(self, context):
    rebuild_coverage(self)


def _update_shell(self, context):
    if not _live(self):
        return
    obj = self.id_data
    mod = garment_core.shell_modifier(obj)
    if mod is not None:
        set_input(mod, "Offset", self.offset)
        set_input(mod, "Looseness", self.looseness)
        set_input(mod, "Resolution", self.resolution)
        set_input(mod, "Border Smooth", self.border_smooth)
    sol = garment_core.thickness_modifier(obj)
    if sol is not None:
        sol.thickness = self.thickness
    obj.update_tag()


def _update_look(self, context):
    if not _live(self):
        return
    obj = self.id_data
    if obj.data.materials and obj.data.materials[0]:
        apply_fabric(obj.data.materials[0], tuple(self.color), self.style)


class DrapeGarment(bpy.types.PropertyGroup):
    is_garment: BoolProperty(default=False)
    body: PointerProperty(name="Body", type=bpy.types.Object)
    armature_name: StringProperty()
    template: EnumProperty(name="Template", items=TEMPLATE_ITEMS, default='TSHIRT')
    coverage_group: StringProperty(name="Coverage Group")

    # coverage (rewrites the body's coverage group)
    sleeve_length: FloatProperty(
        name="Sleeve Length", min=0.0, max=2.0, default=0.45, update=_update_coverage,
        description="0 sleeveless, 1 elbow, 2 wrist")
    body_length: FloatProperty(
        name="Hem", min=0.0, max=1.0, default=0.35, update=_update_coverage,
        description="Shirt hem: 0 at the waist, 1 at the crotch")
    leg_length: FloatProperty(
        name="Leg Length", min=0.0, max=2.0, default=0.45, update=_update_coverage,
        description="0 at the hip, 1 knee, 2 ankle")
    rise: FloatProperty(
        name="Rise", min=0.0, max=1.0, default=0.0, update=_update_coverage,
        description="How far the waistband comes up the torso")
    sock_height: FloatProperty(
        name="Sock Height", min=0.0, max=1.0, default=0.35, update=_update_coverage,
        description="0 at the ankle, 1 at the knee")

    # fit (modifier inputs)
    offset: FloatProperty(
        name="Offset", min=0.0, max=0.1, default=0.006, step=0.05, precision=4,
        subtype='DISTANCE', unit='LENGTH', update=_update_shell,
        description="Closest the cloth gets to the skin")
    looseness: IntProperty(
        name="Looseness", min=0, max=100, default=15, update=_update_shell,
        description="How much the cloth bridges over hollows instead of hugging the body")
    thickness: FloatProperty(
        name="Thickness", min=0.0, max=0.05, default=0.003, step=0.05, precision=4,
        subtype='DISTANCE', unit='LENGTH', update=_update_shell,
        description="Cloth thickness")
    resolution: IntProperty(
        name="Resolution", min=0, max=3, default=1, update=_update_shell,
        description="Subdivision level: smoother cloth and finer edges, more polygons")
    border_smooth: IntProperty(
        name="Edge Smoothing", min=0, max=30, default=4, update=_update_shell,
        description="Rounds off the garment's edges (necklines, sleeve ends, hems)")

    # look
    style: EnumProperty(name="Style", items=STYLES, default='PBR', update=_update_look)
    color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=3, min=0.0, max=1.0,
        default=(0.1, 0.25, 0.6), update=_update_look)


def register():
    bpy.utils.register_class(DrapeSettings)
    bpy.utils.register_class(DrapeGarment)
    bpy.types.Scene.drape = PointerProperty(type=DrapeSettings)
    bpy.types.Object.drape_garment = PointerProperty(type=DrapeGarment)


def unregister():
    del bpy.types.Object.drape_garment
    del bpy.types.Scene.drape
    bpy.utils.unregister_class(DrapeGarment)
    bpy.utils.unregister_class(DrapeSettings)
