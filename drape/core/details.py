"""Details drawn on a garment: straps, belts, piping and zips.

A detail is a curve object the user draws straight onto the garment (Draw
tool, surface depth). Its ``Drape Detail`` modifier keeps the curve stuck to
the garment's current surface and sweeps a profile along it: a flat band
lying on the cloth (strap, belt, zip tape) or a round cord (piping); a zip
adds teeth. When drawing is finished the curve is parented to the bone
nearest it, so it follows the character.
"""

import bpy
from mathutils import Vector

from .nodes import new_geometry_group, set_input
from .fabric import make_fabric

DETAIL_GROUP = "Drape Detail"
DETAIL_VERSION = 4
DETAIL_MODIFIER = "Drape Detail"

KINDS = (
    ('STRAP', "Strap", "A flat strap lying on the cloth (bag strap, braces)"),
    ('BELT', "Belt", "A wide, stiff leather band"),
    ('PIPING', "Piping", "A round cord along a line (trim, drawstring)"),
    ('ZIP', "Zip", "A zip: a narrow tape with metal teeth"),
)
# width m, thickness m, round?, teeth?, colour
KIND_LOOK = {
    'STRAP': (0.025, 0.003, False, False, (0.08, 0.08, 0.09)),
    'BELT': (0.038, 0.005, False, False, (0.22, 0.12, 0.06)),
    'PIPING': (0.006, 0.006, True, False, (0.9, 0.9, 0.88)),
    'ZIP': (0.012, 0.002, False, True, (0.15, 0.15, 0.16)),
}
_LIFT = 0.001     # metres above the cloth
_SPACING = 0.004  # metres between curve samples (and zip teeth)
_SMOOTH_POS = 6     # passes along the curve
_SMOOTH_NORMAL = 12


def _node(ng, idname, x, y, **props):
    n = ng.nodes.new(idname)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def detail_node_group():
    ng = bpy.data.node_groups.get(DETAIL_GROUP)
    if ng is not None and ng.get("drape_version") == DETAIL_VERSION:
        return ng
    if ng is not None:
        ng.name = DETAIL_GROUP + " (old)"
    ng, gi, go = new_geometry_group(DETAIL_GROUP, inputs=(
        ("Surface", 'NodeSocketObject'),
        ("Width", 'NodeSocketFloat'),
        ("Thickness", 'NodeSocketFloat'),
        ("Round", 'NodeSocketBool'),
        ("Teeth", 'NodeSocketBool'),
        ("Material", 'NodeSocketMaterial'),
        ("Teeth Material", 'NodeSocketMaterial'),
    ))
    ng["drape_version"] = DETAIL_VERSION
    L = ng.links.new

    # even samples along the drawn curve
    res = _node(ng, "GeometryNodeResampleCurve", -1000, 0)
    res.inputs["Mode"].default_value = 'Length'
    res.inputs["Length"].default_value = _SPACING
    L(gi.outputs["Geometry"], res.inputs["Curve"])

    # stick to the garment as it is now (posed): nearest point + normal
    info = _node(ng, "GeometryNodeObjectInfo", -1000, -300, transform_space='RELATIVE')
    L(gi.outputs["Surface"], info.inputs["Object"])
    spos = _node(ng, "GeometryNodeInputPosition", -1000, -500)
    snrm = _node(ng, "GeometryNodeInputNormal", -1000, -600)
    at = _node(ng, "GeometryNodeSampleNearestSurface", -800, -400, data_type='FLOAT_VECTOR')
    nr = _node(ng, "GeometryNodeSampleNearestSurface", -800, -600, data_type='FLOAT_VECTOR')
    for s, f in ((at, spos.outputs["Position"]), (nr, snrm.outputs["Normal"])):
        L(info.outputs["Geometry"], s.inputs["Mesh"])
        L(f, s.inputs["Value"])
    raw = _node(ng, "ShaderNodeVectorMath", -700, -600, operation='NORMALIZE')
    L(nr.outputs["Value"], raw.inputs[0])
    # the nearest cloth may be the garment's inside (normal pointing in):
    # flip any normal that points away from where the curve was drawn
    drawn = _node(ng, "GeometryNodeInputPosition", -900, -900)
    away = _node(ng, "ShaderNodeVectorMath", -700, -900, operation='SUBTRACT')
    L(drawn.outputs["Position"], away.inputs[0])
    L(at.outputs["Value"], away.inputs[1])
    side = _node(ng, "ShaderNodeVectorMath", -550, -900, operation='DOT_PRODUCT')
    L(raw.outputs["Vector"], side.inputs[0])
    L(away.outputs["Vector"], side.inputs[1])
    inward = _node(ng, "FunctionNodeCompare", -400, -900, data_type='FLOAT', operation='LESS_THAN')
    L(side.outputs["Value"], inward.inputs["A"])
    inward.inputs["B"].default_value = 0.0
    sign = _node(ng, "ShaderNodeMath", -250, -900, operation='MULTIPLY_ADD')  # 1 or -1
    L(inward.outputs["Result"], sign.inputs[0])
    sign.inputs[1].default_value = -2.0
    sign.inputs[2].default_value = 1.0
    unit = _node(ng, "ShaderNodeVectorMath", -600, -600, operation='SCALE')
    L(raw.outputs["Vector"], unit.inputs[0])
    L(sign.outputs["Value"], unit.inputs["Scale"])
    half = _node(ng, "ShaderNodeMath", -600, -800, operation='MULTIPLY_ADD')
    L(gi.outputs["Thickness"], half.inputs[0])
    half.inputs[1].default_value = 0.5
    half.inputs[2].default_value = _LIFT
    # move each point only along the cloth's normal (onto the surface, then
    # up by half the thickness); sliding sideways would drag points to hems
    gap = _node(ng, "ShaderNodeVectorMath", -420, -1050, operation='DOT_PRODUCT')
    L(away.outputs["Vector"], gap.inputs[0])
    L(unit.outputs["Vector"], gap.inputs[1])
    down = _node(ng, "ShaderNodeMath", -250, -1050, operation='SUBTRACT')
    L(half.outputs["Value"], down.inputs[0])
    L(gap.outputs["Value"], down.inputs[1])
    along_n = _node(ng, "ShaderNodeVectorMath", -100, -1000, operation='SCALE')
    L(unit.outputs["Vector"], along_n.inputs[0])
    L(down.outputs["Value"], along_n.inputs["Scale"])
    lay = _node(ng, "ShaderNodeVectorMath", -240, -500, operation='ADD')
    L(drawn.outputs["Position"], lay.inputs[0])
    L(along_n.outputs["Vector"], lay.inputs[1])
    # remember the cloth's normal per sample (it is smoothed below)
    keep_n = _node(ng, "GeometryNodeStoreNamedAttribute", -800, 0, data_type='FLOAT_VECTOR', domain='POINT')
    keep_n.inputs["Name"].default_value = "drape_n"
    L(res.outputs["Curve"], keep_n.inputs["Geometry"])
    L(unit.outputs["Vector"], keep_n.inputs["Value"])
    stick = _node(ng, "GeometryNodeSetPosition", -600, 0)
    L(keep_n.outputs["Geometry"], stick.inputs["Geometry"])
    L(lay.outputs["Vector"], stick.inputs["Position"])
    # smooth along the curve: near hems and folds the nearest cloth jumps
    # between surfaces, which would crumple the band
    cpos = _node(ng, "GeometryNodeInputPosition", -600, 150)
    cblur = _node(ng, "GeometryNodeBlurAttribute", -450, 150, data_type='FLOAT_VECTOR')
    L(cpos.outputs["Position"], cblur.inputs["Value"])
    cblur.inputs["Iterations"].default_value = _SMOOTH_POS
    calm = _node(ng, "GeometryNodeSetPosition", -450, 0)
    L(stick.outputs["Geometry"], calm.inputs["Geometry"])
    L(cblur.outputs["Value"], calm.inputs["Position"])
    n_in = _node(ng, "GeometryNodeInputNamedAttribute", -450, -150, data_type='FLOAT_VECTOR')
    n_in.inputs["Name"].default_value = "drape_n"
    nblur = _node(ng, "GeometryNodeBlurAttribute", -300, -150, data_type='FLOAT_VECTOR')
    L(n_in.outputs["Attribute"], nblur.inputs["Value"])
    nblur.inputs["Iterations"].default_value = _SMOOTH_NORMAL
    nunit = _node(ng, "ShaderNodeVectorMath", -150, -150, operation='NORMALIZE')
    L(nblur.outputs["Value"], nunit.inputs[0])
    # the band's flat side faces the cloth
    face = _node(ng, "GeometryNodeSetCurveNormal", -300, 0)
    face.inputs["Mode"].default_value = 'Free'
    L(calm.outputs["Geometry"], face.inputs["Curve"])
    L(nunit.outputs["Vector"], face.inputs["Normal"])

    # profile: flat band or round cord
    band = _node(ng, "GeometryNodeCurvePrimitiveQuadrilateral", -400, 300)
    L(gi.outputs["Thickness"], band.inputs["Width"])
    L(gi.outputs["Width"], band.inputs["Height"])
    radius = _node(ng, "ShaderNodeMath", -600, 450, operation='MULTIPLY')
    L(gi.outputs["Width"], radius.inputs[0])
    radius.inputs[1].default_value = 0.5
    cord = _node(ng, "GeometryNodeCurvePrimitiveCircle", -400, 450, mode='RADIUS')
    cord.inputs["Resolution"].default_value = 10
    L(radius.outputs["Value"], cord.inputs["Radius"])
    pick = _node(ng, "GeometryNodeSwitch", -200, 350, input_type='GEOMETRY')
    L(gi.outputs["Round"], pick.inputs["Switch"])
    L(band.outputs["Curve"], pick.inputs["False"])
    L(cord.outputs["Curve"], pick.inputs["True"])
    sweep = _node(ng, "GeometryNodeCurveToMesh", 0, 0)
    sweep.inputs["Fill Caps"].default_value = True
    L(face.outputs["Curve"], sweep.inputs["Curve"])
    L(pick.outputs["Output"], sweep.inputs["Profile Curve"])
    dress = _node(ng, "GeometryNodeSetMaterial", 200, 0)
    L(sweep.outputs["Mesh"], dress.inputs["Geometry"])
    L(gi.outputs["Material"], dress.inputs["Material"])

    # zip teeth: a small block at every sample, across the tape
    pts = _node(ng, "GeometryNodeCurveToPoints", 0, -300, mode='EVALUATED')
    L(face.outputs["Curve"], pts.inputs["Curve"])
    tooth = _node(ng, "GeometryNodeMeshCube", 0, -500)
    size = _node(ng, "ShaderNodeCombineXYZ", -200, -500)
    tw = _node(ng, "ShaderNodeMath", -400, -450, operation='MULTIPLY')
    L(gi.outputs["Width"], tw.inputs[0])
    tw.inputs[1].default_value = 0.45
    L(tw.outputs["Value"], size.inputs["Y"])
    size.inputs["X"].default_value = _SPACING * 0.55
    th = _node(ng, "ShaderNodeMath", -400, -600, operation='ADD')
    L(gi.outputs["Thickness"], th.inputs[0])
    th.inputs[1].default_value = 0.0012
    L(th.outputs["Value"], size.inputs["Z"])
    L(size.outputs["Vector"], tooth.inputs["Size"])
    put = _node(ng, "GeometryNodeInstanceOnPoints", 200, -300)
    L(pts.outputs["Points"], put.inputs["Points"])
    L(tooth.outputs["Mesh"], put.inputs["Instance"])
    L(pts.outputs["Rotation"], put.inputs["Rotation"])
    real = _node(ng, "GeometryNodeRealizeInstances", 400, -300)
    L(put.outputs["Instances"], real.inputs["Geometry"])
    metal = _node(ng, "GeometryNodeSetMaterial", 600, -300)
    L(real.outputs["Geometry"], metal.inputs["Geometry"])
    L(gi.outputs["Teeth Material"], metal.inputs["Material"])
    teeth = _node(ng, "GeometryNodeSwitch", 800, -300, input_type='GEOMETRY')
    L(gi.outputs["Teeth"], teeth.inputs["Switch"])
    L(metal.outputs["Geometry"], teeth.inputs["True"])

    join = _node(ng, "GeometryNodeJoinGeometry", 1000, 0)
    L(teeth.outputs["Output"], join.inputs["Geometry"])
    L(dress.outputs["Geometry"], join.inputs["Geometry"])
    smooth = _node(ng, "GeometryNodeSetShadeSmooth", 1200, 0)
    L(join.outputs["Geometry"], smooth.inputs["Geometry"])
    go.location = (1400, 0)
    L(smooth.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def _metal():
    mat = bpy.data.materials.get("Drape Metal")
    if mat is None:
        mat = make_fabric("Drape Metal", (0.75, 0.75, 0.72))
        bsdf = mat.node_tree.nodes["Drape Fabric"]
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.3
        if "Sheen Weight" in bsdf.inputs:
            bsdf.inputs["Sheen Weight"].default_value = 0.0
    return mat


def home_collection(obj):
    """The first collection of ``obj`` that is in the scene (garments also sit
    in hidden layering collections)."""
    scene_colls = set(bpy.context.scene.collection.children_recursive)
    for c in obj.users_collection:
        if c in scene_colls:
            return c
    return bpy.context.scene.collection


def create_detail(garment, kind, points=None, cyclic=False):
    """A detail curve on ``garment``. ``points`` (world) draws it straight
    away (``cyclic`` closes it, e.g. a belt); without them the curve is
    empty, ready to be drawn."""
    name = f"Drape_{kind.title()}_{garment.name}"
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    obj = bpy.data.objects.new(name, cu)
    home_collection(garment).objects.link(obj)
    if points:
        sp = cu.splines.new('POLY')
        sp.points.add(len(points) - 1)
        for p, co in zip(sp.points, points):
            p.co = (*co, 1.0)
        sp.use_cyclic_u = cyclic

    width, thickness, round_, teeth, color = KIND_LOOK[kind]
    mat = make_fabric(name, color)
    if kind == 'BELT':
        mat.node_tree.nodes["Drape Fabric"].inputs["Roughness"].default_value = 0.45
    cu.materials.append(mat)
    cu.materials.append(_metal())
    mod = obj.modifiers.new(DETAIL_MODIFIER, 'NODES')
    mod.node_group = detail_node_group()
    set_input(mod, "Surface", garment)
    set_input(mod, "Width", width)
    set_input(mod, "Thickness", thickness)
    set_input(mod, "Round", round_)
    set_input(mod, "Teeth", teeth)
    set_input(mod, "Material", mat)
    set_input(mod, "Teeth Material", _metal())
    obj["drape_detail"] = kind
    obj["drape_garment"] = garment.name
    return obj


def nearest_bone(armature, point):
    """Name of the main deform bone whose head-tail segment passes nearest
    ``point`` (world). Physics and helper bones (VRoid J_Sec_* / J_Adj_*,
    twist and share bones) are skipped: a strap shouldn't bounce with them."""
    from .body_regions import classify_bones
    from .coverage import part_roots
    mains = {b.name for b in part_roots(armature).values()}
    parts = classify_bones(armature)
    best, best_d = None, float('inf')
    mw = armature.matrix_world
    for pb in armature.pose.bones:
        if pb.name not in mains and pb.name not in parts:
            continue
        low = pb.name.lower()
        if pb.name not in mains and any(w in low for w in ("j_sec", "j_adj", "twist", "share")):
            continue
        a, b = mw @ pb.head, mw @ pb.tail
        ab = b - a
        t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (point - a).dot(ab) / ab.length_squared))
        d = (a + ab * t - point).length
        if d < best_d:
            best, best_d = pb.name, d
    return best


def attach_detail(obj, armature):
    """Parent a finished detail to the bone nearest its middle (keeps its place)."""
    from .skirt import parent_to_bone
    pts = [obj.matrix_world @ Vector(p.co[:3]) for sp in obj.data.splines for p in sp.points]
    pts += [obj.matrix_world @ p.co for sp in obj.data.splines for p in sp.bezier_points]
    if not pts or armature is None:
        return None
    mid = sum(pts, Vector()) / len(pts)
    bone = nearest_bone(armature, mid)
    world = obj.matrix_world.copy()
    parent_to_bone(obj, armature, bone)
    # parent_to_bone assumes data in world space: put the drawn data back
    obj.data.transform(world)
    return bone
