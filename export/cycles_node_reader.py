import bpy
import pysuperluxcore
import PyOpenColorIO as ocio
from ctypes import c_float
from .. import utils
from ..utils import node as utils_node
from ..utils.errorlog import SuperLuxCoreErrorLog
from . import named_attributes
from . import normal_map_attributes
from .image import ImageExporter
import math


def _filter_glossy_active():
    """Cycles Filter Glossy is exported (path.filterglossy): sharp glass
    must stay a microfacet lobe the engine can blur."""
    try:
        return bpy.context.scene.superluxcore.config.path.cycles_filter_glossy > 0
    except Exception:
        return False
from math import degrees, log
from mathutils import Euler, Matrix, Vector

class _UnsupportedValue(int):
    """A numeric fallback whose identity distinguishes valid zero inputs."""


ERROR_VALUE = _UnsupportedValue(0)
MISSING_IMAGE_COLOR = [1, 0, 1]
# Neutral fallbacks for unsupported outputs; never silently return black

# Node types with no SuperLuxCore equivalent — the generic fallback path uses
# these to emit a specific reason instead of a bare "unsupported" warning.
_UNSUPPORTED_NODE_NOTES = {
    "ShaderNodeScript": "OSL scripts cannot be executed by SuperLuxCore",
    "ShaderNodeShaderToRGB": "shader-to-color requires an Eevee-style raster pass",
    "ShaderNodeOutputAOV": "custom AOVs are written via SuperLuxCore film outputs, not material nodes",
    "ShaderNodeOutputLineStyle": "Freestyle line-style output has no SuperLuxCore equivalent",
    "ShaderNodeLightFalloff": "light falloff is configured on SuperLuxCore light definitions",
    "ShaderNodeRaycast": "scene raycast queries are not available to SuperLuxCore textures",
    "ShaderNodeRadialTiling": "radial-tiling segment decomposition is a "
        "piecewise-transform too complex for the texture stack",
    "ShaderNodeTexIES": "IES profiles live on SuperLuxCore light definitions, not material textures",
    "ShaderNodeTexSky": "sky models exist as SuperLuxCore lights (sky2/sun), not material textures",
    "ShaderNodeSqueeze": "Freestyle squeeze value has no shading meaning",
    "ShaderNodeUVAlongStroke": "Freestyle stroke UVs have no shading meaning",
    "ShaderNodeBackground": "Background is a world-shader node; use Emission in materials",
}
FALLBACK_COLOR = [0.5, 0.5, 0.5]
FALLBACK_FLOAT = 0.5
FALLBACK_VECTOR = [0.0, 0.0, 0.0]

# ShaderNodeLightPath output socket -> SuperLuxCore "rayinfo" texture channel.
# The engine fills HitPoint with the context of the incoming ray during
# Scene::Intersect() (ray flags, generating BSDF event, path depth
# counters, segment length). See SuperLuxCore slg/textures/hitpoint/rayinfo.h.
_LIGHT_PATH_CHANNELS = {
    "Is Camera Ray": "iscameraray",
    "Is Shadow Ray": "isshadowray",
    "Is Diffuse Ray": "isdiffuseray",
    "Is Glossy Ray": "isglossyray",
    "Is Singular Ray": "issingularray",
    "Is Reflection Ray": "isreflectionray",
    "Is Transmission Ray": "istransmissionray",
    # Blender 4.x output; also 1 for hits inside volumes
    "Is Volume Scatter Ray": "isvolumescatterray",
    "Ray Length": "raylength",
    "Ray Depth": "raydepth",
    "Diffuse Depth": "diffusedepth",
    "Glossy Depth": "glossydepth",
    # Cycles counts transparent BSDF crossings; SuperLuxCore increments the
    # path transparentDepth while stepping through pass-through materials
    "Transparent Depth": "transparentdepth",
    "Transmission Depth": "transmissiondepth",
}

math_operation_map = {
    "MULTIPLY": "scale",
    "GREATER_THAN": "greaterthan",
    "LESS_THAN": "lessthan",
}


def _bump_filter_width(node_tree, seen=None):
    """Filter Width of the tree's Bump nodes (groups included); None when
    the tree has none. Blender < 4.4 had no input: one pixel."""
    seen = seen if seen is not None else set()
    if node_tree is None or node_tree.name in seen:
        return None
    seen.add(node_tree.name)
    widths = []
    for n in node_tree.nodes:
        if n.bl_idname == "ShaderNodeBump":
            sk = n.inputs.get("Filter Width")
            widths.append(sk.default_value if sk is not None else 1.0)
        elif n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None:
            w = _bump_filter_width(n.node_tree, seen)
            if w is not None:
                widths.append(w)
    return max(widths) if widths else None


def _apply_bump_filter_width(node_tree, props):
    """Cycles evaluates Bump height differences over Filter Width times the
    pixel footprint, which smooths sub-pixel bump detail at a distance;
    the engine's material bumpfilterwidth reproduces it. Applied to every
    bumped material the tree defined (mix members included)."""
    fw = _bump_filter_width(node_tree)
    if not fw:
        return
    for key in props.GetAllNamesRE(r"scene\.materials\..*\.bumptex"):
        props.Set(pysuperluxcore.Property(key[:-len("bumptex")] + "bumpfilterwidth", fw))


def _set_two_sided_emission(props, superluxcore_name):
    """Cycles' emission closure is two-sided (|N.w|): a mesh emitter lights
    and shows the same radiance from both faces. Flag every material this
    conversion produced (a mix material's emission is read on the
    top-level material). Light objects are exported elsewhere and stay
    one-sided like Cycles area lights."""
    prefix = "scene.materials." + superluxcore_name
    for key in props.GetAllNames(prefix):
        if key.endswith(".type"):
            props.Set(pysuperluxcore.Property(key[:-len("type")] + "emission.twosided", True))


def convert(material, props, superluxcore_name, obj_name=""):
    # print("Converting Cycles node tree of material", material.name_full)
    output = material.node_tree.get_output_node("CYCLES")
    if output is None:
        return black(superluxcore_name)

    link = utils_node.get_link(output.inputs["Surface"])
    volume_link = utils_node.get_link(output.inputs["Volume"]) if "Volume" in output.inputs else None

    # 출력 변위는 여기서 범프를 적용하고 오브젝트 캐시에서 실제 메시 변위를 적용한다.

    if link is None and volume_link is None:
        return black(superluxcore_name)

    if link is not None:
        result = _node(link.from_node, link.from_socket, props, material, superluxcore_name, obj_name)
        if result is ERROR_VALUE:
            return black(superluxcore_name)

        assert result == superluxcore_name
    else:
        # Volume-only material: an invisible surface carrying the interior volume
        props.Set(utils.luxutils.create_props("scene.materials." + superluxcore_name + ".", {
            "type": "null",
        }))

    # BUMP/BOTH의 출력 변위는 표면 법선에도 적용하며 진짜 변위와 구분한다.
    displacement = get_displacement_link(material)
    if displacement is not None and getattr(material, "displacement_method", "BUMP") in {"BUMP", "BOTH"}:
        disp_node = displacement.from_node
        if disp_node.bl_idname == "ShaderNodeDisplacement":
            height = _socket(disp_node.inputs["Height"], props, material, obj_name, None)
            midlevel = _socket(disp_node.inputs["Midlevel"], props, material, obj_name, None)
            scale = _socket(disp_node.inputs["Scale"], props, material, obj_name, None)
            bump_height = _tex_binary("scale", _tex_binary("subtract", height, midlevel,
                superluxcore_name + "_disp_offset", props), scale, superluxcore_name + "_disp_bump", props)
        elif displacement.from_socket.type == "VALUE":
            bump_height = _node(disp_node, displacement.from_socket, props, material,
                                obj_name=obj_name)
        else:
            bump_height = None
            SuperLuxCoreErrorLog.add_warning("출력 벡터 변위의 범프 변환은 추가 구현이 필요합니다", obj_name=obj_name)
        if bump_height is not None:
            bump_key = "scene.materials." + superluxcore_name + ".bumptex"
            if props.IsDefined(bump_key):
                previous = props.Get(bump_key).Get()
                previous = previous[0] if len(previous) == 1 else previous
                bump_height = _tex_binary("add", previous, bump_height, superluxcore_name + "_disp_composed", props)
            props.Set(pysuperluxcore.Property(bump_key, bump_height))

    _apply_bump_filter_width(material.node_tree, props)
    _set_two_sided_emission(props, superluxcore_name)

    if volume_link is not None:
        volume_defs = _volume(volume_link.from_node, volume_link.from_socket,
                              props, material, superluxcore_name, obj_name)
        if volume_defs is not None:
            volume_defs = _promote_textured_volume(volume_defs, obj_name)
            # Cycles volumes always scatter multiply; the engine default
            # (single scattering) rendered every converted medium dark
            # (a furnace volume sphere at 0.42 of the background)
            if volume_defs.get("type") in ("homogeneous", "heterogeneous"):
                volume_defs.setdefault("multiscattering", True)
            volume_name = superluxcore_name + "_volume"
            props.Set(utils.luxutils.create_props("scene.volumes." + volume_name + ".", volume_defs))
            props.Set(pysuperluxcore.Property(
                "scene.materials." + superluxcore_name + ".volume.interior", volume_name))
        # If None, _volume already logged a warning

    return superluxcore_name, props


def _promote_textured_volume(definitions, obj_name):
    """Ray-march volumes whose coefficients vary in space.

    "clear"/"homogeneous" evaluate their coefficient textures once per ray
    segment, so a Cycles volume with a textured density (height falloff,
    noise fog) rendered as one constant - or not at all. Any textured
    coefficient switches to "heterogeneous" with a step sized from the
    carrier object (about 256 steps across its diagonal).
    """
    if definitions.get("type") not in ("clear", "homogeneous"):
        return definitions
    if not any(_is_textured(definitions.get(k))
               for k in ("absorption", "scattering", "emission")):
        return definitions
    diagonal = 1.0
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    if obj is not None:
        diagonal = max(obj.dimensions.length, 1e-3)
    step = max(diagonal / 256.0, 1e-3)
    promoted = dict(definitions)
    promoted["type"] = "heterogeneous"
    promoted.setdefault("scattering", [0.0, 0.0, 0.0])
    promoted["steps.size"] = step
    promoted["steps.maxcount"] = int(math.ceil(diagonal / step)) + 1
    return promoted


def get_displacement_link(material):
    """
    Returns the link feeding the Cycles output's Displacement socket, or
    None. Used by the object cache to decide whether to wrap the mesh in a
    SuperLuxCore "displacement" shape.
    """
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return None
    output = node_tree.get_output_node("CYCLES")
    if output is None:
        return None
    disp_input = output.inputs.get("Displacement")
    if disp_input is None or not disp_input.is_linked:
        return None
    return utils_node.get_link(disp_input)


def export_displacement(link, props, material, obj_name):
    """
    Exports the textures driving a Cycles Displacement/Vector Displacement
    node into props and returns the parameters for a SuperLuxCore "displacement"
    shape, or None when the link is not a supported displacement node.
    """
    node = link.from_node

    if node.bl_idname == "ShaderNodeDisplacement":
        if getattr(node, "space", "OBJECT") != "OBJECT":
            SuperLuxCoreErrorLog.add_warning(
                'Displacement node "%s": world space is not supported, '
                "object space is used instead" % node.name, obj_name=obj_name)
        height = _socket(node.inputs["Height"], props, material, obj_name, None)
        if height is ERROR_VALUE:
            return None
        scale = _socket(node.inputs["Scale"], props, material, obj_name, None)
        midlevel = _socket(node.inputs["Midlevel"], props, material, obj_name, None)
        # 연결 Scale·Midlevel도 높이 텍스처에 포함한다.
        name = str(node.as_pointer()) + "_shape_displacement"
        height = _tex_binary("scale", _tex_binary("subtract", height, midlevel,
            name + "_offset", props), scale, name, props)
        return {"map": height, "map.type": "height", "scale": 1.0, "offset": 0.0}

    if node.bl_idname == "ShaderNodeVectorDisplacement":
        vector = _socket(node.inputs["Vector"], props, material, obj_name, None)
        scale = _socket(node.inputs["Scale"], props, material, obj_name, None)
        midlevel = _socket(node.inputs["Midlevel"], props, material, obj_name, None)
        if any(value is ERROR_VALUE for value in (vector, scale, midlevel)):
            return None
        name = str(node.as_pointer()) + "_shape_vector_displacement"
        vector = _tex_binary("scale", _tex_binary("subtract", vector, midlevel,
            name + "_offset", props), scale, name, props)
        definitions = {"map": vector, "map.type": "vector",
                       "map.space": node.space.lower(), "scale": 1.0, "offset": 0.0}
        identity = normal_map_attributes.resolve_identity(obj_name)
        if identity is not None:
            definitions.update(zip(("map.vertexidlowindex", "map.vertexidhighindex"), identity))
            definitions["map.vertexidsmoothflag"] = True
            definitions["map.normaldelta"] = identity[2]
        if node.space == "TANGENT":
            indices = normal_map_attributes.resolve(obj_name, "")
            if indices is not None:
                definitions.update(zip(("map.normalindex", "map.tangentindex", "map.signindex"), indices))
        return definitions

    # Anything else plugged straight into Displacement behaves like bump in
    # Cycles — the material-level Normal/bump path covers that case.
    return None


def _scalar_or_warn(socket, fallback, node, obj_name):
    """ Reads a scalar socket; warns and falls back when it is textured. """
    if socket.is_linked:
        SuperLuxCoreErrorLog.add_warning(
            'Node "%s": textured "%s" input is not supported for '
            "displacement, using default value" % (node.name, socket.name),
            obj_name=obj_name)
        return fallback
    return socket.default_value


def _imagemap_filter(node, obj_name):
    """ Cycles' Image/Environment Texture `interpolation` -> imagemap filter.
    Cycles offers Closest/Linear/Cubic/Smart; the engine has nearest/linear.
    Closest -> nearest; everything else -> linear (warn on Cubic/Smart). """
    interp = getattr(node, "interpolation", "Linear")
    if interp == "Closest":
        return "nearest"
    if interp in ("Cubic", "Smart"):
        SuperLuxCoreErrorLog.add_warning(
            f'Node "{node.name}": interpolation "{interp}" is approximated '
            "by bilinear (the engine has no cubic/lazy-continuous filter)",
            obj_name=obj_name)
    return "linear"

def black(superluxcore_name="__BLACK__"):
    props = pysuperluxcore.Properties()
    props.SetFromString("""
    scene.materials.{mat_name}.type = matte
    scene.materials.{mat_name}.kd = 0
    """.format(mat_name=superluxcore_name))
    return superluxcore_name, props


def _warn_unsupported(node, reason, fallback, obj_name=""):
    """
    Log a warning about an unsupported node/output/feature and return a
    neutral fallback so the material still renders plausibly instead of
    silently turning black.
    """
    SuperLuxCoreErrorLog.add_warning(
        f'Node "{node.name}" ({node.bl_idname}): {reason}', obj_name=obj_name)
    return fallback


def _tex_helper(props, name, definitions):
    """Emit a scene.textures.* definition under the given name, return the name."""
    tex_name = utils.sanitize_superluxcore_name(name)
    props.Set(utils.luxutils.create_props("scene.textures." + tex_name + ".", definitions))
    return tex_name


def _socket_nondefault(socket, default, eps=1e-4):
    """
    True when an input socket is linked or its constant value differs from
    `default` (the Principled node's factory value). Vector/color defaults are
    compared per channel; `socket` may be None on Blender versions where the
    input does not exist.
    """
    if socket is None:
        return False
    if socket.is_linked:
        return True
    value = getattr(socket, "default_value", default)
    if isinstance(default, (list, tuple)):
        try:
            return any(abs(v - d) > eps for v, d in zip(list(value)[:3], default))
        except TypeError:
            return True
    try:
        return abs(float(value) - float(default)) > eps
    except (TypeError, ValueError):
        return True


def _socket_active(socket):
    """True when a [0,1] weight socket is linked or has a non-zero constant."""
    return socket is not None and (
        socket.is_linked or socket.default_value != 0.0)


def _color_is_gray(value, eps=5e-2):
    """True when a color constant is (near) grayscale, i.e. carries no hue."""
    if _is_textured(value):
        return False
    try:
        v = list(value)[:3]
    except TypeError:
        return True
    return max(v) - min(v) <= eps


def _const_binary(op, value1, value2):
    """Fold a two-operand math op on plain constants (floats or 3-lists)."""
    def as_vec(v):
        return list(v)[:3] if isinstance(v, (list, tuple)) else [v, v, v]

    try:
        if op == "dotproduct":
            a, b = as_vec(value1), as_vec(value2)
            return sum(x * y for x, y in zip(a, b))
        if isinstance(value1, (list, tuple)) or isinstance(value2, (list, tuple)):
            a, b = as_vec(value1), as_vec(value2)
            if op == "add":
                return [x + y for x, y in zip(a, b)]
            if op == "subtract":
                return [x - y for x, y in zip(a, b)]
            if op in {"scale", "multiply"}:
                return [x * y for x, y in zip(a, b)]
            if op == "divide":
                return [x / y if y != 0 else 0.0 for x, y in zip(a, b)]
            return None
        if op == "add":
            return value1 + value2
        if op == "subtract":
            return value1 - value2
        if op in {"scale", "multiply"}:
            return value1 * value2
        if op == "divide":
            return value1 / value2 if value2 != 0 else 0.0
        if op == "power":
            if value2 == 0.:
                return 1.
            if value1 == 0. or (value1 < 0. and value2 != int(value2)):
                return 0.
            return value1 ** value2
        if op == "lessthan":
            return 1.0 if value1 < value2 else 0.0
        if op == "greaterthan":
            return 1.0 if value1 > value2 else 0.0
    except (TypeError, IndexError):
        pass
    return None


def _tex_binary(op, texture1, texture2, name, props):
    """
    Emit a two-operand math texture (add/subtract/scale/divide/dotproduct/power),
    folding constants when both operands are plain values.
    """
    if not _is_textured(texture1) and not _is_textured(texture2):
        folded = _const_binary(op, texture1, texture2)
        if folded is not None:
            return folded
    if op == "power":
        # Power's SDL operands are base/exponent, not texture1/texture2.
        return _tex_helper(props, name, {
            "type": op,
            "base": texture1,
            "exponent": texture2,
        })
    return _tex_helper(props, name, {
        "type": op,
        "texture1": texture1,
        "texture2": texture2,
    })


def _tex_mix(texture1, texture2, amount, name, props):
    """Emit a mix texture, folding constants."""
    if not _is_textured(texture1) and not _is_textured(texture2) \
            and not _is_textured(amount):
        def as_vec(v):
            return list(v)[:3] if isinstance(v, (list, tuple)) else [v, v, v]
        a, b = as_vec(texture1), as_vec(texture2)
        folded = [x * (1 - amount) + y * amount for x, y in zip(a, b)]
        if not isinstance(texture1, (list, tuple)) and not isinstance(texture2, (list, tuple)):
            return folded[0]
        return folded
    return _tex_helper(props, name, {
        "type": "mix",
        "texture1": texture1,
        "texture2": texture2,
        "amount": amount,
    })


def _tex_lerp(a, b, factor, name, props):
    """엔진 Mix의 계수 제한을 피하고 외삽까지 보존한다."""
    delta = _tex_binary("subtract", b, a, name + "_delta", props)
    weighted = _tex_binary("scale", delta, factor, name + "_weighted", props)
    return _tex_binary("add", a, weighted, name, props)


def _tex_clamp(value, low, high, name, props):
    """연결된 경계와 채널별 경계도 처리한다."""
    value = _tex_mathfunc("max", value, low, name + "_min", props)
    return _tex_mathfunc("min", value, high, name, props)


def _group_socket(sockets, requested):
    """표시 이름이 중복되어도 그룹 인터페이스 식별자를 유지한다."""
    identifier = getattr(requested, "identifier", None)
    return next((s for s in sockets if s.identifier == identifier), None)


def _texture_coordinates(node, props, material, obj_name, stack, name):
    """절차 텍스처의 기본 Generated와 연결 좌표를 구분한다."""
    socket = node.inputs.get("Vector")
    if socket is not None and socket.is_linked:
        return _socket(socket, props, material, obj_name, stack)
    return _tex_helper(props, name + "_generated", {
        "type": "hitpoint", "channel": "generated"})


def _output_is_color(socket):
    """색 출력이 좌표 데이터로만 쓰이면 스펙트럼 색 변환을 생략한다."""
    links = list(getattr(socket, "links", ()) or ())
    return not (links and all(link.to_socket.type == "VECTOR" for link in links))


def _tex_band(amount, samples, interpolation, name, props):
    """고해상도 표를 GPU의 16항목 테이블로 나누어 정밀도를 유지한다."""
    if not _is_textured(amount):
        value = float(amount)
        if value <= samples[0][0]:
            return samples[0][1]
        for i in range(1, len(samples)):
            left, right = samples[i - 1], samples[i]
            if value < right[0]:
                if interpolation == "none":
                    return left[1]
                factor = (value - left[0]) / (right[0] - left[0])
                return [a + (b - a) * factor for a, b in zip(left[1], right[1])]
        return samples[-1][1]
    # 원 표에 대한 채널별 최대 오차를 제한하고 평평한 구간을 압축한다.
    if interpolation == "linear" and len(samples) > 16:
        retained = {0, len(samples) - 1}
        pending = [(0, len(samples) - 1)]
        while pending:
            left, right = pending.pop()
            x0, v0 = samples[left]
            x1, v1 = samples[right]
            worst, split = 0., None
            for i in range(left + 1, right):
                x, values = samples[i]
                factor = (x - x0) / (x1 - x0) if x1 != x0 else 0.
                error = max(abs(v - (a + (b - a) * factor)) for v, a, b in zip(values, v0, v1))
                if error > worst:
                    worst, split = error, i
            if worst > 1e-4:
                retained.add(split)
                pending.extend(((left, split), (split, right)))
        samples = [samples[i] for i in sorted(retained)]
    chunks = [samples[i:i + 16] for i in range(0, len(samples) - 1, 15)]
    def emit(index):
        chunk = chunks[index]
        definitions = {"type": "band", "amount": amount, "offsets": len(chunk), "interpolation": interpolation}
        for i, (position, values) in enumerate(chunk):
            definitions[f"offset{i}"] = position
            definitions[f"value{i}"] = values
        return _tex_helper(props, name + f"_table{index}", definitions)
    def combine(begin, end):
        if end - begin == 1:
            return emit(begin)
        middle = (begin + end) // 2
        left, right = combine(begin, middle), combine(middle, end)
        boundary = chunks[middle][0][0]
        select = _tex_lessthan(amount, boundary, name + f"_boundary{middle}", props)
        return _tex_mix(right, left, select, name + f"_select{begin}_{end}", props)
    return combine(0, len(chunks))


def _map_range(node, props, material, obj_name, stack, name):
    """동적 소켓·역방향 범위·벡터 보간·클램프를 산술 텍스처로 전달한다."""
    vector = node.data_type == "FLOAT_VECTOR"
    values = {}
    for key in ("Vector" if vector else "Value", "From Min", "From Max", "To Min", "To Max", "Steps"):
        candidates = [s for s in node.inputs if s.name == key and (s.type == "VECTOR") == vector]
        socket = next((s for s in candidates if s.enabled), candidates[0])
        values[key] = _socket(socket, props, material, obj_name, stack)
    results = []
    for channel in range(3 if vector else 1):
        v = {k: _split_chan(value, channel, name + f"_{k}_{channel}", props)
             if vector else value for k, value in values.items()}
        tag = name + f"_range{channel}"
        width = _tex_binary("subtract", v["From Max"], v["From Min"], tag + "_width", props)
        factor = _tex_binary("divide", _tex_binary("subtract", v["Vector" if vector else "Value"], v["From Min"], tag + "_offset", props), width, tag + "_factor", props)
        mode = node.interpolation_type
        if mode == "STEPPED":
            count = _tex_binary("add", v["Steps"], 1., tag + "_count", props)
            steps = _tex_mathfunc("floor", _tex_binary("scale", factor, count, tag + "_steps", props), None, tag + "_floor", props)
            factor = _tex_binary("divide", steps, v["Steps"], tag + "_stepped", props)
            factor = _tex_binary("scale", factor, _tex_greaterthan(v["Steps"], 0., tag + "_hassteps", props), tag + "_validsteps", props)
        elif mode in {"SMOOTHSTEP", "SMOOTHERSTEP"}:
            factor = _tex_clamp(factor, 0., 1., tag + "_smoothclamp", props)
            square = _tex_binary("scale", factor, factor, tag + "_square", props)
            if mode == "SMOOTHSTEP":
                polynomial = _tex_binary("subtract", 3., _tex_binary("scale", 2., factor, tag + "_two", props), tag + "_poly", props)
                factor = _tex_binary("scale", square, polynomial, tag + "_smooth", props)
            else:
                polynomial = _tex_binary("add", _tex_binary("scale", factor, _tex_binary("subtract", _tex_binary("scale", factor, 6., tag + "_six", props), 15., tag + "_fifteen", props), tag + "_middle", props), 10., tag + "_poly", props)
                factor = _tex_binary("scale", _tex_binary("scale", square, factor, tag + "_cube", props), polynomial, tag + "_smooth", props)
        result = _tex_lerp(v["To Min"], v["To Max"], factor, tag + "_result", props)
        if node.clamp and mode in {"LINEAR", "STEPPED"}:
            low = _tex_mathfunc("min", v["To Min"], v["To Max"], tag + "_low", props)
            high = _tex_mathfunc("max", v["To Min"], v["To Max"], tag + "_high", props)
            result = _tex_clamp(result, low, high, tag + "_clamp", props)
        if not vector:
            valid = _tex_greaterthan(_tex_unary("abs", width, None, tag + "_abswidth", props), 0., tag + "_nonzero", props)
            result = _tex_binary("scale", result, valid, tag + "_valid", props)
        results.append(result)
    if not vector:
        return results[0]
    return _tex_helper(props, name, {"type": "makefloat3", **{f"texture{i+1}": v for i, v in enumerate(results)}})


def _magic_texture(node, output, props, material, obj_name, stack, name):
    """Magic의 깊이 속성과 연결 Scale·Distortion·Vector를 모두 평가한다."""
    serial = 0
    def binary(op, a, b):
        nonlocal serial
        serial += 1
        return _tex_binary(op, a, b, name + f"_m{serial}", props)
    def trig(op, value):
        nonlocal serial
        serial += 1
        return _tex_mathfunc(op, value, None, name + f"_m{serial}", props)
    vector = _texture_coordinates(node, props, material, obj_name, stack, name)
    scale = _socket(node.inputs["Scale"], props, material, obj_name, stack)
    distortion = _socket(node.inputs["Distortion"], props, material, obj_name, stack)
    scaled = binary("scale", vector, scale)
    p = [_split_chan(scaled, i, name + f"_p{i}", props) for i in range(3)]
    x = trig("sin", binary("scale", binary("add", binary("add", p[0], p[1]), p[2]), 5.))
    y = trig("cos", binary("scale", binary("subtract", binary("subtract", p[1], p[0]), p[2]), 5.))
    z = binary("scale", trig("cos", binary("scale", binary("subtract", binary("subtract", p[2], p[0]), p[1]), 5.)), -1.)
    depth = int(node.turbulence_depth)
    if depth > 0:
        x, y, z = [binary("scale", v, distortion) for v in (x, y, z)]
        operations = (
            (1, "cos", (-1, 1, -1), -1), (0, "cos", (1, -1, -1), 1),
            (2, "sin", (-1, -1, -1), 1), (0, "cos", (-1, 1, -1), -1),
            (1, "sin", (-1, 1, 1), -1), (1, "cos", (-1, 1, 1), -1),
            (0, "cos", (1, 1, 1), 1), (2, "sin", (1, 1, -1), 1),
            (0, "cos", (-1, -1, 1), -1), (1, "sin", (1, -1, 1), -1))
        channels = [x, y, z]
        for index, op, signs, sign in operations[:depth]:
            value = binary("add", binary("add", binary("scale", channels[0], signs[0]), binary("scale", channels[1], signs[1])), binary("scale", channels[2], signs[2]))
            channels[index] = binary("scale", trig(op, value), binary("scale", sign, distortion))
        x, y, z = channels
    denominator = binary("scale", distortion, 2.)
    nonzero = _tex_greaterthan(_tex_unary("abs", distortion, None, name + "_absdist", props), 0., name + "_nonzero", props)
    colors = [binary("subtract", .5, _tex_lerp(v, binary("divide", v, denominator), nonzero, name + f"_normalized{i}", props)) for i, v in enumerate((x, y, z))]
    if output.name == "Fac":
        return binary("scale", binary("add", binary("add", colors[0], colors[1]), colors[2]), 1./3.)
    return _tex_helper(props, name, {"type": "makefloat3", "color": _output_is_color(output), **{f"texture{i+1}": v for i, v in enumerate(colors)}})


def _tex_lessthan(t1, t2, name, props):
    """lessthan with constant folding (1 when t1 < t2)."""
    if not _is_textured(t1) and not _is_textured(t2):
        if isinstance(t1, (list, tuple)) or isinstance(t2, (list, tuple)):
            a = list(t1)[:3] if isinstance(t1, (list, tuple)) else [t1] * 3
            b = list(t2)[:3] if isinstance(t2, (list, tuple)) else [t2] * 3
            return [1.0 if x < y else 0.0 for x, y in zip(a, b)]
        return 1.0 if t1 < t2 else 0.0
    return _tex_helper(props, name, {
        "type": "lessthan", "texture1": t1, "texture2": t2})


def _tex_greaterthan(t1, t2, name, props):
    """greaterthan with constant folding."""
    if not _is_textured(t1) and not _is_textured(t2):
        if isinstance(t1, (list, tuple)) or isinstance(t2, (list, tuple)):
            a = list(t1)[:3] if isinstance(t1, (list, tuple)) else [t1] * 3
            b = list(t2)[:3] if isinstance(t2, (list, tuple)) else [t2] * 3
            return [1.0 if x > y else 0.0 for x, y in zip(a, b)]
        return 1.0 if t1 > t2 else 0.0
    return _tex_helper(props, name, {
        "type": "greaterthan", "texture1": t1, "texture2": t2})


_MATHFUNC_UNARY_OPS = {
    "SINE": "sin", "COSINE": "cos", "TANGENT": "tan",
    "ARCSINE": "asin", "ARCCOSINE": "acos", "ARCTANGENT": "atan",
    "SINH": "sinh", "COSH": "cosh", "TANH": "tanh",
    "INVERSE_SQRT": "invsqrt",
    "FLOOR": "floor", "CEIL": "ceil", "TRUNC": "trunc", "FRACT": "fract",
}

_MATHFUNC_BINARY_OPS = {
    "ARCTAN2": "atan2", "FLOORED_MODULO": "floormod",
}


def _floormod_fold(a, b):
    return 0.0 if b == 0.0 else a - b * math.floor(a / b)


_MATHFUNC_FOLD = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "exp": math.exp, "ln": math.log,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "invsqrt": lambda a: 1.0 / math.sqrt(max(a, 1e-9)),
    "floormod": _floormod_fold,
    "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc,
    "fract": lambda value: value - math.floor(value),
    "max": lambda a, b: b if math.isnan(a) else max(a, b),
    "min": lambda a, b: b if math.isnan(a) else min(a, b),
    "lessequal": lambda a, b: float(a <= b),
}


def _tex_mathfunc(op, tex1, tex2, name, props):
    """Emit a native unary/binary mathfunc texture, folding constants."""
    binary = op in ("atan2", "floormod", "max", "lessequal", "min")
    textured = _is_textured(tex1) or (binary and _is_textured(tex2))
    if not textured:
        def as_vec(value):
            return list(value)[:3] if isinstance(value, (list, tuple)) else [value] * 3
        try:
            evaluate = _MATHFUNC_FOLD[op]
            if isinstance(tex1, (list, tuple)) or (binary and isinstance(tex2, (list, tuple))):
                if binary:
                    return [evaluate(a, b) for a, b in zip(as_vec(tex1), as_vec(tex2))]
                return [evaluate(value) for value in as_vec(tex1)]
            return evaluate(tex1, tex2) if binary else evaluate(tex1)
        except (ValueError, OverflowError, ZeroDivisionError):
            pass  # domain error at fold time — let the texture evaluate it
    definitions = {"type": "mathfunc", "op": op, "texture1": tex1}
    if binary:
        definitions["texture2"] = tex2
    return _tex_helper(props, name, definitions)


def _tex_unary(op, tex, arg, name, props):
    """
    Fold/emit single-input math textures: abs (arg=None),
    rounding (arg=increment), modulo (arg=modulus).
    """
    if not _is_textured(tex) and (arg is None or not _is_textured(arg)):
        def ap(f, v):
            if isinstance(v, (list, tuple)):
                return [f(x) for x in v[:3]]
            return f(v)
        if op == "abs":
            return ap(abs, tex)
        if op == "rounding":
            inc = arg if arg else 1.0
            return ap(lambda v: inc * round(v / inc) if inc else v, tex)
        if op == "modulo":
            return ap(lambda v: v % arg if arg else 0.0, tex)
    if op == "abs":
        return _tex_helper(props, name, {"type": "abs", "texture": tex})
    if op == "rounding":
        return _tex_helper(props, name, {
            "type": "rounding", "texture": tex, "increment": arg})
    if op == "modulo":
        return _tex_helper(props, name, {
            "type": "modulo", "texture": tex, "modulo": arg})
    raise ValueError(op)


def _split_chan(value, channel, name, props):
    """Extract one channel of a float3 value or texture (constants fold)."""
    if _is_textured(value):
        return _tex_helper(props, name, {
            "type": "splitfloat3", "texture": value, "channel": channel})
    if isinstance(value, (list, tuple)):
        return list(value)[channel]
    return value


def _combine3(x, y, z, name, props):
    """Reassemble three channel values into a float3 (constants fold)."""
    if _is_textured(x) or _is_textured(y) or _is_textured(z):
        return _tex_helper(props, name, {
            "type": "makefloat3",
            "texture1": x, "texture2": y, "texture3": z})
    def f(v):
        return v[0] if isinstance(v, (list, tuple)) else v
    return [f(x), f(y), f(z)]


def _smooth_min(a, b, k, name, props):
    """
    Polynomial smooth-min: h = clamp(0.5 + 0.5*(b-a)/k, 0, 1);
    result = mix(b, a, h) - k*h*(1-h). Folds constants.
    """
    if not any(_is_textured(t) for t in (a, b, k)):
        def _s(x):
            return x[0] if isinstance(x, (list, tuple)) else x
        va, vb, vk = _s(a), _s(b), max(_s(k), 1e-9)
        h = min(1.0, max(0.0, 0.5 + 0.5 * (vb - va) / vk))
        return vb * (1 - h) + va * h - vk * h * (1 - h)
    d = _tex_binary("subtract", b, a, f"{name}_d", props)
    hd = _tex_binary("divide", d, k, f"{name}_hd", props)
    hh = _tex_binary("scale", hd, 0.5, f"{name}_hh", props)
    hu = _tex_binary("add", 0.5, hh, f"{name}_hu", props)
    h = _tex_helper(props, f"{name}_h", {
        "type": "clamp", "texture": hu, "min": 0.0, "max": 1.0})
    mixv = _tex_mix(b, a, h, f"{name}_mx", props)
    one_h = _tex_binary("subtract", 1.0, h, f"{name}_1h", props)
    hh1 = _tex_binary("scale", h, one_h, f"{name}_hh1", props)
    corr = _tex_binary("scale", k, hh1, f"{name}_cr", props)
    return _tex_binary("subtract", mixv, corr, f"{name}_r", props)


def _v3_mathfunc(op, vec, name, props):
    """Elementwise mathfunc on a vector value or texture (folds consts)."""
    if not _is_textured(vec):
        v = list(vec)[:3] if isinstance(vec, (list, tuple)) else [vec] * 3
        try:
            return [_MATHFUNC_FOLD[op](x) for x in v]
        except (ValueError, OverflowError):
            pass
    comps = [_tex_mathfunc(op, _split_chan(vec, c, f"{name}_c{c}", props),
                           None, f"{name}_f{c}", props)
             for c in range(3)]
    return _combine3(comps[0], comps[1], comps[2], name, props)


def _const_mat_mul_vec(mat_rows, vec, name, props):
    """
    Apply a constant 3x3 matrix (3 rows of 3 floats) to a vector value or
    texture. Rows emit scale/add/makefloat3 helper textures when vec is
    texture-driven; constant vectors fold in Python.
    """
    if not _is_textured(vec):
        v = list(vec)[:3] if isinstance(vec, (list, tuple)) else [vec] * 3
        return [sum(mat_rows[r][c] * v[c] for c in range(3)) for r in range(3)]
    comps = [_split_chan(vec, c, f"{name}_s{c}", props) for c in range(3)]
    out = []
    for r in range(3):
        terms = [
            _tex_binary("scale", comps[c], mat_rows[r][c], f"{name}_r{r}{c}", props)
            for c in range(3) if mat_rows[r][c] != 0
        ]
        if not terms:
            out.append(0.0)
            continue
        acc = terms[0]
        for i, t in enumerate(terms[1:]):
            acc = _tex_binary("add", acc, t, f"{name}_r{r}p{i}", props)
        out.append(acc)
    return _combine3(out[0], out[1], out[2], name + "_mat", props)


def _vtransform_matrix(cfrom, cto, obj_name):
    """
    Constant world-space 4x4 matrix converting from coordinate space
    `cfrom` to `cto` ("WORLD"/"OBJECT"/"CAMERA"), or None when a space
    cannot be resolved (no object of that name, no scene camera).
    """
    def world_mat(space):
        if space == "WORLD":
            return Matrix.Identity(4)
        if space == "CAMERA":
            cam = bpy.context.scene.camera
            return cam.matrix_world.copy() if cam else None
        obj = bpy.data.objects.get(obj_name)
        return obj.matrix_world.copy() if obj else None

    m_from = world_mat(cfrom)
    m_to = world_mat(cto)
    if m_from is None or m_to is None:
        return None
    return m_to.inverted_safe() @ m_from


def _point_transform_channels(matrix, name, props, rows=(0, 1, 2)):
    """월드 히트 위치에 행렬을 적용해 필요한 동차 좌표 채널을 만든다."""
    position = _tex_helper(props, name + "_world", {"type": "hitpoint", "channel": "worldpos"})
    result = []
    for row in rows:
        value = _tex_helper(props, f"{name}_dot{row}", {
            "type": "dotproduct", "texture1": position,
            "texture2": [matrix[row][i] for i in range(3)]})
        result.append(_tex_binary("add", value, matrix[row][3], f"{name}_offset{row}", props))
    return result


def _blend_rgb(node, blend_type, fac, tex1, tex2, superluxcore_name, props, obj_name):
    """색 혼합의 채널별 연산·외삽·조건부 HSV 의미를 보존한다."""
    serial = 0
    def binary(op, a, b):
        nonlocal serial
        serial += 1
        return _tex_binary(op, a, b, superluxcore_name + f"_blend{serial}", props)
    def func(op, a, b=None):
        nonlocal serial
        serial += 1
        return _tex_mathfunc(op, a, b, superluxcore_name + f"_blend{serial}", props)
    def select(a, b, predicate):
        nonlocal serial
        serial += 1
        return _tex_mix(a, b, predicate, superluxcore_name + f"_select{serial}", props)
    def lerp(a, b, factor=fac):
        return binary("add", a, binary("scale", binary("subtract", b, a), factor))
    def absolute(a):
        nonlocal serial
        serial += 1
        return _tex_unary("abs", a, None, superluxcore_name + f"_abs{serial}", props)
    def rgb_to_hsv(color):
        channels = [_split_chan(color, i, superluxcore_name + f"_hsv{serial}_{i}", props) for i in range(3)]
        r, g, b = channels
        maximum = func("max", func("max", r, g), b)
        minimum = func("min", func("min", r, g), b)
        delta = binary("subtract", maximum, minimum)
        saturation = binary("divide", delta, maximum)
        red_h = binary("divide", binary("subtract", g, b), delta)
        green_h = binary("add", binary("divide", binary("subtract", b, r), delta), 2.)
        blue_h = binary("add", binary("divide", binary("subtract", r, g), delta), 4.)
        hue = select(blue_h, green_h, func("lessequal", maximum, g))
        hue = select(hue, red_h, func("lessequal", maximum, r))
        hue = func("floormod", binary("scale", hue, 1./6.), 1.)
        hue = select(hue, 0., func("lessequal", delta, 0.))
        return hue, saturation, maximum
    def hsv_to_rgb(hsv):
        h, saturation, value = hsv
        h = binary("scale", h, 6.)
        channels = []
        for offset in (0., 4., 2.):
            wave = absolute(binary("subtract", func("floormod", binary("add", h, offset), 6.), 3.))
            wave = func("min", func("max", binary("subtract", wave, 1.), 0.), 1.)
            channels.append(binary("scale", value, lerp(1., wave, saturation)))
        nonlocal serial
        serial += 1
        return _tex_helper(props, superluxcore_name + f"_rgb{serial}", {"type": "makefloat3", "color": _output_is_color(next(socket for socket in node.outputs if socket.enabled)), **{f"texture{i+1}": v for i, v in enumerate(channels)}})

    if blend_type in {"HUE", "SATURATION", "COLOR", "VALUE"}:
        h1, s1, v1 = rgb_to_hsv(tex1)
        h2, s2, v2 = rgb_to_hsv(tex2)
        if blend_type == "SATURATION":
            result = select(hsv_to_rgb((h1, lerp(s1, s2), v1)), tex1, func("lessequal", s1, 0.))
        elif blend_type == "VALUE":
            result = hsv_to_rgb((h1, s1, lerp(v1, v2)))
        else:
            target = hsv_to_rgb((h2, s1 if blend_type == "HUE" else s2, v1))
            result = select(lerp(tex1, target), tex1, func("lessequal", s2, 0.))
    else:
        result_channels = []
        for channel in range(3):
            a = _split_chan(tex1, channel, superluxcore_name + f"_a{channel}", props)
            b = _split_chan(tex2, channel, superluxcore_name + f"_b{channel}", props)
            if blend_type == "MIX":
                result = lerp(a, b)
            elif blend_type == "ADD":
                result = binary("add", a, binary("scale", b, fac))
            elif blend_type == "SUBTRACT":
                result = binary("subtract", a, binary("scale", b, fac))
            elif blend_type == "MULTIPLY":
                result = lerp(a, binary("scale", a, b))
            elif blend_type == "DIVIDE":
                result = select(lerp(a, binary("divide", a, b)), a, func("lessequal", absolute(b), 0.))
            elif blend_type == "SCREEN":
                result = lerp(a, binary("subtract", 1., binary("scale", binary("subtract", 1., a), binary("subtract", 1., b))))
            elif blend_type == "OVERLAY":
                dark = binary("scale", 2., binary("scale", a, b))
                light = binary("subtract", 1., binary("scale", 2., binary("scale", binary("subtract", 1., a), binary("subtract", 1., b))))
                result = lerp(a, select(dark, light, func("lessequal", .5, a)))
            elif blend_type in {"DARKEN", "LIGHTEN"}:
                result = lerp(a, func("min" if blend_type == "DARKEN" else "max", a, b))
            elif blend_type == "DIFFERENCE":
                result = lerp(a, absolute(binary("subtract", a, b)))
            elif blend_type == "EXCLUSION":
                target = binary("subtract", binary("add", a, b), binary("scale", 2., binary("scale", a, b)))
                result = func("max", lerp(a, target), 0.)
            elif blend_type == "DODGE":
                denominator = binary("subtract", 1., binary("scale", fac, b))
                ratio = func("min", binary("divide", a, denominator), 1.)
                result = select(ratio, 1., func("lessequal", denominator, 0.))
                result = select(result, 0., func("lessequal", absolute(a), 0.))
            elif blend_type == "BURN":
                denominator = lerp(1., b)
                ratio = binary("subtract", 1., binary("divide", binary("subtract", 1., a), denominator))
                result = select(func("min", func("max", ratio, 0.), 1.), 0., func("lessequal", denominator, 0.))
            elif blend_type == "SOFT_LIGHT":
                screen = binary("subtract", 1., binary("scale", binary("subtract", 1., a), binary("subtract", 1., b)))
                target = binary("add", binary("scale", binary("scale", binary("subtract", 1., a), b), a), binary("scale", a, screen))
                result = lerp(a, target)
            elif blend_type == "LINEAR_LIGHT":
                result = binary("add", a, binary("scale", fac, binary("subtract", binary("scale", b, 2.), 1.)))
            else:
                return None, superluxcore_name, _warn_unsupported(node, f"혼합 모드 {blend_type} 평가 경로 없음", tex1, obj_name)
            result_channels.append(result)
        result = _tex_helper(props, superluxcore_name + "_rgb", {"type": "makefloat3", "color": _output_is_color(next(socket for socket in node.outputs if socket.enabled)), **{f"texture{i+1}": v for i, v in enumerate(result_channels)}})
    return {"type": "scale", "texture1": result, "texture2": 1.}, superluxcore_name, None


def _mapping_node_values(mapping_node, obj_name):
    """
    Constant (location, rotation, scale) of a Cycles Mapping node.
    Linked transform inputs are approximated by their default value.
    """
    def const_input(name, fallback):
        socket = mapping_node.inputs.get(name)
        if socket is None:
            return fallback
        if socket.is_linked:
            SuperLuxCoreErrorLog.add_warning(
                f'Mapping node "{mapping_node.name}": linked "{name}" input is not '
                "supported, using its constant default value", obj_name=obj_name)
        try:
            return list(socket.default_value)[:3]
        except TypeError:
            return socket.default_value

    return (const_input("Location", [0, 0, 0]),
            const_input("Rotation", [0, 0, 0]),
            const_input("Scale", [1, 1, 1]))


def _mapping_matrix(location, rotation, scale):
    """Blender Mapping node transform: scale, then rotate, then translate."""
    return (Matrix.Translation(Vector(location)) @
            Euler(rotation).to_matrix().to_4x4() @
            Matrix.Diagonal(Vector(scale)).to_4x4())


def _mapping_uv_defs(location, rotation, scale, flip_v):
    """
    uvmapping2d definitions for a Mapping node transform (rotation around the
    origin, an approximation of Blender's transform order).
    With flip_v the v-flip required by Blender image space is folded in.
    """
    v_scale = scale[1] if len(scale) > 1 else scale[0]
    if flip_v:
        # Image sampling applies v_img = 1 - v_uv, so the user transform
        # composes to v_img = -sy * v + (1 - ly); the rotation direction flips
        # together with the v axis
        return {
            "mapping.type": "uvmapping2d",
            "mapping.uvscale": [scale[0], -v_scale],
            "mapping.uvdelta": [location[0], 1 - location[1]],
            "mapping.rotation": -degrees(rotation[2]),
        }
    return {
        "mapping.type": "uvmapping2d",
        "mapping.uvscale": [scale[0], v_scale],
        "mapping.uvdelta": [location[0], location[1]],
        "mapping.rotation": degrees(rotation[2]),
    }


def _uv_layer_index(obj_name, uv_map_name):
    """Resolve a UV layer name to the exported uvindex of the object's mesh."""
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    uv_layers = getattr(getattr(obj, "data", None), "uv_layers", None)
    if uv_layers is None:
        return None
    index = uv_layers.find(uv_map_name)
    return index if index >= 0 else None


def _color_attribute_index(obj_name, attribute_name):
    """Resolve a color attribute name to the exported dataindex of the mesh."""
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    attributes = getattr(getattr(obj, "data", None), "color_attributes", None)
    if attributes is None:
        return None
    for index, attribute in enumerate(attributes):
        if attribute.name == attribute_name:
            return index
    return None


def _mapping_3d_space(mapping_node, obj_name):
    """(mapping.type, extra defs) for the coordinates feeding a 3D Mapping.

    A Mapping node transforms whatever reaches its own Vector input; the
    3D mapping block must evaluate that space, not always object space -
    UV -> Mapping -> procedural texture was rendered in object coordinates.
    """
    link = utils_node.get_link(mapping_node.inputs["Vector"])
    src = link.from_node if link else None
    sock = link.from_socket.name if link else None
    if src is not None and src.bl_idname == "ShaderNodeTexCoord" and sock == "UV":
        return "uvmapping3d", {}
    if src is not None and src.bl_idname == "ShaderNodeUVMap":
        index = _uv_layer_index(obj_name, getattr(src, "uv_map", ""))
        return "uvmapping3d", ({"mapping.uvindex": index} if index is not None else {})
    return "localmapping3d", {}


def _image_vector_projection(vector, projection, name, props):
    """Cycles Sphere/Tube remap [0,1] coordinates before projecting."""
    centered = _tex_binary("subtract", vector, [.5, .5, .5], name + "_center", props)
    centered = _tex_binary("scale", centered, 2., name + "_remap", props)
    x, y, z = [_split_chan(centered, i, name + f"_axis{i}", props) for i in range(3)]
    xy = _tex_binary("add", _tex_binary("scale", x, x, name + "_xx", props),
                     _tex_binary("scale", y, y, name + "_yy", props), name + "_xy", props)
    xy_valid = _tex_greaterthan(xy, 0., name + "_xy_valid", props)
    # Metal atan2(0,0) may be NaN; a later zero mask cannot remove it.
    angle_y = _tex_binary("add", y, _tex_binary("subtract", 1., xy_valid,
                                               name + "_axis_guard", props), name + "_angle_y", props)
    angle = _tex_mathfunc("atan2", x, angle_y, name + "_angle", props)
    u = _tex_binary("subtract", .5,
                    _tex_binary("scale", angle, 1. / (2. * math.pi), name + "_angle_uv", props),
                    name + "_u", props)
    u = _tex_binary("scale", u, xy_valid, name + "_safe_u", props)
    if projection == "SPHERE":
        length2 = _tex_binary("add", xy, _tex_binary("scale", z, z, name + "_zz", props),
                              name + "_length2", props)
        length = _tex_binary("power", length2, .5, name + "_length", props)
        ratio = _tex_binary("divide", z, length, name + "_ratio", props)
        ratio = _tex_clamp(ratio, -1., 1., name + "_acos_input", props)
        v = _tex_binary("subtract", 1.,
                        _tex_binary("scale", _tex_mathfunc("acos", ratio, None, name + "_acos", props),
                                    1. / math.pi, name + "_acos_uv", props), name + "_v", props)
        v = _tex_binary("scale", v, _tex_greaterthan(length2, 0., name + "_valid", props),
                        name + "_safe_v", props)
    else:
        v = _tex_binary("scale", _tex_binary("add", z, 1., name + "_height", props),
                        .5, name + "_v", props)
        v = _tex_binary("scale", v, xy_valid, name + "_safe_v", props)
    return _combine3(u, v, 0., name + "_projected", props)


def _vector_mapping_defs(vector_socket, is_2d, flip_v, props, material, obj_name,
                         group_node_stack, post_matrix=None):
    """
    `mapping.*` definitions honoring the node linked to a texture's Vector
    input. Returns an empty dict when the engine default (UV mapping) applies.

    post_matrix (3D only) is applied after the user transform - used to
    remap Cycles coordinates into a legacy texture's expected range.
    """
    defs = _vector_mapping_defs_impl(vector_socket, is_2d, flip_v, props,
                                     material, obj_name, group_node_stack)
    matrix = defs.pop("_matrix", None)
    if post_matrix is None or is_2d:
        return defs
    if matrix is not None:
        defs["mapping.transformation"] = utils.luxutils.matrix_to_list(
            post_matrix @ matrix)
    elif "mapping.transformation" not in defs:
        defs.setdefault("mapping.type", "uvmapping3d")
        defs["mapping.transformation"] = utils.luxutils.matrix_to_list(post_matrix)
    return defs


def _vector_mapping_defs_impl(vector_socket, is_2d, flip_v, props, material,
                              obj_name, group_node_stack):
    link = utils_node.get_link(vector_socket)
    if link is None:
        return {}
    source, source_socket = link.from_node, link.from_socket

    if source.bl_idname == "ShaderNodeMapping":
        location, rotation, scale = _mapping_node_values(source, obj_name)
        if is_2d:
            return _mapping_uv_defs(location, rotation, scale, flip_v)
        # Note: chained Mapping nodes are not composed (single mapping block)
        map_type, extra = _mapping_3d_space(source, obj_name)
        matrix = _mapping_matrix(location, rotation, scale)
        defs = {
            "mapping.type": map_type,
            "mapping.transformation": utils.luxutils.matrix_to_list(matrix),
            "_matrix": matrix,
        }
        defs.update(extra)
        return defs

    if source.bl_idname == "ShaderNodeUVMap":
        index = _uv_layer_index(obj_name, getattr(source, "uv_map", ""))
        if index is None:
            SuperLuxCoreErrorLog.add_warning(
                f'UV map "{getattr(source, "uv_map", "")}" of node "{source.name}" '
                "could not be resolved, using the default UV layer",
                obj_name=obj_name)
            return {}
        return {
            "mapping.type": "uvmapping2d" if is_2d else "uvmapping3d",
            "mapping.uvindex": index,
        }

    if source.bl_idname == "ShaderNodeTexCoord":
        if source_socket.name == "UV":
            return {}  # the default UV mapping already matches
        if source_socket.name == "Generated":
            SuperLuxCoreErrorLog.add_warning(
                "Generated coordinates on this texture Vector mapping path "
                "are approximated by UV coordinates", obj_name=obj_name)
            return {}
        if source_socket.name == "Object" and not is_2d:
            # LocalMapping3D evaluates the hit point in object space
            return {"mapping.type": "localmapping3d"}
        SuperLuxCoreErrorLog.add_warning(
            f'Texture coordinate output "{source_socket.name}" of node '
            f'"{source.name}" is approximated by the default UV mapping',
            obj_name=obj_name)
        return {}

    SuperLuxCoreErrorLog.add_warning(
        f'Node "{source.name}" cannot drive a texture Vector input; '
        "the default UV mapping is used", obj_name=obj_name)
    return {}


def _evaluate_curve(curve_map, curve_mapping, position):
    """Sample a CurveMap, tolerating signature differences between versions.

    Blender 5.x moved evaluation onto the CurveMapping
    (evaluate(curve_map, position)); older releases expose
    CurveMap.evaluate(curve_mapping, position) or CurveMap.evaluate(position).
    """
    try:
        return curve_mapping.evaluate(curve_map, position)
    except (TypeError, AttributeError):
        try:
            return curve_map.evaluate(curve_mapping, position)
        except TypeError:
            return curve_map.evaluate(position)


def _socket(socket, props, material, obj_name, group_node, superluxcore_name=None):
    link = utils_node.get_link(socket)
    if link:
        # Pass superluxcore_name through so pass-through nodes can re-emit the
        # upstream subtree under the requested name (convert() relies on the
        # top-level node returning the name it was given)
        value = _node(link.from_node, link.from_socket, props, material,
                      superluxcore_name, obj_name, group_node)
        if socket.type == "RGBA" and link.from_socket.type == "VECTOR" and _is_textured(value):
            # 벡터를 색으로 연결하면 데이터 RGB를 한 번만 스펙트럼으로 변환한다.
            channels = [_split_chan(value, i, value + f"_color_channel{i}", props) for i in range(3)]
            return _tex_helper(props, value + "_to_color_vector", {
                "type": "makefloat3", "color": True,
                **{f"texture{i+1}": channel for i, channel in enumerate(channels)}})
        if socket.type == "VALUE" and link.from_socket.type in {"VECTOR", "RGBA"}:
            weights = (list(ocio.GetCurrentConfig().getDefaultLumaCoefs())
                       if link.from_socket.type == "RGBA" else [1. / 3.] * 3)
            if _is_textured(value):
                return _tex_helper(props, value + "_to_float_" + link.from_socket.type.lower(), {
                    "type": "dotproduct", "texture1": value, "texture2": weights})
            if isinstance(value, (list, tuple)):
                return sum(component * weight for component, weight in zip(value, weights))
        return value

    if not hasattr(socket, "default_value"):
        return ERROR_VALUE

    try:
        return list(socket.default_value)[:3]
    except TypeError:
        # Not iterable
        return socket.default_value


def _principled_openpbr(node, base_color, metallic, transmission,
                        coat_weight, props, material, superluxcore_name,
                        obj_name, group_node_stack):
    """
    Principled v2 -> OpenPBR material definitions. Principled is OpenPBR's
    parameterization already (Blender 4.5+), so most sockets map 1:1;
    only weight/tint conventions need conversion. All openpbr params are
    clamped in the material, so out-of-range intermediate values are safe.
    """
    s = lambda name, default=None: _socket(
        node.inputs.get(name), props, material, obj_name, group_node_stack) \
        if node.inputs.get(name) is not None else default

    definitions = {
        "type": "openpbr",
        "basecolor": base_color,
        "basemetalness": metallic,
        "specularroughness": s("Roughness"),
        "specularior": s("IOR"),
        "specularanisotropy": s("Anisotropic"),
        "specularrotation": s("Anisotropic Rotation", 0.0),
        "transmissionweight": transmission,
        # Cycles tints transmission by the base color
        "transmissioncolor": base_color,
        # Cycles keeps the base specular IOR against the exterior under a
        # coat (OpenPBR's specular_ior_ratio would make an IOR-1.5 base
        # under an IOR-1.5 coat reflect nothing: coated surfaces 0.56x)
        "coataffectsbaseior": False,
        "cyclesnormalsemantics": True,
        "reflectionnormalcorrection": bool(getattr(material.cycles, "use_bump_map_correction", True)),
    }

    diffuse_roughness = s("Diffuse Roughness")
    if diffuse_roughness is not None:
        definitions["basediffuseroughness"] = diffuse_roughness

    # Specular IOR Level: Cycles level 0.5 == full dielectric F0, which is
    # OpenPBR specular_weight 1.0 -> weight = 2*level (clamped by the material)
    level = s("Specular IOR Level", 0.5)
    if _is_textured(level) or abs(float(level) - 0.5) > 1e-4:
        definitions["specularweight"] = _tex_binary(
            "scale", level, 2.0, superluxcore_name + "_speclvl", props)

    # Specular Tint (v2 color socket, default white = no tint): maps
    # directly onto OpenPBR's specular_color F0 tint
    tint = s("Specular Tint", [1.0, 1.0, 1.0])
    if _is_textured(tint) or not _color_is_gray(tint) or \
            (isinstance(tint, (list, tuple)) and
             any(abs(v - 1.0) > 1e-4 for v in tint)):
        definitions["specularcolor"] = tint

    # Subsurface: Principled radius is a per-channel vector scaled by
    # Subsurface Scale -> openpbr radius (scalar) * radiusscale (color)
    sss_weight = s("Subsurface Weight", 0.0)
    if _is_textured(sss_weight) or float(sss_weight) != 0.0:
        definitions["subsurfaceweight"] = sss_weight
        definitions["subsurfacecolor"] = base_color
        definitions["subsurfaceradiusscale"] = s("Subsurface Radius",
                                                 [1.0, 1.0, 1.0])
        definitions["subsurfaceradius"] = s("Subsurface Scale", 1.0)
        sss_aniso = s("Subsurface Anisotropy", 0.0)
        if sss_aniso is not None:
            definitions["subsurfaceanisotropy"] = sss_aniso

    # Coat: direct 1:1 (Coat Tint approximates OpenPBR coat_color)
    if _is_textured(coat_weight) or float(coat_weight) != 0.0:
        definitions["coatweight"] = coat_weight
        definitions["coatcolor"] = s("Coat Tint", [1.0, 1.0, 1.0])
        definitions["coatroughness"] = s("Coat Roughness", 0.0)
        definitions["coatior"] = s("Coat IOR", 1.5)

    # Fuzz (sheen): v2 Sheen Tint is a color socket -> direct fuzzcolor
    sheen_weight = s("Sheen Weight", 0.0)
    if _is_textured(sheen_weight) or float(sheen_weight) != 0.0:
        definitions["fuzzweight"] = sheen_weight
        definitions["fuzzroughness"] = s("Sheen Roughness", 0.5)
        sheen_tint = s("Sheen Tint", [1.0, 1.0, 1.0])
        if sheen_tint is not None:
            definitions["fuzzcolor"] = sheen_tint

    # Thin film: Principled thickness is nm, openpbr wants micrometers
    tf_thickness = s("Thin Film Thickness", 0.0)
    if _is_textured(tf_thickness) or float(tf_thickness) != 0.0:
        definitions["filmweight"] = 1.0
        definitions["filmthickness"] = _tex_binary(
            "scale", tf_thickness, 0.001, superluxcore_name + "_filmum", props)
        definitions["filmior"] = s("Thin Film IOR", 1.33)

    coat_socket = node.inputs.get("Coat Normal")
    if _socket_active(coat_socket) and _socket_nondefault(coat_socket, (0.0, 0.0, 0.0)):
        definitions["coatnormal"] = _normal_input(coat_socket, props, material,
                                                 obj_name, group_node_stack)

    # Honest warnings for inputs openpbr cannot express
    if _socket_active(node.inputs.get("Transmission Weight")) and \
            _socket_nondefault(node.inputs.get("Transmission Roughness"), 0.0):
        _warn_unsupported(
            node, "Transmission Roughness is not supported by the OpenPBR "
            "material (transmission shares specular roughness); ignored",
            None, obj_name)

    return definitions


def _principled_thin_film(node, definitions, props, material, obj_name,
                          group_node_stack, with_amount):
    """
    Principled v2 Thin Film Thickness/IOR -> SuperLuxCore thin-film interference
    params. Disney uses filmamount + filmthickness + filmior; glass-family
    materials only have filmthickness/filmior (thickness > 0 enables it).
    """
    tf_thickness_socket = node.inputs.get("Thin Film Thickness")
    if tf_thickness_socket is not None and (
        tf_thickness_socket.is_linked
        or tf_thickness_socket.default_value != 0.0
    ):
        if with_amount:
            definitions["filmamount"] = 1.0
        definitions["filmthickness"] = _socket(
            tf_thickness_socket, props, material, obj_name, group_node_stack
        )
        tf_ior_socket = node.inputs.get("Thin Film IOR")
        if tf_ior_socket is not None and (
            tf_ior_socket.is_linked
            or abs(tf_ior_socket.default_value - 1.33) > 1e-4
        ):
            definitions["filmior"] = _socket(
                tf_ior_socket, props, material, obj_name, group_node_stack
            )


def _principled_disney_warnings(node, transmission, thin_wall_on, obj_name):
    """
    Emit warnings for Principled v2 inputs that SuperLuxCore's Disney material
    cannot express. Each warning only fires when the feature is actually
    used (weight active + input linked/non-default) to avoid noise on
    untouched sockets.
    """
    # Sheen Roughness / Sheen Tint (Disney sheen is a fixed-gloss lobe whose
    # tint blends white<->base color; Principled's tint is a free color)
    if _socket_active(node.inputs.get("Sheen Weight")):
        if _socket_nondefault(node.inputs.get("Sheen Roughness"), 0.5):
            _warn_unsupported(
                node, "Sheen Roughness is not supported by SuperLuxCore's Disney "
                "material (the sheen lobe has no roughness); ignored",
                None, obj_name)
        sheen_tint_socket = node.inputs.get("Sheen Tint")
        if sheen_tint_socket is not None and (
                sheen_tint_socket.is_linked
                or not _color_is_gray(sheen_tint_socket.default_value)):
            _warn_unsupported(
                node, "Sheen Tint is a free color in Principled but a "
                "white<->basecolor blend factor in the Disney material; "
                "approximated by its luminance", None, obj_name)

    # Specular Tint has the same color-vs-blend-factor mismatch
    spec_tint_socket = node.inputs.get("Specular Tint")
    if spec_tint_socket is not None and (
            spec_tint_socket.is_linked
            or not _color_is_gray(spec_tint_socket.default_value)):
        _warn_unsupported(
            node, "Specular Tint is a free color in Principled but a "
            "white<->basecolor blend factor in the Disney material; "
            "approximated by its luminance", None, obj_name)

    # Diffuse Roughness: Disney drives the diffuse lobe with the specular
    # roughness, there is no separate parameter
    if _socket_nondefault(node.inputs.get("Diffuse Roughness"), 0.0):
        _warn_unsupported(
            node, "Diffuse Roughness is not supported by SuperLuxCore's Disney "
            "material (the specular Roughness drives the diffuse lobe); "
            "ignored", None, obj_name)

    # Anisotropic Rotation / Tangent: Disney anisotropy is axis-aligned with
    # the shading frame and has no rotation parameter
    if _socket_active(node.inputs.get("Anisotropic")) and (
            _socket_nondefault(node.inputs.get("Anisotropic Rotation"), 0.0)
            or _socket_nondefault(node.inputs.get("Tangent"), (0.0, 0.0, 0.0))):
        _warn_unsupported(
            node, "anisotropy direction (Anisotropic Rotation, Tangent) is "
            "not supported by SuperLuxCore's Disney material; the anisotropy "
            "follows the shading frame", None, obj_name)

    # Subsurface: Disney's subsurface is the weight-only diffuse-profile
    # lobe (a Burley-style approximation) — radius/scale/IOR/anisotropy and
    # the random-walk methods need real volumetric scattering
    if _socket_active(node.inputs.get("Subsurface Weight")):
        sss_ignored = [name for name, socket, default in (
            ("Subsurface Radius", node.inputs.get("Subsurface Radius"),
             (1.0, 0.2, 0.1)),
            ("Subsurface Scale", node.inputs.get("Subsurface Scale"), 0.005),
            ("Subsurface IOR", node.inputs.get("Subsurface IOR"), 1.4),
            ("Subsurface Anisotropy", node.inputs.get("Subsurface Anisotropy"),
             0.0),
        ) if _socket_nondefault(socket, default)]
        sss_method = getattr(node, "subsurface_method", "BURLEY")
        if sss_ignored or sss_method != "BURLEY":
            details = []
            if sss_ignored:
                details.append("ignored inputs: " + ", ".join(sss_ignored))
            if sss_method != "BURLEY":
                details.append(
                    "'%s' scattering requires a scattering interior volume, "
                    "which the Disney material cannot drive"
                    % sss_method.replace("_", " ").title())
            _warn_unsupported(
                node, "subsurface is approximated by the Disney "
                "diffuse-profile lobe (weight only); " + "; ".join(details),
                None, obj_name)

    # Thin Wall only changes the transmission lobe — warn when transmission
    # can actually occur (partial transmission path; the sharp full-
    # transmission case is handled by the archglass mapping)
    transmission_active = _is_textured(transmission) or transmission != 0
    if thin_wall_on and transmission_active:
        _warn_unsupported(
            node, "Thin Wall is not supported by SuperLuxCore's Disney material; "
            "transmission refracts as a solid volume (total internal "
            "reflection and interior volumes apply)", None, obj_name)


def _output_reaches_render(socket, group_node_stack=None):
    """미사용 그룹·음소거 분기를 제외하고 실제 최종 출력 연결을 찾는다."""
    pending = [(socket, tuple(group_node_stack or []))]
    seen = set()
    while pending:
        output, stack = pending.pop()
        key = (output.as_pointer(), tuple(n.as_pointer() for n in stack))
        if key in seen:
            continue
        seen.add(key)
        for link in output.links:
            if (not link.is_valid or getattr(link, "is_muted", False)
                    or not getattr(link.to_socket, "enabled", True)):
                continue
            target = link.to_node
            if target.bl_idname in {"ShaderNodeOutputMaterial", "ShaderNodeOutputWorld",
                                    "ShaderNodeOutputLight", "ShaderNodeOutputAOV"}:
                if getattr(target, "is_active_output", True):
                    return True
            elif target.bl_idname == "NodeGroupOutput":
                if stack and target.is_active_output:
                    parent_output = _group_socket(stack[-1].outputs, link.to_socket)
                    if parent_output is not None:
                        pending.append((parent_output, stack[:-1]))
            elif target.mute:
                for bypass in target.internal_links:
                    if bypass.from_socket == link.to_socket:
                        pending.append((bypass.to_socket, stack))
            elif target.bl_idname == "ShaderNodeGroup" and target.node_tree:
                for child in target.node_tree.nodes:
                    if child.bl_idname == "NodeGroupInput":
                        child_output = _group_socket(child.outputs, link.to_socket)
                        if child_output is not None:
                            pending.append((child_output, stack + (target,)))
            else:
                pending.extend((out, stack) for out in target.outputs if out.enabled)
    return False


def _node(node, output_socket, props, material, superluxcore_name=None, obj_name="", group_node_stack=None):
    if superluxcore_name is None:
        superluxcore_name = str(node.as_pointer()) + output_socket.name
        if group_node_stack:
            for n in group_node_stack:
                superluxcore_name += str(n.as_pointer())
        superluxcore_name = utils.sanitize_superluxcore_name(superluxcore_name)

    if node.bl_idname == "ShaderNodeBsdfPrincipled":
        prefix = "scene.materials."
        base_color = _socket(node.inputs["Base Color"], props, material, obj_name, group_node_stack)
        metallic_socket = node.inputs["Metallic"]
        metallic = _socket(metallic_socket, props, material, obj_name, group_node_stack)
        transmission_socket = node.inputs["Transmission Weight"]
        transmission = _socket(transmission_socket, props, material, obj_name, group_node_stack)

        # --- Principled v2 feature detection (sockets may not exist on
        # older Blender versions -> .get() everywhere) ---

        # Thin Wall: transmission behaves as an infinitely thin slab (no ray
        # offset, no TIR, no interior volume). Only const-True can switch the
        # material type; a linked flag falls back to the warning path.
        thin_wall_socket = node.inputs.get("Thin Wall")
        thin_wall_linked = thin_wall_socket is not None and thin_wall_socket.is_linked
        thin_wall_on = thin_wall_socket is not None and (
            thin_wall_linked or bool(thin_wall_socket.default_value))

        # Coat. Disney's built-in clearcoat is a fixed-IOR (1.5), untinted
        # lobe sharing the material normal. When Coat IOR / Coat Tint / Coat
        # Normal are actually used, wrap the base material in a real
        # dielectric coat layer (glossycoating) instead — see below.
        coat_weight_socket = node.inputs.get("Coat Weight")
        coat_weight = _socket(coat_weight_socket, props, material, obj_name,
                              group_node_stack) if coat_weight_socket is not None else 0.0
        coat_active = _socket_active(coat_weight_socket)
        coat_ior_socket = node.inputs.get("Coat IOR")
        coat_tint_socket = node.inputs.get("Coat Tint")
        coat_normal_socket = node.inputs.get("Coat Normal")
        coat_extra = (_socket_nondefault(coat_ior_socket, 1.5)
                      or _socket_nondefault(coat_tint_socket, (1.0, 1.0, 1.0))
                      or _socket_nondefault(coat_normal_socket, (0.0, 0.0, 0.0)))

        if transmission == 1 and metallic == 0:
            # It's effectively glass instead of a disney material.
            # Don't use mix for performance reasons.
            roughness = _squared_roughness_to_linear(node.inputs["Roughness"], props, material,
                                                     superluxcore_name, obj_name, group_node_stack)
            # Glass materials have no built-in coat lobe, so any active coat
            # needs the glossycoating wrap (even with default coat params).
            use_coating = coat_active

            if thin_wall_on and not thin_wall_linked and roughness == 0:
                # Thin-walled sharp transmission: rays refract in and out of
                # the thin slab and exit parallel to the incident ray, so
                # archglass (Fresnel reflection + unbent transmission, no
                # interior volume, no TIR) is the physically matching model.
                definitions = {
                    "type": "archglass",
                    "kt": base_color,
                    "kr": [1, 1, 1],
                    "interiorior": _socket(node.inputs["IOR"], props, material, obj_name, group_node_stack),
                }
            else:
                if thin_wall_on:
                    _warn_unsupported(
                        node, "Thin Wall is only supported for sharp full "
                        "transmission (mapped to archglass); rough or textured "
                        "transmission is exported as solid glass — rays are "
                        "refracted and the interior volume applies",
                        None, obj_name)
                definitions = {
                    "type": "glass" if roughness == 0 else "roughglass",
                    "kt": base_color,
                    "kr": [1, 1, 1],
                    "interiorior": _socket(node.inputs["IOR"], props, material, obj_name, group_node_stack),
                }

                if roughness != 0:
                    definitions["uroughness"] = roughness
                    definitions["vroughness"] = roughness

            # Thin film works on glass/roughglass/archglass too (activated by
            # filmthickness > 0; there is no filmamount on these materials)
            _principled_thin_film(node, definitions, props, material, obj_name,
                                  group_node_stack, with_amount=False)
        elif getattr(material.superluxcore, "principled_target", "openpbr") == "openpbr":
            # OpenPBR is Principled's native model: direct mapping, and the
            # coat is a built-in lobe so no glossycoating wrap is needed.
            use_coating = False
            definitions = _principled_openpbr(
                node, base_color, metallic, transmission, coat_weight,
                props, material, superluxcore_name, obj_name, group_node_stack)
        else:
            use_coating = coat_active and coat_extra
            definitions = {
                # TODO (needs OpenPBR material — no Disney params):
                #  - subsurface radius/scale/IOR/anisotropy (Disney has weight only)
                #  - sheen roughness/tint color, diffuse roughness
                #  - anisotropic rotation, tangent
                "type": "disney",
                "basecolor": base_color,
                "subsurface": _socket(node.inputs["Subsurface Weight"], props, material, obj_name, group_node_stack),
                "metallic": metallic,
                "specular": _socket(node.inputs["Specular IOR Level"], props, material, obj_name, group_node_stack),
                "speculartint": _socket(node.inputs["Specular Tint"], props, material, obj_name, group_node_stack),
                # Both SuperLuxCore and Cycles use squared roughness here, no need to convert
                "roughness": _socket(node.inputs["Roughness"], props, material, obj_name, group_node_stack),
                "anisotropic": _socket(node.inputs["Anisotropic"], props, material, obj_name, group_node_stack),
                "sheen": _socket(node.inputs["Sheen Weight"], props, material, obj_name, group_node_stack),
                "sheentint": _socket(node.inputs["Sheen Tint"], props, material, obj_name, group_node_stack),
                # When a glossycoating wraps this material, the Disney
                # clearcoat lobe is disabled so the coat is not applied twice.
                "clearcoat": 0.0 if use_coating else coat_weight,
                # Disney clearcoatgloss = 1 - coat_roughness
                "clearcoatgloss": 1.0 if use_coating else (_tex_helper(props, superluxcore_name + "coatgloss", {
                    "type": "subtract",
                    "texture1": 1.0,
                    "texture2": _socket(node.inputs["Coat Roughness"], props, material, obj_name, group_node_stack),
                }) if node.inputs["Coat Roughness"].is_linked
                    or node.inputs["Coat Roughness"].default_value != 0.0
                    else 1.0),
                # Integrated dielectric transmission lobe (no disney+glass
                # mix hack): weight, roughness and IOR map directly.
                "transmission": transmission,
                "ior": _socket(node.inputs["IOR"], props, material, obj_name, group_node_stack),
            }

            # Transmission Roughness: Principled default 0 (sharp). Always emit
            # the socket value — the Disney material otherwise falls back to
            # the base roughness, which would break sharp-transmission looks.
            tr_roughness_socket = node.inputs.get("Transmission Roughness")
            if tr_roughness_socket is not None:
                definitions["transmissionroughness"] = _socket(
                    tr_roughness_socket, props, material, obj_name, group_node_stack
                )

            # Thin film (Principled v2): thickness + IOR -> Disney film params
            _principled_thin_film(node, definitions, props, material, obj_name,
                                  group_node_stack, with_amount=True)

            # --- Honest warnings for the remaining Principled inputs the
            # Disney material cannot express ---
            _principled_disney_warnings(node, transmission, thin_wall_on,
                                        obj_name)

        # Attach these props to the right-most material node (regardless if it's glass, disney or a mix mat)
        # Principled v2: emission = Emission Color * Emission Strength
        emission_strength = _socket(node.inputs["Emission Strength"], props, material, obj_name, group_node_stack)
        emission_color = _socket(node.inputs["Emission Color"], props, material, obj_name, group_node_stack)
        if _is_zero(emission_strength) or _is_zero(emission_color):
            # Statically black emission (Blender 5.x defaults Principled to
            # Emission Strength=1 with a black color). Emitting a constant 0
            # keeps the material off the light list — a scale texture would
            # be non-constant, so the engine would register every triangle
            # using this material as a mesh light (hundreds of thousands of
            # fake lights on ordinary archviz scenes).
            emission = 0.0
        elif emission_color == [1.0, 1.0, 1.0] or emission_color == 1.0:
            emission = emission_strength
        else:
            emission = _tex_binary("scale", emission_strength, emission_color,
                                   superluxcore_name + "emission_col", props)
        transparency = _socket(node.inputs["Alpha"], props, material, obj_name, group_node_stack)
        bump = _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack)

        if use_coating:
            # Wrap the base in a real dielectric coat layer (glossycoating):
            #   index = Coat IOR, ks = Coat Weight scales the coat Fresnel F0
            #   (SuperLuxCore multiplies ks by ((ior-1)/(ior+1))^2, exactly the
            #   Cycles coat F0), uroughness/vroughness = Coat Roughness
            #   (Cycles squared -> SuperLuxCore linear), bumptex = Coat Normal
            #   (the coating evaluates with its own bumped frame while the
            #   base keeps the regular Normal input).
            base_name = utils.sanitize_superluxcore_name(superluxcore_name + "_coatbase")
            base_definitions = dict(definitions)
            # Emission/transparency/normal live on the substrate — the
            # coating delegates passthrough transparency and (when it has no
            # emission itself) emitted radiance to the base material.
            base_definitions.update({
                "emission": emission,
                "transparency": transparency,
                "bumptex": bump,
            })
            props.Set(utils.luxutils.create_props(
                "scene.materials." + base_name + ".", base_definitions))

            coat_roughness = _squared_roughness_to_linear(
                node.inputs["Coat Roughness"], props, material,
                superluxcore_name + "_coat", obj_name, group_node_stack)
            coat_ior = _socket(coat_ior_socket, props, material, obj_name,
                               group_node_stack) if coat_ior_socket is not None else 1.5
            definitions = {
                "type": "glossycoating",
                "base": base_name,
                "ks": coat_weight,
                "uroughness": coat_roughness,
                "vroughness": coat_roughness,
                "index": coat_ior,
                # Cycles' default MULTI_GGX coat = multibounce microfacet
                "multibounce": 1 if getattr(node, "distribution", "MULTI_GGX") == "MULTI_GGX" else 0,
            }
            if _socket_nondefault(coat_normal_socket, (0.0, 0.0, 0.0)):
                definitions["bumptex"] = _socket(
                    coat_normal_socket, props, material, obj_name, group_node_stack)
            if _socket_nondefault(coat_tint_socket, (1.0, 1.0, 1.0)):
                # Cycles Coat Tint is volumetric absorption inside the coat:
                # transmittance = pow(tint, weight / cosNT). SuperLuxCore computes
                # exp(-ka * d * (1/cosi + 1/coso)), so ka = -ln(tint) and
                # d = weight/2 reproduce tint^weight at perpendicular
                # incidence (the angle Cycles normalizes to).
                coat_tint = _socket(coat_tint_socket, props, material, obj_name,
                                    group_node_stack)
                definitions["ka"] = _tex_binary(
                    "scale",
                    _v3_mathfunc("ln", coat_tint, superluxcore_name + "_coatln", props),
                    -1.0, superluxcore_name + "_coatka", props)
                definitions["d"] = _tex_binary(
                    "scale", coat_weight, 0.5, superluxcore_name + "_coatd", props)
        else:
            definitions.update({
                "emission": emission,
                "transparency": transparency,
                "bumptex": bump,
            })
    elif node.bl_idname == "ShaderNodeMixShader":
        prefix = "scene.materials."

        def convert_mat_socket(index):
            mat_name = _socket(node.inputs[index], props, material, obj_name, group_node_stack)
            if mat_name is ERROR_VALUE:
                mat_name, mat_props = black()
                props.Set(mat_props)
            return mat_name

        fac_input = node.inputs["Fac"]
        amount = _socket(fac_input, props, material, obj_name, group_node_stack)
        if fac_input.is_linked and amount is ERROR_VALUE:
            amount = 0.5

        definitions = {
            "type": "mix",
            "material1": convert_mat_socket(1),
            "material2": convert_mat_socket(2),
            "amount": amount,
        }
    elif node.bl_idname == "ShaderNodeAddShader":
        prefix = "scene.materials."

        link1 = utils_node.get_link(node.inputs[0])
        link2 = utils_node.get_link(node.inputs[1])

        # An unlinked input counts as "adding nothing" -> pass the other side,
        # re-emitted under this node's name to keep the name invariant
        if link1 is None:
            return _socket(node.inputs[1], props, material, obj_name,
                           group_node_stack, superluxcore_name)
        if link2 is None:
            return _socket(node.inputs[0], props, material, obj_name,
                           group_node_stack, superluxcore_name)

        def emission_of(emission_node):
            # Recreate the emission texture the Emission branch below produces
            color = _socket(emission_node.inputs["Color"], props, material,
                            obj_name, group_node_stack)
            strength = _socket(emission_node.inputs["Strength"], props, material,
                               obj_name, group_node_stack)
            return _tex_binary("scale", strength, color,
                               str(emission_node.as_pointer()) + "emission_col",
                               props)

        is_emission1 = link1.from_node.bl_idname == "ShaderNodeEmission"
        is_emission2 = link2.from_node.bl_idname == "ShaderNodeEmission"

        if is_emission1 and is_emission2:
            # Exact: a non-scattering material emitting the sum of both emissions
            emission = _tex_binary("add", emission_of(link1.from_node),
                                   emission_of(link2.from_node),
                                   superluxcore_name + "emission_add", props)
            definitions = {
                "type": "matte",
                "kd": [0, 0, 0],
                "emission": emission,
                "emission.gain": [1] * 3,
                "emission.power": 0,
                "emission.efficency": 0,
            }
        elif is_emission1 or is_emission2:
            # Attach a standalone emission to a surface with no emission slot.
            # Existing emission is summed through the additive closure below.
            emission_link = link1 if is_emission1 else link2
            base_socket = node.inputs[1] if is_emission1 else node.inputs[0]
            base_name = _socket(base_socket, props, material, obj_name,
                                group_node_stack, superluxcore_name)
            if base_name is ERROR_VALUE or not isinstance(base_name, str):
                base_name, mat_props = black(superluxcore_name)
                props.Set(mat_props)

            emission_key = "scene.materials." + base_name + ".emission"
            try:
                already_has_emission = props.IsDefined(emission_key)
            except AttributeError:
                try:
                    already_has_emission = emission_key in props.GetAllNames()
                except AttributeError:
                    already_has_emission = False

            # Null is skipped during intersection. Composite materials can
            # inherit emission from children even without their own emission
            # slot; setting that slot would replace the inherited emission.
            base_type = props.Get("scene.materials." + base_name + ".type").GetString()
            can_attach_emission = (not already_has_emission and
                                   base_type not in {"null", "mix", "glossycoating", "twosided"})
            if can_attach_emission:
                emission = emission_of(emission_link.from_node)
                if _is_zero(emission):
                    # Adding a statically black emission adds nothing.
                    return base_name
                props.Set(utils.luxutils.create_props("scene.materials." + base_name + ".", {
                    "emission": emission,
                    "emission.gain": [1] * 3,
                    "emission.power": 0,
                    "emission.efficency": 0,
                }))
                return base_name

        if (is_emission1 != is_emission2 and not can_attach_emission) or \
                (not is_emission1 and not is_emission2):
            def add_mat_socket(index):
                mat_name = _socket(node.inputs[index], props, material, obj_name,
                                   group_node_stack)
                if mat_name is ERROR_VALUE or not isinstance(mat_name, str):
                    mat_name, mat_props = black()
                    props.Set(mat_props)
                return mat_name

            definitions = {
                "type": "mix",
                "material1": add_mat_socket(0),
                "material2": add_mat_socket(1),
                "amount": 0.5,
                "additive": True,
            }
            # A provisional emission+surface export may have used this name.
            # Preserve the re-exported children; the sum owns no emission slot.
            props.DeleteAll(props.GetAllNames(prefix + superluxcore_name + "."))
    elif node.bl_idname == "ShaderNodeBsdfDiffuse":
        prefix = "scene.materials."
        roughness = _socket(node.inputs["Roughness"], props, material, obj_name, group_node_stack)
        # Native roughmatte uses normalized EON roughness, not angular sigma.
        # Preserve the artist's input and the engine's energy-conserving model.
        definitions = {
            "type": "roughmatte" if _is_textured(roughness) or roughness > 0. else "matte",
            "kd": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "bumptex": _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack),
        }
        if definitions["type"] == "roughmatte":
            definitions["sigma"] = roughness
    elif node.bl_idname == "ShaderNodeBsdfGlossy":
        prefix = "scene.materials."

        # Implicitly create a fresnelcolor texture with unique name
        tex_name = superluxcore_name + "fresnel_helper"
        helper_prefix = "scene.textures." + tex_name + "."
        helper_defs = {
            "type": "fresnelcolor",
            "kr": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
        }
        props.Set(utils.luxutils.create_props(helper_prefix, helper_defs))

        # metal2's GGX path squares the roughness itself (alpha = r^2, as
        # Cycles): pass the perceptual value (pre-squaring gave alpha = r^4)
        roughness = _socket(node.inputs["Roughness"], props, material,
                            obj_name, group_node_stack)

        definitions = {
            "type": "metal2",
            "fresnel": tex_name,
            "uroughness": roughness,
            "vroughness": roughness,
            # Cycles Glossy BSDF is GGX-based; MULTI_GGX (the default) is
            # energy-conserving multiscatter
            "distribution": "ggx",
            "multibounce": 1 if getattr(node, "distribution", "MULTI_GGX") == "MULTI_GGX" else 0,
            "bumptex": _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack),
        }
    elif node.bl_idname == "ShaderNodeTexImage":
        if node.image:
            if output_socket == node.outputs["Alpha"] and node.image.alpha_mode == "NONE":
                return 1.0
            if node.image.source == "TILED":
                SuperLuxCoreErrorLog.add_warning(
                    f'Image texture node "{node.name}": UDIM tiled images '
                    "are not supported - only the base tile is used",
                    obj_name=obj_name)
            prefix = "scene.textures."
            if node.extension == "MIRROR":
                # No mirrored-repeat wrap in the imagemap sampler; "repeat"
                # produces a visible tiling seam but not a broken render.
                SuperLuxCoreErrorLog.add_warning(
                    f'Image texture node "{node.name}": MIRROR extension is '
                    "approximated by REPEAT (no mirrored sampling)",
                    obj_name=obj_name)
            extension_map = {
                "REPEAT": "repeat",
                "EXTEND": "clamp",
                "CLIP": "black",
                "MIRROR": "repeat",
            }

            try:
                filepath = ImageExporter.export_cycles_node_reader(node.image)
            except OSError as error:
                SuperLuxCoreErrorLog.add_warning(error, obj_name=obj_name)
                return MISSING_IMAGE_COLOR

            definitions = {
                "type": "imagemap",
                # TODO image sequences
                "file": filepath,
                "wrap": extension_map[node.extension],
                "channel": "alpha" if output_socket == node.outputs["Alpha"] else "rgb",
                **ImageExporter.cycles_colorspace(node.image, output_socket == node.outputs["Alpha"],
                                                   _output_reaches_render(node.outputs["Alpha"], group_node_stack)),
                "gain": 1,
                "filter": _imagemap_filter(node, obj_name),

                "mapping.type": "uvmapping2d",
                "mapping.uvscale": [1, -1],
                "mapping.rotation": 0,
                "mapping.uvdelta": [0, 1],
            }

            projection = getattr(node, "projection", "FLAT")
            if (projection == "BOX" and
                    node.inputs.get("Vector") is not None and
                    node.inputs["Vector"].is_linked):
                # Box projection: Cycles picks the dominant axis of the
                # surface normal and samples the image with that plane's
                # coordinates of the linked Vector (object/generated
                # space). The engine's triplanar texture projects the 3D
                # mapping onto the three planes and writes the planar
                # coordinates as the UV the image map reads (n^4 blend).
                # Sampling the mesh UV instead stretched box-mapped
                # asphalt/stone textures into streaks.
                image_tex = _tex_helper(props, superluxcore_name + "_box", definitions)
                definitions = {
                    "type": "triplanar",
                    "texture1": image_tex,
                    "texture2": image_tex,
                    "texture3": image_tex,
                }
                definitions.update(_vector_mapping_defs(
                    node.inputs["Vector"], False, False, props, material,
                    obj_name, group_node_stack))
            elif projection not in ("FLAT", "SPHERE", "TUBE"):
                SuperLuxCoreErrorLog.add_warning(
                    f'Image Texture node "{node.name}": projection '
                    f'"{node.projection}" is approximated by UV mapping '
                    "(BOX blend requires further compatibility work)",
                    obj_name=obj_name)

            # A linked Vector input (e.g. a Mapping node) overrides the default
            # UV flip mapping
            vector_input = node.inputs.get("Vector")
            if vector_input is not None and definitions.get("type") == "imagemap":
                if projection in {"FLAT", "SPHERE", "TUBE"} and (vector_input.is_linked or projection != "FLAT"):
                    vector = (_socket(vector_input, props, material, obj_name, group_node_stack)
                              if vector_input.is_linked else
                              _tex_helper(props, superluxcore_name + "_default_uv", {"type": "uv", "wrap": False}))
                    if projection != "FLAT":
                        vector = _image_vector_projection(vector, projection, superluxcore_name + "_projection", props)
                    # Image storage is top-down; Cycles Vector uses bottom-up V.
                    vector = _tex_binary("scale", vector, [1., -1., 1.],
                                         superluxcore_name + "_image_orientation", props)
                    definitions["vector"] = _tex_binary("add", vector, [0., 1., 0.],
                                                         superluxcore_name + "_image_vector", props)
                else:
                    definitions.update(_vector_mapping_defs(
                        vector_input, True, True, props, material, obj_name,
                        group_node_stack))
        else:
            return MISSING_IMAGE_COLOR
    elif node.bl_idname == "ShaderNodeBsdfGlass":
        prefix = "scene.materials."
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        roughness = _socket(node.inputs["Roughness"], props, material,
                            obj_name, group_node_stack)
        ior = _socket(node.inputs["IOR"], props, material, obj_name, group_node_stack)

        # Under Filter Glossy a sharp Cycles glass is a microfacet lobe
        # the filter blurs after diffuse bounces: keep it a (near-delta)
        # GGX lobe instead of the delta glass material
        if roughness == 0 and not _filter_glossy_active():
            definitions = {
                "type": "glass",
                "kt": color,
                "kr": color,
                "interiorior": ior,
            }
        else:
            # Rough glass -> OpenPBR transmission: its GGX glass carries the
            # multiscatter energy compensation (a white rough glass vanishes
            # in a furnace like Cycles' MULTI_GGX); roughglass loses ~30% of
            # the energy at roughness 0.8. Cycles' Glass Color tints both
            # reflection and refraction.
            definitions = {
                "type": "openpbr",
                "basecolor": [1.0, 1.0, 1.0],
                "basemetalness": 0.0,
                "specularroughness": roughness,
                "specularior": ior,
                "specularcolor": color,
                "transmissionweight": 1.0,
                "transmissioncolor": color,
            }
        definitions["bumptex"] = _normal_input(node.inputs["Normal"], props, material,
                                               obj_name, group_node_stack)
    elif node.bl_idname == "ShaderNodeBsdfRefraction":
        prefix = "scene.materials."
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        # Perceptual roughness: roughglass's GGX path squares it (alpha = r^2)
        roughness = _socket(node.inputs["Roughness"], props, material,
                            obj_name, group_node_stack)

        sharp = roughness == 0 and not _filter_glossy_active()
        definitions = {
            "type": "glass" if sharp else "roughglass",
            "kt": color,
            "kr": [0, 0, 0],
            "interiorior": _socket(node.inputs["IOR"], props, material, obj_name, group_node_stack),
            "bumptex": _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack),
        }

        if not sharp:
            definitions["uroughness"] = roughness
            definitions["vroughness"] = roughness
            # Cycles glass is GGX; MULTI_GGX (the Glass default) is
            # energy-conserving multiscatter
            definitions["distribution"] = "ggx"
            definitions["multibounce"] = 1 if getattr(node, "distribution", "GGX") == "MULTI_GGX" else 0
    elif node.bl_idname == "ShaderNodeBsdfAnisotropic":
        # Blender 4+ merged Glossy and Anisotropic into this node (a new
        # "ShaderNodeBsdfGlossy" is created as ShaderNodeBsdfAnisotropic):
        # isotropic unless Anisotropy != 0. It used to be exported with a
        # fixed vroughness of 0.05 - every Glossy BSDF got a sharp streak.
        prefix = "scene.materials."

        # Implicitly create a fresnelcolor texture with unique name
        tex_name = superluxcore_name + "fresnel_helper"
        helper_prefix = "scene.textures." + tex_name + "."
        helper_defs = {
            "type": "fresnelcolor",
            "kr": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
        }
        props.Set(utils.luxutils.create_props(helper_prefix, helper_defs))

        # Perceptual roughness: metal2's GGX path squares it
        roughness = _socket(node.inputs["Roughness"], props, material,
                            obj_name, group_node_stack)
        uroughness = vroughness = roughness
        aniso_socket = node.inputs.get("Anisotropy")
        if aniso_socket is not None and (aniso_socket.is_linked or
                                         aniso_socket.default_value != 0.0):
            if aniso_socket.is_linked or isinstance(roughness, str):
                SuperLuxCoreErrorLog.add_warning(
                    f'Glossy node "{node.name}": textured anisotropy/roughness '
                    "is approximated as isotropic", obj_name=obj_name)
            else:
                # Cycles: aspect = sqrt(1 - |a| * 0.9), alpha_t = r^2 / aspect,
                # alpha_b = r^2 * aspect (axes swap for a < 0); metal2
                # squares u/v, so scale the perceptual values by sqrt(aspect)
                a = max(-1.0, min(1.0, aniso_socket.default_value))
                aspect = math.sqrt(1.0 - abs(a) * 0.9)
                ru = roughness / math.sqrt(aspect)
                rv = roughness * math.sqrt(aspect)
                uroughness, vroughness = (ru, rv) if a >= 0 else (rv, ru)
                uroughness = min(1.0, uroughness)
            rot = node.inputs.get("Rotation")
            if rot is not None and (rot.is_linked or rot.default_value != 0.0):
                SuperLuxCoreErrorLog.add_warning(
                    f'Glossy node "{node.name}": anisotropy rotation is not '
                    "supported", obj_name=obj_name)

        definitions = {
            "type": "metal2",
            "fresnel": tex_name,
            "uroughness": uroughness,
            "vroughness": vroughness,
            # GGX-based; MULTI_GGX (the default) is energy-conserving
            "distribution": "ggx",
            "multibounce": 1 if getattr(node, "distribution", "MULTI_GGX") == "MULTI_GGX" else 0,
            "bumptex": _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack),
        }
    elif node.bl_idname == "ShaderNodeBsdfMetallic":
        prefix = "scene.materials."

        ior_socket = node.inputs.get("IOR")
        extinction_socket = node.inputs.get("Extinction")
        physical_ior = ior_socket is not None and getattr(ior_socket, "enabled", True)

        roughness = _socket(node.inputs["Roughness"], props, material,
                            obj_name, group_node_stack)
        anisotropy = _socket(node.inputs["Anisotropy"], props, material,
                             obj_name, group_node_stack)

        # vroughness shrinks with anisotropy (directional streaks); a scalar
        # anisotropy can't compose with a textured roughness — warn then
        if isinstance(anisotropy, str):
            SuperLuxCoreErrorLog.add_warning(
                f'Metallic node "{node.name}": textured anisotropy is not '
                "supported, isotropic roughness is used", obj_name=obj_name)
            vroughness = roughness
        elif isinstance(roughness, str):
            SuperLuxCoreErrorLog.add_warning(
                f'Metallic node "{node.name}": anisotropy with a textured '
                "roughness is approximated", obj_name=obj_name)
            vroughness = roughness
        else:
            vroughness = max(1e-4, roughness * (1.0 - anisotropy))

        if getattr(node, "fresnel_type", "F82") == "F82" and \
                node.inputs.get("Edge Tint") is not None and \
                (node.inputs["Edge Tint"].is_linked or
                 list(node.inputs["Edge Tint"].default_value)[:3] != [0, 0, 0]):
            SuperLuxCoreErrorLog.add_warning(
                f'Metallic node "{node.name}": Edge Tint (F82) is not '
                "supported by the conductor model", obj_name=obj_name)

        definitions = {"type": "metal2"}

        if physical_ior:
            # PHYSICAL mode: explicit complex IOR (n) + extinction (k)
            definitions["n"] = _socket(ior_socket, props, material, obj_name,
                                       group_node_stack)
            definitions["k"] = _socket(extinction_socket, props, material,
                                       obj_name, group_node_stack)
        else:
            # F82 mode (default): derive n,k from the Base Color reflectance
            base_color = _socket(node.inputs["Base Color"], props, material,
                                 obj_name, group_node_stack)
            n_tex = superluxcore_name + "approxn"
            k_tex = superluxcore_name + "approxk"
            props.Set(utils.luxutils.create_props(
                "scene.textures." + n_tex + ".",
                {"type": "fresnelapproxn", "texture": base_color}))
            props.Set(utils.luxutils.create_props(
                "scene.textures." + k_tex + ".",
                {"type": "fresnelapproxk", "texture": base_color}))
            definitions["n"] = n_tex
            definitions["k"] = k_tex

        definitions["uroughness"] = roughness
        definitions["vroughness"] = vroughness
        # Blender's Metallic node is GGX-based; MULTI_GGX (the default) is
        # energy-conserving multiscatter (a white rough metal vanishes in a
        # furnace instead of darkening to the single-scatter albedo)
        definitions["distribution"] = "ggx"
        definitions["multibounce"] = 1 if getattr(node, "distribution", "MULTI_GGX") == "MULTI_GGX" else 0
        if node.inputs.get("Rotation") is not None and \
                (node.inputs["Rotation"].is_linked or
                 node.inputs["Rotation"].default_value != 0.0):
            SuperLuxCoreErrorLog.add_warning(
                f'Metallic node "{node.name}": anisotropy rotation is not '
                "supported", obj_name=obj_name)
        if node.inputs.get("Normal") is not None:
            definitions["bumptex"] = _normal_input(node.inputs["Normal"], props,
                                             material, obj_name, group_node_stack)
        if node.inputs.get("Thin Film Thickness") is not None and \
                (node.inputs["Thin Film Thickness"].is_linked or
                 node.inputs["Thin Film Thickness"].default_value != 0.0):
            SuperLuxCoreErrorLog.add_warning(
                f'Metallic node "{node.name}": thin film on conductors is not '
                "supported by metal2", obj_name=obj_name)
    elif node.bl_idname == "ShaderNodeBsdfHairPrincipled":
        prefix = "scene.materials."

        # Cycles' Principled Hair maps onto SuperLuxCore's Marschner "hairmat".
        def _sock(name, fallback):
            s = node.inputs.get(name)
            return _socket(s, props, material, obj_name, group_node_stack) \
                if s is not None else fallback

        # Cycles' Offset is radians; SuperLuxCore's alpha is degrees.
        offset_sock = node.inputs.get("Offset")
        offset = _socket(offset_sock, props, material, obj_name, group_node_stack) \
            if offset_sock is not None else 0.0
        if offset_sock is not None and offset_sock.is_linked and offset is not ERROR_VALUE:
            alpha = superluxcore_name + "offset_to_deg"
            props.Set(utils.luxutils.create_props("scene.textures." + alpha + ".", {
                "type": "scale",
                "texture1": offset,
                "texture2": 57.29577951308232,
            }))
        else:
            alpha = offset * 57.29577951308232

        definitions = {
            "type": "hairmat",
            "eta": _sock("IOR", 1.55),
            "alpha": alpha,
        }
        # Blender's Principled Hair exposes a model enum: CHIANG (near-field
        # Marschner lobes) maps to beta_m/beta_n, HUANG (microfacet, EGSR'22)
        # maps to roughness/aspectratio.
        if getattr(node, "model", "CHIANG") == "HUANG":
            definitions["model"] = "huang"
            definitions["roughness"] = _sock("Roughness", 0.3)
            definitions["aspectratio"] = _sock("Aspect Ratio", 0.85)
        else:
            # Roughness/Radial Roughness -> beta_m/beta_n. Both are 0..1 and
            # drive the same longitudinal/azimuthal roughness axes; the exact
            # parameterizations differ so this is a first-order match.
            definitions["beta_m"] = _sock("Roughness", 0.3)
            definitions["beta_n"] = _sock("Radial Roughness", 0.3)
        # Color parameterization is mutually exclusive in both engines.
        if node.parametrization == "ABSORPTION":
            definitions["sigma_a"] = _sock("Absorption Coefficient", [0.0, 0.0, 0.0])
        elif node.parametrization == "COLOR":
            definitions["color"] = _sock("Color", [0.5, 0.5, 0.5])
        else:  # "MELANIN" - eumelanin/pheomelanin concentration model
            mel_sock = node.inputs.get("Melanin")
            red_sock = node.inputs.get("Melanin Redness")
            mel_linked = mel_sock is not None and mel_sock.is_linked
            red_linked = red_sock is not None and red_sock.is_linked
            if not mel_linked and not red_linked:
                melanin = mel_sock.default_value if mel_sock is not None else 0.8
                redness = red_sock.default_value if red_sock is not None else 0.0
                # Cycles: melanin_qty = -ln(1 - Melanin); the concentration is
                # split into eumelanin/pheomelanin by the redness fraction.
                qty = -log(max(1.0 - melanin, 0.0001))
                definitions["eumelanin"] = qty * (1.0 - redness)
                definitions["pheomelanin"] = qty * redness
            else:
                SuperLuxCoreErrorLog.add_warning(
                    'Principled Hair node "%s": textured Melanin inputs are '
                    "approximated by constant melanin concentrations" % node.name,
                    obj_name=obj_name)
                definitions["eumelanin"] = 1.3
                definitions["pheomelanin"] = 0.0
    elif node.bl_idname == "ShaderNodeBsdfTranslucent":
        prefix = "scene.materials."
        definitions = {
            "type": "mattetranslucent",
            # TODO kt and kr don't really match Cycles result yet
            "kt": [1, 1, 1],
            "kr": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "bumptex": _normal_input(node.inputs["Normal"], props, material, obj_name, group_node_stack),
        }
    elif node.bl_idname == "ShaderNodeBsdfTransparent":
        prefix = "scene.materials."
        definitions = {
            "type": "null",
        }
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        if color != 1 and color != [1, 1, 1]:
            definitions["transparency"] = color
    elif node.bl_idname == "ShaderNodeHoldout":
        prefix = "scene.materials."
        definitions = {
            "type": "matte",
            "kd": [0, 0, 0],
            "holdout.enable": True,
        }
    elif node.bl_idname == "ShaderNodeMixRGB":
        prefix = "scene.textures."

        fac_input = node.inputs["Fac"]
        fac = _socket(fac_input, props, material, obj_name, group_node_stack)
        fac = _tex_clamp(fac, 0., 1., superluxcore_name + "_factor", props)

        tex1 = _socket(node.inputs["Color1"], props, material, obj_name, group_node_stack)
        tex2 = _socket(node.inputs["Color2"], props, material, obj_name, group_node_stack)

        definitions, superluxcore_name, early = _blend_rgb(
            node, node.blend_type, fac, tex1, tex2, superluxcore_name, props, obj_name)
        if early is not None:
            return early
    elif node.bl_idname == "ShaderNodeMath":
        # Trig/exp/log ops are backed by SuperLuxCore's native "mathfunc"
        # texture (requires a pysuperluxcore build with MATHFUNC_TEX).

        prefix = "scene.textures."
        definitions = {}
        math_output = None

        tex1 = _socket(node.inputs[0], props, material, obj_name, group_node_stack)
        tex2 = _socket(node.inputs[1], props, material, obj_name, group_node_stack)

        if node.operation in {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "GREATER_THAN", "LESS_THAN"}:
            try:
                definitions["type"] = math_operation_map[node.operation]
            except KeyError:
                definitions["type"] = node.operation.lower()
            definitions["texture1"] = tex1
            definitions["texture2"] = tex2
        elif node.operation == "POWER":
            definitions["type"] = "power"
            definitions["base"] = tex1
            definitions["exponent"] = tex2
        elif node.operation == "ABSOLUTE":
            definitions["type"] = "abs"
            definitions["texture"] = tex1
        elif node.operation == "ROUND":
            # Keep the native float32 half-add even for constants: at large
            # magnitudes Python's double arithmetic changes Blender's ties.
            definitions = {"type": "mathfunc", "op": "round", "texture1": tex1}
        elif node.operation == "MODULO":
            definitions["type"] = "modulo"
            definitions["texture"] = tex1
            definitions["modulo"] = tex2
        elif node.operation == "SQRT":
            math_output = _tex_binary("power", tex1, 0.5, superluxcore_name + "_sqrt",
                                      props)
        elif node.operation == "EXPONENT":
            math_output = _tex_mathfunc("exp", tex1, None, superluxcore_name, props)
        elif node.operation in {"MINIMUM", "MAXIMUM"}:
            math_output = _tex_mathfunc("min" if node.operation == "MINIMUM" else "max",
                                        tex1, tex2, superluxcore_name, props)
        elif node.operation == "RADIANS":
            math_output = _tex_binary("scale", tex1, 0.017453292519943295,
                                      superluxcore_name + "_rad", props)
        elif node.operation == "DEGREES":
            math_output = _tex_binary("scale", tex1, 57.29577951308232,
                                      superluxcore_name + "_deg", props)
        elif node.operation == "COMPARE":
            # Blender compares inclusively and floors epsilon at float32 1e-5.
            tex3 = _socket(node.inputs[2], props, material, obj_name,
                           group_node_stack)
            diff = _tex_binary("subtract", tex1, tex2,
                               superluxcore_name + "_df", props)
            if not _is_textured(diff):
                diff = c_float(diff).value
            absd = _tex_unary("abs", diff, None, superluxcore_name + "_ad", props)
            epsilon = _tex_mathfunc("max", tex3, c_float(1e-5).value,
                                    superluxcore_name + "_eps", props)
            math_output = _tex_mathfunc("lessequal", absd, epsilon,
                                        superluxcore_name + "_cmp", props)
        elif node.operation == "PINGPONG":
            # pingpong(x, s) = s - |mod(x, 2s) - s|
            two_s = _tex_binary("scale", tex2, 2.0, superluxcore_name + "_2s",
                                props)
            mod = _tex_unary("modulo", tex1, two_s,
                             superluxcore_name + "_mod", props)
            dev = _tex_unary("abs",
                             _tex_binary("subtract", mod, tex2,
                                         superluxcore_name + "_sub", props),
                             None, superluxcore_name + "_dev", props)
            math_output = _tex_binary("subtract", tex2, dev,
                                      superluxcore_name + "_pp", props)
        elif node.operation in _MATHFUNC_UNARY_OPS:
            math_output = _tex_mathfunc(_MATHFUNC_UNARY_OPS[node.operation],
                                        tex1, None, superluxcore_name, props)
        elif node.operation in _MATHFUNC_BINARY_OPS:
            math_output = _tex_mathfunc(_MATHFUNC_BINARY_OPS[node.operation],
                                        tex1, tex2, superluxcore_name, props)
        elif node.operation in {"SMOOTH_MIN", "SMOOTH_MAX"}:
            # Polynomial smooth-min/max: h = clamp(0.5 + 0.5*(b-a)/k, 0, 1);
            # smin = mix(b, a, h) - k*h*(1-h), smax = -smin(-a, -b).
            # Third input is the smoothing distance k.
            tex3 = _socket(node.inputs[2], props, material, obj_name,
                           group_node_stack)
            if node.operation == "SMOOTH_MAX":
                na = _tex_binary("scale", tex1, -1.0,
                                 superluxcore_name + "_na", props)
                nb = _tex_binary("scale", tex2, -1.0,
                                 superluxcore_name + "_nb", props)
                smin = _smooth_min(na, nb, tex3, superluxcore_name + "_sm",
                                   props)
                math_output = _tex_binary("scale", smin, -1.0,
                                          superluxcore_name + "_smax", props)
            else:
                math_output = _smooth_min(tex1, tex2, tex3, superluxcore_name + "_smin",
                                          props)
        elif node.operation == "LOGARITHM":
            # log_b(x) = ln(x) / ln(b); Cycles' second input is the base
            num = _tex_mathfunc("ln", tex1, None, superluxcore_name + "_num",
                                props)
            den = _tex_mathfunc("ln", tex2, None, superluxcore_name + "_den",
                                props)
            math_output = _tex_binary("divide", num, den, superluxcore_name + "_log",
                                      props)
        elif node.operation == "SIGN":
            lt0 = _tex_lessthan(tex1, 0.0, superluxcore_name + "_lt0", props)
            gt0 = _tex_greaterthan(tex1, 0.0, superluxcore_name + "_gt0", props)
            math_output = _tex_binary("subtract", gt0, lt0,
                                      superluxcore_name + "_sign", props)
        elif node.operation == "MULTIPLY_ADD":
            tex3 = _socket(node.inputs[2], props, material, obj_name,
                           group_node_stack)
            prod = _tex_binary("scale", tex1, tex2, superluxcore_name + "_mp",
                               props)
            math_output = _tex_binary("add", prod, tex3, superluxcore_name + "_ma",
                                      props)
        elif node.operation == "WRAP":
            # wrap(x, min, max) = min + mod(x - min, max - min)
            rng = _tex_binary("subtract",
                              _socket(node.inputs[2], props, material,
                                      obj_name, group_node_stack),
                              tex2, superluxcore_name + "_rng", props)
            shifted = _tex_binary("subtract", tex1, tex2,
                                  superluxcore_name + "_sh", props)
            mod = _tex_unary("modulo", shifted, rng,
                             superluxcore_name + "_mod", props)
            math_output = _tex_binary("add", tex2, mod, superluxcore_name + "_wr", props)
        elif node.operation == "SNAP":
            definitions = {
                "type": "mathfunc",
                "op": "snap",
                "texture1": tex1,
                "texture2": tex2,
            }
        else:
            # Never silently black: pass through the first input
            return _warn_unsupported(
                node, f"unsupported math operation '{node.operation}', passing through "
                "the first input", tex1, obj_name)
    elif node.bl_idname == "ShaderNodeHueSaturation":
        prefix = "scene.textures."

        hue = _socket(node.inputs["Hue"], props, material, obj_name, group_node_stack)
        saturation = _socket(node.inputs["Saturation"], props, material, obj_name, group_node_stack)
        value = _socket(node.inputs["Value"], props, material, obj_name, group_node_stack)
        fac = _socket(node.inputs["Fac"], props, material, obj_name, group_node_stack)
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)

        definitions = {
            "type": "hsv",
            "texture": color,
            "hue": hue,
            "saturation": saturation,
            "value": value,
        }
        converted = _tex_helper(props, superluxcore_name + "_hsv", definitions)
        return _tex_lerp(color, converted, fac, superluxcore_name, props)
    elif node.bl_idname == "ShaderNodeGroup":
        active_output = None
        for subnode in node.node_tree.nodes:
            if subnode.bl_idname == "NodeGroupOutput" and subnode.is_active_output:
                active_output = subnode
                break

        if active_output is None:
            return _warn_unsupported(node, "사용 가능한 그룹 출력이 없음", ERROR_VALUE, obj_name)
        current_input = _group_socket(active_output.inputs, output_socket)
        if current_input is None:
            return _warn_unsupported(node, "그룹 출력 식별자를 찾을 수 없음", ERROR_VALUE, obj_name)

        if group_node_stack is None:
            _group_node_stack = []
        else:
            _group_node_stack = group_node_stack.copy()
        
        _group_node_stack.append(node)
        
        return _socket(current_input, props, material, obj_name,
                       _group_node_stack, superluxcore_name)
    elif node.bl_idname == "NodeGroupInput":
        return _socket(_group_socket(group_node_stack[-1].inputs, output_socket), props,
                       material, obj_name, group_node_stack[:-1], superluxcore_name)
    elif node.bl_idname == "ShaderNodeEmission":
        prefix = "scene.materials."

        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        # According to the Blender manual, strength is in Watts/m² when the node is used on meshes.
        strength = _socket(node.inputs["Strength"], props, material, obj_name, group_node_stack)

        emission = _tex_binary("scale", strength, color,
                               superluxcore_name + "emission_col", props)

        definitions = {
            "type": "matte",
            "kd": [0, 0, 0],
        }
        if _is_zero(emission):
            # Black/off emission: a scale texture would still register every
            # triangle as a mesh light — a constant 0 is nulled by the engine.
            definitions["emission"] = 0.0
        else:
            definitions.update({
                "emission": emission,
                "emission.gain": [1] * 3,
                "emission.power": 0,
                "emission.efficency": 0,
            })
    elif node.bl_idname == "ShaderNodeValue":
        prefix = "scene.textures."

        definitions = {
            "type": "constfloat1",
            "value": node.outputs[0].default_value,
        }
    elif node.bl_idname == "ShaderNodeRGB":
        prefix = "scene.textures."

        definitions = {
            "type": "constfloat3",
            "value": list(node.outputs[0].default_value)[:3],
        }
    elif node.bl_idname == "ShaderNodeValToRGB":
        ramp = node.color_ramp
        amount = _socket(node.inputs["Fac"], props, material, obj_name, group_node_stack)
        alpha = output_socket.name == "Alpha"
        if ramp.interpolation == "CONSTANT" or (ramp.color_mode == "RGB" and ramp.interpolation == "LINEAR"):
            samples = [(element.position, list(element.color)) for element in ramp.elements]
            interpolation = "none" if ramp.interpolation == "CONSTANT" else "linear"
        else:
            # Blender 자체 평가로 색 공간·색상 방향·곡선 보간을 보존한다.
            positions = sorted(set([i / 512 for i in range(513)] + [e.position for e in ramp.elements]))
            samples = [(position, list(ramp.evaluate(position))) for position in positions]
            interpolation = "linear"
        values = [(position, [rgba[3]] * 3 if alpha else rgba[:3]) for position, rgba in samples]
        result = _tex_band(amount, values, interpolation, superluxcore_name, props)
        return _split_chan(result, 0, superluxcore_name + "_alpha", props) if alpha else result
    elif node.bl_idname == "ShaderNodeTexChecker":
        # 연결 좌표·Scale과 기본 Generated를 유지하며 Color/Fac을 구분한다.
        vector = _texture_coordinates(node, props, material, obj_name, group_node_stack, superluxcore_name)
        scale = _socket(node.inputs["Scale"], props, material, obj_name, group_node_stack)
        parity = 0.
        for i in range(3):
            tag = superluxcore_name + f"_checker{i}"
            value = _tex_binary("scale", _split_chan(vector, i, tag + "_input", props), scale, tag + "_scale", props)
            # Cycles가 정수 경계의 부동소수점 오차를 피하는 보정을 그대로 사용한다.
            value = _tex_binary("scale", _tex_binary("add", value, .000001, tag + "_epsilon", props), .999999, tag + "_coordinate", props)
            value = _tex_mathfunc("floor", value, None, tag + "_floor", props)
            value = _tex_unary("abs", value, None, tag + "_abs", props)
            parity = _tex_binary("add", parity, value, tag + "_parity", props)
        factor = _tex_mathfunc("floormod", parity, 2., superluxcore_name + "_factor", props)
        if output_socket.type == "VALUE":
            return factor
        return _tex_mix(_socket(node.inputs["Color2"], props, material, obj_name, group_node_stack),
                        _socket(node.inputs["Color1"], props, material, obj_name, group_node_stack),
                        factor, superluxcore_name, props)
    elif node.bl_idname == "ShaderNodeInvert":
        prefix = "scene.textures."

        fac_input = node.inputs["Fac"]
        fac = _socket(fac_input, props, material, obj_name, group_node_stack)
        if fac_input.is_linked and fac is ERROR_VALUE:
            fac = 1

        tex = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)

        if fac == 0:
            return tex

        definitions = {
            "type": "subtract",
            "texture1": 1,
            "texture2": tex,
        }

        if _is_textured(fac) or (fac > 0 and fac < 1):
            # Here we need to insert a helper texture *after* the current texture
            props.Set(utils.luxutils.create_props(prefix + superluxcore_name + ".", definitions))
            definitions = {
                "type": "mix",
                "texture1": tex,
                "texture2": superluxcore_name,
                "amount": fac,
            }
            superluxcore_name = superluxcore_name + "fac"
    elif node.bl_idname in {"ShaderNodeSeparateRGB", "ShaderNodeSeparateXYZ",
                            "ShaderNodeSeparateColor"}:
        prefix = "scene.textures."

        if node.bl_idname == "ShaderNodeSeparateColor":
            # Blender 5.x renamed Separate RGB; only the RGB mode maps to channels
            if getattr(node, "mode", "RGB") != "RGB":
                return _warn_unsupported(
                    node, f'Separate Color mode "{node.mode}" is not supported '
                    "(only RGB channels can be split)", FALLBACK_FLOAT, obj_name)
            channels = ["Red", "Green", "Blue"]
            tex_socket_name = "Color"
        elif node.bl_idname == "ShaderNodeSeparateRGB":
            channels = ["R", "G", "B"]
            tex_socket_name = "Image"
        else:
            channels = ["X", "Y", "Z"]
            tex_socket_name = "Vector"

        definitions = {
            "type": "splitfloat3",
            "texture": _socket(node.inputs[tex_socket_name], props, material, obj_name, group_node_stack),
            "channel": channels.index(output_socket.name),
        }
    elif node.bl_idname in {"ShaderNodeCombineRGB", "ShaderNodeCombineXYZ",
                            "ShaderNodeCombineColor"}:
        # Blender 5.x renamed Combine RGB; only the RGB mode maps to channels
        if node.bl_idname == "ShaderNodeCombineColor" \
                and getattr(node, "mode", "RGB") != "RGB":
            # Blender 5.x Combine Color modes are input labels: HSV feeds
            # H/S/V, CMYK feeds C/M/K, YUV feeds Y/U/V. All land on the
            # same three channels, so makefloat3 is correct; warn once
            # so the coercion shows in the export log.
            SuperLuxCoreErrorLog.add_warning(
                f'Combine Color mode "{node.mode}" passes channels through '
                "(same positional slots, no color-space conversion)",
                obj_name=obj_name)

        prefix = "scene.textures."

        definitions = {
            "type": "makefloat3",
            "texture1": _socket(node.inputs[0], props, material, obj_name, group_node_stack),
            "texture2": _socket(node.inputs[1], props, material, obj_name, group_node_stack),
            "texture3": _socket(node.inputs[2], props, material, obj_name, group_node_stack),
            # Combine Color/RGB build an RGB color (upsampled in spectral
            # mode); Combine XYZ builds a vector (passed through)
            "color": node.bl_idname != "ShaderNodeCombineXYZ",
        }
    elif node.bl_idname == "ShaderNodeRGBToBW":
        prefix = "scene.textures."

        definitions = {
            "type": "dotproduct",
            "texture1": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "texture2": list(ocio.GetCurrentConfig().getDefaultLumaCoefs()),
        }
    elif node.bl_idname == "ShaderNodeBrightContrast":
        prefix = "scene.textures."

        definitions = {
            "type": "brightcontrast",
            "texture": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "brightness": _socket(node.inputs["Bright"], props, material, obj_name, group_node_stack),
            "contrast": _socket(node.inputs["Contrast"], props, material, obj_name, group_node_stack),
        }
    elif node.bl_idname == "ShaderNodeGamma":
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        gamma = _socket(node.inputs["Gamma"], props, material, obj_name, group_node_stack)
        channels = []
        zero_gamma = _tex_mathfunc("lessequal", _tex_unary("abs", gamma, None, superluxcore_name + "_abs", props), 0., superluxcore_name + "_zero", props)
        for i in range(3):
            tag = superluxcore_name + f"_gamma{i}"
            channel = _split_chan(color, i, tag + "_input", props)
            positive = _tex_greaterthan(channel, 0., tag + "_positive", props)
            base = _tex_mix(1., channel, positive, tag + "_safe_base", props)
            powered = _tex_binary("power", base, gamma, tag + "_power", props)
            value = _tex_mix(channel, powered, positive, tag + "_color", props)
            channels.append(_tex_mix(value, 1., zero_gamma, tag + "_result", props))
        return _tex_helper(props, superluxcore_name, {"type": "makefloat3", "color": _output_is_color(output_socket), **{f"texture{i+1}": v for i, v in enumerate(channels)}})

    elif node.bl_idname == "ShaderNodeNormalMap":
        prefix = "scene.textures."
        spaces = {"TANGENT": 0, "OBJECT": 1, "WORLD": 2,
                  "BLENDER_OBJECT": 3, "BLENDER_WORLD": 4}
        definitions = {
            "type": "cyclesnormalmap",
            "color": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "strength": _socket(node.inputs["Strength"], props, material, obj_name, group_node_stack),
            "space": spaces[node.space],
            "invertgreen": getattr(node, "convention", "OPENGL") == "DIRECTX",
        }
        if node.space == "TANGENT":
            indices = normal_map_attributes.resolve(obj_name, node.uv_map)
            if indices is not None:
                definitions.update(zip(("normalindex", "tangentindex", "signindex"), indices))
    elif node.bl_idname == "ShaderNodeBump":
        prefix = "scene.textures."
        filter_socket = node.inputs.get("Filter Width")
        definitions = {
            "type": "cyclesbump",
            "height": _socket(node.inputs["Height"], props, material, obj_name, group_node_stack),
            "distance": _socket(node.inputs["Distance"], props, material, obj_name, group_node_stack),
            "strength": _socket(node.inputs["Strength"], props, material, obj_name, group_node_stack),
            "normal": _socket(node.inputs["Normal"], props, material, obj_name, group_node_stack),
            "usenormal": node.inputs["Normal"].is_linked,
            "invert": node.invert,
            "filterwidth": filter_socket.default_value if filter_socket is not None else 1.0,
        }
    elif node.bl_idname == "ShaderNodeNewGeometry":
        prefix = "scene.textures."
        definitions = {}
        
        # TODO: when support for pointiness and random per island is added, we have to:
        #  - make sure the necessary shapes are added during object export
        #  - make sure the mesh is re-exported when one of these outputs is used the first time during viewport render, 
        #    otherwise we crash SuperLuxCore in case of random per island, or the feature doesn't work in case of pointiness
        if output_socket.name == "Position":
            definitions["type"] = "position"
        elif output_socket.name == "Normal":
            definitions["type"] = "shadingnormal"
        elif output_socket.name == "True Normal":
            definitions["type"] = "hitpoint"
            definitions["channel"] = "geometrynormal"
        elif output_socket.name == "Backfacing":
            definitions["type"] = "hitpoint"
            definitions["channel"] = "backfacing"
        elif output_socket.name == "Incoming":
            definitions["type"] = "hitpoint"
            definitions["channel"] = "incoming"
        elif output_socket.name == "Parametric":
            definitions["type"] = "hitpoint"
            definitions["channel"] = "parametric"
        else:
            SuperLuxCoreErrorLog.add_warning(f"Unsupported Geometry output socket: {output_socket.name}", obj_name=obj_name)
            return ERROR_VALUE
    elif node.bl_idname == "ShaderNodeObjectInfo":
        prefix = "scene.textures."
        definitions = {}
        
        if output_socket.name == "Object Index":
            definitions["type"] = "objectid"
        elif output_socket.name == "Material Index":
            definitions["type"] = "constfloat1"
            definitions["value"] = material.pass_index
        elif output_socket.name == "Random":
            definitions["type"] = "objectidnormalized"
        elif output_socket.name == "Location":
            # The hit object's world-space origin is the translation column
            # of hitPoint.localToWorld (per-instance for dupli/particles).
            definitions["type"] = "hitpoint"
            definitions["channel"] = "objectorigin"
        else:
            SuperLuxCoreErrorLog.add_warning(f"Unsupported Object Info output socket: {output_socket.name}", obj_name=obj_name)
            return ERROR_VALUE
    elif node.bl_idname == "ShaderNodeHairInfo":
        prefix = "scene.textures."
        definitions = {}

        if output_socket.name == "Intercept":
            # Normalized position along the strand (0 = root, 1 = tip), written
            # by the strands tessellation into vertex AOV layer
            # HAIR_STRAND_U_DATA_INDEX (see slg/shapes/strands.h).
            definitions["type"] = "hitpointvertexaov"
            definitions["dataindex"] = 7
        elif output_socket.name == "Random":
            # Deterministic per-strand random in [0,1), written by the strands
            # tessellation into vertex AOV layer HAIR_STRAND_RANDOM_DATA_INDEX.
            definitions["type"] = "hitpointvertexaov"
            definitions["dataindex"] = 0
        elif output_socket.name == "Is Strand":
            # HairInfo is only meaningful on strand geometry, where every
            # shaded point is a strand.
            definitions["type"] = "constfloat1"
            definitions["value"] = 1.0
        else:
            SuperLuxCoreErrorLog.add_warning(
                f"Unsupported Hair Info output socket: {output_socket.name}",
                obj_name=obj_name)
            return ERROR_VALUE
    elif node.bl_idname == "ShaderNodeParticleInfo":
        prefix = "scene.textures."
        definitions = {}

        # Particle instances are exported as duplicated objects, each carrying
        # its Blender random_id as the SuperLuxCore object id (see object_cache.py).
        # hitPoint.objectID is therefore unique per particle.
        if output_socket.name == "Index":
            # Unique id per particle instance (deterministic, not sequential).
            definitions["type"] = "objectid"
        elif output_socket.name == "Random":
            # Per-particle random in [0, 1) derived from the instance id.
            definitions["type"] = "objectidnormalized"
        elif output_socket.name == "Location":
            # The particle's world position is the per-instance transform's
            # translation - each particle instance exports as its own
            # SceneObject, so hitPoint.p coincides with the particle origin
            # at the hit point. hitpoint.worldpos exposes it directly.
            definitions["type"] = "hitpoint"
            definitions["channel"] = "worldpos"
        else:
            # Age/Lifetime/Location/Size/Velocity/Angular Velocity require
            # particle simulation state that is not exported to SuperLuxCore.
            SuperLuxCoreErrorLog.add_warning(
                f"Unsupported Particle Info output socket: {output_socket.name}",
                obj_name=obj_name)
            return ERROR_VALUE
    elif node.bl_idname == "ShaderNodeCameraData":
        prefix = "scene.textures."
        if output_socket.name == "View Vector":
            # Cycles' View Vector = -I (ray direction); incoming is
            # fixedDir (= -rayDir = I). Negate via a scale texture.
            inv = _tex_helper(props, superluxcore_name + "_inv", {
                "type": "hitpoint", "channel": "incoming"})
            definitions = {
                "type": "scale",
                "texture1": inv,
                "texture2": -1.0,
            }
        elif output_socket.name == "View Distance":
            definitions = {
                "type": "rayinfo",
                "channel": "raylength",
            }
        elif output_socket.name == "View Z Depth":
            # Camera-space depth along the forward axis, stamped per
            # hit by Scene::Intersect (base pose for motion blur).
            definitions = {
                "type": "rayinfo",
                "channel": "viewdepth",
            }
        else:
            return _warn_unsupported(
                node, f"'{output_socket.name}' output is not supported "
                "(needs camera projection); using 0", 0.0, obj_name)
    elif node.bl_idname == "ShaderNodeVolumeInfo":
        # Reads one of the object's OpenVDB grids (density / color / flame /
        # temperature) as a world-space densitygrid texture — the same
        # sampling the auto-built heterogeneous volume uses.
        from . import volume  # lazy: volume->object_cache->cycles_node_reader cycle
        definitions = volume.volume_info_grid_defs(node, output_socket.name, obj_name)
        if definitions is None:
            return ERROR_VALUE
        prefix = "scene.textures."
    elif node.bl_idname == "ShaderNodeBlackbody":
        temperature_socket = node.inputs["Temperature"]
        prefix = "scene.textures."

        if temperature_socket.is_linked:
            # A linked temperature (e.g. a density grid or attribute) drives the
            # per-point Planckian eval on the SuperLuxCore side.
            temperature = _socket(temperature_socket, props, material, obj_name, group_node_stack)
        else:
            temperature = temperature_socket.default_value

        definitions = {
            "type": "blackbody",
            "temperature": temperature,
            "normalize": True,
        }
    elif node.bl_idname == "ShaderNodeMapRange":
        return _map_range(node, props, material, obj_name, group_node_stack, superluxcore_name)
    elif node.bl_idname == "ShaderNodeSubsurfaceScattering":
        prefix = "scene.materials."

        # Nonzero radii use the native OpenPBR bulk-scattering model.
        # Its dielectric interface differs from Cycles' standalone BSSRDF;
        # broader positive-radius fidelity is tracked separately.
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)
        scale = _socket(node.inputs["Scale"], props, material, obj_name, group_node_stack)
        if scale is ERROR_VALUE:
            scale = 1.0
        radius = _socket(node.inputs.get("Radius"), props, material, obj_name,
                         group_node_stack)
        if radius is ERROR_VALUE or radius is None:
            radius = [1.0, 1.0, 1.0]

        # Cycles bssrdf_setup replaces sub-1e-8 channel radii with Lambert
        # diffuse. At zero Scale all channels take this exact local limit;
        # an opaque bulk volume would absorb them before they can exit.
        # Resolve constant Value/RGB outputs without changing the graph.
        # Cycles tests the float32 product of Scale and each Radius channel
        # before remapping it for the selected BSSRDF method.
        def constant_input(value):
            if _is_textured(value):
                key = "scene.textures." + value
                if props.IsDefined(key + ".type") and props.Get(key + ".type").GetString() in \
                        ("constfloat1", "constfloat3"):
                    values = props.Get(key + ".value").Get()
                    return values[0] if len(values) == 1 else values
            return value

        constant_scale = constant_input(scale)
        constant_radius = constant_input(radius)
        radius_channels = None if _is_textured(constant_radius) else \
            (constant_radius if isinstance(constant_radius, (list, tuple)) else [constant_radius] * 3)
        local_diffuse = radius_channels is not None and all(r == 0.0 for r in radius_channels)
        if not _is_textured(constant_scale):
            local_diffuse |= constant_scale <= 0.0
            if radius_channels is not None:
                local_diffuse |= all(c_float(c_float(constant_scale).value * c_float(r).value).value <
                                     c_float(1e-8).value for r in radius_channels)
        if local_diffuse:
            definitions = {"type": "matte", "kd": color}
            if node.inputs.get("Normal") is not None:
                definitions["bumptex"] = _normal_input(
                    node.inputs["Normal"], props, material, obj_name, group_node_stack)
            props.Set(utils.luxutils.create_props(prefix + superluxcore_name + ".", definitions))
            return superluxcore_name

        roughness_socket = node.inputs.get("Roughness")
        roughness = _socket(roughness_socket, props, material, obj_name,
                            group_node_stack) if roughness_socket else 0.5
        if roughness is ERROR_VALUE:
            roughness = 0.5

        # The node's "Weight" input is Blender's hidden closure-weight
        # socket (default 0.0, ignored by Cycles): the standalone SSS node
        # is always fully subsurface. Reading it exported weight 0.
        weight = 1.0

        definitions = {
            "type": "openpbr",
            "basecolor": color,
            "basemetalness": 0.0,
            "specularroughness": roughness,
            "specularior": _socket(node.inputs.get("IOR"), props, material,
                                   obj_name, group_node_stack) or 1.4,
            "subsurfaceweight": weight,
            # Cycles tints SSS by the Color input
            "subsurfacecolor": color,
            # Cycles Scale scales the per-channel Radius vector; openpbr
            # separates the two, so Scale feeds the mean free path and
            # Radius feeds the chromatic scale
            "subsurfaceradius": scale,
            "subsurfaceradiusscale": radius,
        }
        anisotropy_socket = node.inputs.get("Anisotropy")
        if anisotropy_socket is not None:
            anisotropy = _socket(anisotropy_socket, props, material, obj_name,
                                 group_node_stack)
            if anisotropy is not None and anisotropy is not ERROR_VALUE:
                definitions["subsurfaceanisotropy"] = anisotropy
        if node.inputs.get("Normal") is not None:
            definitions["bumptex"] = _normal_input(node.inputs["Normal"], props, material,
                                             obj_name, group_node_stack)
    elif node.bl_idname == "ShaderNodeBsdfVelvet":
        prefix = "scene.materials."

        # Cycles' Velvet BSDF is a sheen lobe (Charlie distribution), so
        # S7's charlie model is the physical match, not legacy velvet.
        # Sigma plays the roughness role -> sheenroughness.
        sigma = _socket(node.inputs["Sigma"], props, material, obj_name, group_node_stack)
        if sigma is ERROR_VALUE:
            sigma = 0.5

        definitions = {
            "type": "velvet",
            "model": "charlie",
            "kd": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
            "sheenroughness": sigma,
        }
        if node.inputs.get("Normal") is not None:
            definitions["bumptex"] = _normal_input(node.inputs["Normal"], props, material,
                                             obj_name, group_node_stack)
    elif node.bl_idname == "ShaderNodeBsdfSheen":
        prefix = "scene.materials."
        roughness_socket = node.inputs.get("Roughness")
        roughness = _socket(roughness_socket, props, material, obj_name,
                            group_node_stack) if roughness_socket else 0.5
        if roughness is ERROR_VALUE:
            roughness = 0.5
        color = _socket(node.inputs["Color"], props, material, obj_name, group_node_stack)

        if getattr(node, "distribution", "MICROFIBER") == "MICROFIBER":
            # Cycles' default sheen is Zeltner's SGGX-LTC microfiber lobe,
            # also used by native OpenPBR fuzz. Disable the other lobes for
            # this standalone closure, including its hidden zero Weight.
            definitions = {
                "type": "openpbr", "baseweight": 0.0, "specularweight": 0.0,
                "fuzzweight": 1.0, "fuzzcolor": color, "fuzzroughness": roughness,
            }
        else:
            # Legacy Ashikhmin remains an approximation pending its native
            # closure. Do not silently claim equivalence to Charlie sheen.
            _warn_unsupported(node, "Ashikhmin sheen is approximated by native Charlie sheen",
                              None, obj_name)
            definitions = {
                "type": "velvet", "model": "charlie", "kd": color,
                "sheenroughness": roughness,
            }
        if node.inputs.get("Normal") is not None:
            definitions["bumptex"] = _normal_input(node.inputs["Normal"], props, material,
                                             obj_name, group_node_stack)
    elif node.bl_idname == "ShaderNodeBsdfToon":
        prefix = "scene.materials."

        # Approximation: no toon closure in SuperLuxCore; matte keeps the base color
        SuperLuxCoreErrorLog.add_warning(
            f'Toon BSDF node "{node.name}" is approximated by a matte material',
            obj_name=obj_name)

        definitions = {
            "type": "matte",
            "kd": _socket(node.inputs["Color"], props, material, obj_name, group_node_stack),
        }
        if node.inputs.get("Normal") is not None:
            definitions["bumptex"] = _normal_input(node.inputs["Normal"], props, material,
                                             obj_name, group_node_stack)
    elif node.bl_idname == "ShaderNodeFresnel":
        prefix = "scene.textures."

        if node.inputs["Normal"].is_linked:
            SuperLuxCoreErrorLog.add_warning(
                f'Fresnel node "{node.name}": the Normal input is not supported',
                obj_name=obj_name)

        ior_socket = node.inputs["IOR"]
        ior = _socket(ior_socket, props, material, obj_name, group_node_stack)
        if ior is ERROR_VALUE:
            ior = 1.45

        if _is_textured(ior):
            # fresnelior's eta is a scalar property - a textured IOR has no
            # angular term to feed. Keep the Schlick F0 chain approximation
            # for that rare case.
            _warn_unsupported(
                node, "textured IOR has no angular Fresnel texture path; "
                "using the Schlick F0 normal-incidence reflectance",
                None, obj_name)
            n_minus_1 = _tex_helper(props, superluxcore_name + "_f0sub", {
                "type": "subtract", "texture1": ior, "texture2": 1})
            n_plus_1 = _tex_helper(props, superluxcore_name + "_f0add", {
                "type": "add", "texture1": ior, "texture2": 1})
            ratio = _tex_helper(props, superluxcore_name + "_f0div", {
                "type": "divide", "texture1": n_minus_1, "texture2": n_plus_1})
            definitions = {"type": "power", "base": ratio, "exponent": 2}
        else:
            # Exact dielectric Fresnel evaluated at the incident angle -
            # the fresnelior texture reads cosi from HitPoint.fixedDir/shadeN.
            definitions = {
                "type": "fresnelior",
                "ior": float(ior),
            }
    elif node.bl_idname == "ShaderNodeLayerWeight":
        name = superluxcore_name
        blend = _socket(node.inputs["Blend"], props, material, obj_name, group_node_stack)
        normal_socket = node.inputs["Normal"]
        normal = _socket(normal_socket, props, material, obj_name, group_node_stack) if normal_socket.is_linked else _tex_helper(props, name + "_normal", {"type": "shadingnormal"})
        incoming = _tex_helper(props, name + "_incoming", {"type": "hitpoint", "channel": "incoming"})
        cosine = _tex_binary("dotproduct", normal, incoming, name + "_dot", props)
        cosine = _tex_clamp(_tex_unary("abs", cosine, None, name + "_abs", props), 0., 1., name + "_cosine", props)
        if output_socket.name == "Facing":
            blend = _tex_clamp(blend, 0., 1. - 1e-5, name + "_blend", props)
            low = _tex_binary("scale", blend, 2., name + "_low", props)
            high = _tex_binary("divide", .5, _tex_binary("subtract", 1., blend, name + "_one_minus", props), name + "_high", props)
            branch = _tex_lessthan(blend, .5, name + "_branch", props)
            exponent = _tex_mix(high, low, branch, name + "_exponent", props)
            powered = _tex_binary("power", cosine, exponent, name + "_power", props)
            return _tex_binary("subtract", 1., powered, name, props)
        eta = _tex_mathfunc("max", _tex_binary("subtract", 1., blend, name + "_eta_input", props), 1e-5, name + "_eta", props)
        inverse_eta = _tex_binary("divide", 1., eta, name + "_eta_inverse", props)
        backfacing = _tex_helper(props, name + "_backfacing", {"type": "hitpoint", "channel": "backfacing"})
        eta = _tex_mix(inverse_eta, eta, backfacing, name + "_side_eta", props)
        sin_squared = _tex_binary("subtract", 1., _tex_binary("scale", cosine, cosine, name + "_cos_squared", props), name + "_sin_squared", props)
        transmitted_squared = _tex_binary("subtract", 1., _tex_binary("divide", sin_squared, _tex_binary("scale", eta, eta, name + "_eta_squared", props), name + "_sin_transmitted", props), name + "_cos_transmitted_squared", props)
        transmitted = _tex_binary("power", _tex_mathfunc("max", transmitted_squared, 0., name + "_nonnegative", props), .5, name + "_cos_transmitted", props)
        eta_cos = _tex_binary("scale", eta, cosine, name + "_eta_cos", props)
        eta_transmitted = _tex_binary("scale", eta, transmitted, name + "_eta_transmitted", props)
        parallel = _tex_binary("divide", _tex_binary("subtract", eta_cos, transmitted, name + "_parallel_num", props), _tex_binary("add", eta_cos, transmitted, name + "_parallel_den", props), name + "_parallel", props)
        perpendicular = _tex_binary("divide", _tex_binary("subtract", cosine, eta_transmitted, name + "_perpendicular_num", props), _tex_binary("add", cosine, eta_transmitted, name + "_perpendicular_den", props), name + "_perpendicular", props)
        reflected = _tex_binary("scale", .5, _tex_binary("add", _tex_binary("scale", parallel, parallel, name + "_parallel_squared", props), _tex_binary("scale", perpendicular, perpendicular, name + "_perpendicular_squared", props), name + "_sum", props), name + "_reflected", props)
        total_reflection = _tex_mathfunc("lessequal", transmitted_squared, 0., name + "_tir", props)
        return _tex_mix(reflected, 1., total_reflection, name, props)
    elif node.bl_idname == "ShaderNodeLightPath":
        # The SuperLuxCore "rayinfo" texture exposes the context of the ray that
        # generated the current hit point (stored in HitPoint by
        # Scene::Intersect()). All Light Path outputs are supported.
        channel = _LIGHT_PATH_CHANNELS.get(output_socket.name)
        if channel is None:
            return _warn_unsupported(
                node, f"unknown Light Path output '{output_socket.name}'; "
                "using constant 0", 0.0, obj_name)

        prefix = "scene.textures."
        definitions = {
            "type": "rayinfo",
            "channel": channel,
        }
    elif node.bl_idname == "ShaderNodeMix":
        prefix = "scene.textures."
        data_type = node.data_type

        # The unified Mix node keeps one "Factor"/"A"/"B" socket per data type;
        # only the ones matching the active type are enabled. Match both the
        # name and the socket type for robustness.
        socket_type = {"FLOAT": "NodeSocketFloat",
                       "VECTOR": "NodeSocketVector",
                       "RGBA": "NodeSocketColor"}.get(data_type)
        factor_type = "NodeSocketVector" if (
            data_type == "VECTOR" and
            getattr(node, "factor_mode", "UNIFORM") == "NON_UNIFORM"
        ) else "NodeSocketFloat"

        def mix_input(name, bl_socket):
            candidates = [s for s in node.inputs if s.name == name]
            for socket in candidates:
                if socket.bl_idname.startswith(bl_socket) and socket.enabled:
                    return socket
            for socket in candidates:
                if socket.bl_idname.startswith(bl_socket):
                    return socket
            return candidates[0] if candidates else None

        factor_socket = mix_input("Factor", factor_type)
        fac = _socket(factor_socket, props, material, obj_name,
                      group_node_stack) if factor_socket else 0.5

        socket_a = mix_input("A", socket_type)
        socket_b = mix_input("B", socket_type)
        if socket_a is None or socket_b is None:
            return _warn_unsupported(
                node, "could not resolve the A/B inputs", FALLBACK_FLOAT, obj_name)
        # Note: a legitimate 0 input compares equal to ERROR_VALUE; a failed
        # upstream node already logged its own warning, so just use the value
        tex1 = _socket(socket_a, props, material, obj_name, group_node_stack)
        tex2 = _socket(socket_b, props, material, obj_name, group_node_stack)

        if data_type == "RGBA":
            if getattr(node, "clamp_factor", True):
                fac = _tex_clamp(fac, 0., 1., superluxcore_name + "_factor", props)
            definitions, superluxcore_name, early = _blend_rgb(
                node, node.blend_type, fac, tex1, tex2, superluxcore_name, props, obj_name)
            if early is not None:
                return _tex_clamp(early, 0., 1., superluxcore_name + "_resultclamp", props) if node.clamp_result else early
        elif data_type in {"FLOAT", "VECTOR"}:
            # 엔진 Mix는 스칼라 계수만 사용하므로 벡터 계수와 외삽은 산술식으로 보존한다.
            if getattr(node, "clamp_factor", True):
                fac = _tex_mathfunc("max", fac, 0., superluxcore_name + "_factor_min", props)
                fac = _tex_mathfunc("min", fac, 1., superluxcore_name + "_factor_max", props)
            delta = _tex_binary("subtract", tex2, tex1, superluxcore_name + "_delta", props)
            weighted = _tex_binary("scale", delta, fac, superluxcore_name + "_weighted", props)
            return _tex_binary("add", tex1, weighted, superluxcore_name + "_mix", props)
        else:
            # ROTATION
            return _warn_unsupported(
                node, f'data type "{data_type}" is not supported, passing through '
                "input A", tex1, obj_name)

        if getattr(node, "clamp_result", False):
            # Clamp the mix result (mirrors the use_clamp handling below)
            props.Set(utils.luxutils.create_props(prefix + superluxcore_name + ".", definitions))
            definitions = {
                "type": "clamp",
                "texture": superluxcore_name,
                "min": 0,
                "max": 1,
            }
            superluxcore_name = superluxcore_name + "clamp"
    elif node.bl_idname == "ShaderNodeVectorMath":
        prefix = "scene.textures."
        operation = node.operation
        vector_out = output_socket.name != "Value"

        vector1 = _socket(node.inputs[0], props, material, obj_name, group_node_stack)
        vector2 = _socket(node.inputs[1], props, material, obj_name, group_node_stack)

        # Elementwise Spectrum ops double as vector math ops in SuperLuxCore
        direct_ops = {
            "ADD": "add",
            "SUBTRACT": "subtract",
            "MULTIPLY": "scale",
            "DOT_PRODUCT": "dotproduct",
        }

        if operation in direct_ops:
            definitions = {
                "type": direct_ops[operation],
                "texture1": vector1,
                "texture2": vector2,
            }
        elif operation == "DIVIDE":
            # Cycles safe_divide handles zero denominators per component.
            # Spectrum division only guards an entirely black denominator;
            # scalar division guards each component without producing inf/NaN.
            channels = [
                _tex_binary(
                    "divide",
                    _split_chan(vector1, i, superluxcore_name + f"_a{i}", props),
                    _split_chan(vector2, i, superluxcore_name + f"_b{i}", props),
                    superluxcore_name + f"_divide{i}", props)
                for i in range(3)
            ]
            return _combine3(*channels, superluxcore_name, props)
        elif operation == "SIGN":
            channels = []
            for i in range(3):
                value = _split_chan(vector1, i, superluxcore_name + f"_input{i}", props)
                positive = _tex_greaterthan(value, 0., superluxcore_name + f"_positive{i}", props)
                negative = _tex_lessthan(value, 0., superluxcore_name + f"_negative{i}", props)
                channels.append(_tex_binary("subtract", positive, negative, superluxcore_name + f"_sign{i}", props))
            return _tex_helper(props, superluxcore_name, {"type": "makefloat3", **{f"texture{i+1}": v for i, v in enumerate(channels)}})
        elif operation == "POWER":
            channels = [_tex_binary("power", _split_chan(vector1, i, superluxcore_name + f"_a{i}", props), _split_chan(vector2, i, superluxcore_name + f"_b{i}", props), superluxcore_name + f"_power{i}", props) for i in range(3)]
            return _tex_helper(props, superluxcore_name, {"type": "makefloat3", **{f"texture{i+1}": v for i, v in enumerate(channels)}})
        elif operation == "ABSOLUTE":
            definitions = {"type": "abs", "texture": vector1}
        elif operation == "MODULO":
            definitions = {
                "type": "modulo",
                "texture": vector1,
                "modulo": vector2,
            }
        elif operation == "SCALE":
            definitions = {
                "type": "scale",
                "texture1": vector1,
                "texture2": _socket(node.inputs["Scale"], props, material,
                                    obj_name, group_node_stack),
            }
        elif operation == "LENGTH":
            # |v| = sqrt(v . v)
            squared = _tex_helper(props, superluxcore_name + "_sq", {
                "type": "dotproduct", "texture1": vector1, "texture2": vector1})
            definitions = {"type": "power", "base": squared, "exponent": 0.5}
        elif operation == "DISTANCE":
            # |a - b| = sqrt((a - b) . (a - b))
            diff = _tex_helper(props, superluxcore_name + "_diff", {
                "type": "subtract", "texture1": vector1, "texture2": vector2})
            squared = _tex_helper(props, superluxcore_name + "_sq", {
                "type": "dotproduct", "texture1": diff, "texture2": diff})
            definitions = {"type": "power", "base": squared, "exponent": 0.5}
        elif operation == "NORMALIZE":
            # v / |v|; the scalar length broadcasts to all 3 channels
            squared = _tex_helper(props, superluxcore_name + "_sq", {
                "type": "dotproduct", "texture1": vector1, "texture2": vector1})
            length = _tex_helper(props, superluxcore_name + "_len", {
                "type": "power", "base": squared, "exponent": 0.5})
            definitions = {
                "type": "divide",
                "texture1": vector1,
                "texture2": length,
            }
        elif operation == "CROSS_PRODUCT":
            a = [_split_chan(vector1, i, superluxcore_name + f"_a{i}", props)
                 for i in range(3)]
            b = [_split_chan(vector2, i, superluxcore_name + f"_b{i}", props)
                 for i in range(3)]

            def _mul(t1, t2, tag):
                return _tex_binary("scale", t1, t2, superluxcore_name + tag, props)

            cross = [
                _tex_binary("subtract", _mul(a[1], b[2], "_x0p"),
                            _mul(a[2], b[1], "_x0m"), superluxcore_name + "_cx", props),
                _tex_binary("subtract", _mul(a[2], b[0], "_x1p"),
                            _mul(a[0], b[2], "_x1m"), superluxcore_name + "_cy", props),
                _tex_binary("subtract", _mul(a[0], b[1], "_x2p"),
                            _mul(a[1], b[0], "_x2m"), superluxcore_name + "_cz", props),
            ]
            return _combine3(cross[0], cross[1], cross[2],
                             superluxcore_name + "_cross", props)
        elif operation in {"REFLECT", "REFRACT"}:
            # Cycles는 두 번째 입력을 안전하게 정규화한 뒤 반사·굴절을 계산한다.
            length2 = _tex_binary("dotproduct", vector2, vector2,
                                  superluxcore_name + "_normal_len2", props)
            length = _tex_binary("power", length2, .5, superluxcore_name + "_normal_len", props)
            vector2 = _tex_binary("divide", vector2, length, superluxcore_name + "_normal", props)
            if operation == "REFRACT":
                eta = _socket(node.inputs["Scale"], props, material, obj_name, group_node_stack)
                dot = _tex_binary("dotproduct", vector1, vector2, superluxcore_name + "_dot", props)
                dot2 = _tex_binary("scale", dot, dot, superluxcore_name + "_dot2", props)
                eta2 = _tex_binary("scale", eta, eta, superluxcore_name + "_eta2", props)
                term = _tex_binary("subtract", 1., dot2, superluxcore_name + "_sin2", props)
                term = _tex_binary("scale", eta2, term, superluxcore_name + "_term", props)
                k = _tex_binary("subtract", 1., term, superluxcore_name + "_k", props)
                positive = _tex_mathfunc("max", k, 0., superluxcore_name + "_positive", props)
                root = _tex_binary("power", positive, .5, superluxcore_name + "_root", props)
                amount = _tex_binary("scale", eta, dot, superluxcore_name + "_eta_dot", props)
                amount = _tex_binary("add", amount, root, superluxcore_name + "_amount", props)
                incoming = _tex_binary("scale", vector1, eta, superluxcore_name + "_incoming", props)
                normal = _tex_binary("scale", vector2, amount, superluxcore_name + "_normal_scaled", props)
                result = _tex_binary("subtract", incoming, normal, superluxcore_name + "_refract", props)
                valid = _tex_binary("subtract", 1., _tex_lessthan(k, 0., superluxcore_name + "_tir", props),
                                    superluxcore_name + "_valid", props)
                return _tex_binary("scale", result, valid, superluxcore_name + "_result", props)
            dot = _tex_binary("dotproduct", vector1, vector2,
                              superluxcore_name + "_dot", props)
            two_dot = _tex_binary("scale", dot, 2.0, superluxcore_name + "_2d", props)
            scaled_n = _tex_binary("scale", vector2, two_dot,
                                   superluxcore_name + "_sn", props)
            return _tex_binary("subtract", vector1, scaled_n,
                               superluxcore_name + "_refl", props)
        elif operation == "PROJECT":
            # proj of a onto b = b * (a . b) / (b . b)
            dot = _tex_binary("dotproduct", vector1, vector2,
                              superluxcore_name + "_dot", props)
            len2 = _tex_binary("dotproduct", vector2, vector2,
                               superluxcore_name + "_len2", props)
            frac = _tex_binary("divide", dot, len2, superluxcore_name + "_fr", props)
            return _tex_binary("scale", vector2, frac,
                               superluxcore_name + "_proj", props)
        elif operation == "FACEFORWARD":
            # Blender: returns n if dot(i, nref) < 0 else -n, i.e.
            # n * (2*lt(dot,0) - 1). Inputs: Vector, Incident, Reference.
            incident = _socket(node.inputs[1], props, material, obj_name,
                               group_node_stack)
            reference = _socket(node.inputs[2], props, material, obj_name,
                                group_node_stack)
            dot = _tex_binary("dotproduct", incident, reference,
                              superluxcore_name + "_dot", props)
            lt = _tex_lessthan(dot, 0.0, superluxcore_name + "_lt", props)
            sign = _tex_binary("subtract",
                               _tex_binary("scale", lt, 2.0,
                                           superluxcore_name + "_lt2", props),
                               1.0, superluxcore_name + "_sgn", props)
            return _tex_binary("scale", vector1, sign,
                               superluxcore_name + "_ff", props)
        elif operation == "MULTIPLY_ADD":
            # a * b + c (elementwise)
            vector3 = _socket(node.inputs[2], props, material, obj_name,
                              group_node_stack)
            prod = _tex_binary("scale", vector1, vector2,
                               superluxcore_name + "_mp", props)
            return _tex_binary("add", prod, vector3,
                               superluxcore_name + "_madd", props)
        elif operation in {"MINIMUM", "MAXIMUM"}:
            return _tex_mathfunc("min" if operation == "MINIMUM" else "max",
                                 vector1, vector2, superluxcore_name, props)
        elif operation == "WRAP":
            # 입력 순서는 값, 최댓값, 최솟값이다. 폭 0은 최솟값을 반환한다.
            minimum = _socket(node.inputs[2], props, material, obj_name, group_node_stack)
            width = _tex_binary("subtract", vector2, minimum, superluxcore_name + "_width", props)
            shifted = _tex_binary("subtract", vector1, minimum, superluxcore_name + "_shift", props)
            wrapped = _tex_mathfunc("floormod", shifted, width, superluxcore_name + "_wrapped", props)
            return _tex_binary("add", wrapped, minimum, superluxcore_name + "_wrap", props)
        elif operation == "ROUND":
            shifted = _tex_binary("add", vector1, .5, superluxcore_name + "_half", props)
            return _tex_mathfunc("floor", shifted, 0., superluxcore_name + "_round", props)
        elif operation == "SNAP":
            definitions = {
                "type": "mathfunc",
                "op": "snap",
                "texture1": vector1,
                "texture2": vector2,
            }
        elif operation in {"FLOOR", "CEIL", "FRACTION"}:
            definitions = {
                "type": "mathfunc",
                "op": {"FLOOR": "floor", "CEIL": "ceil", "FRACTION": "fract"}[operation],
                "texture1": vector1,
            }
        elif operation in {"SINE", "COSINE", "TANGENT"}:
            # Elementwise trig via mathfunc (matches Cycles' per-component
            # semantics); constants fold to plain vectors
            op = {"SINE": "sin", "COSINE": "cos", "TANGENT": "tan"}[operation]
            return _v3_mathfunc(op, vector1, superluxcore_name, props)
        else:
            # 지원하지 않는 향후 연산은 경고와 함께 첫 번째 입력을 전달한다.
            # pass through instead of blacking out
            if vector_out:
                return _warn_unsupported(
                    node, f"vector math operation '{operation}' is not supported, "
                    "passing through the first input", vector1, obj_name)
    elif node.bl_idname == "ShaderNodeTexCoord":
        prefix = "scene.textures."
        coord = output_socket.name
        if coord == "UV":
            definitions = {"type": "uv", "wrap": False}
        elif coord == "Normal":
            definitions = {"type": "shadingnormal"}
        elif coord == "Object":
            if getattr(node, "object", None) is not None:
                values = _point_transform_channels(node.object.matrix_world.inverted_safe(),
                                                    superluxcore_name, props)
                return _combine3(*values, superluxcore_name + "_object", props)
            # object-space hit point - Cycles' Object output
            definitions = {
                "type": "hitpoint",
                "channel": "objectspace",
            }
        elif coord == "Generated":
            # Exact: object-space hit point normalized into the mesh's local
            # bbox [0,1]^3 - Cycles' Generated coordinate.
            definitions = {
                "type": "hitpoint",
                "channel": "generated",
            }
        elif coord == "Reflection":
            # Exact: reflect(-fixedDir, shadeN) evaluated at the hit point
            definitions = {
                "type": "hitpoint",
                "channel": "reflection",
            }
        elif coord in {"Camera", "Window"}:
            scene = bpy.context.scene
            camera = scene.camera
            if camera is None or camera.data.type not in {"PERSP", "ORTHO"}:
                return _warn_unsupported(node, "현재 카메라에서 좌표 투영을 지원하지 않습니다",
                                         FALLBACK_VECTOR, obj_name)
            world_to_camera = camera.matrix_world.normalized().inverted_safe()
            if coord == "Camera":
                # Cycles의 카메라 좌표는 전방이 +Z이며 Blender 카메라는 -Z이다.
                transform = Matrix.Diagonal((1., 1., -1., 1.)) @ world_to_camera
                values = _point_transform_channels(transform, superluxcore_name, props)
                return _combine3(*values, superluxcore_name + "_camera", props)
            projection = camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),
                x=scene.render.resolution_x, y=scene.render.resolution_y,
                scale_x=scene.render.pixel_aspect_x, scale_y=scene.render.pixel_aspect_y)
            x, y, w = _point_transform_channels(projection @ world_to_camera,
                                                superluxcore_name, props, (0, 1, 3))
            values = []
            for i, value in enumerate((x, y)):
                value = _tex_binary("divide", value, w, f"{superluxcore_name}_divide{i}", props)
                value = _tex_binary("scale", value, .5, f"{superluxcore_name}_half{i}", props)
                values.append(_tex_binary("add", value, .5, f"{superluxcore_name}_ndc{i}", props))
            return _combine3(values[0], values[1], 0., superluxcore_name + "_window", props)
        else:
            # "Camera" and any future outputs
            return _warn_unsupported(
                node, f"texture coordinate output '{coord}' is not supported; "
                "returning a zero vector", FALLBACK_VECTOR, obj_name)
    elif node.bl_idname == "ShaderNodeUVMap":
        prefix = "scene.textures."
        definitions = {"type": "uv", "wrap": False}

        uv_map = getattr(node, "uv_map", "")
        if uv_map:
            index = _uv_layer_index(obj_name, uv_map)
            if index is None:
                SuperLuxCoreErrorLog.add_warning(
                    f'UV map "{uv_map}" of node "{node.name}" could not be resolved '
                    f'on object "{obj_name}", using the default UV layer',
                    obj_name=obj_name)
            else:
                definitions["mapping.uvindex"] = index
    elif node.bl_idname == "ShaderNodeMapping":
        prefix = "scene.textures."
        definitions = {"type": "vectormapping",
                       "mode": {"POINT": 0, "TEXTURE": 1, "VECTOR": 2, "NORMAL": 3}[node.vector_type]}
        for key in ("Vector", "Location", "Rotation", "Scale"):
            socket = node.inputs.get(key)
            definitions[key.lower()] = (_socket(socket, props, material, obj_name, group_node_stack)
                                        if socket is not None else [0., 0., 0.])
    elif node.bl_idname == "ShaderNodeNormal":
        # The "Normal" output is the fixed direction set in the node widget
        try:
            normal = list(node.outputs["Normal"].default_value)[:3]
        except (TypeError, KeyError):
            normal = [0.0, 0.0, 1.0]

        if output_socket.name == "Dot":
            prefix = "scene.textures."
            other = _socket(node.inputs["Normal"], props, material, obj_name,
                            group_node_stack)
            if _is_textured(other):
                definitions = {
                    "type": "dotproduct",
                    "texture1": other,
                    "texture2": normal,
                }
            elif isinstance(other, (list, tuple)):
                return sum(a * b for a, b in zip(other, normal))
            else:
                return 0.0
        else:
            return normal
    elif node.bl_idname == "ShaderNodeTangent":
        # No tangent texture in SuperLuxCore (hitPoint.dpdu/dpdv is not exposed)
        return _warn_unsupported(
            node, "Tangent node is not supported; returning a zero vector",
            FALLBACK_VECTOR, obj_name)
    elif node.bl_idname == "ShaderNodeBevel":
        prefix = "scene.textures."
        # Bump-only rounded edges; requires the edgedetectoraov shape wrapper
        # (requested by needs_edge_detector_shape when this node is present)
        if node.inputs["Normal"].is_linked:
            SuperLuxCoreErrorLog.add_warning(
                f'Bevel node "{node.name}": the Normal input is not '
                "supported, the shading normal is used", obj_name=obj_name)
        if node.inputs["Radius"].is_linked:
            SuperLuxCoreErrorLog.add_warning(
                f'Bevel node "{node.name}": a texture-linked Radius is not '
                "supported, using the constant default", obj_name=obj_name)
        definitions = {
            "type": "bevel",
            "radius": node.inputs["Radius"].default_value,
        }
    elif node.bl_idname == "ShaderNodeAmbientOcclusion":
        # No AO texture in SuperLuxCore; approximate "fully lit"
        if output_socket.name == "AO":
            return _warn_unsupported(
                node, "Ambient Occlusion is not supported; returning 1 "
                "(unoccluded)", 1.0, obj_name)
        color = _socket(node.inputs["Color"], props, material, obj_name,
                        group_node_stack)
        if color is ERROR_VALUE:
            color = [1.0, 1.0, 1.0]
        return _warn_unsupported(
            node, "Ambient Occlusion is not supported; passing through the "
            "unoccluded color", color, obj_name)
    elif node.bl_idname == "ShaderNodeWireframe":
        prefix = "scene.textures."

        if node.use_pixel_size:
            SuperLuxCoreErrorLog.add_warning(
                f'Wireframe node "{node.name}": pixel size mode is not supported',
                obj_name=obj_name)

        definitions = {
            "type": "wireframe",
            # Fac output: 1 on edges (border), 0 inside
            "border": 1.0,
            "inside": 0.0,
            "width": _socket(node.inputs["Size"], props, material, obj_name,
                             group_node_stack),
        }
    elif node.bl_idname in {"ShaderNodeAttribute", "ShaderNodeVertexColor"}:
        prefix = "scene.textures."
        # ShaderNodeVertexColor is the legacy (pre-3.0) version of the
        # Attribute node and only exposes the layer name plus Color/Alpha
        attribute_name = node.attribute_name \
            if node.bl_idname == "ShaderNodeAttribute" \
            else getattr(node, "layer_name", "")

        data_index = _color_attribute_index(obj_name, attribute_name)

        if output_socket.name == "Vector" and data_index is None:
            # A named UV layer can serve the Vector output
            uv_index = _uv_layer_index(obj_name, attribute_name)
            if uv_index is not None:
                definitions = {
                    "type": "uv",
                    "mapping.uvindex": uv_index,
                }
                data_index = -2  # marker: handled

        if data_index is None:
            # Generic named attribute (e.g. written by Geometry Nodes):
            # exported by mesh_converter as vertex/triangle AOV or an
            # extra color layer.
            named = named_attributes.resolve(obj_name, attribute_name)
            if named is not None:
                kind, named_index = named
                if output_socket.name == "Alpha":
                    # Scalar/vector attributes carry no alpha channel
                    definitions = {"type": "constfloat1", "value": 1.0}
                elif output_socket.name == "Fac":
                    definitions = {
                        "type": {
                            named_attributes.KIND_VERTEX_AOV:
                                "hitpointvertexaov",
                            named_attributes.KIND_TRIANGLE_AOV:
                                "hitpointtriangleaov",
                            named_attributes.KIND_COLOR: "hitpointgrey",
                        }[kind],
                        "dataindex": named_index,
                    }
                    if kind == named_attributes.KIND_COLOR:
                        definitions["channel"] = -1
                else:
                    # "Color" and "Vector" outputs
                    definitions = {
                        "type": {
                            named_attributes.KIND_VERTEX_AOV:
                                "hitpointvertexaov",
                            named_attributes.KIND_TRIANGLE_AOV:
                                "hitpointtriangleaov",
                            named_attributes.KIND_COLOR: "hitpointcolor",
                        }[kind],
                        "dataindex": named_index,
                    }
                data_index = -2  # marker: handled

        if data_index is None:
            return _warn_unsupported(
                node, f'attribute "{attribute_name}" could not be resolved to an '
                "exported vertex color, UV layer, or named attribute; "
                "returning mid grey",
                FALLBACK_COLOR if output_socket.name != "Fac" else FALLBACK_FLOAT,
                obj_name)

        if data_index != -2:
            if output_socket.name == "Fac":
                definitions = {
                    "type": "hitpointgrey",
                    "dataindex": data_index,
                    "channel": -1,
                }
            elif output_socket.name == "Alpha":
                definitions = {
                    "type": "hitpointalpha",
                    "dataindex": data_index,
                }
            else:
                # "Color" and "Vector"
                definitions = {
                    "type": "hitpointcolor",
                    "dataindex": data_index,
                }
    elif node.bl_idname == "ShaderNodeTexVoronoi":
        prefix = "scene.textures."

        def voronoi_input(label, fallback):
            socket = node.inputs.get(label)
            return _socket(socket, props, material, obj_name, group_node_stack) if socket is not None and socket.enabled else fallback

        definitions = {
            "type": "cyclesnoise", "noisetype": "voronoi",
            "dimensions": int(node.voronoi_dimensions[0]),
            "vector": _texture_coordinates(node, props, material, obj_name, group_node_stack, superluxcore_name + "_vector"),
            "w": voronoi_input("W", 0.), "scale": voronoi_input("Scale", 5.),
            "detail": voronoi_input("Detail", 0.), "roughness": voronoi_input("Roughness", .5),
            "lacunarity": voronoi_input("Lacunarity", 2.),
            "offset": voronoi_input("Smoothness", 1.), "gain": voronoi_input("Exponent", .5),
            "distortion": voronoi_input("Randomness", 1.),
            "feature": node.feature.lower(), "metric": node.distance.lower(),
            "normalize": bool(node.normalize), "output": output_socket.name.lower(),
            "color": output_socket.name == "Color" and _output_is_color(output_socket),
        }
    elif node.bl_idname == "ShaderNodeTexNoise":
        prefix = "scene.textures."

        # Exact: cyclesnoise is a port of the Cycles Noise kernel (hash,
        # Perlin, fractal types, normalize, distortion and Color seeds).
        dims = {"1D": 1, "2D": 2, "3D": 3, "4D": 4}.get(node.noise_dimensions, 3)

        vector_socket = node.inputs.get("Vector")
        if vector_socket is not None and vector_socket.is_linked:
            vec_tex = _socket(vector_socket, props, material, obj_name,
                              group_node_stack)
        else:
            # Cycles' default texture coordinate is Generated
            vec_tex = node.name + "::noisegenerated"
            props.Set(utils.luxutils.create_props(
                f"{prefix}{vec_tex}.", {"type": "hitpoint",
                                        "channel": "generated"}))

        def _fin(name, default):
            sk = node.inputs.get(name)
            if sk is None or not sk.enabled:
                return default
            return _socket(sk, props, material, obj_name, group_node_stack)

        color_output = output_socket.name == "Color"
        # The Color output is authored RGB unless it only drives vector
        # inputs (e.g. a distortion offset), where it must stay raw under
        # spectral rendering
        links = list(getattr(output_socket, "links", []) or [])
        is_color = not (links and all(l.to_socket.type == "VECTOR"
                                      for l in links))

        definitions = {
            "type": "cyclesnoise",
            "vector": vec_tex,
            "w": _fin("W", 0.0),
            "scale": _fin("Scale", 5.0),
            "detail": _fin("Detail", 2.0),
            "roughness": _fin("Roughness", 0.5),
            "lacunarity": _fin("Lacunarity", 2.0),
            "offset": _fin("Offset", 0.0),
            "gain": _fin("Gain", 1.0),
            "distortion": _fin("Distortion", 0.0),
            "noisetype": {
                "FBM": "fbm",
                "MULTIFRACTAL": "multifractal",
                "HYBRID_MULTIFRACTAL": "hybrid_multifractal",
                "RIDGED_MULTIFRACTAL": "ridged_multifractal",
                "HETERO_TERRAIN": "hetero_terrain",
            }.get(getattr(node, "noise_type", "FBM"), "fbm"),
            "dimensions": dims,
            "normalize": bool(getattr(node, "normalize", True)),
            "output": "color" if color_output else "fac",
            "color": is_color,
        }
    elif node.bl_idname == "ShaderNodeTexWhiteNoise":
        prefix = "scene.textures."
        vector_socket = node.inputs.get("Vector")
        w_socket = node.inputs.get("W")
        definitions = {
            "type": "cyclesnoise", "noisetype": "white",
            "dimensions": int(node.noise_dimensions[0]),
            # White Noise의 비연결 Vector는 Generated가 아닌 저장된 소켓 값이다.
            "vector": _socket(vector_socket, props, material, obj_name, group_node_stack) if vector_socket else [0., 0., 0.],
            "w": _socket(w_socket, props, material, obj_name, group_node_stack) if w_socket else 0.,
            "output": "color" if output_socket.name == "Color" else "fac",
            "color": _output_is_color(output_socket),
        }
    elif node.bl_idname == "ShaderNodeTexGabor":
        prefix = "scene.textures."

        # SuperLuxCore gabornoise implements Lagae 2009 sparse Gabor
        # convolution (2D), normalized after Tavernier 2019, with phasor
        # phase/intensity outputs (Tricard 2019).
        if node.gabor_type != "2D":
            SuperLuxCoreErrorLog.add_warning(
                f'Gabor node "{node.name}": 3D mode is approximated by 2D '
                "evaluation of xy", obj_name=obj_name)

        def _fin(name, default):
            sk = node.inputs[name]
            if sk.is_linked:
                SuperLuxCoreErrorLog.add_warning(
                    f'Gabor node "{node.name}": linked {name} input is not '
                    "supported, using its default", obj_name=obj_name)
            return sk.default_value if not sk.is_linked else default

        vector_socket = node.inputs["Vector"]
        if vector_socket.is_linked:
            vec_tex = _socket(vector_socket, props, material, obj_name,
                              group_node_stack)
        else:
            vec_tex = node.name + "::gaborpos"
            props.Set(utils.luxutils.create_props(
                f"{prefix}{vec_tex}.", {"type": "position"}))

        out_map = {"Value": "value", "Phase": "phase",
                   "Intensity": "intensity"}
        definitions = {
            "type": "gabornoise",
            "vector": vec_tex,
            "scale": _fin("Scale", 1.0),
            "frequency": _fin("Frequency", 2.0),
            "isotropy": _fin("Anisotropy", 0.0),
            # Orientation 2D/3D share the display name "Orientation";
            # address the 2D one by identifier
            "orientation": next((sk.default_value for sk in node.inputs
                                 if sk.identifier == "Orientation 2D"), 0.0),
            "output": out_map.get(output_socket.name, "value"),
        }
    elif node.bl_idname == "ShaderNodeTexBrick":
        prefix = "scene.textures."

        def _finput(name, default):
            s = node.inputs.get(name)
            if s is None:
                return default
            if s.is_linked:
                SuperLuxCoreErrorLog.add_warning(
                    f'Brick node "{node.name}": textured "{name}" is not '
                    "supported, using its default", obj_name=obj_name)
                return default
            return s.default_value

        if node.inputs.get("Mortar Smooth") is not None and \
                _finput("Mortar Smooth", 0.0) != 0.0:
            SuperLuxCoreErrorLog.add_warning(
                f'Brick node "{node.name}": mortar smoothing is not supported',
                obj_name=obj_name)
        if getattr(node, "squash", 0.0) != 0.0:
            SuperLuxCoreErrorLog.add_warning(
                f'Brick node "{node.name}": squash is not supported',
                obj_name=obj_name)

        # Color2 is approximated as the per-brick modulation texture
        # (SuperLuxCore modulates each brick by brickmodtex; Cycles alternates
        # deterministically) — the pattern is preserved, the alternation
        # is randomized instead.
        color2_socket = node.inputs.get("Color2")
        if color2_socket is not None:
            SuperLuxCoreErrorLog.add_warning(
                f'Brick node "{node.name}": Color2 is approximated as random '
                "per-brick modulation", obj_name=obj_name)

        offset = getattr(node, "offset", 0.5)
        definitions = {
            "type": "brick",
            "bricktex": _socket(node.inputs["Color1"], props, material,
                                obj_name, group_node_stack),
            "brickmodtex": _socket(color2_socket, props, material, obj_name,
                                   group_node_stack) if color2_socket else 1.0,
            "mortartex": _socket(node.inputs["Mortar"], props, material,
                                 obj_name, group_node_stack),
            "mortarsize": _finput("Mortar Size", 0.01),
            "brickmodbias": _finput("Bias", 0.0),
            "brickwidth": _finput("Brick Width", 0.5),
            "brickheight": _finput("Row Height", 0.25),
            "brickdepth": _finput("Brick Width", 0.5),
            "brickbond": "running",
            "brickrun": max(0.0, min(1.0, 1.0 - offset)),
        }
        definitions.update(_vector_mapping_defs(
            node.inputs["Vector"], False, False, props, material, obj_name,
            group_node_stack))

        if output_socket.name == "Fac":
            SuperLuxCoreErrorLog.add_warning(
                f'Brick node "{node.name}": the Fac output is approximated by '
                "the brick color texture", obj_name=obj_name)
    elif node.bl_idname == "ShaderNodeTexWave":
        prefix = "scene.textures."

        # Exact: the engine's cyclesnoise "wave" mode ports Cycles svm_wave
        # (bands/rings, directions, sin/saw/tri, phase, fBM distortion).
        # The former blender_wood approximation had a different frequency
        # and distortion (065 desert ripples 2x too dark under a low sun).
        vector_socket = node.inputs["Vector"]
        if vector_socket.is_linked:
            vec_tex = _socket(vector_socket, props, material, obj_name,
                              group_node_stack)
        else:
            # Cycles' default texture coordinate is Generated
            vec_tex = node.name + "::wavegenerated"
            props.Set(utils.luxutils.create_props(
                f"{prefix}{vec_tex}.", {"type": "hitpoint",
                                        "channel": "generated"}))

        def _fin(name, default):
            sk = node.inputs.get(name)
            if sk is None or not sk.enabled:
                return default
            return _socket(sk, props, material, obj_name, group_node_stack)

        rings = node.wave_type == "RINGS"
        direction = node.rings_direction if rings else node.bands_direction
        dir_bits = {"X": 0, "Y": 1, "Z": 2, "DIAGONAL": 3, "SPHERICAL": 3}.get(direction, 0)
        profile_bits = {"SIN": 0, "SAW": 1, "TRI": 2}.get(node.wave_profile, 0)
        wave_mode = (1 if rings else 0) | (dir_bits << 1) | (profile_bits << 3)

        definitions = {
            "type": "cyclesnoise",
            "noisetype": "wave",
            "wavemode": wave_mode,
            "vector": vec_tex,
            "scale": _fin("Scale", 5.0),
            "distortion": _fin("Distortion", 0.0),
            "detail": _fin("Detail", 2.0),
            "gain": _fin("Detail Scale", 1.0),
            "roughness": _fin("Detail Roughness", 0.5),
            "offset": _fin("Phase Offset", 0.0),
            "dimensions": 3,
            # Color and Fac are the same scalar
            "output": "fac",
        }
    elif node.bl_idname == "ShaderNodeTexGradient":
        prefix = "scene.textures."

        # blender_blend covers the classic gradient progressions
        progression_map = {
            "LINEAR": "linear",
            "QUADRATIC": "quadratic",
            "EASING": "easing",
            "DIAGONAL": "diagonal",
            "SPHERICAL": "spherical",
            "QUADRATIC_SPHERE": "halo",
            "RADIAL": "radial",
        }
        if node.gradient_type not in progression_map:
            _warn_unsupported(
                node, f'gradient type "{node.gradient_type}" is approximated by '
                '"linear"', None, obj_name)

        definitions = {
            "type": "blender_blend",
            "progressiontype": progression_map.get(node.gradient_type, "linear"),
            "direction": "horizontal",
        }
        # blender_blend is Blender's legacy blend texture: its linear,
        # quadratic, easing and diagonal ramps expect coordinates in -1..1
        # ((1 + x) / 2). Cycles' Gradient uses the raw coordinate, so map
        # p -> 2p - 1 after the user transform. Spherical/radial/halo use
        # the same formula in both and need no remap.
        legacy_remap = None
        if node.gradient_type in {"LINEAR", "QUADRATIC", "EASING", "DIAGONAL"}:
            legacy_remap = (Matrix.Translation(Vector((-1.0, -1.0, -1.0))) @
                            Matrix.Diagonal(Vector((2.0, 2.0, 2.0))).to_4x4())
        definitions.update(_vector_mapping_defs(
            node.inputs["Vector"], False, False, props, material, obj_name,
            group_node_stack, post_matrix=legacy_remap))
    elif node.bl_idname == "ShaderNodeTexMagic":
        return _magic_texture(node, output_socket, props, material, obj_name, group_node_stack, superluxcore_name)
    elif node.bl_idname in {"ShaderNodeRGBCurve", "ShaderNodeFloatCurve", "ShaderNodeVectorCurve"}:
        mapping = node.mapping
        mapping.update()
        rgb = node.bl_idname == "ShaderNodeRGBCurve"
        scalar = node.bl_idname == "ShaderNodeFloatCurve"
        source = _socket(node.inputs["Color" if rgb else "Value" if scalar else "Vector"], props, material, obj_name, group_node_stack)
        factor_socket = node.inputs.get("Factor") or node.inputs.get("Fac")
        factor = _socket(factor_socket, props, material, obj_name, group_node_stack)
        curves = list(mapping.curves)
        low = min(point.location[0] for curve in curves for point in curve.points)
        high = max(point.location[0] for curve in curves for point in curve.points)
        high = max(high, low + 1e-6)
        channels = []
        for channel in range(1 if scalar else 3):
            tag = superluxcore_name + f"_curve{channel}"
            value = source if scalar else _split_chan(source, channel, tag + "_input", props)
            def evaluate(position):
                if rgb:
                    position = _evaluate_curve(curves[3], mapping, position)
                return _evaluate_curve(curves[channel], mapping, position)
            samples = [evaluate(low + (high - low) * i / 256) for i in range(257)]
            amount = _tex_binary("divide", _tex_binary("subtract", value, low, tag + "_offset", props), high - low, tag + "_amount", props)
            curve_value = _tex_band(amount, [(i / 256, [sample] * 3) for i, sample in enumerate(samples)], "linear", tag, props)
            curve_value = _split_chan(curve_value, 0, tag + "_scalar", props)
            if mapping.extend == "EXTRAPOLATED":
                step = (high - low) / 256
                left_slope = (samples[1] - samples[0]) / step
                right_slope = (samples[-1] - samples[-2]) / step
                left = _tex_binary("scale", _tex_mathfunc("min", _tex_binary("subtract", value, low, tag + "_leftoffset", props), 0., tag + "_left", props), left_slope, tag + "_leftline", props)
                right = _tex_binary("scale", _tex_mathfunc("max", _tex_binary("subtract", value, high, tag + "_rightoffset", props), 0., tag + "_right", props), right_slope, tag + "_rightline", props)
                curve_value = _tex_binary("add", _tex_binary("add", curve_value, left, tag + "_extrapleft", props), right, tag + "_extrapright", props)
            channels.append(_tex_lerp(value, curve_value, factor, tag + "_result", props))
        if scalar:
            return channels[0]
        return _tex_helper(props, superluxcore_name, {"type": "makefloat3", "color": rgb and _output_is_color(output_socket), **{f"texture{i+1}": v for i, v in enumerate(channels)}})
    elif node.bl_idname == "ShaderNodeTexEnvironment":
        if node.image:
            prefix = "scene.textures."
            try:
                filepath = ImageExporter.export_cycles_node_reader(node.image)
            except OSError as error:
                SuperLuxCoreErrorLog.add_warning(error, obj_name=obj_name)
                return MISSING_IMAGE_COLOR

            # Equirectangular / mirror-ball projection via the engine's
            # direction-based mapping: the hit's incoming direction is
            # turned into env UVs, not the surface UV. The texture's
            # Vector input (if linked) still routes through _vector_mapping_defs
            # for local transforms; the fallback for the default socket
            # is the direction mapping.
            proj = getattr(node, "projection", "EQUIRECTANGULAR")
            if proj == "EQUIRECTANGULAR":
                pass  # dirmapping2d covers the standard case
            elif proj == "MIRROR_BALL":
                SuperLuxCoreErrorLog.add_warning(
                    f'Environment Texture node "{node.name}": MIRROR_BALL '
                    "projection approximated by equirectangular",
                    obj_name=obj_name)

            definitions = {
                "type": "imagemap",
                "file": filepath,
                "wrap": "repeat",
                "channel": "rgb",
                **ImageExporter.cycles_colorspace(node.image),
                "gain": 1,
                "filter": _imagemap_filter(node, obj_name),
            }
            vector_input = node.inputs.get("Vector")
            if vector_input is not None and not vector_input.is_linked:
                # Unlinked Vector: the hit's incoming direction is the
                # equirect coordinate (Cycles samples by view direction).
                definitions["mapping.type"] = "dirmapping2d"
            elif vector_input is not None and vector_input.is_linked:
                SuperLuxCoreErrorLog.add_warning(
                    f'Environment Texture node "{node.name}": a linked '
                    "Vector input can't feed the direction projection - "
                    "falls back to surface UV", obj_name=obj_name)
                definitions.update(_vector_mapping_defs(
                    vector_input, True, False, props, material, obj_name,
                    group_node_stack))
        else:
            return MISSING_IMAGE_COLOR
    elif node.bl_idname == "ShaderNodeWavelength":
        prefix = "scene.textures."

        # Approximation: the wavelength (nm) is remapped from [380, 780] to
        # [0, 1] and looked up in a coarse piecewise sRGB spectrum table
        # (Bruton-style), ignoring the intensity rolloff at the range ends
        wl_socket = node.inputs.get("Wavelength")
        wl = _socket(wl_socket, props, material, obj_name, group_node_stack) \
            if wl_socket is not None else 550.0

        amount = _tex_helper(props, superluxcore_name + "_wl_remap", {
            "type": "remap",
            "value": wl,
            "sourcemin": 380.0,
            "sourcemax": 780.0,
            "targetmin": 0.0,
            "targetmax": 1.0,
        })

        # (wavelength, linear sRGB) samples, piecewise approximation
        spectrum = [
            (380.0, [0.0, 0.0, 1.0]),
            (400.0, [0.67, 0.0, 1.0]),
            (440.0, [0.0, 0.0, 1.0]),
            (460.0, [0.0, 0.4, 1.0]),
            (490.0, [0.0, 1.0, 1.0]),
            (510.0, [0.0, 1.0, 0.0]),
            (540.0, [0.43, 1.0, 0.0]),
            (580.0, [1.0, 1.0, 0.0]),
            (610.0, [1.0, 0.54, 0.0]),
            (645.0, [1.0, 0.0, 0.0]),
            (780.0, [1.0, 0.0, 0.0]),
        ]
        definitions = {
            "type": "band",
            "amount": amount,
            "offsets": len(spectrum),
            "interpolation": "linear",
        }
        for i, (wl_value, rgb) in enumerate(spectrum):
            definitions[f"offset{i}"] = (wl_value - 380.0) / 400.0
            definitions[f"value{i}"] = rgb
    elif node.bl_idname == "ShaderNodeClamp":
        # Legacy clamp node (removed in Blender 4.0 where it is upgraded to
        # Map Range); maps exactly onto the SuperLuxCore clamp texture
        prefix = "scene.textures."
        definitions = {
            "type": "clamp",
            "texture": _socket(node.inputs["Value"], props, material, obj_name,
                               group_node_stack),
            "min": _socket(node.inputs["Min"], props, material, obj_name,
                           group_node_stack),
            "max": _socket(node.inputs["Max"], props, material, obj_name,
                           group_node_stack),
        }
    elif node.bl_idname == "ShaderNodeVectorRotate":
        vector = _socket(node.inputs["Vector"], props, material, obj_name,
                         group_node_stack)
        center = _socket(node.inputs["Center"], props, material, obj_name,
                         group_node_stack)
        rtype = getattr(node, "rotation_type", "AXIS_ANGLE")

        # SuperLuxCore has no vector-rotate texture, but a rotation about a
        # constant axis/euler is just a constant 3x3 matrix, which composes
        # out of splitfloat3/scale/add/makefloat3 (see _const_mat_mul_vec).
        rot_mat = None
        if rtype == "AXIS_ANGLE":
            axis = _socket(node.inputs["Axis"], props, material, obj_name,
                           group_node_stack)
            angle = _socket(node.inputs["Angle"], props, material, obj_name,
                            group_node_stack)
            if not _is_textured(axis) and not _is_textured(angle):
                try:
                    rot_mat = Matrix.Rotation(
                        angle, 3, Vector(list(axis)[:3]).normalized())
                except (ValueError, TypeError):
                    rot_mat = Matrix.Identity(3)
        elif rtype in {"X_AXIS", "Y_AXIS", "Z_AXIS"}:
            angle = _socket(node.inputs["Angle"], props, material, obj_name,
                            group_node_stack)
            if not _is_textured(angle):
                rot_mat = Matrix.Rotation(angle, 3, rtype[0])
        else:  # EULER
            rot = _socket(node.inputs["Rotation"], props, material, obj_name,
                          group_node_stack)
            if not _is_textured(rot):
                rot_mat = Euler(list(rot)[:3]).to_matrix()

        if rot_mat is None:
            return _warn_unsupported(
                node, "texture-driven axis/angle/rotation inputs are not "
                "supported; passing through the vector", vector, obj_name)

        if getattr(node, "invert", False):
            rot_mat = rot_mat.transposed()

        # v' = R (v - center) + center
        shifted = vector if _is_zero(center) else _tex_binary(
            "subtract", vector, center, superluxcore_name + "_sh", props)
        rotated = _const_mat_mul_vec([list(r) for r in rot_mat], shifted,
                                     superluxcore_name + "_rot", props)
        if _is_zero(center):
            return rotated
        return _tex_binary("add", rotated, center,
                           superluxcore_name + "_rotc", props)
    elif node.bl_idname == "ShaderNodeVectorTransform":
        vector = _socket(node.inputs["Vector"], props, material, obj_name,
                         group_node_stack)
        cfrom, cto = node.convert_from, node.convert_to
        if cfrom == cto:
            return vector

        # The from->to matrix is constant per material instance, so the
        # transform composes out of the same linear-map helpers as
        # VectorRotate. Note: for dupli/instanced objects the base object's
        # matrix is used (per-instance object spaces are not expressible).
        mat = _vtransform_matrix(cfrom, cto, obj_name)
        if mat is None:
            return _warn_unsupported(
                node, f"cannot resolve the {cfrom.lower()} -> {cto.lower()} "
                "transform (missing object/camera); passing through the "
                "vector", vector, obj_name)

        vtype = getattr(node, "vector_type", "VECTOR")
        if vtype == "NORMAL":
            # Normals transform by the inverse-transpose
            lin = mat.inverted_safe().transposed().to_3x3()
            trans = None
        else:
            lin = mat.to_3x3()
            trans = [mat[0][3], mat[1][3], mat[2][3]] if vtype == "POINT" else None

        transformed = _const_mat_mul_vec([list(r) for r in lin], vector,
                                         superluxcore_name + "_xf", props)
        if trans is not None and any(t != 0 for t in trans):
            return _tex_binary("add", transformed, trans,
                               superluxcore_name + "_xft", props)
        return transformed
    elif node.bl_idname == "ShaderNodeBsdfHair":
        # Legacy Cycles hair BSDF (pre-Principled). Map onto the Marschner
        # "hairmat" like ShaderNodeBsdfHairPrincipled; the Reflection/
        # Transmission lobe split cannot be expressed.
        prefix = "scene.materials."
        component = getattr(node, "component", "Reflection")
        _warn_unsupported(
            node, f"legacy Hair BSDF approximated by hairmat (the "
            f"'{component}' lobe weighting is not separable)", None, obj_name)

        offset_sock = node.inputs.get("Offset")
        offset = _socket(offset_sock, props, material, obj_name,
                         group_node_stack) if offset_sock is not None else 0.0
        if offset_sock is not None and offset_sock.is_linked \
                and offset is not ERROR_VALUE:
            alpha = superluxcore_name + "offset_to_deg"
            props.Set(utils.luxutils.create_props(
                "scene.textures." + alpha + ".", {
                    "type": "scale",
                    "texture1": offset,
                    "texture2": 57.29577951308232,
                }))
        else:
            alpha = offset * 57.29577951308232

        def _hair_sock(name, fallback):
            s = node.inputs.get(name)
            return _socket(s, props, material, obj_name, group_node_stack) \
                if s is not None else fallback

        definitions = {
            "type": "hairmat",
            "eta": 1.55,
            "beta_m": _hair_sock("RoughnessU", 0.1),
            "beta_n": _hair_sock("RoughnessV", 0.1),
            "alpha": alpha,
            "color": _hair_sock("Color", [0.5, 0.5, 0.5]),
        }
    elif node.bl_idname == "ShaderNodeBsdfRayPortal":
        # No portal BSDF in SuperLuxCore; transparent is the closest match (rays
        # continue through the surface unaltered)
        prefix = "scene.materials."
        _warn_unsupported(
            node, "Ray Portal BSDF has no SuperLuxCore equivalent; approximated "
            "by transparent", None, obj_name)
        definitions = {
            "type": "transparent",
            "kt": _socket(node.inputs.get("Color"), props, material, obj_name,
                          group_node_stack)
                  if node.inputs.get("Color") is not None else 1.0,
        }
    elif node.bl_idname == "ShaderNodeEeveeSpecular":
        # Legacy Eevee-only specular BSDF; approximate with glossy2.
        # Cycles' Specular input scales F0 by 0.08.
        prefix = "scene.materials."
        _warn_unsupported(
            node, "Eevee Specular BSDF approximated by glossy2", None,
            obj_name)

        def _eevee_sock(name, fallback):
            s = node.inputs.get(name)
            return _socket(s, props, material, obj_name, group_node_stack) \
                if s is not None else fallback

        spec = _eevee_sock("Specular", 0.0)
        ks = _tex_binary("scale", spec, 0.08, superluxcore_name + "_f0", props) \
            if spec != 0 else [0.0, 0.0, 0.0]
        roughness = _eevee_sock("Roughness", 0.0)
        definitions = {
            "type": "glossy2" if roughness != 0 else "glass",
            "kd": _eevee_sock("Base Color", [0.8, 0.8, 0.8]),
            "ks": ks,
            "interiorior": 1.46,
        }
        if roughness != 0:
            definitions["uroughness"] = roughness
            definitions["vroughness"] = roughness
            # Eevee specular is GGX-based; match the distribution
            definitions["distribution"] = "ggx"
    elif node.bl_idname == "ShaderNodePointInfo":
        prefix = "scene.textures."
        if output_socket.name == "Position":
            _warn_unsupported(
                node, "'Position' is approximated by the hit position on the "
                "instanced sphere (the point's surface, not its center)",
                None, obj_name)
            definitions = {"type": "position"}
        elif output_socket.name == "Random":
            # Points are exported as per-point instances, so the per-object
            # normalized id doubles as a stable per-point random
            definitions = {"type": "objectidnormalized"}
        else:  # Radius
            return _warn_unsupported(
                node, "'Radius' has no per-instance texture channel in "
                "SuperLuxCore; using 1.0", 1.0, obj_name)
    elif node.bl_idname == "ShaderNodeSqueeze":
        # Sigmoid: out = 1 / (1 + exp(-(v - c) * w))
        v = _socket(node.inputs["Value"], props, material, obj_name,
                    group_node_stack)
        w = _socket(node.inputs["Width"], props, material, obj_name,
                    group_node_stack)
        c = _socket(node.inputs["Center"], props, material, obj_name,
                    group_node_stack)
        if not any(_is_textured(t) for t in (v, w, c)):
            def _s(x):
                return x[0] if isinstance(x, (list, tuple)) else x
            try:
                return 1.0 / (1.0 + math.exp(-(_s(v) - _s(c)) * _s(w)))
            except OverflowError:
                return 0.0
        d = _tex_binary("subtract", v, c, superluxcore_name + "_d", props)
        x = _tex_binary("scale", d, w, superluxcore_name + "_x", props)
        nx = _tex_binary("scale", x, -1.0, superluxcore_name + "_nx", props)
        e = _tex_mathfunc("exp", nx, None, superluxcore_name + "_e", props)
        den = _tex_binary("add", 1.0, e, superluxcore_name + "_den", props)
        return _tex_binary("divide", 1.0, den, superluxcore_name, props)
    else:
        note = _UNSUPPORTED_NODE_NOTES.get(node.bl_idname)
        SuperLuxCoreErrorLog.add_warning(
            f"Unsupported node type: {node.name}"
            + (f" ({node.bl_idname}): {note}" if note else ""),
            obj_name=obj_name)

        # TODO do this for unsupported mixRGB and math modes, too
        # Try to skip this node by looking at its internal links (the same that are used when the node is muted)
        if node.internal_links:
            links = node.internal_links[0].from_socket.links
            if links:
                link = links[0]
                print("current node", node.name, "failed, testing next node:", link.from_node.name)
                return _node(link.from_node, link.from_socket, props, material, superluxcore_name, obj_name, group_node_stack)

        # Return a neutral fallback matching the output type instead of a
        # black/error result so unsupported nodes don't silently break renders
        socket_type = getattr(output_socket, "bl_idname", "")
        if socket_type == "NodeSocketShader":
            # Emit a plain grey material under the requested name
            prefix = "scene.materials."
            definitions = {
                "type": "matte",
                "kd": FALLBACK_COLOR,
            }
        elif socket_type == "NodeSocketColor":
            return list(FALLBACK_COLOR)
        elif socket_type.startswith("NodeSocketVector"):
            return list(FALLBACK_VECTOR)
        else:
            # Float/Int/Bool and everything else
            return FALLBACK_FLOAT

    # Both native definitions and helper-generated Math results must reach
    # the same post-operation Clamp stage. Do not emit an identity texture
    # merely to name a helper result or a folded constant.
    if node.bl_idname == "ShaderNodeMath" and math_output is not None:
        result_texture = math_output
    else:
        props.Set(utils.luxutils.create_props(prefix + superluxcore_name + ".", definitions))
        result_texture = superluxcore_name

    if node.bl_idname in {"ShaderNodeMixRGB", "ShaderNodeMath"} and node.use_clamp:
        return _tex_helper(props, superluxcore_name + "clamp", {
            "type": "clamp",
            "texture": result_texture,
            "min": 0,
            "max": 1,
        })

    return result_texture


# Tangent-space color of the unperturbed normal (0, 0, 1)
_FLAT_NORMAL_COLOR = [0.5, 0.5, 1.0]


def _normal_input(socket, props, material, obj_name, group_node_stack):
    """Interpret linked shader normals as direction vectors, preserving Bump nodes."""
    link = utils_node.get_link(socket)
    value = _socket(socket, props, material, obj_name, group_node_stack)
    if link is None:
        return value
    if _is_textured(value):
        prefix = "scene.textures." + value
        kind = props.Get(prefix + ".type").GetString() if props.IsDefined(prefix + ".type") else ""
        if kind in {"normalvector", "normalmap", "cyclesnormalmap", "cyclesbump"}:
            return value
        if kind == "mix" and props.IsDefined(prefix + ".bumpnormal") and props.Get(prefix + ".bumpnormal").GetBool():
            return value
    return _tex_helper(props, "normal_input_" + str(socket.as_pointer()),
                       {"type": "normalvector", "texture": value})


def _squared_roughness_to_linear(socket, props, material, superluxcore_name, obj_name, group_node):
    roughness = _socket(socket, props, material, obj_name, group_node)
    if socket.is_linked and roughness is not ERROR_VALUE:
        # Implicitly create a math texture with unique name
        tex_name = superluxcore_name + "roughness_converter"
        helper_prefix = "scene.textures." + tex_name + "."
        helper_defs = {
            "type": "power",
            "base": roughness,
            "exponent": 2,
        }
        props.Set(utils.luxutils.create_props(helper_prefix, helper_defs))
        return tex_name
    else:
        return roughness ** 2


def _is_textured(value):
    return isinstance(value, str)


def _is_zero(value):
    if _is_textured(value):
        return False
    if isinstance(value, (list, tuple)):
        return all(v == 0 for v in value)
    return value == 0


def _volume_asymmetry(anisotropy):
    """SuperLuxCore expects a 3-channel asymmetry; broadcast a scalar anisotropy."""
    if anisotropy is ERROR_VALUE:
        return [0, 0, 0]
    if _is_textured(anisotropy) or isinstance(anisotropy, (list, tuple)):
        return anisotropy
    return [anisotropy] * 3


def _volume_transmit_to_absorb(color, name, props):
    """Cycles volume colors are what SURVIVES: sigma_a = (1 - saturate(color)).

    Using the color itself as the absorption coefficient renders the
    complement (red wine -> green). Constants fold; textures get a
    clamp + subtract helper pair.
    """
    if not _is_textured(color):
        vec = list(color)[:3] if isinstance(color, (list, tuple)) else [color] * 3
        return [1.0 - min(max(c, 0.0), 1.0) for c in vec]
    clamped = _tex_helper(props, name + "_sat", {
        "type": "clamp", "texture": color, "min": 0.0, "max": 1.0})
    return _tex_binary("subtract", [1.0, 1.0, 1.0], clamped, name + "_inv", props)


def _volume(node, output_socket, props, material, name_base, obj_name,
            group_node_stack=None):
    """
    Convert a Cycles volume shader subtree into scene.volumes.* definitions.
    Returns a dict for create_props("scene.volumes.<name>.", defs), or None
    (after logging a warning) when the node cannot be converted.
    Coefficients are floats, [r, g, b] lists or texture names.
    """
    def coeff(socket_name, fallback):
        socket = node.inputs.get(socket_name)
        if socket is None:
            return fallback
        value = _socket(socket, props, material, obj_name, group_node_stack)
        return fallback if value is ERROR_VALUE else value

    if node.bl_idname == "ShaderNodeVolumeAbsorption":
        # Pure absorption maps exactly onto a SuperLuxCore "clear" volume;
        # Cycles: sigma_a = density * (1 - Color)
        density = coeff("Density", 1.0)
        color = coeff("Color", FALLBACK_COLOR)
        absorb = _volume_transmit_to_absorb(color, name_base + "_abscolor", props)
        return {
            "type": "clear",
            "absorption": _tex_binary("scale", absorb, density,
                                      name_base + "_absorption", props),
        }

    if node.bl_idname == "ShaderNodeVolumeScatter":
        density = coeff("Density", 1.0)
        color = coeff("Color", [1.0, 1.0, 1.0])
        return {
            "type": "homogeneous",
            "absorption": 0,
            # Approximation: Cycles' color times density acts as sigma_s
            "scattering": _tex_binary("scale", color, density,
                                      name_base + "_scattering", props),
            "asymmetry": _volume_asymmetry(coeff("Anisotropy", 0.0)),
        }

    if node.bl_idname == "ShaderNodeEmission":
        # Emission in the Volume socket is volume emission; a clear volume
        # carries it (SuperLuxCore volumes have a dedicated emission channel)
        return {
            "type": "clear",
            "absorption": 0,
            "emission": _tex_binary("scale", coeff("Color", [1.0, 1.0, 1.0]),
                                    coeff("Strength", 1.0),
                                    name_base + "_emission", props),
        }

    if node.bl_idname == "ShaderNodeVolumePrincipled":
        density = coeff("Density", 1.0)
        color = coeff("Color", [1.0, 1.0, 1.0])
        # Cycles svm_node_principled_volume:
        # sigma_a = density * (1 - Color) * (1 - Absorption Color)
        absorb = _tex_binary(
            "scale",
            _volume_transmit_to_absorb(color, name_base + "_pvcolor", props),
            _volume_transmit_to_absorb(coeff("Absorption Color", [0, 0, 0]),
                                       name_base + "_pvabs", props),
            name_base + "_pvabsprod", props)
        definitions = {
            "type": "homogeneous",
            "absorption": _tex_binary("scale", absorb, density,
                                      name_base + "_absorption", props),
            "scattering": _tex_binary("scale", color, density,
                                      name_base + "_scattering", props),
            "asymmetry": _volume_asymmetry(coeff("Anisotropy", 0.0)),
        }
        emission = _tex_binary("scale", coeff("Emission Color", [0, 0, 0]),
                               coeff("Emission Strength", 0.0),
                               name_base + "_emission", props)
        blackbody = coeff("Blackbody Intensity", 0.)
        if not _is_zero(blackbody):
            temperature = _tex_mathfunc("max", coeff("Temperature", 1000.), 0., name_base + "_temperature", props)
            color_temperature = _tex_mathfunc("max", temperature, 800., name_base + "_color_temperature", props)
            spectrum = _tex_helper(props, name_base + "_blackbody", {"type": "blackbody", "temperature": color_temperature, "normalize": True})
            # 원 엔진의 흑체는 고정 절대 정규화를 쓰므로 휘도 1의 색 계약으로 변환한다.
            luminance = 0.
            for channel, weight in enumerate((.2126, .7152, .0722)):
                value = _split_chan(spectrum, channel, name_base + f"_blackbody_rgb{channel}", props)
                luminance = _tex_binary("add", luminance, _tex_binary("scale", value, weight, name_base + f"_blackbody_y{channel}", props), name_base + f"_blackbody_sum{channel}", props)
            luminance = _tex_mathfunc("max", luminance, 1e-20, name_base + "_blackbody_luminance", props)
            spectrum = _tex_binary("divide", spectrum, luminance, name_base + "_blackbody_unit_luminance", props)
            fourth = _tex_binary("power", temperature, 4., name_base + "_temperature4", props)
            intensity = _tex_binary("scale", 5.670373e-14 / math.pi, _tex_lerp(1., fourth, blackbody, name_base + "_thermal", props), name_base + "_intensity", props)
            intensity = _tex_mathfunc("max", intensity, 0., name_base + "_positive_intensity", props)
            intensity = _tex_binary("scale", intensity, _tex_greaterthan(blackbody, 0., name_base + "_has_blackbody", props), name_base + "_enabled_intensity", props)
            tint = coeff("Blackbody Tint", [1., 1., 1.])
            thermal = _tex_binary("scale", _tex_binary("scale", spectrum, tint, name_base + "_tinted", props), intensity, name_base + "_blackbody_emission", props)
            emission = _tex_binary("add", emission, thermal, name_base + "_total_emission", props)
        if not _is_zero(emission):
            definitions["emission"] = emission
        return definitions

    if node.bl_idname == "ShaderNodeVolumeCoefficients":
        # Coefficients are already physical sigma_a / sigma_s — a cleaner
        # mapping than the Principled color*density approximation
        definitions = {
            "type": "homogeneous",
            "absorption": coeff("Absorption Coefficients", [0.0, 0.0, 0.0]),
            "scattering": coeff("Scatter Coefficients", [0.0, 0.0, 0.0]),
            "asymmetry": _volume_asymmetry(coeff("Anisotropy", 0.0)),
        }
        ior = coeff("IOR", 1.0)
        if ior != 1.0:
            definitions["ior"] = ior
        emission = coeff("Emission Coefficients", [0.0, 0.0, 0.0])
        if not _is_zero(emission):
            definitions["emission"] = emission
        weight = coeff("Weight", 1.0)
        if weight != 1.0 and not _is_zero(weight):
            for key in ("absorption", "scattering", "emission"):
                if key in definitions and not _is_zero(definitions[key]):
                    definitions[key] = _tex_binary(
                        "scale", definitions[key], weight,
                        f"{name_base}_{key}_w", props)
        for unsupported in ("Backscatter", "Alpha", "Diameter"):
            sock = node.inputs.get(unsupported)
            if sock is not None and \
                    (sock.is_linked or sock.default_value != 0.0):
                SuperLuxCoreErrorLog.add_warning(
                    f'Volume Coefficients node "{node.name}": "{unsupported}" '
                    "is not supported", obj_name=obj_name)
        return definitions

    if node.bl_idname in {"ShaderNodeAddShader", "ShaderNodeMixShader"}:
        is_add = node.bl_idname == "ShaderNodeAddShader"
        indices = (0, 1) if is_add else (1, 2)
        children = []
        for index in indices:
            link = utils_node.get_link(node.inputs[index])
            child = _volume(link.from_node, link.from_socket, props, material, name_base + f"_child{index}", obj_name, group_node_stack) if link is not None else None
            children.append(child or {"type": "clear", "absorption": 0.})
        amount = 1. if is_add else _tex_clamp(_socket(node.inputs["Fac"], props, material, obj_name, group_node_stack), 0., 1., name_base + "_factor", props)
        child1, child2 = children
        merged = {}
        for key in ("absorption", "scattering", "emission"):
            value1, value2 = child1.get(key, 0.), child2.get(key, 0.)
            if _is_zero(value1) and _is_zero(value2):
                continue
            merged[key] = _tex_binary("add", value1, value2, f"{name_base}_{key}", props) if is_add else _tex_lerp(value1, value2, amount, f"{name_base}_{key}", props)
        # 산란이 있는 합성을 clear로 지정하면 엔진이 산란을 버린다.
        merged["type"] = "clear" if _is_zero(merged.get("scattering", 0.)) else "homogeneous"
        if merged["type"] != "clear":
            scattering = []
            phase = []
            for index, child in enumerate(children):
                sigma = child.get("scattering", 0.)
                weight = 1. if is_add else _tex_binary("subtract", 1., amount, name_base + "_weight1", props) if index == 0 else amount
                weighted = _tex_binary("scale", sigma, weight, name_base + f"_sigma{index}", props)
                scattering.append(weighted)
                phase.append(_tex_binary("scale", weighted, child.get("asymmetry", [0., 0., 0.]), name_base + f"_phase{index}", props))
            merged["asymmetry"] = _tex_binary("divide", _tex_binary("add", phase[0], phase[1], name_base + "_phase", props), _tex_binary("add", scattering[0], scattering[1], name_base + "_sigma", props), name_base + "_asymmetry", props)
        return merged

    if node.bl_idname == "ShaderNodeGroup" and node.node_tree:
        active_output = None
        for subnode in node.node_tree.nodes:
            if subnode.bl_idname == "NodeGroupOutput" and subnode.is_active_output:
                active_output = subnode
                break

        group_input = _group_socket(active_output.inputs, output_socket) \
            if active_output is not None else None
        link = utils_node.get_link(group_input) if group_input is not None else None
        if link is None:
            return _warn_unsupported(
                node, "node group has no usable linked volume output", None, obj_name)

        stack = list(group_node_stack or [])
        stack.append(node)
        return _volume(link.from_node, link.from_socket, props, material,
                       name_base, obj_name, stack)

    if node.bl_idname == "NodeGroupInput" and group_node_stack:
        socket = _group_socket(group_node_stack[-1].inputs, output_socket)
        link = utils_node.get_link(socket) if socket is not None else None
        if link is None:
            return _warn_unsupported(
                node, "unlinked volume group input", None, obj_name)
        return _volume(link.from_node, link.from_socket, props, material,
                       name_base, obj_name, group_node_stack[:-1])

    return _warn_unsupported(
        node, "cannot be used as a volume shader", None, obj_name)
