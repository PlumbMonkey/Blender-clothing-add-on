"""Drape — simple, intuitive clothing creation for Blender 5.1+.

Paint where a garment goes on a Character Creator (FBX), VRoid (VRM), or
generic body and get a fitted, non-destructive garment. Sister tool to
Wisp (hair). See BUILD-PLAN.md at the repo root.
"""

import bpy
from bpy.app.handlers import persistent

from . import properties
from . import operators
from .ui import panels

_ALL_CLASSES = (
    *operators.CLASSES,
    *panels.CLASSES,
)


@persistent
def _on_load(*_args):
    from .core.garment import upgrade_if_needed
    upgrade_if_needed()


def register():
    properties.register()
    for cls in _ALL_CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_on_load, first_interval=0.1)  # the file already open


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(_ALL_CLASSES):
        bpy.utils.unregister_class(cls)
    properties.unregister()
