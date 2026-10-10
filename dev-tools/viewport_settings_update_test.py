"""Check evaluated viewport settings and a paused worker's film resize.

Run in Blender with the add-on enabled. DEV=OCL selects the configured GPU.
This exercises real native rendering without claiming GUI redraw coverage.
"""

import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

import bpy
import numpy as np
import pysuperluxcore


def graph_fingerprint():
    def value(v):
        if isinstance(v, (str, bool, int, float)) or v is None:
            return v
        if isinstance(v, bpy.types.ID):
            return v.name_full
        if hasattr(v, "__iter__"):
            return [value(x) for x in v]
        return str(v)

    graphs = {}
    for data in list(bpy.data.materials) + list(bpy.data.worlds) + list(bpy.data.lights):
        tree = getattr(data, "node_tree", None)
        if tree is not None:
            graphs[data.bl_rna.identifier + ":" + data.name_full] = {
                "nodes": sorted((
                    n.name, n.bl_idname,
                    [(i.identifier, value(i.default_value)) for i in n.inputs
                     if hasattr(i, "default_value")],
                    [(p.identifier, value(getattr(n, p.identifier)))
                     for p in n.bl_rna.properties if p.type == "ENUM" and not p.is_readonly],
                ) for n in tree.nodes),
                "links": sorted((l.from_node.name, l.from_socket.identifier,
                                 l.to_node.name, l.to_socket.identifier) for l in tree.links),
            }
    return hashlib.sha256(json.dumps(graphs, sort_keys=True).encode()).hexdigest()


def main():
    package = next(
        a.module for a in bpy.context.preferences.addons
        if a.module.endswith(".superluxcore") or a.module == "superluxcore"
    )
    export = importlib.import_module(package + ".export")
    utils = importlib.import_module(package + ".utils")
    worker_module = importlib.import_module(package + ".engine.session_worker")
    error_log = importlib.import_module(package + ".utils.errorlog").SuperLuxCoreErrorLog
    output = Path(os.environ.get("SUPERLUXCORE_AUDIT_DIR", "/tmp/viewport-settings-test"))
    output.mkdir(parents=True, exist_ok=True)
    if os.environ.get("SUPERLUXCORE_VIEWPORT_FIXTURE"):
        bpy.ops.wm.open_mainfile(filepath=os.environ["SUPERLUXCORE_VIEWPORT_FIXTURE"])
    scene = bpy.context.scene
    original_graph = graph_fingerprint()
    scene.render.engine = "SUPERLUXCORE"
    settings = scene.superluxcore.viewport
    depsgraph = bpy.context.evaluated_depsgraph_get()
    checked = []

    # Neither property setters nor the test explicitly tag the scene. Only
    # normal dependency-graph evaluation may propagate the new RNA value.
    for prop in settings.bl_rna.properties:
        if prop.identifier in {"rna_type", "name"} or prop.is_readonly:
            continue
        name = prop.identifier
        old = getattr(settings, name)
        if prop.type == "BOOLEAN":
            new = not old
        elif prop.type == "ENUM":
            new = next(x.identifier for x in prop.enum_items if x.identifier != old)
        elif prop.type == "INT":
            new = old + 1 if old < prop.hard_max else old - 1
        elif prop.type == "FLOAT":
            new = min(prop.hard_max, max(prop.hard_min, old + 0.1))
        else:
            raise AssertionError((name, prop.type))
        setattr(settings, name, new)
        expected = getattr(settings, name)
        assert expected != old, name
        depsgraph.update()
        actual = getattr(depsgraph.scene_eval.superluxcore.viewport, name)
        checked.append({"property": name, "expected": expected, "evaluated": actual})
        assert actual == expected, checked[-1]
        setattr(settings, name, old)
        depsgraph.update()
        assert getattr(depsgraph.scene_eval.superluxcore.viewport, name) == old, name
    assert len(checked) == 21, len(checked)
    (output / "rna-settings.json").write_text(json.dumps(checked, indent=2) + "\n")

    settings.device = "OCL" if os.environ.get("DEV") == "OCL" else "CPU"
    if settings.device == "OCL":
        bpy.context.preferences.addons[package].preferences.gpu_backend = "METAL"
    settings.pixel_size = "1"
    # Avoid a post-pause denoiser/readback race in this worker-only test.
    settings.use_denoiser = False
    scene.update_tag()
    depsgraph.update()
    context = SimpleNamespace(
        scene=scene,
        preferences=bpy.context.preferences,
        region=SimpleNamespace(width=1280, height=720),
        region_data=SimpleNamespace(view_perspective="PERSP"),
        space_data=SimpleNamespace(
            shading=SimpleNamespace(type="RENDERED"),
            use_render_border=False,
            render_border_min_x=0.0, render_border_min_y=0.0,
            render_border_max_x=1.0, render_border_max_y=1.0,
        ),
    )
    error_log.clear(force_ui_update=False)
    exporter = export.Exporter()
    result = exporter.export_scene(depsgraph, None)
    assert result is not None, "scene export failed"
    native_scene, _ = result
    props = export.config.convert(exporter, depsgraph.scene_eval, context)
    assert str(props), "viewport config export failed"
    assert props.Get("path.spectral.enable").GetBool(), "spectral rendering disabled"
    exporter.config_cache.diff(props)

    class Engine:
        session = None
        viewport_start_time = 0.0

    engine = Engine()
    worker = worker_module.SessionWorker(engine)
    rows = []

    def wait_for_frame(dimensions, previous_mutation):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            error = worker.pop_error()
            assert error is None, error
            if worker.session is not None and worker.mutation_seq > previous_mutation:
                with worker.session_lock:
                    session = worker.session
                    session.UpdateStats()
                    film = session.GetFilm()
                    live_size = (film.GetWidth(), film.GetHeight())
                    if live_size == dimensions:
                        pixels = np.zeros(dimensions[0] * dimensions[1] * 3, dtype=np.float32)
                        film.GetOutputFloat(pysuperluxcore.FilmOutputType.RGB, pixels, 0, False)
                        if np.isfinite(pixels).all() and pixels.mean() > 1e-5:
                            name = "pixel-size-" + settings.pixel_size
                            film.SaveOutput(
                                str(output / (name + ".exr")),
                                pysuperluxcore.FilmOutputType.RGB, pysuperluxcore.Properties(),
                            )
                            return {
                                "pixel_size": settings.pixel_size,
                                "film_size": list(live_size),
                                "finite": True, "mean": float(pixels.mean()),
                                "mutation": worker.mutation_seq,
                                "elapsed": 90 - (deadline - time.monotonic()),
                                "renderengine": props.Get("renderengine.type").GetString(),
                            }
            time.sleep(0.02)
        raise AssertionError(("no post-resize frame", dimensions, worker.phase))

    try:
        worker.submit_start(native_scene, props)
        rows.append(wait_for_frame((1280, 720), 0))
        for pixel_size in ("2", "4", "1"):
            previous_mutation = worker.mutation_seq
            with worker.session_lock:
                worker.session.Pause()
                assert worker.session.IsInPause()
            old_started = engine.viewport_start_time
            settings.pixel_size = pixel_size
            depsgraph.update()
            evaluated = depsgraph.scene_eval
            dimensions = utils.calc_filmsize(evaluated, context)
            assert dimensions == (1280 // int(pixel_size), 720 // int(pixel_size))
            props = export.config.convert(exporter, evaluated, context)
            assert str(props) and exporter.config_cache.diff(props), pixel_size
            worker.submit_config(props)
            row = wait_for_frame(dimensions, previous_mutation)
            with worker.session_lock:
                assert not worker.session.IsInPause()
            assert engine.viewport_start_time > old_started
            row.update(was_paused=True, resumed=True, halt_timer_reanchored=True)
            rows.append(row)
        errors = [str(x) for x in error_log.errors]
        assert not errors, errors
        assert graph_fingerprint() == original_graph, "Cycles graphs changed"
        native = Path(pysuperluxcore.pysuperluxcore.__file__)
        summary = {
            "version": pysuperluxcore.Version(),
            "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            "rna_properties_checked": len(checked), "frames": rows,
            "graph_sha256": original_graph, "graph_unchanged": True,
            "gui_redraw_verified": False, "public_deployed": False,
        }
        (output / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("VIEWPORT_SETTINGS_PASS", json.dumps(summary), flush=True)
    finally:
        worker.shutdown()
        worker._thread.join(timeout=30)
        assert not worker._thread.is_alive(), "worker shutdown timed out"


if __name__ == "__main__":
    main()
