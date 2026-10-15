"""Drape — simple, intuitive clothing creation for Blender 5.1+.

Paint where a garment goes on a Character Creator (FBX), VRoid (VRM), or
generic body and get a fitted, non-destructive garment. Sister tool to
Wisp (hair). See BUILD-PLAN.md at the repo root.
"""

import bpy

from .ui import panels

_ALL_CLASSES = (
    *panels.CLASSES,
)


def register():
    for cls in _ALL_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_ALL_CLASSES):
        bpy.utils.unregister_class(cls)
