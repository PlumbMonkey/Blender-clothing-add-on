"""Drape operators."""

import bpy

from .core.rig import find_armature, detect_pipeline, find_body_mesh
from .core.body_regions import (
    detect_regions,
    apply_painted_region,
    region_group_name,
    PREVIEW_ATTR,
    REGION_ATTR,
)

PIPELINE_LABELS = {'CC': "Character Creator", 'VROID': "VRoid", 'GENERIC': "Generic"}


def _armature(settings):
    return bpy.data.objects.get(settings.armature_name) if settings.armature_name else None


def _summary(counts):
    return ", ".join(f"{k.title()} {v}" for k, v in counts.items() if v)


class DRAPE_OT_setup_body(bpy.types.Operator):
    """Detect the character's pipeline, armature and body mesh from the active
    object (select any part of the character), then split the body into
    garment regions from its skin weights"""
    bl_idname = "drape.setup_body"
    bl_label = "Set Up Body"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "Select any part of the character first")
            return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        arm = obj if obj.type == 'ARMATURE' else find_armature(obj)
        if arm is None:
            self.report({'ERROR'}, "No armature found: Drape needs a rigged body")
            return {'CANCELLED'}
        pipeline = detect_pipeline(arm)
        body = find_body_mesh(arm, pipeline)
        if body is None:
            self.report({'ERROR'}, "No body mesh found on this character")
            return {'CANCELLED'}

        counts = detect_regions(body, arm)
        if not any(counts.values()):
            self.report({'ERROR'}, "The body has no skin weights Drape recognises")
            return {'CANCELLED'}

        s = context.scene.drape
        s.target = body
        s.armature_name = arm.name
        s.pipeline = pipeline
        self.report({'INFO'}, f"{PIPELINE_LABELS[pipeline]}: '{body.name}' | {_summary(counts)}")
        return {'FINISHED'}


class DRAPE_OT_show_regions(bpy.types.Operator):
    """Colour the body by region in the viewport (Solid shading); click again
    to go back to material colours"""
    bl_idname = "drape.show_regions"
    bl_label = "Show Regions"

    @classmethod
    def poll(cls, context):
        s = context.scene.drape
        return (s.target is not None and context.space_data is not None
                and context.space_data.type == 'VIEW_3D')

    def execute(self, context):
        body = context.scene.drape.target
        attrs = body.data.color_attributes
        if PREVIEW_ATTR not in attrs:
            self.report({'WARNING'}, "Run Set Up Body first")
            return {'CANCELLED'}
        shading = context.space_data.shading
        if shading.type == 'SOLID' and shading.color_type == 'VERTEX':
            shading.color_type = 'MATERIAL'
            return {'FINISHED'}
        attrs.active_color = attrs[PREVIEW_ATTR]
        shading.type = 'SOLID'
        shading.color_type = 'VERTEX'
        return {'FINISHED'}


class DRAPE_OT_paint_region(bpy.types.Operator):
    """Repaint the chosen region by weight painting (paint = add to the region,
    erase = give the skin back to its neighbours)"""
    bl_idname = "drape.paint_region"
    bl_label = "Refine by Painting"

    @classmethod
    def poll(cls, context):
        s = context.scene.drape
        return s.target is not None and REGION_ATTR in s.target.data.attributes

    def execute(self, context):
        s = context.scene.drape
        body = s.target
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        body.hide_set(False)
        body.select_set(True)
        context.view_layer.objects.active = body
        group = region_group_name(s.paint_region)
        body.vertex_groups.active = body.vertex_groups[group]
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        self.report({'INFO'}, f"Painting {group}. Click Finish Painting when done")
        return {'FINISHED'}


class DRAPE_OT_finish_painting(bpy.types.Operator):
    """Return to object mode and fold the repainted region back into the
    region map (each vertex belongs to exactly one region)"""
    bl_idname = "drape.finish_painting"
    bl_label = "Finish Painting"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        s = context.scene.drape
        if s.target is None:
            return {'CANCELLED'}
        counts = apply_painted_region(s.target, _armature(s), s.paint_region)
        if counts:
            self.report({'INFO'}, f"Regions updated | {_summary(counts)}")
        return {'FINISHED'}


CLASSES = (
    DRAPE_OT_setup_body,
    DRAPE_OT_show_regions,
    DRAPE_OT_paint_region,
    DRAPE_OT_finish_painting,
)
