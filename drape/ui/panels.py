"""Drape workflow panel."""

import bpy

from ..constants import PANEL_CATEGORY
from ..core.body_regions import REGION_ATTR


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
                        and context.active_object.mode == 'WEIGHT_PAINT')
            if in_paint:
                col.operator("drape.finish_painting", icon='CHECKMARK')
            else:
                col.operator("drape.paint_region", icon='BRUSH_DATA')

        # --- Garment (Phase 2) ---
        header, body = layout.panel("drape_sec_garment", default_closed=True)
        header.label(text="Garment", icon='MOD_CLOTH')
        if body:
            body.label(text="Coming in Phase 2", icon='INFO')


CLASSES = (
    DRAPE_PT_main,
)
