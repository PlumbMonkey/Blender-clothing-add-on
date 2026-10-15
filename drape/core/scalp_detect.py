"""Heuristic scalp detection (ported from v2, decoupled from UI props).

Functions accept a params object with plain attributes; ScalpDetectParams
provides defaults, but any object with matching attribute names (e.g. a
Blender PropertyGroup) works too.
"""

from dataclasses import dataclass

from mathutils import Vector

from .geometry import (
    compute_head_bounds,
    build_bmesh,
    world_vertex,
    safe_normal_world,
    vertex_curvature_score,
    cleanup_and_fill,
    apply_mask_to_group,
    ensure_vertex_group,
    clear_vertex_group,
)


@dataclass
class ScalpDetectParams:
    # Bone-based detection (preferred path)
    head_weight_threshold: float = 0.25  # min head-bone skin weight to count as head
    hairline_ratio: float = 0.55         # front hairline height within head span (0=chin, 1=crown)
    nape_ratio: float = 0.30             # how far down the back scalp reaches
    forward_axis: tuple = (0.0, -1.0, 0.0)  # facing direction of the character
    # Generic fallback heuristics (no rig available)
    head_upper_fraction: float = 0.35
    scalp_height_ratio: float = 0.40
    min_up_normal: float = -0.05
    min_radial_normal: float = 0.15
    max_forward_normal: float = 0.55
    max_curvature: float = 0.78
    radius_min_ratio: float = 0.35
    radius_max_ratio: float = 1.08
    face_exclusion_ratio: float = 0.08
    side_ear_zone_ratio: float = 0.56
    sideburn_length: float = 0.06
    cleanup_passes: int = 2


def detect_scalp(obj, group_name, params=None, head_bone_name=None):
    """Detect the scalp region of ``obj`` and write it to vertex group
    ``group_name``. Uses head-bone skin weights when ``head_bone_name`` is
    given and present as a vertex group (robust for CC/VRoid full-body
    meshes); otherwise falls back to the generic mesh heuristic.
    Returns the number of selected vertices.
    """
    p = params or ScalpDetectParams()
    if head_bone_name and obj.vertex_groups.get(head_bone_name) is not None:
        return _detect_from_head_bone(obj, group_name, head_bone_name, p)
    return _detect_generic(obj, group_name, p)


def _detect_from_head_bone(obj, group_name, head_bone_name, p):
    vg = obj.vertex_groups[head_bone_name]
    vg_index = vg.index

    # Head verts = skinned to head bone above threshold
    head_idx = set()
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg_index and g.weight >= p.head_weight_threshold:
                head_idx.add(v.index)
                break
    if not head_idx:
        return 0

    bm = build_bmesh(obj)
    fwd = Vector(p.forward_axis).normalized()

    coords = {i: world_vertex(obj, obj.data.vertices[i]) for i in head_idx}
    z0 = min(c.z for c in coords.values())
    z1 = max(c.z for c in coords.values())
    span = max(1e-6, z1 - z0)
    hairline_z = z0 + p.hairline_ratio * span
    nape_z = z0 + p.nape_ratio * span

    adjacency = {}
    for v in bm.verts:
        adjacency[v.index] = [e.other_vert(v).index for e in v.link_edges]

    selected = set()
    for i in head_idx:
        v = bm.verts[i]
        wp = coords[i]
        wn = safe_normal_world(obj, v.normal)
        fwd_dot = wn.dot(fwd)

        above_hairline = wp.z >= hairline_z
        # back/side of skull below the hairline down to the nape
        back_ok = fwd_dot <= 0.05 and wp.z >= nape_z

        if not (above_hairline or back_ok):
            continue
        # drop crinkly geometry (ears) but keep smooth skull
        if vertex_curvature_score(v) > p.max_curvature:
            continue
        selected.add(i)

    bm.free()

    selected = cleanup_and_fill(selected, adjacency, passes=p.cleanup_passes)
    apply_mask_to_group(obj, group_name, selected)
    return len(selected)


def split_scalp_regions(obj, scalp_group_name, region_group_names):
    """Split the scalp vertex group into 5 region groups.

    ``region_group_names`` maps keys 'BANGS','SIDE_L','SIDE_R','BACK','CROWN'
    to vertex group names. Front is assumed -Y. Returns {key: vert_count}.
    """
    scalp_vg = obj.vertex_groups.get(scalp_group_name)
    if scalp_vg is None:
        return {}

    idx_co = {}
    for v in obj.data.vertices:
        try:
            if scalp_vg.weight(v.index) > 0.5:
                idx_co[v.index] = world_vertex(obj, v)
        except RuntimeError:
            pass
    if not idx_co:
        return {}

    xs = [c.x for c in idx_co.values()]
    ys = [c.y for c in idx_co.values()]
    zs = [c.z for c in idx_co.values()]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    z0, z1 = min(zs), max(zs)
    xc = (x0 + x1) / 2.0
    xspan = max(1e-6, x1 - x0)
    yspan = max(1e-6, y1 - y0)
    zspan = max(1e-6, z1 - z0)

    buckets = {k: [] for k in region_group_names}
    for i, c in idx_co.items():
        y_frac = (c.y - y0) / yspan   # 0 = front (-Y), 1 = back
        z_frac = (c.z - z0) / zspan
        x_off = (c.x - xc) / xspan    # -0.5 .. 0.5

        if z_frac >= 0.75:
            key = 'CROWN'
        elif y_frac <= 0.30:
            key = 'BANGS'
        elif y_frac >= 0.62:
            key = 'BACK'
        elif x_off <= 0.0:
            key = 'SIDE_L'
        else:
            key = 'SIDE_R'
        buckets[key].append(i)

    counts = {}
    for key, group_name in region_group_names.items():
        apply_mask_to_group(obj, group_name, buckets.get(key, []))
        counts[key] = len(buckets.get(key, []))
    return counts


def _detect_generic(obj, group_name, p):

    bounds = compute_head_bounds(
        obj,
        head_upper_fraction=p.head_upper_fraction,
        scalp_height_ratio=p.scalp_height_ratio,
    )
    if bounds is None:
        return 0

    bm = build_bmesh(obj)

    x_span = max(1e-6, bounds.max_v.x - bounds.min_v.x)
    ear_x_threshold = x_span * p.side_ear_zone_ratio * 0.5

    adjacency = {}
    selected = set()

    up = Vector((0.0, 0.0, 1.0))
    fwd = Vector((0.0, -1.0, 0.0))

    for v in bm.verts:
        adjacency[v.index] = [e.other_vert(v).index for e in v.link_edges]

    for v in bm.verts:
        wp = world_vertex(obj, v)
        wn = safe_normal_world(obj, v.normal)

        # Height filter with sideburn-dependent extension near ear zones
        x_dist_from_center = abs(wp.x - bounds.center.x)
        in_ear_zone = x_dist_from_center >= ear_x_threshold
        sideburn_drop = p.sideburn_length * (1.0 if in_ear_zone else 0.0)
        local_z_threshold = bounds.z_threshold - sideburn_drop
        height_ok = wp.z >= local_z_threshold

        # Normal filter
        up_dot = wn.dot(up)
        fwd_dot = wn.dot(fwd)
        radial = (wp - bounds.center)
        radial = radial.normalized() if radial.length else Vector((0, 0, 1))
        radial_dot = wn.dot(radial)

        normal_ok = (up_dot >= p.min_up_normal) or (radial_dot >= p.min_radial_normal)
        not_face_forward = fwd_dot <= p.max_forward_normal

        # Curvature filter
        curv = vertex_curvature_score(v)
        curvature_ok = curv <= p.max_curvature

        # Radial band filter
        dist = (wp - bounds.center).length
        rmin = bounds.radius * p.radius_min_ratio
        rmax = bounds.radius * p.radius_max_ratio
        radial_ok = (dist >= rmin) and (dist <= rmax)

        # Face exclusion plane
        face_plane = bounds.center.y - bounds.radius * p.face_exclusion_ratio
        front_ok = wp.y <= face_plane or in_ear_zone

        if height_ok and normal_ok and not_face_forward and curvature_ok and radial_ok and front_ok:
            selected.add(v.index)

    bm.free()

    selected = cleanup_and_fill(selected, adjacency, passes=p.cleanup_passes)
    apply_mask_to_group(obj, group_name, selected)
    return len(selected)


def build_hairline_group(obj, scalp_group_name, group_name, front_band=0.08):
    """Derive a soft hairline weight band at the front of the scalp group."""
    scalp_vg = obj.vertex_groups.get(scalp_group_name)
    if scalp_vg is None:
        return None

    hairline_vg = ensure_vertex_group(obj, group_name)
    clear_vertex_group(obj, hairline_vg)

    coords = []
    scalp_indices = []
    for v in obj.data.vertices:
        try:
            w = scalp_vg.weight(v.index)
            if w > 0.5:
                p = world_vertex(obj, v)
                coords.append(p)
                scalp_indices.append(v.index)
        except RuntimeError:
            pass

    if not coords:
        return hairline_vg

    y_min = min(p.y for p in coords)
    y_max = max(p.y for p in coords)
    band = (y_max - y_min) * max(0.02, front_band)
    threshold = y_min + band

    x_vals = [p.x for p in coords]
    x_min, x_max = min(x_vals), max(x_vals)
    x_span = max(1e-6, x_max - x_min)

    for idx in scalp_indices:
        p = world_vertex(obj, obj.data.vertices[idx])
        if p.y <= threshold:
            t = (p.x - x_min) / x_span
            arc = 1.0 - (2.0 * t - 1.0) ** 2
            w = max(0.0, min(1.0, 0.4 + 0.6 * arc))
            hairline_vg.add([idx], w, 'REPLACE')

    return hairline_vg
