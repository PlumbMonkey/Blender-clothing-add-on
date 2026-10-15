"""Drape core — shared engine module, vendored from Wisp.

Copied from Wisp's ``wisp/core/`` at commit f49647b (Wisp v0.4.0,
github.com/PlumbMonkey/Blender-Hair-style-add-on). Only the modules that
apply to bodies were taken; the hair-specific ones (groom, hair_stack,
hair_material, hair_sim, strands, scalp_cap, head_follow, hair_names) stay
in Wisp. Fixes made here should go back to Wisp too, until the two copies
are merged into one shared module.

Same rules as Wisp's core:

- No dependency on Drape UI, operators, or PropertyGroups.
  Functions take plain parameter objects (dataclasses) or explicit args.
- bpy/bmesh/mathutils are allowed, but no bpy.context reads inside core
  logic — callers pass objects explicitly.

Contents:
- geometry:      mesh math, bounds, curvature, vertex-group helpers
- rig:           CC / VRoid / generic detection, armature + body lookup
- scalp_detect:  bone-weight region detection (scalp today; generalise to
                 torso/arms/legs/hips/feet in Phase 1)
- nodes:         Geometry Nodes builder utilities
- motion:        FBX motion retarget onto the body's armature (Phase 6)
"""
