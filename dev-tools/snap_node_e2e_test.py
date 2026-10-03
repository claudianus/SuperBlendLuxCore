# SPDX-License-Identifier: Apache-2.0
"""Real Blender nodes -> repository exporter -> rebuilt CPU/GPU renderer.

Run Blender --background --python-exit-code 1 --python dev-tools/snap_node_e2e_test.py.
Requires an enabled SuperLuxCore extension for its registered dependencies.
SUPERLUXCORE_TEST_PYTHON selects the external Python with the built module's
ABI; SUPERLUXCORE_TEST_GPU_DEVICES selects the GPU mask (default 010).
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import bpy
from bl_ext.user_default.superluxcore.export import cycles_node_reader as installed

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT.parent / "SuperLuxCore"
# Exercise repository code even when the installed extension is older.
spec = importlib.util.spec_from_file_location(installed.__name__, ROOT / "export/cycles_node_reader.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def build_cases():
    material = bpy.data.materials.new("SnapCompatibilityProbe")
    material.use_nodes = True
    tree = material.node_tree
    cases = []
    for index, (a, b, clamped, linked) in enumerate([
        (1.75, 1., False, False), (-1.25, 1., False, True),
        (2.75, 1., True, True), (1.75, 0., False, True)]):
        node = tree.nodes.new("ShaderNodeMath")
        node.operation = "SNAP"
        node.use_clamp = clamped
        for socket, value in zip(node.inputs[:2], [a, b]):
            socket.default_value = value
            if linked:
                source = tree.nodes.new("ShaderNodeValue")
                source.outputs[0].default_value = value
                tree.links.new(source.outputs[0], socket)
        expected = 0. if b == 0 else math.floor(a / b) * b
        if clamped:
            expected = min(1., max(0., expected))
        cases.append(export_case(node, material, f"math-snap-{index}", [expected] * 3))
    vector = tree.nodes.new("ShaderNodeCombineXYZ")
    vector.inputs["Y"].default_value = 1.5
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "SINE"
    tree.links.new(vector.outputs[0], scalar.inputs[0])
    cases.append(export_case(scalar, material, "vector-to-scalar-sine", [math.sin(.5)] * 3))
    import PyOpenColorIO as ocio
    colour = tree.nodes.new("ShaderNodeRGB")
    colour.outputs[0].default_value = (0., 1.5, 0., 1.)
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "SINE"
    tree.links.new(colour.outputs[0], scalar.inputs[0])
    luminance = 1.5 * ocio.GetCurrentConfig().getDefaultLumaCoefs()[1]
    cases.append(export_case(scalar, material, "colour-to-scalar-sine",
                             [math.sin(luminance)] * 3))
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "ADD"
    scalar.inputs[1].default_value = 0.
    tree.links.new(colour.outputs[0], scalar.inputs[0])
    cases.append(export_case(scalar, material, "colour-to-scalar-add", [luminance] * 3))
    bw = tree.nodes.new("ShaderNodeRGBToBW")
    tree.links.new(colour.outputs[0], bw.inputs[0])
    cases.append(export_case(bw, material, "colour-luminance", [luminance] * 3))
    product = tree.nodes.new("ShaderNodeVectorMath")
    product.operation = "MULTIPLY"
    product.inputs[1].default_value = (3., 0., 0.)
    tree.links.new(vector.outputs[0], product.inputs[0])
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "SINE"
    tree.links.new(product.outputs[0], scalar.inputs[0])
    cases.append(export_case(scalar, material, "derived-vector-to-scalar", [0.] * 3))
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "MULTIPLY_ADD"
    scalar.inputs[0].default_value = 1.5
    scalar.inputs[1].default_value = 2.
    tree.links.new(vector.outputs[0], scalar.inputs[2])
    cases.append(export_case(scalar, material, "vector-to-third-scalar-input", [3.5] * 3))
    for boundary in ("input", "output"):
        group_tree = bpy.data.node_groups.new("ScalarBoundary_" + boundary, "ShaderNodeTree")
        group_tree.interface.new_socket(name="Result", in_out="OUTPUT", socket_type="NodeSocketFloat")
        output = group_tree.nodes.new("NodeGroupOutput")
        group = tree.nodes.new("ShaderNodeGroup")
        group.node_tree = group_tree
        if boundary == "input":
            group_tree.interface.new_socket(name="Value", in_out="INPUT", socket_type="NodeSocketFloat")
            source = group_tree.nodes.new("NodeGroupInput")
            group_tree.links.new(source.outputs[0], output.inputs[0])
            tree.links.new(vector.outputs[0], group.inputs[0])
            expected = math.sin(.5)
        else:
            source = group_tree.nodes.new("ShaderNodeRGB")
            source.outputs[0].default_value = (0., 1.5, 0., 1.)
            group_tree.links.new(source.outputs[0], output.inputs[0])
            expected = math.sin(luminance)
        scalar = tree.nodes.new("ShaderNodeMath")
        scalar.operation = "SINE"
        tree.links.new(group.outputs[0], scalar.inputs[0])
        cases.append(export_case(scalar, material, "group-scalar-" + boundary, [expected] * 3))
    for value, clamped in [(.25, False), (.25, True), (9., False)]:
        node = tree.nodes.new("ShaderNodeMath")
        node.operation = "SQRT"
        node.use_clamp = clamped
        source = tree.nodes.new("ShaderNodeValue")
        source.outputs[0].default_value = value
        tree.links.new(source.outputs[0], node.inputs[0])
        expected = math.sqrt(value)
        if clamped:
            expected = min(1., max(0., expected))
        cases.append(export_case(node, material,
                                 f"linked-sqrt-{value}-clamp-{int(clamped)}", [expected] * 3))
    rounded = tree.nodes.new("ShaderNodeMath")
    rounded.operation = "ROUND"
    rounded.inputs[0].default_value = 8388609.
    residual = tree.nodes.new("ShaderNodeMath")
    residual.operation = "SUBTRACT"
    residual.inputs[1].default_value = 8388610.
    tree.links.new(rounded.outputs[0], residual.inputs[0])
    cases.append(export_case(residual, material, "round-float32-half-add", [0.] * 3))
    rounding_ops = {
        "FLOOR": math.floor, "CEIL": math.ceil, "TRUNC": math.trunc,
        "FRACT": lambda value: value - math.floor(value),
        "ROUND": lambda value: math.floor(value + .5),
    }
    for operation, evaluate in rounding_ops.items():
        for value in (-1.5, -1., 0., 1., 1.75):
            for linked in (False, True):
                node = tree.nodes.new("ShaderNodeMath")
                node.operation = operation
                node.inputs[0].default_value = value
                if linked:
                    source = tree.nodes.new("ShaderNodeValue")
                    source.outputs[0].default_value = value
                    tree.links.new(source.outputs[0], node.inputs[0])
                expected = evaluate(value)
                cases.append(export_case(node, material,
                                         f"math-{operation.lower()}-{value}-linked-{int(linked)}",
                                         [expected] * 3))
    for operation in ("FLOOR", "CEIL", "FRACTION"):
        node = tree.nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        source = tree.nodes.new("ShaderNodeCombineXYZ")
        values = (-1.5, -1., 1.75)
        for socket, value in zip(source.inputs, values):
            socket.default_value = value
        tree.links.new(source.outputs[0], node.inputs[0])
        evaluate = rounding_ops["FRACT" if operation == "FRACTION" else operation]
        cases.append(export_case(node, material, "vector-" + operation.lower(),
                                 [evaluate(value) for value in values]))
    # Helper-generated Math outputs must use the same final Clamp stage as
    # direct native textures. Exercise both constant folding and linked graphs.
    for operation, values, raw in [
        ("SQRT", (9.,), 3.), ("SQRT", (.25,), .5),
        ("EXPONENT", (1.,), math.e),
        ("MINIMUM", (2., 3.), 2.), ("MAXIMUM", (2., 3.), 3.),
        ("SINE", (-math.pi / 2.,), -1.),
        ("RADIANS", (-90.,), -math.pi / 2.),
        ("DEGREES", (.04,), math.degrees(.04)),
        ("LOGARITHM", (16., 2.), 4.),
        ("MULTIPLY_ADD", (2., 2., -1.), 3.),
        ("SMOOTH_MIN", (2., 3., .2), 2.),
        ("SMOOTH_MAX", (2., 3., .2), 3.),
        ("SIGN", (-2.,), -1.),
    ]:
        for clamped in (False, True):
            node = tree.nodes.new("ShaderNodeMath")
            node.operation = operation
            node.use_clamp = clamped
            for socket, value in zip(node.inputs, values):
                socket.default_value = value
                if clamped and raw != .5:
                    source = tree.nodes.new("ShaderNodeValue")
                    source.outputs[0].default_value = value
                    tree.links.new(source.outputs[0], socket)
            expected = min(1., max(0., raw)) if clamped else raw
            label = f"math-{operation.lower()}-{values[0]}-clamp-{int(clamped)}"
            cases.append(export_case(node, material, label, [expected] * 3))
    for operation in ["SNAP", "ADD"]:
        node = tree.nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        vectors = [(1.75, -1.25, .5), (1., 1., 0.)]
        for socket, vector in zip(node.inputs[:2], vectors):
            source = tree.nodes.new("ShaderNodeCombineXYZ")
            for component, value in zip(source.inputs, vector):
                component.default_value = value
            tree.links.new(source.outputs[0], socket)
        expected = [1., -2., 0.] if operation == "SNAP" else [2.75, -.25, .5]
        cases.append(export_case(node, material, "vector-" + operation.lower(), expected))
    node = tree.nodes.new("ShaderNodeTexCoord")
    cases.append(export_case(node, material, "generated-coordinates", [.5, .5, 0.], "Generated"))
    scaled = tree.nodes.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    scaled.inputs["Scale"].default_value = 2.
    tree.links.new(node.outputs["Generated"], scaled.inputs[0])
    shifted = tree.nodes.new("ShaderNodeVectorMath")
    shifted.operation = "ADD"
    shifted.inputs[1].default_value = (.4, .4, .4)
    tree.links.new(scaled.outputs[0], shifted.inputs[0])
    snapped = tree.nodes.new("ShaderNodeVectorMath")
    snapped.operation = "SNAP"
    snapped.inputs[1].default_value = (1., 1., 0.)
    tree.links.new(shifted.outputs[0], snapped.inputs[0])
    cases.append(export_case(snapped, material, "procedural-vector-snap", [1., 1., 0.]))
    return cases


def export_case(node, material, label, expected, output_name=None):
    props = reader.pysuperluxcore.Properties()
    output = node.outputs[output_name] if output_name else node.outputs[0]
    texture_name = reader.utils.sanitize_superluxcore_name("probe_" + label.replace("-", "_"))
    name = reader._node(node, output, props, material, texture_name,
                        obj_name="Probe", group_node_stack=[])
    return {"label": label, "output": name, "graph": props.ToString(), "expected": expected}


def main():
    python = os.environ.get("SUPERLUXCORE_TEST_PYTHON") or shutil.which("python3.13")
    if not python:
        raise RuntimeError("Set SUPERLUXCORE_TEST_PYTHON to the built module's Python executable")
    env = os.environ.copy()
    module_dir = ENGINE / "out/build/src/pysuperluxcore/Release"
    env["PYTHONPATH"] = str(module_dir) + os.pathsep + env.get("PYTHONPATH", "")
    with tempfile.TemporaryDirectory(prefix="blender-snap-") as directory:
        cases = Path(directory) / "cases.json"
        cases.write_text(json.dumps(build_cases()), encoding="utf-8")
        result = subprocess.run([
            python, str(ENGINE / "dev-tools/math-snap-regression.py"), "--cases", str(cases),
            "--gpu-devices", os.environ.get("SUPERLUXCORE_TEST_GPU_DEVICES", "010")],
            cwd=ENGINE, env=env, capture_output=True, text=True, timeout=600)
        print(result.stdout, flush=True)
        if result.returncode:
            print(result.stderr[-8000:], flush=True)
            raise RuntimeError(f"Snap render regression failed: {result.returncode}")
    print("PASS: real Blender Math/VectorMath/Texture Coordinate export and CPU/GPU rendering", flush=True)


if __name__ == "__main__":
    main()
