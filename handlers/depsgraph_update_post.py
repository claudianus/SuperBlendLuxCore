import bpy
from bpy.app.handlers import persistent
from ..export.caches import persistent_scene
from ..utils import misc

@persistent
def handler(scene):
    # Lights/worlds created since the last snapshot get their
    # use_cycles_settings interpretation pinned to the engine that
    # authored them (see utils.misc.tag_new_light_world).
    misc.tag_new_light_world(scene.render.engine)

    # If material name was changed, rename the node tree, too.
    for mat in bpy.data.materials:
        if mat.library is not None:
            continue
        node_tree = mat.superluxcore.node_tree

        if node_tree and node_tree.name != mat.name:
            node_tree.name = mat.name

    persistent_scene.on_depsgraph_update(
        scene, bpy.context.evaluated_depsgraph_get()
    )
