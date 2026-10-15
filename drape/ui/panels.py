"""Drape workflow panel."""

import bpy

from ..constants import PANEL_CATEGORY


class DRAPE_PT_main(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_label = "Drape Clothing Creator"

    def draw(self, context):
        layout = self.layout

        # --- Body Setup (Phase 1) ---
        header, body = layout.panel("drape_sec_body", default_closed=False)
        header.label(text="Body Setup", icon='ARMATURE_DATA')
        if body:
            body.label(text="Coming in Phase 1", icon='INFO')

        # --- Garment (Phase 2) ---
        header, body = layout.panel("drape_sec_garment", default_closed=True)
        header.label(text="Garment", icon='MOD_CLOTH')
        if body:
            body.label(text="Coming in Phase 2", icon='INFO')


CLASSES = (
    DRAPE_PT_main,
)
