"""기존 Blender 설정을 읽되 저장된 SuperLuxCore의 명시적 선택을 우선한다."""
from types import SimpleNamespace


def transparent_film(scene):
    """투명 필름은 렌더할 때 읽으며 원본 씬을 수정하지 않는다."""
    camera = scene.camera
    if camera is not None:
        pipeline = camera.data.superluxcore.imagepipeline
        if pipeline.is_property_set("transparent_film"):
            return pipeline.transparent_film
    return bool(scene.render.film_transparent)


def motion_blur(scene):
    """Blender 모션 설정을 자동 해석하고 확장 전용 설정은 보존한다."""
    settings = scene.camera.data.superluxcore.motion_blur
    if settings.is_property_set("enable") or not scene.render.use_motion_blur:
        return settings
    shutter = float(scene.render.motion_blur_shutter)
    position = getattr(scene.render, "motion_blur_position", "CENTER")
    offset = {"START": shutter / 2., "END": -shutter / 2.}.get(position, 0.)
    return SimpleNamespace(enable=True, object_blur=True, camera_blur=True,
                           shutter=shutter, steps=settings.steps, offset=offset)


def object_motion_blur(obj):
    """기존 Cycles의 개별 물체 제외와 명시적 확장 설정을 보존한다."""
    settings = obj.superluxcore
    if not getattr(getattr(obj, "cycles", None), "use_motion_blur", True):
        return False
    if settings.is_property_set("enable_motion_blur"):
        return settings.enable_motion_blur
    return True


def path_depth(scene, name, fallback):
    """명시적으로 작성된 Cycles 바운스 제한만 자동으로 읽는다."""
    source = {"depth_total": "max_bounces", "depth_diffuse": "diffuse_bounces",
              "depth_glossy": "glossy_bounces", "depth_volume": "volume_bounces"}.get(name)
    native = scene.superluxcore.config.path
    cycles = getattr(scene, "cycles", None)
    if source and cycles is not None and cycles.is_property_set(source) and not native.is_property_set(name):
        return max(0, int(getattr(cycles, source)))
    return fallback
