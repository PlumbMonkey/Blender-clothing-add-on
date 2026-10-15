"""Skirt: a real mesh, not a body shell.

A shell that follows the body would split between the legs, so a skirt is
built as an A-line tube: its waist ring hugs the body, it flares out as it
goes down, and every ring is pushed clear of the body (hips, buttocks,
thighs) so the cloth simulation starts outside the body. The skirt is
parented to the pelvis bone, so it follows the hips; cloth simulation then
lets the lower part drape and swing.
"""

import math
from dataclasses import dataclass

import bmesh
import numpy as np
from mathutils import Matrix

from .body_regions import REGIONS, REGION_ATTR, _read_int_attr
from .coverage import part_roots

PIN_GROUP = "Drape_Pin"
_AROUND = 64          # vertices around the skirt
_ROW_GAP = 0.02       # metres between rings
_CLEARANCE = 0.012    # extra gap kept from the body below the waist (m)
_SECTOR = 1.6         # angular width of a body sample, in ring steps


@dataclass
class SkirtParams:
    length: float = 0.7    # 0 at the hip joint … 1 knee … 2 ankle
    flare: float = 0.35    # extra radius per metre of drop
    waist: float = 0.2     # waistband height: 0 top of the hips … 1 crotch
    offset: float = 0.006  # gap at the waistband (m)


def _world_coords(body, depsgraph):
    """Body vertices in world space as posed now (evaluated, armature on)."""
    ev = body.evaluated_get(depsgraph)
    me = ev.data
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(ev.matrix_world, dtype=np.float64)
    return co @ mw[:3, :3].T + mw[:3, 3]


def pelvis_bone(armature):
    roots = part_roots(armature)
    bone = roots.get('PELVIS')
    return bone.name if bone else None


def _joint_z(armature, part):
    bone = part_roots(armature).get(part)
    if bone is None:
        return None
    return (armature.matrix_world @ bone.head_local).z


def build_skirt(body, armature, params, depsgraph, under=None):
    """(verts, faces, pin weights) of an A-line skirt in world space.
    ``under``: world points (N×3) of garments worn beneath, which the skirt
    must clear as well as the body."""
    regions = _read_int_attr(body.data, REGION_ATTR)
    if regions is None:
        raise RuntimeError("Set Up Body first")
    regions = np.array(regions)
    world = _world_coords(body, depsgraph)
    if len(world) != len(regions):
        raise RuntimeError("The body's vertex count changed since Set Up Body")

    hips = world[regions == REGIONS.index('HIPS')]
    if len(hips) == 0:
        raise RuntimeError("No hips region on this body")
    hips_hi, hips_lo = hips[:, 2].max(), hips[:, 2].min()
    cx, cy = hips[:, 0].mean(), hips[:, 1].mean()
    waist_z = hips_hi - params.waist * (hips_hi - hips_lo)

    # hem height along the leg: 0 hip joint, 1 knee, 2 ankle (both legs averaged)
    def avg_z(role):
        zs = [z for z in (_joint_z(armature, f"{role}_{s}") for s in "LR") if z is not None]
        return sum(zs) / len(zs) if zs else None
    hip_z, knee_z, ankle_z = avg_z('THIGH'), avg_z('CALF'), avg_z('FOOT')
    if None in (hip_z, knee_z, ankle_z):
        raise RuntimeError("Couldn't find the leg joints on this rig")
    L = max(0.0, min(2.0, params.length))
    hem_z = hip_z + (knee_z - hip_z) * L if L <= 1.0 else knee_z + (ankle_z - knee_z) * (L - 1.0)
    hem_z = min(hem_z, waist_z - 0.1)

    rows = max(6, int(round((waist_z - hem_z) / _ROW_GAP)) + 1)
    zs = np.linspace(waist_z, hem_z, rows)

    # the body's outline around the skirt axis, per ring height and angle
    # (arms and hands excluded: they hang beside the hips in an A-pose)
    keep = ~np.isin(regions, [REGIONS.index(r) for r in ('ARMS', 'HANDS', 'HEAD', 'NECK')])
    pts = world[keep]
    if under is not None and len(under):
        # lower garments, minus their sleeves (anything out past the hips)
        reach = np.hypot(hips[:, 0] - cx, hips[:, 1] - cy).max() * 1.6
        near = np.hypot(under[:, 0] - cx, under[:, 1] - cy) < reach
        pts = np.concatenate([pts, under[near]])
    ang = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
    rad = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    thetas = np.linspace(0.0, 2 * math.pi, _AROUND, endpoint=False)
    half = math.pi / _AROUND * _SECTOR
    radius = np.zeros((rows, _AROUND))
    for r, z in enumerate(zs):
        band = np.abs(pts[:, 2] - z) < _ROW_GAP
        a, d = ang[band], rad[band]
        for k, t in enumerate(thetas):
            diff = np.abs((a - t + math.pi) % (2 * math.pi) - math.pi)
            hit = d[diff < half]
            radius[r, k] = hit.max() if len(hit) else 0.0
    # rings with no body nearby (between the legs low down) borrow from above
    for r in range(1, rows):
        radius[r] = np.where(radius[r] > 0, radius[r], radius[r - 1])

    # A-line: waist ring + flare, never inside the body, never narrowing
    drop = waist_z - zs
    cone = radius[0][None, :] + params.offset + params.flare * drop[:, None]
    clear = radius + params.offset + np.where(drop[:, None] > 0.03, _CLEARANCE, 0.0)
    shape = np.maximum(cone, clear)
    shape = np.maximum.accumulate(shape, axis=0)
    for _ in range(3):  # round off sector noise around each ring
        shape = (np.roll(shape, 1, axis=1) + 2 * shape + np.roll(shape, -1, axis=1)) / 4

    verts = []
    for r, z in enumerate(zs):
        for k, t in enumerate(thetas):
            verts.append((cx + shape[r, k] * math.cos(t), cy + shape[r, k] * math.sin(t), z))
    faces = []
    for r in range(rows - 1):
        for k in range(_AROUND):
            a, b = r * _AROUND + k, r * _AROUND + (k + 1) % _AROUND
            faces.append((a, a + _AROUND, b + _AROUND, b))  # normals face out
    pins = [1.0 if r < 2 else (0.5 if r == 2 else 0.0) for r in range(rows) for _ in range(_AROUND)]
    return verts, faces, pins


def write_skirt_mesh(obj, verts, faces, pins):
    """Replace the skirt object's mesh (keeps the object, its parent and modifiers)."""
    me = obj.data
    if me.shape_keys is not None:
        obj.shape_key_clear()
    bm = bmesh.new()
    bverts = [bm.verts.new(v) for v in verts]
    for f in faces:
        bm.faces.new([bverts[i] for i in f])
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    # mesh coords are world: undo the bone-parent transform
    me.transform(obj.matrix_world.inverted())
    vg = obj.vertex_groups.get(PIN_GROUP) or obj.vertex_groups.new(name=PIN_GROUP)
    vg.remove(list(range(len(verts))))
    for i, w in enumerate(pins):
        if w > 0:
            vg.add([i], w, 'REPLACE')
    me.update()


def parent_to_bone(obj, armature, bone_name):
    """Bone-parent ``obj`` so it follows the bone, keeping its world placement."""
    pb = armature.pose.bones[bone_name]
    tail = armature.matrix_world @ pb.matrix @ Matrix.Translation((0.0, pb.bone.length, 0.0))
    obj.parent = armature
    obj.parent_type = 'BONE'
    obj.parent_bone = bone_name
    obj.matrix_parent_inverse = tail.inverted()
    obj.matrix_basis = Matrix.Identity(4)
