"""
External-process rendering.

The exported SuperLuxCore scene is serialized to a binary .bcf and rendered
by a detached Python process. Blender's render() call returns right
after the spawn, so the dependency graph and all evaluated scene
memory are released while the heavy render runs outside — the only way
to actually get Blender-side scene memory back during a render.

When the detached process finishes, a timer copies the beauty output
to the render output path and shows it in an image editor.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque

import bpy
import pysuperluxcore

RUNNER = os.path.join(os.path.dirname(__file__), "external_render_runner.py")
DONE_MARK = "__done__"


class _Job:
    """One in-flight external render."""

    def __init__(self, proc, workdir, log_path, target_path, frame, settings=None):
        self.proc = proc
        self.workdir = workdir
        self.log_path = log_path
        self.target_path = target_path
        self.frame = frame
        self.settings = settings


_jobs = []


def _snapshot_settings(scene):
    """Plain values only: do not pin the exported Blender scene to a job."""
    fields = {
        "image_settings": ("file_format", "color_mode", "color_depth", "quality",
                           "compression", "exr_codec", "tiff_codec", "jpeg2k_codec"),
        "view_settings": ("view_transform", "look", "exposure", "gamma",
                          "use_white_balance", "temperature", "tint"),
        "display_settings": ("display_device",),
    }
    result = {}
    for group, names in fields.items():
        source = scene.render.image_settings if group == "image_settings" else getattr(scene, group)
        result[group] = {name: getattr(source, name) for name in names if hasattr(source, name)}
    if scene.view_settings.use_curve_mapping:
        mapping = scene.view_settings.curve_mapping
        result["curves"] = [[(tuple(p.location), p.handle_type) for p in c.points] for c in mapping.curves]
        result["black_level"] = tuple(mapping.black_level)
        result["white_level"] = tuple(mapping.white_level)
    return result


def _configure_beauty(config_props, workdir, beauty_index=0):
    """Keep the final combined pipeline in float EXR until Blender saves it.

    PNG film outputs quantize/clip the linear beauty before the requested
    output format and Blender view transform can be applied.
    """
    names = config_props.GetAllUniqueSubNames("film.outputs")
    candidates = []
    for name in names:
        kind = config_props.Get(name + ".type").GetString()
        if kind in ("RGB_IMAGEPIPELINE", "RGBA_IMAGEPIPELINE"):
            index = config_props.Get(name + ".index", [0]).GetInt()
            candidates.append((index, kind == "RGBA_IMAGEPIPELINE", kind))
    if not candidates:
        raise RuntimeError("External render has no combined image pipeline output")
    # Higher pipeline indices may be light-group/AOV or gamma-corrected
    # noise-estimation outputs. The render engine identifies the beauty.
    selected = [c for c in candidates if c[0] == beauty_index]
    if not selected:
        raise RuntimeError("External render combined pipeline is missing")
    index, _, kind = max(selected)
    if any(c[1] for c in candidates):
        kind = "RGBA_IMAGEPIPELINE"
    slot = max((int(n.rsplit(".", 1)[-1]) for n in names), default=-1) + 1
    prefix = "film.outputs." + str(slot)
    for key, value in (("type", kind), ("index", index),
                       ("filename", os.path.join(workdir, "beauty.exr"))):
        config_props.Set(pysuperluxcore.Property(prefix + "." + key, value))


def run(config_props, superluxcore_scene, scene, beauty_index=0):
    workdir = tempfile.mkdtemp(prefix="blc_extrender_")
    try:
        return _start(config_props, superluxcore_scene, scene, workdir, beauty_index)
    except Exception:
        shutil.rmtree(workdir)
        raise


def _start(config_props, superluxcore_scene, scene, workdir, beauty_index):
    """Serialize the render config, spawn the detached renderer and
    return immediately. Called on the main thread during render()."""
    bcf_path = os.path.join(workdir, "scene.bcf")
    settings = _snapshot_settings(scene)
    if settings["image_settings"]["file_format"] == "OPEN_EXR_MULTILAYER":
        raise RuntimeError("External rendering does not yet support multilayer EXR output")
    _configure_beauty(config_props, workdir, beauty_index)

    # The detached process enumerates devices itself; a selection string
    # sized for Blender's enumeration would not match (and crash on load)
    if "opencl.devices.select" in config_props.GetAllNames():
        config_props.Delete("opencl.devices.select")

    renderconfig = pysuperluxcore.RenderConfig(config_props, superluxcore_scene)
    renderconfig.Save(bcf_path)
    # Release the in-process scene + parsed config before spawning:
    # the external process rebuilds everything from the .bcf.
    del renderconfig
    del superluxcore_scene

    site_packages = os.path.dirname(os.path.dirname(pysuperluxcore.__file__))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [site_packages, env.get("PYTHONPATH", "")]
    )

    # Vulkan is opt-in engine-side (never auto-selected by an empty
    # opencl.devices.select), so the child must re-derive the selection
    # string from its own enumeration — pass the wanted backend through.
    from . import get_addon_preferences  # utils/__init__.py
    gpu_backend = get_addon_preferences(bpy.context).gpu_backend
    if gpu_backend == "VULKAN":
        env["BLC_GPU_BACKEND"] = gpu_backend

    log_path = os.path.join(workdir, "render.log")
    target_path = bpy.path.abspath(scene.render.filepath)
    if scene.render.use_file_extension:
        target_path = bpy.path.ensure_ext(target_path, scene.render.file_extension)
    # Blender 5.x has no bpy.app.binary_path_python but sys.executable
    # already points at the bundled interpreter
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [sys.executable, RUNNER, bcf_path, workdir],
            stdout=log, stderr=subprocess.STDOUT, cwd=workdir, env=env,
        )

    print(f"[BLC] External render started (PID {proc.pid})")
    print(f"[BLC]   scene: {bcf_path}")
    print(f"[BLC]   log:   {log_path}")
    print(
        "[BLC] Blender-side scene memory is released now; the render "
        "cannot be cancelled from Blender — kill the process to abort."
    )

    _jobs.append(
        _Job(proc, workdir, log_path, target_path, scene.frame_current, settings)
    )
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=2.0, persistent=True)


def _find_beauty(workdir):
    """The float output explicitly selected by _configure_beauty."""
    linear = os.path.join(workdir, "beauty.exr")
    return linear if os.path.isfile(linear) else None


def _resolve_target(job):
    path = job.target_path
    if "#" in path:
        path = re.sub(
            r"#+", lambda m: str(job.frame).zfill(len(m.group())), path
        )
    return path


def _poll():
    for job in list(_jobs):
        # A done marker can precede process exit. Keep ownership until
        # poll() reaps the child; never wait on Blender's UI thread.
        if job.proc.poll() is None:
            continue
        _jobs.remove(job)
        _finish(job)
    # Re-register while jobs are pending; the timer stops otherwise
    return 2.0 if _jobs else None


def _finish(job):
    if job.proc.poll() is None:
        return
    # The result is saved/loaded before the scratch directory disappears.
    # Failures print a bounded log tail; serialized scenes and AOVs are
    # never retained indefinitely in the system temporary directory.
    try:
        if job.proc.returncode != 0:
            try:
                with open(job.log_path) as f:
                    tail = "".join(deque(f, maxlen=15))[-16384:]
            except OSError:
                tail = ""
            raise RuntimeError(f"External render failed (exit {job.proc.returncode}):\n{tail}")
        beauty = _find_beauty(job.workdir)
        if beauty is None:
            raise RuntimeError("External render produced no float beauty image")
        target = _resolve_target(job)
        if not target:
            raise RuntimeError("External render needs an output filepath")
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        _save_beauty(job, beauty, target)
        print(f"[BLC] External render saved: {target}")
        image = bpy.data.images.load(target, check_existing=True)
        # Show it in an image editor if one is visible
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    area.spaces.active.image = image
                    return
    except Exception as error:
        print(f"[BLC] {error}")
        from .errorlog import SuperLuxCoreErrorLog
        SuperLuxCoreErrorLog.add_error(str(error))
    finally:
        shutil.rmtree(job.workdir)


def _save_beauty(job, beauty, target):
    """Use the same Blender color/output conversion as an internal render."""
    settings = job.settings
    if settings is None:
        raise RuntimeError("External render output settings are missing")
    scene = bpy.data.scenes.new("SuperLuxCore external output")
    image = None
    try:
        for group in ("display_settings", "view_settings", "image_settings"):
            dest = scene.render.image_settings if group == "image_settings" else getattr(scene, group)
            for name, value in settings[group].items():
                setattr(dest, name, value)
        if "curves" in settings:
            scene.view_settings.use_curve_mapping = True
            mapping = scene.view_settings.curve_mapping
            mapping.initialize()
            mapping.black_level = settings["black_level"]
            mapping.white_level = settings["white_level"]
            for curve, points in zip(mapping.curves, settings["curves"]):
                for point in list(curve.points)[1:-1]:
                    curve.points.remove(point)
                for p, (xy, handle) in zip((curve.points[0], curve.points[-1]), (points[0], points[-1])):
                    p.location, p.handle_type = xy, handle
                for xy, handle in points[1:-1]:
                    curve.points.new(*xy).handle_type = handle
            mapping.update()
        image = bpy.data.images.load(beauty, check_existing=False)
        image.save_render(target, scene=scene)
    finally:
        if image is not None:
            bpy.data.images.remove(image)
        bpy.data.scenes.remove(scene)
