"""Drape operators."""

import time

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
    TEMPLATES, TEMPLATE_DEFAULTS, TEMPLATE_FIT, TIGHTNESS_FIT, CoverageParams,
    coverage_group_name, compute_coverage, write_coverage,
)
from .core.garment import create_garment, add_thickness, shell_modifier
from .core.nodes import set_input
from .core import skirt as skirt_core, sim
from .core.layers import DEFAULT_LAYER, sync_layers, lower_points
from .core.trim import ensure_trim
from .core import details as details_core
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
    """The garment the panel is about: the one being painted or drawn on,
    else the active object."""
    s = context.scene.drape
    for busy in (s.painting_garment, s.drawing_on):
        if busy is not None and busy.drape_garment.is_garment:
            return busy
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
        if template == 'SKIRT':
            return self._add_skirt(context, body, arm)
        params = CoverageParams(**TEMPLATE_DEFAULTS[template])
        fit = TEMPLATE_FIT[template]
        offset, looseness = TIGHTNESS_FIT[fit['tightness']]

        name = _unique_name(body, template)
        group = coverage_group_name(name)
        n = write_coverage(body, group, compute_coverage(body, arm, template, params))
        if n == 0:
            self.report({'ERROR'}, "This garment covers nothing on this body")
            return {'CANCELLED'}

        collection = body.users_collection[0] if body.users_collection else context.scene.collection
        mat = make_fabric(name, fit['color'])
        obj = create_garment(body, name, group, mat, collection,
                             offset=offset, thickness=fit['thickness'],
                             looseness=looseness)

        g = obj.drape_garment  # is_garment stays False until filled: no update storms
        g.body = body
        g.armature_name = arm.name if arm else ""
        g.template = template
        g.coverage_group = group
        for k, v in vars(params).items():
            setattr(g, k, v)
        g.tightness = fit['tightness']
        g.offset, g.thickness, g.looseness = offset, fit['thickness'], looseness
        g.color = fit['color']
        g.layer = DEFAULT_LAYER[template]
        g.is_garment = True
        sync_layers(body)
        ensure_trim(obj)

        _select_only(context, obj)
        self.report({'INFO'}, f"Added {TEMPLATES[template]} ({n} body verts covered)")
        return {'FINISHED'}

    def _add_skirt(self, context, body, arm):
        if arm is None:
            self.report({'ERROR'}, "A skirt needs a rigged body")
            return {'CANCELLED'}
        bone = skirt_core.pelvis_bone(arm)
        if bone is None:
            self.report({'ERROR'}, "Couldn't find the pelvis bone")
            return {'CANCELLED'}
        fit = TEMPLATE_FIT['SKIRT']
        offset = TIGHTNESS_FIT[fit['tightness']][0]
        params = skirt_core.SkirtParams(offset=offset)
        name = _unique_name(body, 'SKIRT')
        collection = body.users_collection[0] if body.users_collection else context.scene.collection
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        collection.objects.link(obj)
        g = obj.drape_garment
        g.body = body  # needed to find the garments it goes over
        g.layer = DEFAULT_LAYER['SKIRT']
        dg = context.evaluated_depsgraph_get()
        try:
            verts, faces, pins = skirt_core.build_skirt(body, arm, params, dg,
                                                        under=lower_points(obj, dg))
        except RuntimeError as e:
            bpy.data.objects.remove(obj)
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        skirt_core.parent_to_bone(obj, arm, bone)
        skirt_core.write_skirt_mesh(obj, verts, faces, pins)
        obj.data.materials.append(make_fabric(name, fit['color']))
        add_thickness(obj, fit['thickness'])
        obj["drape_built_offset"] = offset

        g.armature_name = arm.name
        g.template = 'SKIRT'
        g.skirt_length, g.flare, g.waist_height = params.length, params.flare, params.waist
        g.tightness = fit['tightness']
        g.offset, g.thickness = offset, fit['thickness']
        g.color = fit['color']
        g.is_garment = True
        sync_layers(body)
        ensure_trim(obj)

        _select_only(context, obj)
        self.report({'INFO'}, "Added Skirt: click Drape to let it fall")
        return {'FINISHED'}


# --- simulation (Phase 3) -------------------------------------------------------

def _update_wind(body):
    """Wind blows for a body while any of its garments uses the Windy cloth."""
    windy = any(o.drape_garment.is_garment and o.drape_garment.body == body
                and sim.cloth_modifier(o) is not None and o.drape_garment.sim_preset == 'WINDY'
                for o in bpy.data.objects)
    sim.ensure_wind(body, windy)


def _is_mesh_garment(obj):
    """Garments with their own mesh (skirts), as opposed to body shells."""
    return shell_modifier(obj) is None


class DRAPE_OT_simulate(bpy.types.Operator):
    """Let the garment fall and settle as cloth (pinned at the waist or
    shoulders, colliding with the body). Skirts keep the settled drape;
    with Whole Animation the cloth is simulated over the scene's frames"""
    bl_idname = "drape.simulate"
    bl_label = "Drape"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_garment(context) is not None

    def execute(self, context):
        garment = active_garment(context)
        g = garment.drape_garment
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        sim.ensure_collider(g.body)
        sim.drop_drape(garment)

        shell = shell_modifier(garment)
        pins = sim.PIN_GROUP
        if shell is not None:  # body shell: its mesh carries the body's pin group
            pins = sim.pin_group_name(garment.name)
            sim.write_shell_pins(g.body, garment.name, g.template, g.coverage_group)
        # body shells carry ~10x a skirt's vertices: trade a little accuracy for speed
        mod = sim.ensure_cloth(garment, g.sim_preset, after=shell.name if shell else None,
                               quality=5 if shell else 8, pin_group=pins)
        _update_wind(g.body)
        scene = context.scene
        if g.sim_animation:
            mod.point_cache.frame_start, mod.point_cache.frame_end = scene.frame_start, scene.frame_end

        t = time.time()
        sim.bake(garment)
        secs = time.time() - t
        frames = mod.point_cache.frame_end - mod.point_cache.frame_start
        if _is_mesh_garment(garment) and not g.sim_animation:
            sim.keep_drape(garment)
            self.report({'INFO'}, f"Draped in {secs:.1f} s ({frames} frames); the drape is kept")
        else:
            self.report({'INFO'}, f"Simulated {frames} frames in {secs:.1f} s")
        _select_only(context, garment)
        return {'FINISHED'}


class DRAPE_OT_release_drape(bpy.types.Operator):
    """Forget the kept drape and go back to the garment's built shape"""
    bl_idname = "drape.release_drape"
    bl_label = "Release Drape"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = active_garment(context)
        return obj is not None and sim.cloth_modifier(obj) is not None

    def execute(self, context):
        garment = active_garment(context)
        sim.drop_drape(garment)
        sim.free_bake(garment)
        return {'FINISHED'}


class DRAPE_OT_remove_cloth(bpy.types.Operator):
    """Remove the cloth simulation from this garment"""
    bl_idname = "drape.remove_cloth"
    bl_label = "Remove Cloth"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = active_garment(context)
        return obj is not None and sim.cloth_modifier(obj) is not None

    def execute(self, context):
        garment = active_garment(context)
        sim.remove_cloth(garment)
        _update_wind(garment.drape_garment.body)
        return {'FINISHED'}


class DRAPE_OT_paint_coverage(bpy.types.Operator):
    """Paint where this garment goes on the body (paint = cover, erase =
    uncover). The garment updates live while you paint"""
    bl_idname = "drape.paint_coverage"
    bl_label = "Paint Coverage"

    @classmethod
    def poll(cls, context):
        obj = active_garment(context)
        return obj is not None and obj.drape_garment.template != 'SKIRT'

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


# --- drawn details (Phase 4) ------------------------------------------------------

class DRAPE_OT_draw_detail(bpy.types.Operator):
    """Draw a strap, belt, piping or zip straight onto this garment: draw
    strokes on the cloth, then click Finish Drawing"""
    bl_idname = "drape.draw_detail"
    bl_label = "Draw Detail"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_garment(context) is not None and context.space_data is not None             and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        garment = active_garment(context)
        s = context.scene.drape
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        obj = details_core.create_detail(garment, s.detail_kind)
        s.drawing_detail = obj
        s.drawing_on = garment
        _select_only(context, obj)
        bpy.ops.object.mode_set(mode='EDIT')
        paint = context.scene.tool_settings.curve_paint_settings
        paint.depth_mode = 'SURFACE'
        paint.surface_offset = 0.0
        paint.curve_type = 'POLY'
        bpy.ops.wm.tool_set_by_id(name="builtin.draw")
        self.report({'INFO'}, f"Draw the {s.detail_kind.lower()} on the garment, then click Finish Drawing")
        return {'FINISHED'}


class DRAPE_OT_finish_detail(bpy.types.Operator):
    """Stop drawing and attach the detail to the bone nearest it, so it
    follows the character"""
    bl_idname = "drape.finish_detail"
    bl_label = "Finish Drawing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.drape.drawing_detail is not None

    def execute(self, context):
        s = context.scene.drape
        obj, garment = s.drawing_detail, s.drawing_on
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        s.drawing_detail = None
        s.drawing_on = None
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        if not obj.data.splines:
            bpy.data.objects.remove(obj)
            self.report({'WARNING'}, "Nothing was drawn")
            return {'CANCELLED'}
        arm = bpy.data.objects.get(garment.drape_garment.armature_name) if garment else None
        bone = details_core.attach_detail(obj, arm)
        _select_only(context, garment or obj)
        self.report({'INFO'}, f"Detail attached to {bone}" if bone else "Detail added")
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
    DRAPE_OT_simulate,
    DRAPE_OT_release_drape,
    DRAPE_OT_remove_cloth,
    DRAPE_OT_draw_detail,
    DRAPE_OT_finish_detail,
)
