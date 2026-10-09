"""MikkTSpace corner data for Cycles normals and vector displacement."""
import bpy
import numpy as np
import pysuperluxcore
from ..utils.errorlog import SuperLuxCoreErrorLog

_maps = {}
_requirements = {}
_identities = {}
_LIMIT = 8


def clear():
    _maps.clear()
    _requirements.clear()
    _identities.clear()


def resolve_identity(obj_name):
    return _identities.get(obj_name)


def resolve(obj_name, uv_name):
    mapping = _maps.get(obj_name)
    if mapping is None:
        obj = bpy.data.objects.get(obj_name) if obj_name else None
        mapping = _maps.get(getattr(getattr(obj, 'data', None), 'name', None))
    return mapping.get(uv_name) if mapping else None


def _nodes(tree, seen):
    if tree is None or tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    for node in tree.nodes:
        if node.bl_idname == 'ShaderNodeGroup':
            yield from _nodes(node.node_tree, seen)
        elif node.bl_idname == 'ShaderNodeVectorDisplacement' or (node.bl_idname == 'ShaderNodeNormalMap' and node.space == 'TANGENT'):
            if node.outputs[0].is_linked:
                yield node


def requirements(obj):
    """Material graph changes can require new mesh data on cached scenes."""
    if obj is None:
        return ()
    requested = set()
    seen = set()
    for slot in obj.material_slots:
        material = slot.material
        if material:
            material = material.original
            if material.use_nodes:
                requested.update(getattr(node, 'uv_map', '') for node in _nodes(material.node_tree, seen) if node.space == 'TANGENT')
    return tuple(sorted(requested))


def changed(obj):
    return obj.name in _requirements and (requirements(obj), _needs_identity(obj)) != _requirements[obj.name]


def _needs_identity(obj):
    return any(node.bl_idname == 'ShaderNodeVectorDisplacement'
               for slot in obj.material_slots if slot.material and slot.material.use_nodes
               and slot.material.original.displacement_method != 'BUMP'
               for node in _nodes(slot.material.original.node_tree, set()))


def _tangents(mesh, uv_name, normals):
    """Use the installed Cycles Mikk triangle convention without mesh edits."""
    points = np.empty((len(mesh.vertices), 3), np.float32)
    corners = np.empty(len(mesh.loops), np.uint32)
    triangle_corners = np.empty(len(mesh.loop_triangles) * 3, np.uint32)
    polygon_indices = np.empty(len(mesh.loop_triangles), np.uint32)
    smooth = np.empty(len(mesh.polygons), dtype=bool)
    mesh.vertices.foreach_get('co', points.ravel())
    mesh.loops.foreach_get('vertex_index', corners)
    mesh.loop_triangles.foreach_get('loops', triangle_corners)
    mesh.loop_triangles.foreach_get('polygon_index', polygon_indices)
    mesh.polygons.foreach_get('use_smooth', smooth)
    uv = None
    if uv_name:
        values = np.empty((len(mesh.loops), 2), np.float32)
        mesh.uv_layers[uv_name].data.foreach_get('uv', values.ravel())
        uv = values[triangle_corners].reshape(-1, 3, 2)
    tangent, sign = pysuperluxcore.ComputeMikkTangents(
        points, corners[triangle_corners].reshape(-1, 3),
        normals[triangle_corners].reshape(-1, 3, 3), uv, smooth[polygon_indices],
        cycles_normal_precision=True)
    tangent = tangent.reshape(-1, 3)
    sign = sign.ravel()
    _, first = np.unique(triangle_corners, return_index=True)
    result = np.empty((len(mesh.loops), 3), np.float32)
    result_sign = np.empty(len(mesh.loops), np.float32)
    result[triangle_corners[first]] = tangent[first]
    result_sign[triangle_corners[first]] = sign[first]
    return result, result_sign


def collect(obj, mesh, normals, colors, alphas, vertex_aovs):
    """Append original object-space normals, tangents and signs to data channels."""
    requested = requirements(obj)
    needs_identity = _needs_identity(obj)
    _requirements[obj.name] = (requested, needs_identity)
    _identities.pop(obj.name, None)
    if needs_identity:
        if len(vertex_aovs) + 2 > _LIMIT:
            SuperLuxCoreErrorLog.add_warning('Vector Displacement: original vertex identity channel budget exceeded', obj_name=obj.name)
        else:
            vertices = np.empty(len(mesh.loops), np.uint32)
            mesh.loops.foreach_get('vertex_index', vertices)
            counts = np.empty(len(mesh.polygons), np.int32)
            smooth = np.empty(len(mesh.polygons), dtype=bool)
            mesh.polygons.foreach_get('loop_total', counts)
            mesh.polygons.foreach_get('use_smooth', smooth)
            flags = np.repeat(smooth.astype(np.float32), counts) * 65536
            _identities[obj.name] = (len(vertex_aovs), len(vertex_aovs) + 1,
                                     getattr(mesh, 'normals_domain', 'POINT') == 'CORNER')
            vertex_aovs.extend([(vertices & 0xffff).astype(np.float32) + flags, (vertices >> 16).astype(np.float32)])
    mapping = {}
    _maps[obj.name] = mapping
    _maps[mesh.name] = mapping
    if getattr(obj, 'data', None) is not None:
        _maps[obj.data.name] = mapping
    if not requested:
        return
    active = next((layer.name for layer in mesh.uv_layers if layer.active_render),
                  mesh.uv_layers.active.name if mesh.uv_layers.active else '')
    if len(colors) + 2 > _LIMIT:
        SuperLuxCoreErrorLog.add_warning('Normal Map: mesh colour data channel budget exceeded', obj_name=obj.name)
        return
    normal_index = len(colors)
    # DefineMeshExt adopts contiguous arrays and transforms the normal buffer
    # in place. Raw object-space normal data must own a separate allocation.
    colors.append(np.array(normals, dtype=np.float32, order='C', copy=True))
    by_uv = {}
    for key in sorted(requested):
        uv_name = key or active
        if uv_name in by_uv:
            mapping[key] = by_uv[uv_name]
            continue
        if uv_name and mesh.uv_layers.find(uv_name) < 0:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent UV map is unavailable: ' + uv_name, obj_name=obj.name)
            continue
        if len(colors) >= _LIMIT or len(alphas) >= _LIMIT:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent data channel budget exceeded', obj_name=obj.name)
            continue
        try:
            tangent, sign = _tangents(mesh, uv_name, normals)
        except (RuntimeError, ValueError) as error:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent calculation failed: ' + str(error), obj_name=obj.name)
            continue
        indices = (normal_index, len(colors), len(alphas))
        colors.append(np.ascontiguousarray(tangent))
        alphas.append(np.ascontiguousarray(sign))
        mapping[key] = by_uv[uv_name] = indices
