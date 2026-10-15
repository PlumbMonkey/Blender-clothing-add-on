"""Garment coverage: which part of the body a garment covers.

Coverage is a 0..1 vertex group on the body (``DRAPE_COV_<name>``) that the
garment shell reads live, so the user can repaint it and watch the garment
follow. Templates fill it from the Phase 1 regions plus a few lengths:

- limb lengths are measured along the bones (0 = shoulder/hip joint,
  1 = elbow/knee, 2 = wrist/ankle), so they fit any body;
- shirt hems are measured down the hips region (0 = waist, 1 = crotch).
"""

from dataclasses import dataclass

from mathutils import Vector

from .body_regions import (
    PARTS, REGIONS, PART_ATTR, REGION_ATTR, classify_bones, _read_int_attr,
)
from .geometry import ensure_vertex_group, clear_vertex_group


@dataclass
class CoverageParams:
    sleeve_length: float = 0.45  # 0 sleeveless … 1 elbow … 2 wrist
    body_length: float = 0.35    # shirt hem: 0 waist … 1 crotch
    leg_length: float = 0.45     # 0 hip … 1 knee … 2 ankle
    rise: float = 0.0            # how far trousers come up the torso (0 … 1)
    sock_height: float = 0.35    # 0 ankle … 1 knee


TEMPLATES = {
    'TSHIRT': "T-Shirt",
    'TANK': "Tank Top",
    'LONGSLEEVE': "Long Sleeve",
    'SHORTS': "Shorts",
    'PANTS': "Pants",
    'SOCKS': "Socks",
}

# Coverage fades from 1 to 0 over this distance (metres) across the garment's
# edge, so the 0.5 line sits exactly on the cut (a plane along a limb, a hem
# height) and interpolates cleanly across long triangles, instead of
# snapping to whichever vertices happen to be nearest.
EDGE_FADE = 0.03
_INSIDE = 1.0  # region fully inside the garment

# Defaults each template starts from (anything not listed keeps CoverageParams).
TEMPLATE_DEFAULTS = {
    'TSHIRT': {'sleeve_length': 0.45, 'body_length': 0.35},
    'TANK': {'sleeve_length': 0.0, 'body_length': 0.35},
    'LONGSLEEVE': {'sleeve_length': 1.95, 'body_length': 0.4},
    'SHORTS': {'leg_length': 0.45, 'rise': 0.0},
    'PANTS': {'leg_length': 1.95, 'rise': 0.0},
    'SOCKS': {'sock_height': 0.35},
}

# Fit and look each template starts with (offset/thickness in metres).
TEMPLATE_FIT = {
    'TSHIRT': {'offset': 0.008, 'thickness': 0.003, 'looseness': 15, 'color': (0.10, 0.25, 0.60)},
    'TANK': {'offset': 0.007, 'thickness': 0.0025, 'looseness': 12, 'color': (0.85, 0.85, 0.82)},
    'LONGSLEEVE': {'offset': 0.008, 'thickness': 0.003, 'looseness': 15, 'color': (0.55, 0.12, 0.12)},
    'SHORTS': {'offset': 0.004, 'thickness': 0.003, 'looseness': 30, 'color': (0.12, 0.12, 0.14)},
    'PANTS': {'offset': 0.004, 'thickness': 0.003, 'looseness': 30, 'color': (0.10, 0.16, 0.30)},
    'SOCKS': {'offset': 0.0015, 'thickness': 0.0015, 'looseness': 3, 'color': (0.9, 0.9, 0.9)},
}

# Which sliders matter for which template (the panel shows only these).
TEMPLATE_PARAMS = {
    'TSHIRT': ('sleeve_length', 'body_length'),
    'TANK': ('body_length',),
    'LONGSLEEVE': ('sleeve_length', 'body_length'),
    'SHORTS': ('leg_length', 'rise'),
    'PANTS': ('leg_length', 'rise'),
    'SOCKS': ('sock_height',),
}

# Each limb part is measured from its own joint to the next one down.
_LIMB_NEXT = {
    'UPPERARM': 'FOREARM', 'FOREARM': 'HAND',
    'THIGH': 'CALF', 'CALF': 'FOOT',
}


def coverage_group_name(name):
    return f"DRAPE_COV_{name}"


def limb_segments(armature):
    """{part: (start, end)} in world space (rest pose) for every limb part,
    from the part's root bone head to the next part's root bone head."""
    parts = classify_bones(armature)
    roots = {}
    for b in armature.data.bones:
        p = parts.get(b.name)
        if p is None:
            continue
        if b.parent is None or parts.get(b.parent.name) != p:
            roots.setdefault(p, b)
    mw = armature.matrix_world
    segs = {}
    for part, bone in roots.items():
        role, _, side = part.partition('_')
        nxt = _LIMB_NEXT.get(role)
        if nxt is None:
            continue
        child = roots.get(f"{nxt}_{side}")
        if child is None:
            continue
        segs[part] = (mw @ bone.head_local, mw @ child.head_local)
    return segs


def _t_along(p, seg):
    a, b = seg
    d = b - a
    n2 = d.length_squared
    return 0.0 if n2 == 0.0 else max(0.0, min(1.0, (p - a).dot(d) / n2))


def compute_coverage(body, armature, template, params):
    """Per-vertex 0/1 coverage list for ``template`` on ``body``."""
    regions = _read_int_attr(body.data, REGION_ATTR)
    parts = _read_int_attr(body.data, PART_ATTR)
    if regions is None or parts is None:
        raise RuntimeError("Set Up Body first")
    mw = body.matrix_world
    world = [mw @ v.co for v in body.data.vertices]
    segs = limb_segments(armature)

    def region_z(name):
        idx = REGIONS.index(name)
        zs = [world[i].z for i, r in enumerate(regions) if r == idx]
        return (min(zs), max(zs)) if zs else (0.0, 0.0)

    hips_lo, hips_hi = region_z('HIPS')
    torso_lo, torso_hi = region_z('TORSO')
    hip_span = max(1e-6, hips_hi - hips_lo)

    def limb_margin(i, part, length, upper, lower):
        """Signed metres from the cut to the vertex along the limb (> 0 =
        covered); ``length`` runs 0..1 over the upper part, 1..2 the lower."""
        role = part.partition('_')[0]
        seg = segs.get(part)
        if seg is None or role not in (upper, lower):
            return None
        cut = length if role == upper else length - 1.0
        return (cut - _t_along(world[i], seg)) * (seg[1] - seg[0]).length

    p = params
    cov = [0.0] * len(world)
    for i, (r, pi) in enumerate(zip(regions, parts)):
        region, part = REGIONS[r], PARTS[pi]
        z = world[i].z
        margin = None  # signed metres inside the garment's edge; None = not covered
        if template in ('TSHIRT', 'TANK', 'LONGSLEEVE'):
            if region == 'TORSO':
                margin = _INSIDE
            elif region == 'HIPS':
                margin = z - (hips_hi - p.body_length * hip_span)
            elif region == 'ARMS':
                margin = limb_margin(i, part, p.sleeve_length, 'UPPERARM', 'FOREARM')
        elif template in ('SHORTS', 'PANTS'):
            if region == 'HIPS':
                margin = _INSIDE
            elif region == 'TORSO':
                margin = torso_lo + p.rise * (torso_hi - torso_lo) - z
            elif region == 'LEGS':
                margin = limb_margin(i, part, p.leg_length, 'THIGH', 'CALF')
        elif template == 'SOCKS':
            if region == 'FEET':
                margin = _INSIDE
            elif part.startswith('CALF'):
                seg = segs.get(part)
                if seg is not None:
                    margin = (_t_along(world[i], seg) - (1.0 - p.sock_height)) * (seg[1] - seg[0]).length
        if margin is not None:
            cov[i] = max(0.0, min(1.0, 0.5 + margin / EDGE_FADE))
    return cov


def write_coverage(body, group_name, coverage):
    """Write a coverage list into the body's coverage vertex group.
    Returns how many vertices are covered (weight ≥ 0.5)."""
    vg = ensure_vertex_group(body, group_name)
    clear_vertex_group(body, vg)
    full = [i for i, w in enumerate(coverage) if w >= 1.0]
    if full:
        vg.add(full, 1.0, 'REPLACE')
    for i, w in enumerate(coverage):
        if 0.0 < w < 1.0:
            vg.add([i], w, 'REPLACE')
    return sum(1 for w in coverage if w >= 0.5)
