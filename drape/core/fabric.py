"""One-click fabric materials: simple PBR cloth, or a two-tone toon shade.

Each garment gets its own material whose nodes are named here, so colour
and style can be changed later without rebuilding it. Toon uses Shader to
RGB, which only works in EEVEE (Cycles shows the flat base colour).
"""

import bpy

STYLES = (
    ('PBR', "Fabric", "Soft, matte cloth with a little sheen (EEVEE and Cycles)"),
    ('TOON', "Toon", "Two-tone cel shading for anime characters (EEVEE only)"),
)

_SHADOW = 0.55  # toon shadow tone, as a fraction of the base colour


def _clear(nt):
    for n in list(nt.nodes):
        nt.nodes.remove(n)


def _build_pbr(nt, color):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Drape Fabric"
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.85
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = 0.35
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def _build_toon(nt, color):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (800, 0)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (0, 0)
    to_rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    to_rgb.location = (200, 0)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.name = "Drape Toon Ramp"
    ramp.location = (400, 0)
    ramp.color_ramp.interpolation = 'CONSTANT'
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (650, 0)
    nt.links.new(diff.outputs["BSDF"], to_rgb.inputs["Shader"])
    nt.links.new(to_rgb.outputs["Color"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    _set_toon_color(ramp, color)


def _set_toon_color(ramp, color):
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    els[0].color = (*(c * _SHADOW for c in color), 1.0)
    els[1].position = 0.35
    els[1].color = (*color, 1.0)


def make_fabric(name, color, style='PBR'):
    """A new fabric material."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    apply_fabric(mat, color, style)
    return mat


def apply_fabric(mat, color, style='PBR'):
    """(Re)build ``mat`` for ``style`` if needed, then set its colour."""
    nt = mat.node_tree
    if mat.get("drape_style") != style:
        _clear(nt)
        (_build_toon if style == 'TOON' else _build_pbr)(nt, color)
        mat["drape_style"] = style
    if style == 'TOON':
        _set_toon_color(nt.nodes["Drape Toon Ramp"], color)
    else:
        nt.nodes["Drape Fabric"].inputs["Base Color"].default_value = (*color, 1.0)
    mat.diffuse_color = (*color, 1.0)  # Solid-mode viewport colour
