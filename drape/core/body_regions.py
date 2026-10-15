"""Body part and garment-region detection from skin weights.

Every deform bone gets a body *part* (upper arm L, calf R, torso, ...):
the main bones are recognised by name, and every other bone (twist, share,
finger, toe, physics and adjustment bones) inherits the part of its nearest
recognised ancestor. Each vertex then goes to the part holding the most of
its skin weight. Parts roll up into coarse *regions* (torso, arms, legs, ...)
that garments are built from and that the user can repaint.

Works on Character Creator (CC_Base_*), VRoid (J_Bip_* / J_Sec_* / J_Adj_*),
Mixamo (mixamorig:*) and Rigify (DEF-*) naming. Weight-based, so it is
non-destructive on rigged meshes: it only reads vertex groups, and writes
an integer point attribute plus one vertex group per region.
"""

import re

from .geometry import ensure_vertex_group, clear_vertex_group

# --- parts ------------------------------------------------------------------

PARTS = (
    'NONE', 'HEAD', 'NECK', 'TORSO', 'PELVIS',
    'UPPERARM_L', 'UPPERARM_R', 'FOREARM_L', 'FOREARM_R', 'HAND_L', 'HAND_R',
    'THIGH_L', 'THIGH_R', 'CALF_L', 'CALF_R', 'FOOT_L', 'FOOT_R',
)
PART_INDEX = {p: i for i, p in enumerate(PARTS)}

# Checked in order against the bone's core name (side and rig prefixes
# stripped, e.g. "J_Bip_L_LowerArm" -> "lowerarm"). Order matters:
# "forearm" before "arm", "upperleg" before "leg".
_ROLE_KEYWORDS = (
    ('HAND', ('hand',)),
    ('FOREARM', ('forearm', 'lowerarm', 'elbow')),
    ('UPPERARM', ('upperarm', 'uparm')),
    ('FOOT', ('foot', 'toe')),
    ('CALF', ('calf', 'lowerleg', 'shin', 'knee')),
    ('THIGH', ('thigh', 'upperleg', 'upleg')),
    ('TORSO', ('clavicle', 'shoulder', 'spine', 'chest', 'waist', 'breast',
               'ribs', 'torso', 'abdomen')),
    ('HEAD', ('head',)),
    ('NECK', ('neck',)),
    ('PELVIS', ('pelvis', 'hip')),
)
# Whole-name matches for rigs that call the upper arm "arm" and the calf "leg"
# (Mixamo: LeftArm / LeftForeArm, LeftUpLeg / LeftLeg; Rigify: upper_arm.L).
_ROLE_EXACT = {'arm': 'UPPERARM', 'leg': 'CALF'}

_SIDED = {'HAND', 'FOREARM', 'UPPERARM', 'FOOT', 'CALF', 'THIGH'}
_PREFIXES = ('cc_base_', 'j_bip_', 'j_adj_', 'j_sec_', 'mixamorig:', 'def-', 'org-')
_SIDE_TOKENS = {'l': 'L', 'left': 'L', 'r': 'R', 'right': 'R'}


def _core_name(bone_name):
    """(core, side) from a bone name: side is 'L', 'R' or None."""
    n = bone_name.lower()
    for pre in _PREFIXES:
        if n.startswith(pre):
            n = n[len(pre):]
    side = None
    kept = []
    for tok in re.split(r'[_.\-: ]+', n):
        if not tok:
            continue
        if tok in _SIDE_TOKENS:
            side = _SIDE_TOKENS[tok]
            continue
        if tok == 'c':  # VRoid centre marker
            continue
        for word, s in (('left', 'L'), ('right', 'R')):
            if tok.startswith(word) and len(tok) > len(word):
                side, tok = s, tok[len(word):]
        kept.append(tok)
    return ''.join(kept), side


def _role_of(core):
    stem = re.sub(r'\d+$', '', core)
    if stem in _ROLE_EXACT:
        return _ROLE_EXACT[stem]
    for role, words in _ROLE_KEYWORDS:
        if any(w in core for w in words):
            return role
    return None


def classify_bones(armature):
    """{bone name: part} for every bone of ``armature`` that maps to a part."""
    own = {}
    for b in armature.data.bones:
        core, side = _core_name(b.name)
        role = _role_of(core)
        if role is None:
            continue
        if role in _SIDED:
            if side is None:  # unnamed side: fall back to rest position (+X = left)
                x = b.head_local.x
                side = 'L' if x > 0 else 'R'
            own[b.name] = f"{role}_{side}"
        else:
            own[b.name] = role

    def nearest_own(bone):
        while bone is not None and bone.name not in own:
            bone = bone.parent
        return bone

    parts = {}
    for b in armature.data.bones:
        p = nearest_own(b)
        if p is None:
            continue
        part = own[p.name]
        # A bone continuing its parent's limb keeps the parent's side: the
        # hierarchy beats the name (VRoid ships a J_Sec_R_* bone under the
        # left thigh).
        up = nearest_own(p.parent)
        if up is not None and own[up.name].split('_')[0] == part.split('_')[0]:
            part = parts.get(up.name, own[up.name])
        parts[b.name] = part
    return parts


# --- regions ----------------------------------------------------------------

REGIONS = ('NONE', 'HEAD', 'NECK', 'TORSO', 'HIPS', 'ARMS', 'HANDS', 'LEGS', 'FEET')
REGION_INDEX = {r: i for i, r in enumerate(REGIONS)}

PART_REGION = {
    'NONE': 'NONE', 'HEAD': 'HEAD', 'NECK': 'NECK', 'TORSO': 'TORSO', 'PELVIS': 'HIPS',
    'UPPERARM_L': 'ARMS', 'UPPERARM_R': 'ARMS', 'FOREARM_L': 'ARMS', 'FOREARM_R': 'ARMS',
    'HAND_L': 'HANDS', 'HAND_R': 'HANDS',
    'THIGH_L': 'LEGS', 'THIGH_R': 'LEGS', 'CALF_L': 'LEGS', 'CALF_R': 'LEGS',
    'FOOT_L': 'FEET', 'FOOT_R': 'FEET',
}

REGION_COLORS = {
    'NONE': (1.0, 0.0, 1.0),
    'HEAD': (0.92, 0.78, 0.62),
    'NECK': (0.95, 0.55, 0.25),
    'TORSO': (0.20, 0.50, 0.92),
    'HIPS': (0.58, 0.30, 0.82),
    'ARMS': (0.22, 0.75, 0.42),
    'HANDS': (0.92, 0.85, 0.20),
    'LEGS': (0.85, 0.25, 0.25),
    'FEET': (0.30, 0.30, 0.32),
}

PART_ATTR = "drape_part"
REGION_ATTR = "drape_region"
PREVIEW_ATTR = "Drape Regions"


def region_group_name(region):
    return f"DRAPE_REGION_{region}"


def _part_scores(obj, group_parts):
    """Per vertex: {part: summed skin weight}."""
    scores = []
    for v in obj.data.vertices:
        acc = {}
        for g in v.groups:
            part = group_parts.get(g.group)
            if part is not None and g.weight > 0.0:
                acc[part] = acc.get(part, 0.0) + g.weight
        scores.append(acc)
    return scores


def _group_parts(obj, armature):
    """{vertex group index: part} for the groups named after classified bones."""
    bone_parts = classify_bones(armature)
    return {vg.index: bone_parts[vg.name] for vg in obj.vertex_groups if vg.name in bone_parts}


def _write_int_attr(mesh, name, values):
    attr = mesh.attributes.get(name)
    if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'INT'):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(name, 'INT', 'POINT')
    attr.data.foreach_set("value", values)


def _read_int_attr(mesh, name):
    attr = mesh.attributes.get(name)
    if attr is None:
        return None
    values = [0] * len(mesh.vertices)
    attr.data.foreach_get("value", values)
    return values


def write_regions(obj, regions):
    """Store region indices and mirror them into one vertex group per region."""
    _write_int_attr(obj.data, REGION_ATTR, regions)
    members = {r: [] for r in REGIONS if r != 'NONE'}
    for i, r in enumerate(regions):
        name = REGIONS[r]
        if name != 'NONE':
            members[name].append(i)
    counts = {}
    for name, idx in members.items():
        vg = ensure_vertex_group(obj, region_group_name(name))
        clear_vertex_group(obj, vg)
        if idx:
            vg.add(idx, 1.0, 'REPLACE')
        counts[name] = len(idx)
    write_preview_colors(obj, regions)
    return counts


def write_preview_colors(obj, regions):
    """Colour attribute for viewing the regions (Solid shading → Attribute)."""
    mesh = obj.data
    attr = mesh.color_attributes.get(PREVIEW_ATTR)
    if attr is None:
        attr = mesh.color_attributes.new(PREVIEW_ATTR, 'FLOAT_COLOR', 'POINT')
    flat = []
    for r in regions:
        flat.extend((*REGION_COLORS[REGIONS[r]], 1.0))
    attr.data.foreach_set("color", flat)


def detect_regions(obj, armature):
    """Assign every vertex of ``obj`` a part and a region from its skin weights.

    Returns {region: vertex count}. Vertices with no classified weight (or
    meshes with no armature) land in NONE.
    """
    if armature is None:
        return {}
    scores = _part_scores(obj, _group_parts(obj, armature))
    parts = [PART_INDEX[max(s, key=s.get)] if s else 0 for s in scores]
    regions = [REGION_INDEX[PART_REGION[PARTS[p]]] for p in parts]
    _write_int_attr(obj.data, PART_ATTR, parts)
    write_seam_fields(obj, regions)
    return write_regions(obj, regions)


SIDE_ATTR = "drape_side"      # < 0 front, > 0 back: its 0 line = side and shoulder seams
CENTER_ATTR = "drape_center"  # < 0 / > 0 either side of the middle: front placket
ARM_ATTR = "drape_arm"        # 1 on arms and hands: its 0.5 line = armhole seams


def _write_float_attr(mesh, name, values):
    attr = mesh.attributes.get(name)
    if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'FLOAT'):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(name, 'FLOAT', 'POINT')
    attr.data.foreach_set("value", values)


def write_seam_fields(obj, regions):
    """Fields whose 0 / 0.5 lines are where garments have seams. They ride
    on the body mesh, so they follow it through the garment shells."""
    mw = obj.matrix_world
    world = [mw @ v.co for v in obj.data.vertices]
    core = {REGION_INDEX['TORSO'], REGION_INDEX['HIPS']}
    trunk = [world[i] for i, r in enumerate(regions) if r in core] or world
    cx = sum(p.x for p in trunk) / len(trunk)
    cy = sum(p.y for p in trunk) / len(trunk)
    arm = {REGION_INDEX['ARMS'], REGION_INDEX['HANDS']}
    # characters face -Y (CC, VRoid, Mixamo, Rigify all import that way)
    _write_float_attr(obj.data, SIDE_ATTR, [p.y - cy for p in world])
    _write_float_attr(obj.data, CENTER_ATTR, [p.x - cx for p in world])
    _write_float_attr(obj.data, ARM_ATTR, [1.0 if r in arm else 0.0 for r in regions])


def apply_painted_region(obj, armature, region, threshold=0.5):
    """Fold a repainted region group back into the exclusive region map.

    Painted-in vertices (weight ≥ threshold) join ``region`` and leave
    their old one; vertices erased from it fall back to the best other
    region by skin weight. Returns {region: vertex count}.
    """
    current = _read_int_attr(obj.data, REGION_ATTR)
    vg = obj.vertex_groups.get(region_group_name(region))
    if current is None or vg is None:
        return {}
    target = REGION_INDEX[region]
    gi = vg.index
    painted = [0.0] * len(obj.data.vertices)
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                painted[v.index] = g.weight
                break

    scores = None
    orphans = []
    for i, w in enumerate(painted):
        if w >= threshold:
            current[i] = target
        elif current[i] == target:
            if scores is None:
                scores = _part_scores(obj, _group_parts(obj, armature)) if armature else []
            by_region = {}
            for part, s in (scores[i].items() if scores else ()):
                reg = PART_REGION[part]
                if reg != region:
                    by_region[reg] = by_region.get(reg, 0.0) + s
            if by_region:
                current[i] = REGION_INDEX[max(by_region, key=by_region.get)]
            else:
                current[i] = 0
                orphans.append(i)
    if orphans:
        _adopt_from_neighbours(obj, current, orphans, exclude=target)
    return write_regions(obj, current)


def _adopt_from_neighbours(obj, regions, orphans, exclude):
    """Give erased vertices that only had weight on the erased region the most
    common region among their mesh neighbours, growing inward from the edge."""
    adj = {i: [] for i in orphans}
    for e in obj.data.edges:
        a, b = e.vertices
        if a in adj:
            adj[a].append(b)
        if b in adj:
            adj[b].append(a)
    pending = set(orphans)
    while pending:
        settled = {}
        for i in pending:
            votes = {}
            for n in adj[i]:
                r = regions[n]
                if r not in (0, exclude):
                    votes[r] = votes.get(r, 0) + 1
            if votes:
                settled[i] = max(votes, key=votes.get)
        if not settled:  # an island with no other region around it
            break
        for i, r in settled.items():
            regions[i] = r
        pending -= settled.keys()
