"""Geometry Nodes builder utilities."""

import bpy


def set_input_default(node_group, socket_name, value):
    """Set the default value for a node group input socket (4.0+ interface API)."""
    for item in node_group.interface.items_tree:
        if (
            item.item_type == 'SOCKET'
            and item.in_out == 'INPUT'
            and item.name == socket_name
        ):
            item.default_value = value
            return


def new_geometry_group(name, inputs=(), outputs=(("Geometry", 'NodeSocketGeometry'),)):
    """Create a GeometryNodeTree with declared interface sockets.

    ``inputs``/``outputs`` are sequences of (name, socket_type) tuples.
    A Geometry input is always created first. Returns (group, group_input_node,
    group_output_node).
    """
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.nodes.clear()

    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    gi.location = (-900, 0)
    go.location = (900, 0)

    ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    for sock_name, sock_type in inputs:
        ng.interface.new_socket(name=sock_name, in_out='INPUT', socket_type=sock_type)
    for sock_name, sock_type in outputs:
        ng.interface.new_socket(name=sock_name, in_out='OUTPUT', socket_type=sock_type)

    return ng, gi, go


def ensure_geo_modifier(obj, modifier_name, rebuild_fn=None):
    """Get or create a NODES modifier. If ``rebuild_fn`` is given, the old
    node group is discarded and ``rebuild_fn(modifier)`` builds a fresh one.
    """
    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != 'NODES':
        mod = obj.modifiers.new(name=modifier_name, type='NODES')

    if rebuild_fn is not None:
        if mod.node_group:
            old_ng = mod.node_group
            mod.node_group = None
            if old_ng.users == 0:
                bpy.data.node_groups.remove(old_ng, do_unlink=True)
        rebuild_fn(mod)

    return mod
