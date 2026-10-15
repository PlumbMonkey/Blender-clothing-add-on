"""Motion transfer — put an animation from another armature (e.g. an iClone
FBX export) onto the character's own armature.

Bones are matched by name. Each bone is driven through its *rest-pose
offset* rather than by copying local channels, so it works even when the
source's bones are oriented differently (different FBX import options,
roll conventions): at every frame

    target_world = source_world @ (source_rest_world⁻¹ @ target_rest_world)

(or, if the two rest poses differ, target_world = source_world), and the result is converted back into the target's local pose channels by
pure matrix math (no per-bone depsgraph updates), then keyed.
"""

from mathutils import Matrix


def _rest_world(arm, bone):
    return arm.matrix_world @ bone.matrix_local


def matching_bones(source, target):
    """Target bone names that also exist in the source, parents first."""
    names = set(source.data.bones.keys())
    ordered = []

    def walk(b):
        if b.name in names:
            ordered.append(b.name)
        for c in b.children:
            walk(c)

    for b in target.data.bones:
        if b.parent is None:
            walk(b)
    return ordered


def rest_offsets(source, target, names, tolerance=0.01):
    """({bone: offset}, mode). When both rigs share a rest pose (joints within
    ``tolerance`` metres) the offsets absorb any difference in bone axes. If
    the rests differ (e.g. an FBX whose bind pose is a posed frame) they can't
    be compared, so the bones' world orientation is copied as is — exact for
    the same character exported with the same bone axes."""
    gap = max((( _rest_world(source, source.data.bones[n]).translation
                - _rest_world(target, target.data.bones[n]).translation).length for n in names),
              default=0.0)
    if gap > tolerance:
        return {n: Matrix.Identity(4) for n in names}, "world"
    out = {}
    for n in names:
        sw = _rest_world(source, source.data.bones[n])
        tw = _rest_world(target, target.data.bones[n])
        out[n] = sw.inverted_safe() @ tw
    return out, "rest"


def target_basis(source, target, names, offsets):
    """{bone: matrix_basis} for the target at the current frame."""
    tinv = target.matrix_world.inverted_safe()
    arm_pose = {}  # desired target pose, armature space
    for n in names:
        sw = source.matrix_world @ source.pose.bones[n].matrix
        arm_pose[n] = tinv @ (sw @ offsets[n])
    basis = {}
    for n in names:
        bone = target.data.bones[n]
        p = bone.parent
        if p is not None and p.name in arm_pose:
            parent_pose = arm_pose[p.name]
        elif p is not None:
            parent_pose = target.pose.bones[p.name].matrix  # unmatched parent: as it is
        else:
            parent_pose = None
        if parent_pose is None:
            local_rest, local_pose = bone.matrix_local, arm_pose[n]
        else:
            local_rest = p.matrix_local.inverted_safe() @ bone.matrix_local
            local_pose = parent_pose.inverted_safe() @ arm_pose[n]
        m = local_rest.inverted_safe() @ local_pose
        # keep the target's own proportions: drop any scale the source carried
        loc, rot, _ = m.decompose()
        basis[n] = Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
    return basis
