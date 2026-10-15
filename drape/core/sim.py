"""Cloth simulation for garments.

- The body collides through a proxy object (``Drape_Collider_<body>``): a
  Geometry Nodes copy of the evaluated body with a Collision modifier, so
  the character's own object is never modified.
- Pins hold the garment where real clothes are held up: the waistband for
  bottoms and skirts, the shoulders for tops. Shell garments get their pin
  weights from a body vertex group (``DRAPE_PIN_<garment>``) that the shell
  copies into the garment's ``Drape_Pin`` group; skirts carry their own.
- Presets set the fabric and how long to simulate. Everything is in metres
  (garments sit in world units), which is what Blender's cloth is tuned for.
"""

import bpy
from mathutils import Vector

from .body_regions import REGIONS, REGION_ATTR, _read_int_attr
from .geometry import ensure_vertex_group, clear_vertex_group
from .nodes import new_geometry_group

CLOTH_MODIFIER = "Drape Cloth"
PIN_GROUP = "Drape_Pin"
COLLIDER_GROUP = "Drape Body Collider"

PRESETS = (
    ('DRAPE', "Drape", "Cotton settling under gravity: soft folds"),
    ('SETTLE', "Settle", "Heavier, stiffer cloth (denim): small, quick settle"),
    ('WINDY', "Windy", "Light cloth (silk) in a breeze"),
)

_FABRIC = {
    #          mass  tension shear bending air  frames
    'DRAPE': (0.30, 15.0, 5.0, 0.5, 1.0, 60),
    'SETTLE': (0.80, 40.0, 15.0, 8.0, 1.0, 40),
    'WINDY': (0.15, 5.0, 2.0, 0.05, 1.5, 120),
}


def preset_frames(preset):
    return _FABRIC[preset][5]


# --- body collider -----------------------------------------------------------

def collider_name(body):
    return f"Drape_Collider_{body.name}"


def _collider_group():
    ng = bpy.data.node_groups.get(COLLIDER_GROUP)
    if ng is not None:
        return ng
    ng, gi, go = new_geometry_group(COLLIDER_GROUP, inputs=(("Body", 'NodeSocketObject'),))
    info = ng.nodes.new("GeometryNodeObjectInfo")
    info.transform_space = 'RELATIVE'
    only_mesh = ng.nodes.new("GeometryNodeSeparateComponents")
    ng.links.new(gi.outputs["Body"], info.inputs["Object"])
    ng.links.new(info.outputs["Geometry"], only_mesh.inputs["Geometry"])
    ng.links.new(only_mesh.outputs["Mesh"], go.inputs["Geometry"])
    return ng


def ensure_collider(body):
    """The body's collision proxy (created once per body)."""
    from .nodes import set_input
    obj = bpy.data.objects.get(collider_name(body))
    if obj is None:
        obj = bpy.data.objects.new(collider_name(body), bpy.data.meshes.new(collider_name(body)))
        (body.users_collection[0] if body.users_collection else bpy.context.scene.collection).objects.link(obj)
        mod = obj.modifiers.new("Drape Body", 'NODES')
        mod.node_group = _collider_group()
        set_input(mod, "Body", body)
        obj.modifiers.new("Collision", 'COLLISION')
        obj.display_type = 'WIRE'
        obj.hide_render = True
        obj.hide_select = True
    col = obj.collision
    col.thickness_outer = 0.003
    col.thickness_inner = 0.01
    col.cloth_friction = 5.0
    col.damping = 0.1
    obj.hide_viewport = False
    obj.hide_set(True)  # out of sight; still evaluated, so it still collides
    return obj


# --- pins for shell garments ---------------------------------------------------

def pin_group_name(garment_name):
    return f"DRAPE_PIN_{garment_name}"


def write_shell_pins(body, garment_name, template, coverage_group):
    """Pin weights on the body for a shell garment: shoulders for tops,
    waistband for bottoms, everything for socks."""
    regions = _read_int_attr(body.data, REGION_ATTR)
    cov = body.vertex_groups.get(coverage_group)
    if regions is None or cov is None:
        return 0
    mw = body.matrix_world
    z = [(mw @ v.co).z for v in body.data.vertices]
    covered = [0.0] * len(z)
    for v in body.data.vertices:
        for g in v.groups:
            if g.group == cov.index:
                covered[v.index] = g.weight
    torso = REGIONS.index('TORSO')
    hips = REGIONS.index('HIPS')

    def span(idx):
        zs = [z[i] for i, r in enumerate(regions) if r == idx]
        return (min(zs), max(zs)) if zs else (0.0, 0.0)

    t_lo, t_hi = span(torso)
    h_lo, h_hi = span(hips)
    pins = [0.0] * len(z)
    for i, r in enumerate(regions):
        if covered[i] < 0.5:
            continue
        if template in ('TSHIRT', 'TANK', 'LONGSLEEVE'):
            if r == torso and z[i] >= t_hi - 0.3 * (t_hi - t_lo):
                pins[i] = 1.0
        elif template in ('SHORTS', 'PANTS'):
            if r == torso or (r == hips and z[i] >= h_hi - 0.2 * (h_hi - h_lo)):
                pins[i] = 1.0
        else:  # socks and anything skin-tight
            pins[i] = 1.0
    vg = ensure_vertex_group(body, pin_group_name(garment_name))
    clear_vertex_group(body, vg)
    on = [i for i, w in enumerate(pins) if w > 0]
    if on:
        vg.add(on, 1.0, 'REPLACE')
    return len(on)


# --- cloth ---------------------------------------------------------------------

def cloth_modifier(obj):
    mod = obj.modifiers.get(CLOTH_MODIFIER)
    return mod if mod is not None and mod.type == 'CLOTH' else None


def ensure_cloth(obj, preset, after=None, quality=8):
    """Add (or retune) the garment's cloth modifier. It sits right after the
    modifier named ``after`` (the shell), else first — always before the
    thickness, which must be added to the simulated surface."""
    ensure_vertex_group(obj, PIN_GROUP)
    mod = cloth_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(CLOTH_MODIFIER, 'CLOTH')
    idx = 0
    if after is not None and obj.modifiers.get(after) is not None:
        idx = obj.modifiers.find(after) + 1
    with bpy.context.temp_override(object=obj):
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=idx)

    mass, tension, shear, bending, air, frames = _FABRIC[preset]
    st = mod.settings
    st.quality = quality
    st.mass = mass
    st.tension_stiffness = st.compression_stiffness = tension
    st.shear_stiffness = shear
    st.bending_stiffness = bending
    st.air_damping = air
    st.vertex_group_mass = PIN_GROUP
    st.pin_stiffness = 1.0
    cs = mod.collision_settings
    cs.collision_quality = 3
    cs.distance_min = 0.004
    cs.use_self_collision = False
    pc = mod.point_cache
    scene = bpy.context.scene
    pc.frame_start = scene.frame_start
    pc.frame_end = scene.frame_start + frames
    return mod


def ensure_wind(body, enable):
    """A gentle wind blowing at the character from its front-left, or none."""
    name = f"Drape_Wind_{body.name}"
    obj = bpy.data.objects.get(name)
    if not enable:
        if obj is not None:
            bpy.data.objects.remove(obj)
        return None
    if obj is not None and obj.field is None:  # left over from an older Drape
        bpy.data.objects.remove(obj)
        obj = None
    if obj is None:
        # a force field only exists on objects made by the effector operator
        bpy.ops.object.effector_add(type='WIND')
        obj = bpy.context.active_object
        obj.name = name
        target = body.users_collection[0] if body.users_collection else bpy.context.scene.collection
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        target.objects.link(obj)
        obj.empty_display_size = 0.3
    obj.field.type = 'WIND'
    obj.field.strength = 2.0
    obj.field.noise = 1.5
    obj.field.flow = 0.5
    bb = [body.matrix_world @ Vector(c) for c in body.bound_box]
    centre = sum(bb, Vector()) / 8
    obj.location = centre + Vector((0.6, -1.2, 0.0))
    direction = (centre - obj.location).normalized()
    obj.rotation_euler = Vector((0, 0, 1)).rotation_difference(direction).to_euler()
    return obj


def bake(obj):
    """Simulate the garment's cloth over its cache range (blocking)."""
    mod = cloth_modifier(obj)
    if mod is None:
        return False
    with bpy.context.temp_override(point_cache=mod.point_cache, scene=bpy.context.scene):
        bpy.ops.ptcache.free_bake()
        bpy.ops.ptcache.bake(bake=True)
    return True


def free_bake(obj):
    mod = cloth_modifier(obj)
    if mod is not None:
        with bpy.context.temp_override(point_cache=mod.point_cache, scene=bpy.context.scene):
            bpy.ops.ptcache.free_bake()


DRAPE_KEY = "Drape Settled"


def keep_drape(obj):
    """Store the cloth's last simulated frame as a shape key on the garment's
    own mesh and switch the cloth off: the garment keeps that drape (and still
    follows its parent bone) without re-simulating. Mesh garments only."""
    mod = cloth_modifier(obj)
    if mod is None or len(obj.data.vertices) == 0:
        return False
    scene = bpy.context.scene
    here = scene.frame_current
    scene.frame_set(mod.point_cache.frame_end)
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    old = obj.data.shape_keys.key_blocks.get(DRAPE_KEY)
    if old is not None:
        obj.shape_key_remove(old)
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.modifier_apply_as_shapekey(keep_modifier=True, modifier=mod.name)
    key = obj.data.shape_keys.key_blocks[-1]
    key.name = DRAPE_KEY
    key.value = 1.0
    mod.show_viewport = mod.show_render = False
    scene.frame_set(here)
    return True


def drop_drape(obj):
    """Undo Keep Drape: remove the shape key and switch the cloth back on."""
    keys = obj.data.shape_keys
    if keys is not None and keys.key_blocks.get(DRAPE_KEY) is not None:
        obj.shape_key_clear()
    mod = cloth_modifier(obj)
    if mod is not None:
        mod.show_viewport = mod.show_render = True


def remove_cloth(obj):
    drop_drape(obj)
    mod = cloth_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)
