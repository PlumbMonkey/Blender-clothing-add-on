"""Geometry and mesh utility helpers (ported from v2, decoupled from props)."""

import math
from dataclasses import dataclass

import bmesh
from mathutils import Vector


@dataclass
class HeadBounds:
    min_v: Vector
    max_v: Vector
    center: Vector
    radius: float
    z_threshold: float
    z_min: float
    z_max: float


def world_vertex(obj, v):
    return obj.matrix_world @ v.co


def safe_normal_world(obj, normal):
    n = obj.matrix_world.to_3x3() @ normal
    if n.length == 0:
        return Vector((0.0, 0.0, 1.0))
    return n.normalized()


def compute_head_bounds(obj, head_upper_fraction=0.35, scalp_height_ratio=0.40):
    """Estimate head bounds from a (possibly full-body) mesh.

    Takes explicit params rather than a props object so core stays
    UI-independent.
    """
    world_coords = [world_vertex(obj, v) for v in obj.data.vertices]
    if not world_coords:
        return None

    min_v = Vector((
        min(p.x for p in world_coords),
        min(p.y for p in world_coords),
        min(p.z for p in world_coords),
    ))
    max_v = Vector((
        max(p.x for p in world_coords),
        max(p.y for p in world_coords),
        max(p.z for p in world_coords),
    ))

    total_height = max(1e-6, max_v.z - min_v.z)
    z_min = max_v.z - total_height * head_upper_fraction
    z_max = max_v.z

    head_points = [p for p in world_coords if p.z >= z_min]
    if not head_points:
        head_points = world_coords

    center = sum(head_points, Vector((0.0, 0.0, 0.0))) / len(head_points)
    radius = sum((p - center).length for p in head_points) / len(head_points)
    radius = max(radius, total_height * 0.08)

    head_height = max(1e-6, z_max - z_min)
    z_threshold = z_min + head_height * scalp_height_ratio

    return HeadBounds(
        min_v=min_v,
        max_v=max_v,
        center=center,
        radius=radius,
        z_threshold=z_threshold,
        z_min=z_min,
        z_max=z_max,
    )


def build_bmesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def vertex_curvature_score(v):
    """Approximate local curvature via average neighboring normal-angle."""
    if not v.link_edges:
        return 0.0
    n0 = v.normal.normalized() if v.normal.length else Vector((0, 0, 1))
    acc = 0.0
    count = 0
    for e in v.link_edges:
        ov = e.other_vert(v)
        n1 = ov.normal.normalized() if ov.normal.length else Vector((0, 0, 1))
        d = max(-1.0, min(1.0, n0.dot(n1)))
        acc += math.acos(d)
        count += 1
    return acc / max(1, count)


def connected_components(indices_set, adjacency):
    visited = set()
    comps = []
    for start in indices_set:
        if start in visited:
            continue
        stack = [start]
        comp = set()
        visited.add(start)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for nb in adjacency.get(cur, []):
                if nb in indices_set and nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def cleanup_and_fill(mask_indices, adjacency, passes=2):
    """Keep the largest connected region, then fill small holes."""
    if not mask_indices:
        return set()

    selected = set(mask_indices)

    comps = connected_components(selected, adjacency)
    if comps:
        selected = max(comps, key=len)

    for _ in range(max(0, passes)):
        to_add = set()
        for vidx, nbs in adjacency.items():
            if vidx in selected:
                continue
            if not nbs:
                continue
            hit = sum(1 for n in nbs if n in selected)
            if hit >= 4 and hit >= int(0.6 * len(nbs)):
                to_add.add(vidx)
        selected |= to_add

    return selected


def ensure_vertex_group(obj, name):
    vg = obj.vertex_groups.get(name)
    if vg is None:
        vg = obj.vertex_groups.new(name=name)
    return vg


def clear_vertex_group(obj, vg):
    all_indices = [v.index for v in obj.data.vertices]
    if all_indices:
        vg.remove(all_indices)


def apply_mask_to_group(obj, group_name, selected_indices):
    vg = ensure_vertex_group(obj, group_name)
    clear_vertex_group(obj, vg)
    if selected_indices:
        vg.add(list(selected_indices), 1.0, 'REPLACE')
