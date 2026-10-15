"""Drape settings: per scene (body setup) and per garment object."""

import bpy
from bpy.props import (
    PointerProperty, StringProperty, EnumProperty, FloatProperty,
    IntProperty, BoolProperty, FloatVectorProperty,
)

from .core.body_regions import REGIONS
from .core.coverage import (
    TEMPLATES, TIGHTNESS_FIT, CoverageParams, compute_coverage, write_coverage,
)
from .core.fabric import STYLES, apply_fabric
from .core.sim import PRESETS as SIM_PRESETS
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


def rebuild_skirt(g):
    """Rebuild a skirt's mesh from its sliders (drops any kept drape and
    simulation, which no longer match the new shape)."""
    from .core import skirt as skirt_core, sim
    obj = g.id_data
    arm = bpy.data.objects.get(g.armature_name)
    sim.drop_drape(obj)
    sim.free_bake(obj)
    params = skirt_core.SkirtParams(length=g.skirt_length, flare=g.flare,
                                    waist=g.waist_height, offset=g.offset)
    verts, faces, pins = skirt_core.build_skirt(g.body, arm, params,
                                                bpy.context.evaluated_depsgraph_get())
    skirt_core.write_skirt_mesh(obj, verts, faces, pins)


def rebuild_coverage(g):
    """Rewrite a garment's coverage group (or a skirt's mesh) from its
    template and lengths."""
    if not _live(g):
        return
    if g.template == 'SKIRT':
        rebuild_skirt(g)
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
    if self.template == 'SKIRT' and self.offset != obj.get("drape_built_offset"):
        obj["drape_built_offset"] = self.offset
        rebuild_skirt(self)
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


TIGHTNESS = (
    ('SKIN', "Skin-tight", "Hugs every curve, like a leotard or compression wear"),
    ('FITTED', "Fitted", "Close to the body but bridges small hollows"),
    ('RELAXED', "Relaxed", "Everyday fit: smooths over the muscles"),
    ('LOOSE', "Loose", "Baggy: stands off the body and bridges big hollows"),
)


def _update_tightness(self, context):
    if not _live(self):
        return
    self.offset, self.looseness = TIGHTNESS_FIT[self.tightness]  # each fires _update_shell


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
    skirt_length: FloatProperty(
        name="Length", min=0.1, max=2.0, default=0.7, update=_update_coverage,
        description="Hem: 0 at the hip joint, 1 knee, 2 ankle")
    flare: FloatProperty(
        name="Flare", min=0.0, max=1.5, default=0.35, update=_update_coverage,
        description="How much the skirt widens as it goes down (0 = pencil skirt)")
    waist_height: FloatProperty(
        name="Waist", min=0.0, max=0.8, default=0.2, update=_update_coverage,
        description="Waistband: 0 at the top of the hips, higher numbers sit lower")
    sock_height: FloatProperty(
        name="Sock Height", min=0.0, max=1.0, default=0.35, update=_update_coverage,
        description="0 at the ankle, 1 at the knee")

    # fit (modifier inputs)
    tightness: EnumProperty(
        name="Fit", items=TIGHTNESS, default='RELAXED', update=_update_tightness,
        description="Quick fit: sets Offset and Looseness together")
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

    # simulation
    sim_preset: EnumProperty(name="Cloth", items=SIM_PRESETS, default='DRAPE',
                             description="Fabric and motion for the cloth simulation")
    sim_animation: BoolProperty(
        name="Whole Animation", default=False,
        description="Simulate over the scene's frame range (for animated characters) "
                    "instead of a short settle")

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
