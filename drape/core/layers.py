"""Garment layering: which garments sit over which.

Every garment has a layer number (higher = further out). A body shell reads
the garments on lower layers of the same body through its own
``Drape_Under_<garment>`` collection (kept outside the scene, with a fake
user) and is pushed out over them. A skirt is a mesh, so it takes the lower
garments into account when it is built instead.
"""

import bpy
import numpy as np

from .garment import shell_modifier
from .nodes import set_input

# Layer each template starts on: socks under bottoms under tops; a skirt
# goes over a tucked-in top.
DEFAULT_LAYER = {
    'SOCKS': 1, 'SHORTS': 2, 'PANTS': 2,
    'TANK': 3, 'TSHIRT': 3, 'LONGSLEEVE': 3,
    'SKIRT': 4,
}

UNDER_PREFIX = "Drape_Under_"


def under_collection_name(garment):
    return f"{UNDER_PREFIX}{garment.name}"


def body_garments(body):
    return [o for o in bpy.data.objects
            if o.drape_garment.is_garment and o.drape_garment.body == body]


def lower_garments(garment):
    g = garment.drape_garment
    return [o for o in body_garments(g.body) if o is not garment
            and o.drape_garment.layer < g.layer]


def sync_layers(body):
    """Point every shell garment of ``body`` at the garments beneath it."""
    for obj in body_garments(body):
        mod = shell_modifier(obj)
        if mod is None:
            continue
        name = under_collection_name(obj)
        coll = bpy.data.collections.get(name)
        if coll is None:
            coll = bpy.data.collections.new(name)
            coll.use_fake_user = True  # not in the scene: keep it alive
        wanted = set(lower_garments(obj))
        for o in list(coll.objects):
            if o not in wanted:
                coll.objects.unlink(o)
        for o in wanted:
            if o.name not in coll.objects:
                coll.objects.link(o)
        set_input(mod, "Under", coll)
        obj.update_tag()
    # collections of garments that no longer exist
    for coll in list(bpy.data.collections):
        if coll.name.startswith(UNDER_PREFIX) and coll.name[len(UNDER_PREFIX):] not in bpy.data.objects:
            bpy.data.collections.remove(coll)


def lower_points(garment, depsgraph):
    """World-space vertices of every garment beneath ``garment`` (N×3)."""
    pts = []
    for o in lower_garments(garment):
        ev = o.evaluated_get(depsgraph)
        me = ev.data
        if len(me.vertices) == 0:
            continue
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        mw = np.array(ev.matrix_world, dtype=np.float64)
        pts.append(co @ mw[:3, :3].T + mw[:3, 3])
    return np.concatenate(pts) if pts else np.zeros((0, 3))
