"""Rig/pipeline detection: find the armature, head bone, and source pipeline."""


def find_armature(obj):
    """Armature driving ``obj`` via modifier or parenting, or None."""
    for m in obj.modifiers:
        if m.type == 'ARMATURE' and m.object:
            return m.object
    p = obj.parent
    while p:
        if p.type == 'ARMATURE':
            return p
        p = p.parent
    return None


def detect_pipeline(armature):
    """'CC' (Character Creator), 'VROID', or 'GENERIC' from bone naming."""
    if armature is None:
        return 'GENERIC'
    names = {b.name.lower() for b in armature.data.bones}
    if any(n.startswith("cc_base_") for n in names):
        return 'CC'
    if any(n.startswith("j_bip_") for n in names):
        return 'VROID'
    return 'GENERIC'


PREFERRED_HEAD_BONES = ("cc_base_head", "j_bip_c_head", "head")


def find_head_bone(armature):
    """Best-guess head bone name, or None."""
    if armature is None:
        return None
    by_lower = {b.name.lower(): b.name for b in armature.data.bones}
    for pref in PREFERRED_HEAD_BONES:
        if pref in by_lower:
            return by_lower[pref]
    candidates = [n for n in by_lower if "head" in n]
    if candidates:
        # shortest name is usually the actual head, not e.g. "HeadTop_End"
        return by_lower[min(candidates, key=len)]
    return None


def find_body_mesh(armature, pipeline):
    """The mesh most likely to contain the scalp skin for this pipeline."""
    if armature is None:
        return None
    meshes = [o for o in armature.children_recursive if o.type == 'MESH']
    preferred = {
        'CC': ("cc_base_body",),
        'VROID': ("body",),
    }.get(pipeline, ())
    for name in preferred:
        for o in meshes:
            if o.name.lower().startswith(name):
                return o
    # generic fallback: mesh with the most vertices
    return max(meshes, key=lambda o: len(o.data.vertices), default=None)


EYE_BONE_HINTS = ("cc_base_l_eye", "cc_base_r_eye", "j_adj_l_faceeye", "j_adj_r_faceeye",
                  "lefteye", "righteye", "eye.l", "eye.r", "eye_l", "eye_r")


def find_eye_z(armature):
    """World-space height of the eyes from eye bones, or None."""
    if armature is None:
        return None
    zs = []
    for pb in armature.pose.bones:
        if pb.name.lower() in EYE_BONE_HINTS:
            zs.append((armature.matrix_world @ pb.head).z)
    return sum(zs) / len(zs) if zs else None
