"""Blender에서 Cycles 픽셀 필터를 가져온 뒤 RNA 제한과 내보내기를 검사한다."""
import bpy
import math
import importlib
from types import SimpleNamespace

export_config = importlib.import_module("bl_ext.user_default.superluxcore.export.config")

scene = bpy.context.scene
scene.render.engine = "SUPERLUXCORE"
scene.cycles.use_denoising = False
config = scene.superluxcore.config
for kind, scale, tag in (("BOX", .5, "BOX"), ("GAUSSIAN", 1.5, "GAUSSIAN"),
                         ("BLACKMAN_HARRIS", 1., "BLACKMANHARRIS")):
    for width in (.01, .5, 1.5, 4.):
        scene.cycles.pixel_filter_type = kind
        scene.cycles.filter_width = width
        actual_width = scene.cycles.filter_width
        assert bpy.ops.superluxcore.import_cycles_settings() == {"FINISHED"}
        assert config.filter == tag and config.filter_enabled
        assert math.isclose(config.filter_width, actual_width * scale, rel_tol=1e-5)
        if kind == "GAUSSIAN":
            assert math.isclose(config.gaussian_alpha, 8. / actual_width ** 2, rel_tol=1e-5)
        exported = export_config.convert(SimpleNamespace(lightgroup_cache=set()), scene)
        assert exported.Get("film.filter.type").GetString() == tag
        assert math.isclose(exported.Get("film.filter.width").GetFloat(),
                            actual_width * scale, rel_tol=1e-5)
        if kind == "GAUSSIAN":
            assert math.isclose(exported.Get("film.filter.gaussian.alpha").GetFloat(),
                                8. / actual_width ** 2, rel_tol=1e-5)
        # 같은 설정을 다시 가져와도 값이 바뀌지 않는지 확인한다.
        before = (config.filter, config.filter_width, config.gaussian_alpha)
        bpy.ops.superluxcore.import_cycles_settings()
        assert before == (config.filter, config.filter_width, config.gaussian_alpha)
        print(f"PASS {kind} width={actual_width:g} radius={config.filter_width:g}", flush=True)
print("PASS 픽셀 필터 12조건", flush=True)
