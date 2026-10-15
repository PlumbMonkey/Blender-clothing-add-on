"""Trim: hems, seams and buttons, added on top of a finished garment.

The ``Drape Trim`` modifier runs last, after the thickness (Solidify),
which marks the original (inner) surface ``DRAPE_SHELL`` and its edge band
``DRAPE_RIM``; the outside is the unmarked copy.
Solidify can only write vertex groups the mesh already has; a body shell's
mesh carries the *body's* vertex groups, so the two (empty) groups are made
on the body as well as on the garment.
Lines are found as the edges between two kinds of faces, then smoothed as
curves and swept into thin tubes:

- hems: outside faces next to rim faces (every open edge of the garment);
- seams: outside faces either side of the body's seam fields — front |
  back (side and shoulder seams) and torso | arm (armholes);
- buttons: down the front middle of the torso, on tops.

Fields come from the body (``drape_side`` / ``drape_center`` / ``drape_arm``,
written by Set Up Body) and ride through the shell; a garment without them
(a skirt) simply gets hems only.
"""

import bpy

from .body_regions import SIDE_ATTR, CENTER_ATTR, ARM_ATTR
from .nodes import new_geometry_group

TRIM_GROUP = "Drape Trim"
TRIM_VERSION = 6
BUTTON_DEPTH = 0.002
BUTTON_LIFT = 0.0025  # clears the cloth curving away under a flat button (sternum dip)
TRIM_MODIFIER = "Drape Trim"
SHELL_GROUP = "DRAPE_SHELL"
RIM_GROUP = "DRAPE_RIM"
_LINE_PASSES = 4


def _node(ng, idname, x, y, **props):
    n = ng.nodes.new(idname)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _link(ng, a, b):
    ng.links.new(a, b)


def _face_mean_above(ng, field, threshold, x, y):
    """Float field: 1 on faces whose mean ``field`` is above ``threshold``."""
    cmp = _node(ng, "FunctionNodeCompare", x, y, data_type='FLOAT', operation='GREATER_THAN')
    _link(ng, field, cmp.inputs["A"])
    cmp.inputs["B"].default_value = threshold
    on_faces = _node(ng, "GeometryNodeFieldOnDomain", x + 180, y, domain='FACE', data_type='FLOAT')
    _link(ng, cmp.outputs["Result"], on_faces.inputs["Value"])
    return on_faces.outputs["Value"]


def _edge_between(ng, face_field, x, y):
    """Bool edge field: the edge's two faces disagree on ``face_field`` (mean 0.5)."""
    on_edges = _node(ng, "GeometryNodeFieldOnDomain", x, y, domain='EDGE', data_type='FLOAT')
    _link(ng, face_field, on_edges.inputs["Value"])
    near = _node(ng, "FunctionNodeCompare", x + 180, y, data_type='FLOAT', operation='EQUAL')
    near.mode = 'ELEMENT'
    _link(ng, on_edges.outputs["Value"], near.inputs["A"])
    near.inputs["B"].default_value = 0.5
    near.inputs["Epsilon"].default_value = 0.1
    return near.outputs["Result"]


def _both_faces(ng, face_field, x, y):
    """Bool edge field: both faces of the edge have ``face_field`` = 1."""
    on_edges = _node(ng, "GeometryNodeFieldOnDomain", x, y, domain='EDGE', data_type='FLOAT')
    _link(ng, face_field, on_edges.inputs["Value"])
    full = _node(ng, "FunctionNodeCompare", x + 180, y, data_type='FLOAT', operation='GREATER_THAN')
    _link(ng, on_edges.outputs["Value"], full.inputs["A"])
    full.inputs["B"].default_value = 0.99
    return full.outputs["Result"]


def _and(ng, a, b, x, y):
    n = _node(ng, "FunctionNodeBooleanMath", x, y, operation='AND')
    _link(ng, a, n.inputs[0])
    _link(ng, b, n.inputs[1])
    return n.outputs[0]


def _attr(ng, name, x, y):
    n = _node(ng, "GeometryNodeInputNamedAttribute", x, y, data_type='FLOAT')
    n.inputs["Name"].default_value = name
    return n.outputs["Attribute"]


def _tube(ng, geo, selection, radius, x, y, smooth=True):
    """Edges → smoothed curve → tube of ``radius`` (geometry socket)."""
    to_curve = _node(ng, "GeometryNodeMeshToCurve", x, y)
    _link(ng, geo, to_curve.inputs["Mesh"])
    _link(ng, selection, to_curve.inputs["Selection"])
    curve = to_curve.outputs["Curve"]
    if smooth:
        pos = _node(ng, "GeometryNodeInputPosition", x, y - 200)
        blur = _node(ng, "GeometryNodeBlurAttribute", x + 180, y - 200, data_type='FLOAT_VECTOR')
        _link(ng, pos.outputs["Position"], blur.inputs["Value"])
        blur.inputs["Iterations"].default_value = _LINE_PASSES
        setp = _node(ng, "GeometryNodeSetPosition", x + 180, y)
        _link(ng, curve, setp.inputs["Geometry"])
        _link(ng, blur.outputs["Value"], setp.inputs["Position"])
        curve = setp.outputs["Geometry"]
    circle = _node(ng, "GeometryNodeCurvePrimitiveCircle", x + 360, y - 200, mode='RADIUS')
    circle.inputs["Resolution"].default_value = 8
    _link(ng, radius, circle.inputs["Radius"])
    sweep = _node(ng, "GeometryNodeCurveToMesh", x + 540, y)
    _link(ng, curve, sweep.inputs["Curve"])
    _link(ng, circle.outputs["Curve"], sweep.inputs["Profile Curve"])
    return sweep.outputs["Mesh"]


def _gate(ng, geo, amount, x, y):
    """Pass ``geo`` only when ``amount`` > 0."""
    on = _node(ng, "FunctionNodeCompare", x, y - 150, data_type='FLOAT', operation='GREATER_THAN')
    _link(ng, amount, on.inputs["A"])
    on.inputs["B"].default_value = 0.0
    sw = _node(ng, "GeometryNodeSwitch", x + 180, y, input_type='GEOMETRY')
    _link(ng, on.outputs["Result"], sw.inputs["Switch"])
    _link(ng, geo, sw.inputs["True"])
    return sw.outputs["Output"]


def trim_node_group():
    ng = bpy.data.node_groups.get(TRIM_GROUP)
    if ng is not None and ng.get("drape_version") == TRIM_VERSION:
        return ng
    if ng is not None:
        ng.name = TRIM_GROUP + " (old)"
    ng, gi, go = new_geometry_group(TRIM_GROUP, inputs=(
        ("Hem", 'NodeSocketFloat'),
        ("Seams", 'NodeSocketFloat'),
        ("Buttons", 'NodeSocketInt'),
        ("Button Size", 'NodeSocketFloat'),
        ("Material", 'NodeSocketMaterial'),
        ("Button Material", 'NodeSocketMaterial'),
    ))
    ng["drape_version"] = TRIM_VERSION
    defaults = {"Hem": 0.0015, "Seams": 0.001, "Buttons": 0, "Button Size": 0.006}
    for item in ng.interface.items_tree:
        if item.item_type == 'SOCKET' and item.name in defaults:
            item.default_value = defaults[item.name]
            item.min_value = 0
    geo = gi.outputs["Geometry"]

    # Solidify marks the *original* surface (the inside); the outside is the
    # new copy, i.e. faces with no marked vertex
    marked = _face_mean_above(ng, _attr(ng, SHELL_GROUP, -1400, -100), 0.01, -1200, -100)
    outside = _node(ng, "ShaderNodeMath", -1000, -100, operation='SUBTRACT')
    outside.inputs[0].default_value = 1.0
    _link(ng, marked, outside.inputs[1])
    shell_face = outside.outputs["Value"]

    # hems: outer shell next to the rim
    hem_edges = _edge_between(ng, shell_face, -800, -100)
    hems = _gate(ng, _tube(ng, geo, hem_edges, gi.outputs["Hem"], -500, 0),
                 gi.outputs["Hem"], 300, 0)

    # seams: outer shell faces either side of a body seam field
    on_shell = _both_faces(ng, shell_face, -800, -500)
    side = _edge_between(ng, _face_mean_above(ng, _attr(ng, SIDE_ATTR, -1400, -500), 0.0, -1200, -500), -800, -700)
    arm = _edge_between(ng, _face_mean_above(ng, _attr(ng, ARM_ATTR, -1400, -900), 0.5, -1200, -900), -800, -900)
    either = _node(ng, "FunctionNodeBooleanMath", -500, -800, operation='OR')
    _link(ng, side, either.inputs[0])
    _link(ng, arm, either.inputs[1])
    seam_edges = _and(ng, on_shell, either.outputs[0], -320, -700)
    seams = _gate(ng, _tube(ng, geo, seam_edges, gi.outputs["Seams"], -150, -700),
                  gi.outputs["Seams"], 600, -700)

    # buttons: down the front middle of the torso (not the arms, not the back)
    middle = _edge_between(ng, _face_mean_above(ng, _attr(ng, CENTER_ATTR, -1400, -1300), 0.0, -1200, -1300), -800, -1300)
    front = _node(ng, "FunctionNodeCompare", -800, -1500, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, _attr(ng, SIDE_ATTR, -1000, -1500), front.inputs["A"])
    front.inputs["B"].default_value = 0.0
    trunk = _node(ng, "FunctionNodeCompare", -800, -1650, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, _attr(ng, ARM_ATTR, -1000, -1650), trunk.inputs["A"])
    trunk.inputs["B"].default_value = 0.5
    placket = _and(ng, _and(ng, _and(ng, middle, on_shell, -500, -1300), front.outputs["Result"], -320, -1350),
                   trunk.outputs["Result"], -140, -1400)
    line = _node(ng, "GeometryNodeMeshToCurve", 40, -1300)
    _link(ng, geo, line.inputs["Mesh"])
    _link(ng, placket, line.inputs["Selection"])
    ends = _node(ng, "GeometryNodeTrimCurve", 220, -1300, mode='FACTOR')
    _link(ng, line.outputs["Curve"], ends.inputs["Curve"])
    ends.inputs[2].default_value = 0.06  # Start
    ends.inputs[3].default_value = 0.94  # End
    spaced = _node(ng, "GeometryNodeResampleCurve", 400, -1300)
    _link(ng, ends.outputs["Curve"], spaced.inputs["Curve"])
    _link(ng, gi.outputs["Buttons"], spaced.inputs["Count"])
    spots = _node(ng, "GeometryNodeCurveToPoints", 580, -1300, mode='EVALUATED')
    _link(ng, spaced.outputs["Curve"], spots.inputs["Curve"])
    nrm = _node(ng, "GeometryNodeInputNormal", 400, -1550)
    face_n = _node(ng, "GeometryNodeSampleNearestSurface", 580, -1500, data_type='FLOAT_VECTOR')
    _link(ng, geo, face_n.inputs["Mesh"])
    _link(ng, nrm.outputs["Normal"], face_n.inputs["Value"])
    align = _node(ng, "FunctionNodeAlignRotationToVector", 760, -1500, axis='Z')
    _link(ng, face_n.outputs["Value"], align.inputs["Vector"])
    # sit each button on top of the cloth, not half inside it
    seat = _node(ng, "ShaderNodeVectorMath", 760, -1650, operation='SCALE')
    _link(ng, face_n.outputs["Value"], seat.inputs[0])
    seat.inputs["Scale"].default_value = BUTTON_DEPTH * 0.5 + BUTTON_LIFT
    seated = _node(ng, "GeometryNodeSetPosition", 760, -1300)
    _link(ng, spots.outputs["Points"], seated.inputs["Geometry"])
    _link(ng, seat.outputs["Vector"], seated.inputs["Offset"])
    disc = _node(ng, "GeometryNodeMeshCylinder", 580, -1700, fill_type='NGON')
    disc.inputs["Vertices"].default_value = 16
    disc.inputs["Depth"].default_value = BUTTON_DEPTH
    _link(ng, gi.outputs["Button Size"], disc.inputs["Radius"])
    place = _node(ng, "GeometryNodeInstanceOnPoints", 940, -1300)
    _link(ng, seated.outputs["Geometry"], place.inputs["Points"])
    _link(ng, disc.outputs["Mesh"], place.inputs["Instance"])
    _link(ng, align.outputs[0], place.inputs["Rotation"])
    real = _node(ng, "GeometryNodeRealizeInstances", 1120, -1300)
    _link(ng, place.outputs["Instances"], real.inputs["Geometry"])
    btn_mat = _node(ng, "GeometryNodeSetMaterial", 1120, -1450)
    _link(ng, real.outputs["Geometry"], btn_mat.inputs["Geometry"])
    _link(ng, gi.outputs["Button Material"], btn_mat.inputs["Material"])
    buttons = _gate(ng, btn_mat.outputs["Geometry"], gi.outputs["Buttons"], 1300, -1300)

    join = _node(ng, "GeometryNodeJoinGeometry", 1600, 0)
    trims = _node(ng, "GeometryNodeJoinGeometry", 1400, -400)
    for g in (seams, hems):
        _link(ng, g, trims.inputs["Geometry"])
    smooth = _node(ng, "GeometryNodeSetShadeSmooth", 1500, -400)
    _link(ng, trims.outputs["Geometry"], smooth.inputs["Geometry"])
    dress = _node(ng, "GeometryNodeSetMaterial", 1650, -400)  # tubes come out bare
    _link(ng, smooth.outputs["Geometry"], dress.inputs["Geometry"])
    _link(ng, gi.outputs["Material"], dress.inputs["Material"])
    _link(ng, dress.outputs["Geometry"], join.inputs["Geometry"])
    _link(ng, buttons, join.inputs["Geometry"])
    _link(ng, geo, join.inputs["Geometry"])
    go.location = (1800, 0)
    _link(ng, join.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def ensure_trim(obj):
    """Give a garment its trim modifier (last in the stack) and make its
    thickness mark the outer shell and rim for it."""
    owners = [obj]
    body = obj.drape_garment.body
    if body is not None:
        owners.append(body)
    for owner in owners:
        for name in (SHELL_GROUP, RIM_GROUP):
            vg = owner.vertex_groups.get(name) or owner.vertex_groups.new(name=name)
            if owner is body:
                # an empty group doesn't survive into the shell's mesh; a
                # zero weight on every vertex does (and changes nothing)
                vg.add(list(range(len(body.data.vertices))), 0.0, 'REPLACE')
    sol = obj.modifiers.get("Drape Thickness")
    if sol is not None:
        sol.shell_vertex_group = SHELL_GROUP
        sol.rim_vertex_group = RIM_GROUP
    mod = obj.modifiers.get(TRIM_MODIFIER)
    if mod is None or mod.type != 'NODES':
        mod = obj.modifiers.new(TRIM_MODIFIER, 'NODES')
    mod.node_group = trim_node_group()
    from .nodes import set_input
    if obj.data.materials and obj.data.materials[0] is not None:
        set_input(mod, "Material", obj.data.materials[0])
    btn = button_material()
    if obj.data.materials.find(btn.name) < 0:
        obj.data.materials.append(btn)  # a slot, so the buttons render with it
    set_input(mod, "Button Material", btn)
    with bpy.context.temp_override(object=obj):
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=len(obj.modifiers) - 1)
    return mod


BUTTON_MATERIAL = "Drape Buttons"


def button_material():
    """Off-white plastic buttons, shared by every garment."""
    mat = bpy.data.materials.get(BUTTON_MATERIAL)
    if mat is None:
        from .fabric import make_fabric
        mat = make_fabric(BUTTON_MATERIAL, (0.92, 0.9, 0.85))
        bsdf = mat.node_tree.nodes["Drape Fabric"]
        bsdf.inputs["Roughness"].default_value = 0.35
        if "Sheen Weight" in bsdf.inputs:
            bsdf.inputs["Sheen Weight"].default_value = 0.0
    return mat


def trim_modifier(obj):
    mod = obj.modifiers.get(TRIM_MODIFIER)
    return mod if mod is not None and mod.type == 'NODES' else None
