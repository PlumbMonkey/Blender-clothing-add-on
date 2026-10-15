"""Garment shell: a non-destructive garment generated from body coverage.

The garment is its own mesh object at the world origin with two modifiers:

1. ``Drape Shell`` (Geometry Nodes, group "Drape Garment Shell"): reads the
   body *as evaluated* (posed, shape-keyed) in world space, welds split
   seams, keeps the faces near the (softened) coverage, subdivides them,
   then cuts along the true 0.5 line (uncovered vertices snap to where the
   coverage crosses 0.5 on each edge) and smooths that edge as a line,
   relaxes the surface (Looseness, fading out at the edges) so it bridges
   hollows like cloth, then pushes anything nearer the body than Offset
   back out to it.
2. ``Drape Thickness`` (Solidify): gives the cloth its thickness, outward.

Because the shell reads the live body, it follows the body's animation and
updates while the coverage is being painted. Distances are in metres (the
garment sits at the world origin with no scale, whatever the body's units).
"""

import bpy

from .nodes import new_geometry_group, set_input, get_input

SHELL_GROUP = "Drape Garment Shell"
SHELL_VERSION = 12
PIN_ATTR = "Drape_Pin"  # garment vertex group the cloth pins with
SNAP_MERGE = 0.001  # metres: joins vertices snapped onto the same edge point
LOOSE_FADE = 0.04  # metres: looseness fades to nothing at the garment edges
WELD_DISTANCE = 0.0001  # metres: joins duplicated seam vertices
COVERAGE_ATTR = "drape_cov"
BORDER_LINE_PASSES = 6  # final smoothing of the cut line, along the line
SHELL_MODIFIER = "Drape Shell"
THICKNESS_MODIFIER = "Drape Thickness"


def _link(ng, a, b):
    ng.links.new(a, b)


def _node(ng, idname, x, y, **props):
    n = ng.nodes.new(idname)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def shell_node_group():
    """The shared shell node group (rebuilt when SHELL_VERSION changes)."""
    old = bpy.data.node_groups.get(SHELL_GROUP)
    if old is not None and old.get("drape_version") == SHELL_VERSION:
        return old
    if old is not None:
        old.name = SHELL_GROUP + " (old)"
    ng = _build_shell_group()
    if old is not None:
        _upgrade_modifiers(old, ng)
    return ng


def _upgrade_modifiers(old, new):
    """Move every garment from an older shell group onto the new one, carrying
    input values across by name (socket identifiers can shift between
    versions)."""
    names = [i.name for i in old.interface.items_tree
             if i.item_type == 'SOCKET' and i.in_out == 'INPUT' and i.name != "Geometry"]
    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type != 'NODES' or mod.node_group is not old:
                continue
            values = {}
            for n in names:
                try:
                    values[n] = get_input(mod, n)
                except (KeyError, AttributeError):
                    pass
            mod.node_group = new
            for n, v in values.items():
                try:
                    set_input(mod, n, v)
                except (KeyError, TypeError, AttributeError):
                    pass
            obj.update_tag()
    if old.users == 0:
        bpy.data.node_groups.remove(old)


def _build_shell_group():
    ng, gi, go = new_geometry_group(SHELL_GROUP, inputs=(
        ("Body", 'NodeSocketObject'),
        ("Coverage", 'NodeSocketString'),
        ("Offset", 'NodeSocketFloat'),
        ("Resolution", 'NodeSocketInt'),
        ("Border Smooth", 'NodeSocketInt'),
        ("Looseness", 'NodeSocketInt'),
        ("Material", 'NodeSocketMaterial'),
        ("Pin", 'NodeSocketString'),
    ))
    ng["drape_version"] = SHELL_VERSION
    defaults = {"Offset": 0.004, "Resolution": 1, "Border Smooth": 4, "Looseness": 15}
    for item in ng.interface.items_tree:
        if item.item_type == 'SOCKET' and item.name in defaults:
            item.default_value = defaults[item.name]
            if item.name in ("Resolution", "Border Smooth", "Looseness"):
                item.min_value = 0
                item.max_value = {"Resolution": 3, "Border Smooth": 30}.get(item.name, 100)
    gi.location = (-1400, 0)

    # body in world space (garment object sits at the origin)
    info = _node(ng, "GeometryNodeObjectInfo", -1200, 200, transform_space='RELATIVE')
    _link(ng, gi.outputs["Body"], info.inputs["Object"])
    # weld split seams first (VRoid bodies duplicate every UV/material seam
    # vertex: unwelded, they open as holes, fake hems, and stop the coverage
    # softening below at every seam)
    # body mesh only: other add-ons' modifiers on the body can add instances
    # (the VRM add-on's MToon Outline does), which would ride along otherwise
    only_mesh = _node(ng, "GeometryNodeSeparateComponents", -1100, 600)
    _link(ng, info.outputs["Geometry"], only_mesh.inputs["Geometry"])
    weld = _node(ng, "GeometryNodeMergeByDistance", -1100, 400)
    _link(ng, only_mesh.outputs["Mesh"], weld.inputs["Geometry"])
    weld.inputs["Distance"].default_value = WELD_DISTANCE
    body = weld.outputs["Geometry"]

    # soften the 0/1 coverage on the body so its 0.5 line runs smooth
    # (Border Smooth = blur passes), and store it for the cuts below
    cov = _node(ng, "GeometryNodeInputNamedAttribute", -1200, -100, data_type='FLOAT')
    _link(ng, gi.outputs["Coverage"], cov.inputs["Name"])
    soften = _node(ng, "GeometryNodeBlurAttribute", -1000, -100, data_type='FLOAT')
    _link(ng, cov.outputs["Attribute"], soften.inputs["Value"])
    _link(ng, gi.outputs["Border Smooth"], soften.inputs["Iterations"])
    store = _node(ng, "GeometryNodeStoreNamedAttribute", -1000, 200, data_type='FLOAT', domain='POINT')
    store.inputs["Name"].default_value = COVERAGE_ATTR
    _link(ng, body, store.inputs["Geometry"])
    _link(ng, soften.outputs["Value"], store.inputs["Value"])
    soft = _node(ng, "GeometryNodeInputNamedAttribute", -1000, -300, data_type='FLOAT')
    soft.inputs["Name"].default_value = COVERAGE_ATTR

    # cut 1: keep the covered faces plus a band around them …
    far = _node(ng, "FunctionNodeCompare", -800, -300, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, soft.outputs["Attribute"], far.inputs["A"])
    far.inputs["B"].default_value = 0.02
    band = _node(ng, "GeometryNodeDeleteGeometry", -800, 200, domain='FACE', mode='ALL')
    _link(ng, store.outputs["Geometry"], band.inputs["Geometry"])
    _link(ng, far.outputs["Result"], band.inputs["Selection"])

    # … subdivide (coverage interpolates), then cut 2 at 0.5 on the finer mesh
    # (a face's value is the mean of its corners)
    subd = _node(ng, "GeometryNodeSubdivisionSurface", -600, 200)
    _link(ng, band.outputs["Geometry"], subd.inputs["Mesh"])
    _link(ng, gi.outputs["Resolution"], subd.inputs["Level"])
    fine = subd.outputs["Mesh"]

    # the true edge: a point on every edge whose coverage crosses 0.5, at the
    # crossing (linear along the edge), so the cut ignores face sizes
    ev = _node(ng, "GeometryNodeInputMeshEdgeVertices", -600, -1100)
    c1 = _node(ng, "GeometryNodeSampleIndex", -420, -1000, data_type='FLOAT', domain='POINT')
    c2 = _node(ng, "GeometryNodeSampleIndex", -420, -1200, data_type='FLOAT', domain='POINT')
    for smp, idx in ((c1, ev.outputs["Vertex Index 1"]), (c2, ev.outputs["Vertex Index 2"])):
        _link(ng, fine, smp.inputs["Geometry"])
        _link(ng, soft.outputs["Attribute"], smp.inputs["Value"])
        _link(ng, idx, smp.inputs["Index"])
    d1 = _node(ng, "ShaderNodeMath", -240, -1000, operation='SUBTRACT')
    _link(ng, c1.outputs["Value"], d1.inputs[0])
    d1.inputs[1].default_value = 0.5
    d2 = _node(ng, "ShaderNodeMath", -240, -1200, operation='SUBTRACT')
    _link(ng, c2.outputs["Value"], d2.inputs[0])
    d2.inputs[1].default_value = 0.5
    sides = _node(ng, "ShaderNodeMath", -60, -1100, operation='MULTIPLY')
    _link(ng, d1.outputs["Value"], sides.inputs[0])
    _link(ng, d2.outputs["Value"], sides.inputs[1])
    crosses = _node(ng, "FunctionNodeCompare", 120, -1100, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, sides.outputs["Value"], crosses.inputs["A"])
    crosses.inputs["B"].default_value = 0.0
    span = _node(ng, "ShaderNodeMath", -60, -1300, operation='SUBTRACT')  # c1 - c2
    _link(ng, d1.outputs["Value"], span.inputs[0])
    _link(ng, d2.outputs["Value"], span.inputs[1])
    frac = _node(ng, "ShaderNodeMath", 120, -1300, operation='DIVIDE')  # (c1-.5)/(c1-c2)
    _link(ng, d1.outputs["Value"], frac.inputs[0])
    _link(ng, span.outputs["Value"], frac.inputs[1])
    step = _node(ng, "ShaderNodeVectorMath", 120, -1500, operation='SUBTRACT')
    _link(ng, ev.outputs["Position 2"], step.inputs[0])
    _link(ng, ev.outputs["Position 1"], step.inputs[1])
    along = _node(ng, "ShaderNodeVectorMath", 300, -1400, operation='SCALE')
    _link(ng, step.outputs["Vector"], along.inputs[0])
    _link(ng, frac.outputs["Value"], along.inputs["Scale"])
    cross_pos = _node(ng, "ShaderNodeVectorMath", 480, -1300, operation='ADD')
    _link(ng, ev.outputs["Position 1"], cross_pos.inputs[0])
    _link(ng, along.outputs["Vector"], cross_pos.inputs[1])
    iso = _node(ng, "GeometryNodeMeshToPoints", 660, -1100, mode='EDGES')
    _link(ng, fine, iso.inputs["Mesh"])
    _link(ng, crosses.outputs["Result"], iso.inputs["Selection"])
    _link(ng, cross_pos.outputs["Vector"], iso.inputs["Position"])

    # cut 2: keep every face that touches covered skin (so the true edge
    # runs inside the kept faces) …
    inside = _node(ng, "FunctionNodeCompare", -600, -300, data_type='FLOAT', operation='GREATER_EQUAL')
    _link(ng, soft.outputs["Attribute"], inside.inputs["A"])
    inside.inputs["B"].default_value = 0.5
    as_float = _node(ng, "ShaderNodeMath", -420, -300, operation='MULTIPLY')
    _link(ng, inside.outputs["Result"], as_float.inputs[0])
    as_float.inputs[1].default_value = 1.0
    untouched = _node(ng, "FunctionNodeCompare", -240, -300, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, as_float.outputs["Value"], untouched.inputs["A"])  # face mean: 0 = no corner covered
    untouched.inputs["B"].default_value = 1e-4
    cut = _node(ng, "GeometryNodeDeleteGeometry", -420, 200, domain='FACE', mode='ALL')
    _link(ng, fine, cut.inputs["Geometry"])
    _link(ng, untouched.outputs["Result"], cut.inputs["Selection"])

    # … then pull the uncovered vertices onto the nearest point of the true edge
    iso_near = _node(ng, "GeometryNodeSampleNearest", 1020, -1100, domain='POINT')
    _link(ng, iso.outputs["Points"], iso_near.inputs["Geometry"])
    iso_pos = _node(ng, "GeometryNodeInputPosition", 1020, -1300)
    iso_at = _node(ng, "GeometryNodeSampleIndex", 1200, -1100, data_type='FLOAT_VECTOR', domain='POINT')
    _link(ng, iso.outputs["Points"], iso_at.inputs["Geometry"])
    _link(ng, iso_pos.outputs["Position"], iso_at.inputs["Value"])
    _link(ng, iso_near.outputs["Index"], iso_at.inputs["Index"])
    # (every uncovered vertex left, border or not: a kept face can have an
    # uncovered corner inside the mesh, which would poke out as a tooth)
    outside = _node(ng, "FunctionNodeCompare", -420, -500, data_type='FLOAT', operation='LESS_THAN')
    _link(ng, soft.outputs["Attribute"], outside.inputs["A"])
    outside.inputs["B"].default_value = 0.5
    snap = _node(ng, "GeometryNodeSetPosition", -240, 200)
    _link(ng, cut.outputs["Geometry"], snap.inputs["Geometry"])
    _link(ng, outside.outputs["Result"], snap.inputs["Selection"])
    _link(ng, iso_at.outputs["Value"], snap.inputs["Position"])
    # vertices snapped onto the same edge point leave zero-area faces, whose
    # undefined normals make Solidify throw spikes: merge them
    collapse = _node(ng, "GeometryNodeMergeByDistance", -60, 200)
    _link(ng, snap.outputs["Geometry"], collapse.inputs["Geometry"])
    collapse.inputs["Distance"].default_value = SNAP_MERGE
    trimmed = collapse.outputs["Geometry"]

    # smooth the open border as a line: border edges → curves, blur along
    # the curves, then snap each border vertex to its smoothed curve point
    # (Blur Attribute on the mesh itself also pulls from interior verts)
    nbrs = _node(ng, "GeometryNodeInputMeshEdgeNeighbors", -600, -250)
    is_edge = _node(ng, "FunctionNodeCompare", -420, -250, data_type='INT', operation='EQUAL')
    _link(ng, nbrs.outputs["Face Count"], is_edge.inputs["A"])
    is_edge.inputs["B"].default_value = 1
    on_pts = _node(ng, "GeometryNodeFieldOnDomain", -240, -250, domain='EDGE', data_type='FLOAT')
    _link(ng, is_edge.outputs["Result"], on_pts.inputs["Value"])
    border = _node(ng, "FunctionNodeCompare", -60, -250, data_type='FLOAT', operation='GREATER_THAN')
    _link(ng, on_pts.outputs["Value"], border.inputs["A"])
    border.inputs["B"].default_value = 0.0

    to_curve = _node(ng, "GeometryNodeMeshToCurve", -420, -500)
    _link(ng, trimmed, to_curve.inputs["Mesh"])
    _link(ng, is_edge.outputs["Result"], to_curve.inputs["Selection"])
    orig_pts = _node(ng, "GeometryNodeCurveToPoints", -200, -650, mode='EVALUATED')
    _link(ng, to_curve.outputs["Curve"], orig_pts.inputs["Curve"])
    c_pos = _node(ng, "GeometryNodeInputPosition", -420, -750)
    c_blur = _node(ng, "GeometryNodeBlurAttribute", -200, -800, data_type='FLOAT_VECTOR')
    _link(ng, c_pos.outputs["Position"], c_blur.inputs["Value"])
    c_blur.inputs["Iterations"].default_value = BORDER_LINE_PASSES
    c_set = _node(ng, "GeometryNodeSetPosition", 0, -500)
    _link(ng, to_curve.outputs["Curve"], c_set.inputs["Geometry"])
    _link(ng, c_blur.outputs["Value"], c_set.inputs["Position"])
    smooth_pts = _node(ng, "GeometryNodeCurveToPoints", 200, -500, mode='EVALUATED')
    _link(ng, c_set.outputs["Geometry"], smooth_pts.inputs["Curve"])
    nearest = _node(ng, "GeometryNodeSampleNearest", 0, -700, domain='POINT')
    _link(ng, orig_pts.outputs["Points"], nearest.inputs["Geometry"])
    lookup = _node(ng, "GeometryNodeSampleIndex", 400, -550, data_type='FLOAT_VECTOR', domain='POINT')
    _link(ng, smooth_pts.outputs["Points"], lookup.inputs["Geometry"])
    _link(ng, c_pos.outputs["Position"], lookup.inputs["Value"])
    _link(ng, nearest.outputs["Index"], lookup.inputs["Index"])
    smooth = _node(ng, "GeometryNodeSetPosition", 600, 200)
    _link(ng, trimmed, smooth.inputs["Geometry"])
    _link(ng, border.outputs["Result"], smooth.inputs["Selection"])
    _link(ng, lookup.outputs["Value"], smooth.inputs["Position"])

    # looseness: relax the whole surface so it bridges hollows like cloth
    pos = _node(ng, "GeometryNodeInputPosition", 600, -150)
    relax = _node(ng, "GeometryNodeBlurAttribute", 780, -150, data_type='FLOAT_VECTOR')
    _link(ng, pos.outputs["Position"], relax.inputs["Value"])
    _link(ng, gi.outputs["Looseness"], relax.inputs["Iterations"])
    # … fading out towards the edges: relaxing an open tube curls its end
    # inward and folds the hem under itself
    edge_pts = _node(ng, "GeometryNodeMeshToPoints", 780, -350, mode='VERTICES')
    _link(ng, smooth.outputs["Geometry"], edge_pts.inputs["Mesh"])
    _link(ng, border.outputs["Result"], edge_pts.inputs["Selection"])
    to_edge = _node(ng, "GeometryNodeProximity", 960, -350, target_element='POINTS')
    _link(ng, edge_pts.outputs["Points"], to_edge.inputs[0])
    fade = _node(ng, "ShaderNodeMapRange", 1140, -350, data_type='FLOAT', interpolation_type='SMOOTHSTEP')
    _link(ng, to_edge.outputs["Distance"], fade.inputs["Value"])
    fade.inputs["From Min"].default_value = 0.0
    fade.inputs["From Max"].default_value = LOOSE_FADE
    moved = _node(ng, "ShaderNodeVectorMath", 960, -150, operation='SUBTRACT')
    _link(ng, relax.outputs["Value"], moved.inputs[0])
    _link(ng, pos.outputs["Position"], moved.inputs[1])
    faded = _node(ng, "ShaderNodeVectorMath", 1140, -150, operation='SCALE')
    _link(ng, moved.outputs["Vector"], faded.inputs[0])
    _link(ng, fade.outputs["Result"], faded.inputs["Scale"])
    loose = _node(ng, "GeometryNodeSetPosition", 1320, 200)
    _link(ng, smooth.outputs["Geometry"], loose.inputs["Geometry"])
    _link(ng, faded.outputs["Vector"], loose.inputs["Offset"])

    # collide: anything closer to the body than Offset is pushed out to it
    # p' = p + n * max(Offset - (p - s)·n, 0), s/n = nearest body point/normal
    body_pos = _node(ng, "GeometryNodeInputPosition", 960, -300)
    body_nrm = _node(ng, "GeometryNodeInputNormal", 960, -450)
    s_pos = _node(ng, "GeometryNodeSampleNearestSurface", 1140, -250, data_type='FLOAT_VECTOR')
    s_nrm = _node(ng, "GeometryNodeSampleNearestSurface", 1140, -450, data_type='FLOAT_VECTOR')
    for s, field in ((s_pos, body_pos.outputs["Position"]), (s_nrm, body_nrm.outputs["Normal"])):
        _link(ng, body, s.inputs["Mesh"])
        _link(ng, field, s.inputs["Value"])
    unit = _node(ng, "ShaderNodeVectorMath", 1320, -450, operation='NORMALIZE')
    _link(ng, s_nrm.outputs["Value"], unit.inputs[0])
    here = _node(ng, "GeometryNodeInputPosition", 1140, -650)
    rel = _node(ng, "ShaderNodeVectorMath", 1320, -650, operation='SUBTRACT')
    _link(ng, here.outputs["Position"], rel.inputs[0])
    _link(ng, s_pos.outputs["Value"], rel.inputs[1])
    dist = _node(ng, "ShaderNodeVectorMath", 1500, -550, operation='DOT_PRODUCT')
    _link(ng, rel.outputs["Vector"], dist.inputs[0])
    _link(ng, unit.outputs["Vector"], dist.inputs[1])
    short = _node(ng, "ShaderNodeMath", 1680, -550, operation='SUBTRACT')
    _link(ng, gi.outputs["Offset"], short.inputs[0])
    _link(ng, dist.outputs["Value"], short.inputs[1])
    need = _node(ng, "ShaderNodeMath", 1860, -550, operation='MAXIMUM')
    _link(ng, short.outputs["Value"], need.inputs[0])
    need.inputs[1].default_value = 0.0
    push = _node(ng, "ShaderNodeVectorMath", 2040, -450, operation='SCALE')
    _link(ng, unit.outputs["Vector"], push.inputs[0])
    _link(ng, need.outputs["Value"], push.inputs["Scale"])
    project = _node(ng, "GeometryNodeSetPosition", 2220, 200)
    _link(ng, loose.outputs["Geometry"], project.inputs["Geometry"])
    _link(ng, push.outputs["Vector"], project.inputs["Offset"])

    shade = _node(ng, "GeometryNodeSetShadeSmooth", 2400, 200)
    _link(ng, project.outputs["Geometry"], shade.inputs["Geometry"])
    mat = _node(ng, "GeometryNodeSetMaterial", 2580, 200)
    _link(ng, shade.outputs["Geometry"], mat.inputs["Geometry"])
    _link(ng, gi.outputs["Material"], mat.inputs["Material"])
    # cloth pins: copy the body's pin weights (named by the Pin input) into
    # the garment's Drape_Pin vertex group
    pin_in = _node(ng, "GeometryNodeInputNamedAttribute", 2580, -200, data_type='FLOAT')
    _link(ng, gi.outputs["Pin"], pin_in.inputs["Name"])
    pin = _node(ng, "GeometryNodeStoreNamedAttribute", 2780, 200, data_type='FLOAT', domain='POINT')
    pin.inputs["Name"].default_value = PIN_ATTR
    _link(ng, mat.outputs["Geometry"], pin.inputs["Geometry"])
    _link(ng, pin_in.outputs["Attribute"], pin.inputs["Value"])
    go.location = (2980, 200)
    _link(ng, pin.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def create_garment(body, name, coverage_group, material, collection,
                   offset=0.004, thickness=0.003, resolution=1, border_smooth=4,
                   looseness=15):
    """New garment object driven by ``body``'s ``coverage_group``."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)

    mod = obj.modifiers.new(SHELL_MODIFIER, 'NODES')
    mod.node_group = shell_node_group()
    set_input(mod, "Body", body)
    set_input(mod, "Coverage", coverage_group)
    set_input(mod, "Material", material)
    set_input(mod, "Offset", offset)
    set_input(mod, "Resolution", resolution)
    set_input(mod, "Border Smooth", border_smooth)
    set_input(mod, "Looseness", looseness)

    add_thickness(obj, thickness)
    return obj


def add_thickness(obj, thickness):
    """The cloth-thickness Solidify (always last in the stack)."""
    sol = obj.modifiers.new(THICKNESS_MODIFIER, 'SOLIDIFY')
    sol.thickness = thickness
    sol.offset = 1.0
    sol.use_even_offset = False  # even offset spikes at tight folds (crotch)
    sol.thickness_clamp = 1.0
    sol.use_rim = True
    sol.use_quality_normals = True
    return sol


def upgrade_if_needed():
    """Bring garments made by an older Drape onto the current shell group."""
    ng = bpy.data.node_groups.get(SHELL_GROUP)
    if ng is not None and ng.get("drape_version") != SHELL_VERSION:
        shell_node_group()


def shell_modifier(obj):
    mod = obj.modifiers.get(SHELL_MODIFIER)
    return mod if mod is not None and mod.type == 'NODES' else None


def thickness_modifier(obj):
    mod = obj.modifiers.get(THICKNESS_MODIFIER)
    return mod if mod is not None and mod.type == 'SOLIDIFY' else None
