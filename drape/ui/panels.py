"""Drape workflow panel."""

import bpy

from ..constants import PANEL_CATEGORY
from ..core.body_regions import REGION_ATTR
from ..core.coverage import TEMPLATE_PARAMS
from ..core.sim import CLOTH_MODIFIER, DRAPE_KEY
from ..operators import active_garment


class DRAPE_PT_main(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_label = "Drape Clothing Creator"

    def draw(self, context):
        layout = self.layout
        s = context.scene.drape

        # --- Body Setup (Phase 1) ---
        header, body = layout.panel("drape_sec_body", default_closed=False)
        header.label(text="Body Setup", icon='ARMATURE_DATA')
        if body:
            col = body.column()
            col.operator("drape.setup_body", icon='VIEWZOOM')
            ready = s.target is not None and REGION_ATTR in s.target.data.attributes
            if s.target:
                col.label(text=f"{s.pipeline or '?'}: {s.target.name}", icon='CHECKMARK')
            if ready:
                col.operator("drape.show_regions", icon='COLOR')

        # --- Regions (Phase 1) ---
        header, body = layout.panel("drape_sec_regions", default_closed=True)
        header.label(text="Regions", icon='BRUSH_DATA')
        if body:
            col = body.column()
            col.enabled = s.target is not None
            col.prop(s, "paint_region")
            in_paint = (context.active_object is not None
                        and context.active_object.mode == 'WEIGHT_PAINT'
                        and s.painting_garment is None)  # not a garment's coverage
            if in_paint:
                col.operator("drape.finish_painting", icon='CHECKMARK')
            else:
                col.operator("drape.paint_region", icon='BRUSH_DATA')

        # --- Garments (Phase 2) ---
        header, body = layout.panel("drape_sec_garment", default_closed=False)
        header.label(text="Garments", icon='MOD_CLOTH')
        if body:
            col = body.column()
            row = col.row(align=True)
            row.prop(s, "new_template", text="")
            row.operator("drape.add_garment", text="Add", icon='ADD')

            garment = active_garment(context)
            if garment is not None:
                self._draw_garment(context, col, garment)
            else:
                col.label(text="Select a garment to edit it", icon='INFO')

    def _draw_garment(self, context, col, garment):
        g = garment.drape_garment
        col.separator()
        col.label(text=garment.name, icon='MATCLOTH')
        row = col.row(align=True)
        row.prop(g, "layer")
        row.prop(g, "silhouette", text="")

        box = col.box().column()
        box.label(text="Shape")
        for name in TEMPLATE_PARAMS.get(g.template, ()):
            box.prop(g, name, slider=True)
        skirt = g.template == 'SKIRT'
        if not skirt:
            painting = context.scene.drape.painting_garment == garment
            row = box.row(align=True)
            if painting:
                row.operator("drape.finish_coverage", icon='CHECKMARK')
            else:
                row.operator("drape.paint_coverage", icon='BRUSH_DATA')
            row.operator("drape.reset_coverage", text="", icon='LOOP_BACK')

        box = col.box().column()
        box.label(text="Fit")
        if not skirt:
            box.prop(g, "tightness")
        box.prop(g, "offset", text="Waist Gap" if skirt else "Offset")
        if not skirt:
            box.prop(g, "looseness", slider=True)
        box.prop(g, "thickness")
        if not skirt:
            box.prop(g, "border_smooth", slider=True)
            box.prop(g, "resolution")

        box = col.box().column()
        box.label(text="Simulate")
        box.row().prop(g, "sim_preset", expand=True)
        box.prop(g, "sim_animation")
        box.operator("drape.simulate", icon='MOD_CLOTH')
        cloth = garment.modifiers.get(CLOTH_MODIFIER)
        if cloth is not None:
            keys = garment.data.shape_keys
            if keys is not None and keys.key_blocks.get(DRAPE_KEY) is not None:
                box.label(text="Drape kept", icon='CHECKMARK')
            row = box.row(align=True)
            row.operator("drape.release_drape", icon='LOOP_BACK')
            row.operator("drape.remove_cloth", text="", icon='X')

        box = col.box().column()
        box.label(text="Trim")
        box.prop(g, "hem")
        if not skirt:
            box.prop(g, "seams")
        if g.template in ('TSHIRT', 'TANK', 'LONGSLEEVE'):
            row = box.row(align=True)
            row.prop(g, "buttons")
            row.prop(g, "button_size", text="Size")

        box = col.box().column()
        box.label(text="Details")
        s = context.scene.drape
        if s.drawing_detail is not None:
            box.operator("drape.finish_detail", icon='CHECKMARK')
        else:
            row = box.row(align=True)
            row.prop(s, "detail_kind", text="")
            row.operator("drape.draw_detail", text="Draw", icon='GREASEPENCIL')

        box = col.box().column()
        box.label(text="Look")
        box.prop(g, "style", expand=True)
        box.prop(g, "color", text="")


CLASSES = (
    DRAPE_PT_main,
)
