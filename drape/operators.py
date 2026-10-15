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
from .core.coverage import (
    TEMPLATES, TEMPLATE_DEFAULTS, TEMPLATE_FIT, CoverageParams,
    coverage_group_name, compute_coverage, write_coverage,
)
from .core.garment import create_garment
from .core.fabric import make_fabric

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


# --- garments (Phase 2) -------------------------------------------------------

def active_garment(context):
    """The garment the panel is about: the one being painted, else the active object."""
    s = context.scene.drape
    if s.painting_garment is not None and s.painting_garment.drape_garment.is_garment:
        return s.painting_garment
    obj = context.active_object
    if obj is not None and obj.drape_garment.is_garment:
        return obj
    return None


def _unique_name(body, template):
    base = f"Drape_{TEMPLATES[template].replace(' ', '').replace('-', '')}_{body.name}"
    name, i = base, 1
    while name in bpy.data.objects or body.vertex_groups.get(coverage_group_name(name)):
        name = f"{base}.{i:03d}"
        i += 1
    return name


def _select_only(context, obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class DRAPE_OT_add_garment(bpy.types.Operator):
    """Add a garment of the chosen kind to the body. It is generated from a
    coverage map on the body, follows the body's animation, and every slider
    updates it live"""
    bl_idname = "drape.add_garment"
    bl_label = "Add Garment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.drape
        return s.target is not None and REGION_ATTR in s.target.data.attributes

    def execute(self, context):
        s = context.scene.drape
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        body, arm, template = s.target, _armature(s), s.new_template
        params = CoverageParams(**TEMPLATE_DEFAULTS[template])
        fit = TEMPLATE_FIT[template]

        name = _unique_name(body, template)
        group = coverage_group_name(name)
        n = write_coverage(body, group, compute_coverage(body, arm, template, params))
        if n == 0:
            self.report({'ERROR'}, "This garment covers nothing on this body")
            return {'CANCELLED'}

        collection = body.users_collection[0] if body.users_collection else context.scene.collection
        mat = make_fabric(name, fit['color'])
        obj = create_garment(body, name, group, mat, collection,
                             offset=fit['offset'], thickness=fit['thickness'],
                             looseness=fit['looseness'])

        g = obj.drape_garment  # is_garment stays False until filled: no update storms
        g.body = body
        g.armature_name = arm.name if arm else ""
        g.template = template
        g.coverage_group = group
        for k, v in vars(params).items():
            setattr(g, k, v)
        g.offset, g.thickness, g.looseness = fit['offset'], fit['thickness'], fit['looseness']
        g.color = fit['color']
        g.is_garment = True

        _select_only(context, obj)
        self.report({'INFO'}, f"Added {TEMPLATES[template]} ({n} body verts covered)")
        return {'FINISHED'}


class DRAPE_OT_paint_coverage(bpy.types.Operator):
    """Paint where this garment goes on the body (paint = cover, erase =
    uncover). The garment updates live while you paint"""
    bl_idname = "drape.paint_coverage"
    bl_label = "Paint Coverage"

    @classmethod
    def poll(cls, context):
        return active_garment(context) is not None

    def execute(self, context):
        garment = active_garment(context)
        g = garment.drape_garment
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.scene.drape.painting_garment = garment
        _select_only(context, g.body)
        g.body.vertex_groups.active = g.body.vertex_groups[g.coverage_group]
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        self.report({'INFO'}, f"Painting {garment.name}. Click Finish Painting when done")
        return {'FINISHED'}


class DRAPE_OT_finish_coverage(bpy.types.Operator):
    """Stop painting and select the garment again"""
    bl_idname = "drape.finish_coverage"
    bl_label = "Finish Painting"

    def execute(self, context):
        s = context.scene.drape
        garment = s.painting_garment
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        s.painting_garment = None
        if garment is not None:
            _select_only(context, garment)
        return {'FINISHED'}


class DRAPE_OT_reset_coverage(bpy.types.Operator):
    """Throw away painted changes and rebuild the coverage from the
    garment's template and lengths"""
    bl_idname = "drape.reset_coverage"
    bl_label = "Reset to Template"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_garment(context) is not None

    def execute(self, context):
        from .properties import rebuild_coverage
        rebuild_coverage(active_garment(context).drape_garment)
        return {'FINISHED'}


CLASSES = (
    DRAPE_OT_setup_body,
    DRAPE_OT_show_regions,
    DRAPE_OT_paint_region,
    DRAPE_OT_finish_painting,
    DRAPE_OT_add_garment,
    DRAPE_OT_paint_coverage,
    DRAPE_OT_finish_coverage,
    DRAPE_OT_reset_coverage,
)
