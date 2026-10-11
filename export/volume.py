import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
import bpy
import mathutils
import numpy as np
import pysuperluxcore

from .. import utils
from ..utils import node as utils_node
from ..utils.errorlog import SuperLuxCoreErrorLog
from .caches.exported_data import ExportedObject


# Conversion state belongs to this VDB instance, including when its material
# and node groups are shared. Release the grid metadata after each conversion.
_grid_context = ContextVar("superluxcore_volume_grid_context", default=None)


class _GridContext:
    def __init__(self, obj, key, scene, transform):
        self.obj = obj
        self.key = key
        self.filepath = _resolve_frame_filepath(obj.data, scene)
        self.transform = transform.copy()
        self.names = set(pysuperluxcore.GetOpenVDBGridNames(self.filepath))
        self.infos = {}
        self.used = set()
        self.implicit = set()

    def info(self, grid):
        if grid not in self.infos:
            self.infos[grid] = pysuperluxcore.GetOpenVDBGridInfo(self.filepath, grid)
        return self.infos[grid]


@contextmanager
def _with_grid_context(context):
    token = _grid_context.set(context)
    try:
        yield
    finally:
        _grid_context.reset(token)


def grid_context_key():
    context = _grid_context.get()
    return context.key if context is not None else ""


def _context_for_object(obj_name):
    context = _grid_context.get()
    if context is not None:
        return context
    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != "VOLUME":
        return None
    filepath = _resolve_frame_filepath(obj.data, bpy.context.scene)
    if not filepath or not os.path.isfile(filepath):
        return None
    return _GridContext(obj, utils.sanitize_superluxcore_name(obj_name),
                        bpy.context.scene, obj.matrix_world)


def _index_to_object(info):
    # OpenVDB uses row vectors; GetOpenVDBGridInfo serializes its rows.
    matrix = info[3]
    return mathutils.Matrix([matrix[i:i + 4] for i in range(0, 16, 4)]).transposed()


def _grid_defs(context, grid):
    if not grid or grid not in context.names:
        return None
    info = context.info(grid)
    bbox = info[1]
    resolution = [bbox[i + 3] - bbox[i] for i in range(3)]
    if any(n <= 0 for n in resolution):
        return None
    # The native dense reader samples the leaf index interval [min,max).
    # Preserve the actual affine transform, rather than its world-space AABB.
    index_box = (mathutils.Matrix.Translation(mathutils.Vector(bbox[:3])) @
                 mathutils.Matrix.Diagonal((*resolution, 1.0)))
    world_box = context.transform @ _index_to_object(info) @ index_box
    context.used.add(grid)
    return {
        "type": "densitygrid", "wrap": "black", "storage": "float",
        "nx": resolution[0], "ny": resolution[1], "nz": resolution[2],
        "openvdb.file": context.filepath, "openvdb.grid": grid,
        "mapping.type": "globalmapping3d",
        "mapping.transformation": utils.luxutils.matrix_to_list(world_box, invert=True),
    }


def attribute_grid_defs(attribute_name, obj_name, implicit=False):
    context = _context_for_object(obj_name)
    definitions = _grid_defs(context, attribute_name) if context is not None else None
    if definitions is not None and implicit:
        context.implicit.add(attribute_name)
    return definitions


def _used_shader_grids(props, shader, context):
    # Cycles drops dead explicit attributes during graph optimization. Keep
    # Principled's implicit requests, but a field multiplied by zero must not
    # invent bounds for an otherwise topology-free emitting volume.
    textures = {}
    for name in props.GetAllNames("scene.textures."):
        texture, key = name[len("scene.textures."):].split(".", 1)
        values = props.Get(name).Get()
        textures.setdefault(texture, {})[key] = values[0] if len(values) == 1 else values
    zero_cache = {}
    def zero(value, seen=()):
        if isinstance(value, (int, float)):
            return value == 0
        if isinstance(value, (list, tuple)):
            return all(zero(v, seen) for v in value)
        if not isinstance(value, str) or value not in textures or value in seen:
            return False
        if value not in zero_cache:
            definition = textures[value]
            kind = definition.get("type")
            trail = (*seen, value)
            zero_cache[value] = (
                kind in {"constfloat1", "constfloat3"} and zero(definition.get("value"), trail)
                or kind == "scale" and (zero(definition.get("texture1"), trail)
                                       or zero(definition.get("texture2"), trail)))
        return zero_cache[value]
    used = set(context.implicit)
    visited = set()
    def visit(value):
        if not isinstance(value, str) or value not in textures or value in visited or zero(value):
            return
        visited.add(value)
        definition = textures[value]
        if "openvdb.grid" in definition:
            used.add(definition["openvdb.grid"])
        for operand in definition.values():
            visit(operand)
    for value in shader.values():
        visit(value)
    return used


def has_grid_context(obj_name):
    context = _grid_context.get()
    obj = bpy.data.objects.get(obj_name) if context is None else context.obj
    return obj is not None and obj.type == "VOLUME"


# A unit cube spanning [0, 1]^3, with outward-facing normals.
# Each face contributes 4 loop vertices so normals stay flat-shaded.
_CUBE_LOOP_POINTS = np.array(
    [
        # -Z face
        [0, 0, 0], [0, 1, 0], [1, 1, 0], [1, 0, 0],
        # +Z face
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
        # -Y face
        [0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
        # +Y face
        [0, 1, 0], [0, 1, 1], [1, 1, 1], [1, 1, 0],
        # -X face
        [0, 0, 0], [0, 0, 1], [0, 1, 1], [0, 1, 0],
        # +X face
        [1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1],
    ],
    dtype=np.float32,
)

_CUBE_TRIANGLES = np.array(
    [
        [0, 1, 2], [0, 2, 3],
        [4, 5, 6], [4, 6, 7],
        [8, 9, 10], [8, 10, 11],
        [12, 13, 14], [12, 14, 15],
        [16, 17, 18], [16, 18, 19],
        [20, 21, 22], [20, 22, 23],
    ],
    dtype=np.uint32,
)

_CUBE_LOOP_NORMALS = np.array(
    [
        [0, 0, -1]] * 4
    + [[0, 0, 1]] * 4
    + [[0, -1, 0]] * 4
    + [[0, 1, 0]] * 4
    + [[-1, 0, 0]] * 4
    + [[1, 0, 0]] * 4,
    dtype=np.float32,
)


def _resolve_frame_filepath(vol_data, scene):
    """Return the .vdb file for the current frame, honoring sequence settings."""
    if not vol_data.filepath:
        return ""
    filepath = bpy.path.abspath(vol_data.filepath)
    if not vol_data.is_sequence:
        return filepath

    stem, extension = os.path.splitext(filepath)
    number = re.search(r"[0-9]+$", os.path.basename(stem))
    if number is None or int(number.group()) > 2147483647:
        return filepath
    # Blender's evaluated RNA already applies start/duration/mode, then
    # offset. Use its actual frame instead of reindexing directory entries;
    # missing files must remain missing and CLIP outside its range is empty.
    frame = vol_data.grids.frame
    if frame == 2147483647:  # Blender VOLUME_FRAME_NONE
        return ""
    digits = str(abs(frame)).zfill(len(number.group()))
    suffix = ("-" if frame < 0 else "") + digits
    return stem[:-len(number.group())] + suffix + extension


def volume_info_grid_defs(node, output_socket_name, obj_name):
    """Volume Info reads fixed standard names, as Cycles' Attribute nodes do."""
    grid = {"Density": "density", "Color": "color", "Flame": "flame",
            "Temperature": "temperature"}.get(output_socket_name)
    return attribute_grid_defs(grid, obj_name)


def _material_volume_defs(obj, obj_key, props):
    """
    Convert every authored Cycles Volume subtree, including Principled
    attribute fields and groups. An unlinked output is an empty medium.
    """
    mat = obj.material_slots[0].material if len(obj.material_slots) else None
    node_tree = getattr(mat, "node_tree", None)
    if mat is None or node_tree is None:
        return None
    output = node_tree.get_output_node("CYCLES")
    if output is None or "Volume" not in output.inputs:
        return None
    link = utils_node.get_link(output.inputs["Volume"])
    if link is None:
        return {"type": "clear", "absorption": 0.0}

    from . import cycles_node_reader  # lazy: object_cache->cycles_node_reader cycle
    return cycles_node_reader._volume(
        link.from_node, link.from_socket, props, mat,
        obj_key + "_vol", obj.name) or {"type": "clear", "absorption": 0.0}


def convert_volume_obj(
    exporter,
    dg_obj_instance,
    obj,
    obj_key,
    depsgraph,
    superluxcore_scene,
    scene_props,
    is_viewport_render,
    view_layer,
):
    """
    Convert a Blender VOLUME object (OpenVDB file) to a bounded box mesh
    carrying a heterogeneous SuperLuxCore volume fed by densitygrid textures.
    """
    vol_data = obj.data
    scene = depsgraph.scene_eval if depsgraph.scene_eval else bpy.context.scene

    filepath = _resolve_frame_filepath(vol_data, scene)
    if not filepath:
        if vol_data.filepath:
            # An evaluated CLIP frame outside the sequence is intentionally empty.
            return None
        SuperLuxCoreErrorLog.add_warning(
            'Volume object "%s": generated (in-memory) volumes are not '
            "supported yet; import an OpenVDB file instead" % obj.name
        )
        return None
    if not os.path.isfile(filepath):
        SuperLuxCoreErrorLog.add_warning(
            'Volume object "%s": file not found: %s' % (obj.name, filepath)
        )
        return None

    props = scene_props
    transform = dg_obj_instance.matrix_world.copy()
    try:
        context = _GridContext(obj, obj_key, scene, transform)
        with _with_grid_context(context):
            mat_vol = _material_volume_defs(obj, obj_key, props)
            if mat_vol is None:
                # Cycles' default VDB shader is Principled Volume: density
                # attribute, grey albedo, no automatic flame emission.
                density = 1.0
                definitions = _grid_defs(context, "density")
                if definitions is not None:
                    density = obj_key + "_density"
                    props.Set(utils.luxutils.create_props(
                        "scene.textures." + density + ".", definitions))
                from . import cycles_node_reader
                coefficient = cycles_node_reader._tex_binary(
                    "scale", density, 0.5, obj_key + "_default_coefficient", props)
                mat_vol = {"absorption": coefficient, "scattering": coefficient}
    except Exception as error:
        SuperLuxCoreErrorLog.add_warning(
            'Volume object "%s": %s' % (obj.name, error))
        return None

    # Cycles builds the carrier from requested voxel attributes. A material
    # requesting only absent fields has no grid topology and renders empty.
    context.used = _used_shader_grids(props, mat_vol, context)
    if not context.used:
        return None

    bounds = []
    step_candidates = []
    for grid in sorted(context.used):
        info = context.info(grid)
        bbox = info[1]
        index_to_object = _index_to_object(info)
        # Include interpolation padding around each grid, in its own frame.
        # Native interpolation at the last voxel is a separate edge-fidelity
        # limitation; enlarging a common AABB cannot correct its sampling.
        for x in (bbox[0] - 1, bbox[3] + 1):
            for y in (bbox[1] - 1, bbox[4] + 1):
                for z in (bbox[2] - 1, bbox[5] + 1):
                    bounds.append(index_to_object @ mathutils.Vector((x, y, z)))
        world_grid = transform @ index_to_object
        step_candidates.extend(world_grid.col[i].to_3d().length for i in range(3))
    bb_min = mathutils.Vector([min(point[i] for point in bounds) for i in range(3)])
    bb_max = mathutils.Vector([max(point[i] for point in bounds) for i in range(3)])
    extent = bb_max - bb_min
    if any(value <= 1e-9 for value in extent):
        return None
    bbox_matrix = (mathutils.Matrix.Translation(bb_min) @
                   mathutils.Matrix.Diagonal((*extent, 1.0)))
    world_box = transform @ bbox_matrix
    loop_points = np.array(
        [tuple(bbox_matrix @ mathutils.Vector(p)) for p in _CUBE_LOOP_POINTS],
        dtype=np.float32)
    mesh_name = obj_key + "_volumebox"
    superluxcore_scene.DefineMeshExt(
        name=mesh_name, points=loop_points, triangles=_CUBE_TRIANGLES,
        normals=_CUBE_LOOP_NORMALS, uvs=None, colors=None, alphas=None,
        transformation=None)

    vol_absorption = mat_vol.get("absorption", [0.0, 0.0, 0.0])
    vol_scattering = mat_vol.get("scattering", [0.0, 0.0, 0.0])
    vol_emission = mat_vol.get("emission", [0.0, 0.0, 0.0])
    vol_asymmetry = mat_vol.get("asymmetry", [0.0, 0.0, 0.0])
    # OBJECT space keeps optical thickness invariant under object scaling.
    # Cycles uses the transformed normalized (1,1,1) direction, also under
    # nonuniform scale and shear. Display density does not affect rendering.
    object_space = getattr(vol_data.render, "space", "OBJECT") == "OBJECT"
    density_scale = 1.0
    if object_space:
        direction = transform.to_3x3() @ mathutils.Vector((1, 1, 1)).normalized()
        density_scale = 1.0 / max(direction.length, 1e-20)
    if density_scale != 1.0:
        from . import cycles_node_reader
        vol_absorption, vol_scattering, vol_emission = [
            cycles_node_reader._tex_binary("scale", value, density_scale,
                obj_key + "_object_space_" + key, props)
            for key, value in (("absorption", vol_absorption),
                               ("scattering", vol_scattering),
                               ("emission", vol_emission))]

    auto_step = min(step_candidates)
    user_step = max(0.0, getattr(vol_data.render, "step_size", 0.0))
    if user_step > 0.0 and object_space:
        user_step *= 1.0 / density_scale
    step_size = max(user_step if user_step > 0.0 else auto_step, 1e-5)
    axis_lengths = [world_box.col[i].to_3d().length for i in range(3)]
    diagonal = sum(axis_lengths)
    maxcount = max(1, math.ceil(diagonal / step_size)) + 1

    vol_name = obj_key + "_volume"
    props.Set(
        utils.luxutils.create_props(
            "scene.volumes.%s." % vol_name,
            {
                "type": "heterogeneous",
                "absorption": vol_absorption,
                "scattering": vol_scattering,
                "asymmetry": vol_asymmetry,
                "emission": vol_emission,
                "steps.size": step_size,
                "steps.maxcount": maxcount,
                # Cycles volumes scatter multiply (single-scattering
                # only rendered OpenVDB media dark)
                "multiscattering": 1,
                "ior": 1.0,
                "priority": 0,
                "emission.id": 0,
            },
        )
    )

    # A VDB bounds mesh has no optical surface. A null boundary crosses the
    # medium without inventing a dielectric bounce/caustic at the bounds.
    mat_name = obj_key + "_volmat"
    props.Set(
        utils.luxutils.create_props(
            "scene.materials.%s." % mat_name,
            {
                "type": "null",
                "volume.interior": vol_name,
            },
        )
    )

    visible_to_cam = utils.visible_to_camera(
        dg_obj_instance, is_viewport_render, view_layer
    )
    exported = ExportedObject(
        obj_key,
        [(mesh_name, 0)],
        [mat_name],
        transform,
        visible_to_cam,
        utils.make_object_id(dg_obj_instance),
    )
    exported.volume_frame_signature = (vol_data.filepath, vol_data.grids.frame)
    return exported
