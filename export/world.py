import pysuperluxcore
from .. import utils
from ..utils.node import get_active_output
from . import light
from ..utils.errorlog import SuperLuxCoreErrorLog

# TODO: currently it is not possible to remove the world volume during viewport render


def convert(exporter, depsgraph, scene, is_viewport_render):
    props = pysuperluxcore.Properties()
    world = scene.world

    if not world:
        return props

    # World light (this is a SuperLuxCore concept)
    world_light_props = light.convert_world(exporter, world, scene, is_viewport_render)
    if world_light_props:
        props.Set(world_light_props)

    # World volume
    volume_node_tree = world.superluxcore.volume

    if volume_node_tree:
        superluxcore_name = utils.get_superluxcore_name(volume_node_tree)
        active_output = get_active_output(volume_node_tree)
        try:
            active_output.export(exporter, depsgraph, props, superluxcore_name)
            props.Set(pysuperluxcore.Property("scene.world.volume.default", superluxcore_name))
        except Exception as error:
            msg = 'World "%s": %s' % (world.name, error)
            SuperLuxCoreErrorLog.add_warning(msg)
    else:
        _convert_cycles_world_volume(world, props)

    return props


def _convert_cycles_world_volume(world, props):
    """Cycles world shader Volume output (atmospheric fog) -> the engine's
    default volume for rays outside any object. It was silently dropped."""
    node_tree = getattr(world, "node_tree", None)
    if not getattr(world, "use_nodes", True) or node_tree is None:
        return
    output = node_tree.get_output_node("CYCLES")
    if output is None or "Volume" not in output.inputs:
        return
    from ..utils import node as utils_node
    link = utils_node.get_link(output.inputs["Volume"])
    if link is None:
        return

    from . import cycles_node_reader
    name = utils.get_superluxcore_name(world) + "_worldvolume"
    try:
        defs = cycles_node_reader._volume(link.from_node, link.from_socket,
                                          props, world, name, "")
    except Exception as error:
        SuperLuxCoreErrorLog.add_warning(
            'World "%s": volume conversion failed: %s' % (world.name, error))
        return
    if defs is None:
        return
    if defs.get("type") == "heterogeneous" or any(
            isinstance(defs.get(k), str)
            for k in ("absorption", "scattering", "emission")):
        SuperLuxCoreErrorLog.add_warning(
            'World "%s": a textured world volume is evaluated once per ray '
            "segment (no ray marching over the infinite world)" % world.name)
        if defs.get("type") == "heterogeneous":
            defs["type"] = "homogeneous"
    if defs.get("type") == "homogeneous":
        # Cycles volumes scatter multiply
        defs.setdefault("multiscattering", True)
    props.Set(utils.luxutils.create_props("scene.volumes." + name + ".", defs))
    props.Set(pysuperluxcore.Property("scene.world.volume.default", name))
