"""MikkTSpace corner data for Cycles Normal Map inputs, without editing meshes."""
import bpy
import numpy as np
from ..utils.errorlog import SuperLuxCoreErrorLog

_maps = {}
_requirements = {}
_LIMIT = 8


def clear():
    _maps.clear()
    _requirements.clear()


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
        elif node.bl_idname == 'ShaderNodeNormalMap' and node.space == 'TANGENT' and node.outputs['Normal'].is_linked:
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
                requested.update(node.uv_map for node in _nodes(material.node_tree, seen))
    return tuple(sorted(requested))


def changed(obj):
    return obj.name in _requirements and requirements(obj) != _requirements[obj.name]


def collect(obj, mesh, normals, colors, alphas):
    """Append original object-space normals, tangents and signs to data channels."""
    requested = requirements(obj)
    _requirements[obj.name] = requested
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
        if not uv_name or mesh.uv_layers.find(uv_name) < 0:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent UV map is unavailable: ' + (uv_name or '<active>'), obj_name=obj.name)
            continue
        if len(colors) >= _LIMIT or len(alphas) >= _LIMIT:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent data channel budget exceeded', obj_name=obj.name)
            continue
        try:
            mesh.calc_tangents(uvmap=uv_name)
            tangent = np.empty((len(mesh.loops), 3), np.float32)
            sign = np.empty(len(mesh.loops), np.float32)
            mesh.loops.foreach_get('tangent', tangent.ravel())
            mesh.loops.foreach_get('bitangent_sign', sign)
        except (RuntimeError, ValueError) as error:
            SuperLuxCoreErrorLog.add_warning('Normal Map: tangent calculation failed: ' + str(error), obj_name=obj.name)
            continue
        indices = (normal_index, len(colors), len(alphas))
        colors.append(np.ascontiguousarray(tangent))
        alphas.append(np.ascontiguousarray(sign))
        mapping[key] = by_uv[uv_name] = indices
