"""Preset lifecycle, old-library compatibility and reconstruction-only routing.

Real CUDA/Blender tests separately check the native model and actual sessions.
"""
import ast
from dataclasses import replace
import gc
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preset_backend', ROOT/'engine/dlss.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class Function:
    def __init__(self, fn): self.fn = fn
    def __call__(self, *args): return self.fn(*args)


class Library:
    def __init__(self, setter=True, reject=False):
        self.destroyed = []
        self.selected = []
        self.slc_dlss_abi = Function(lambda: 1)
        self.slc_dlss_create = Function(lambda *args: 123)
        self.slc_dlss_destroy = Function(lambda handle: self.destroyed.append(handle))
        self.slc_dlss_stats = Function(lambda *args: None)
        self.slc_dlss_process = Function(lambda *args: 1)
        if setter:
            def select(handle, preset, message, capacity):
                self.selected.append(preset)
                if reject: message.value = b'injected selection failure'
                return int(not reject)
            self.slc_dlss_set_preset = Function(select)


def construct(lib, preset='DEFAULT'):
    with mock.patch.object(m, '_library_path', return_value=Path('/unused')), \
         mock.patch.object(m.C, 'CDLL', return_value=lib):
        return m.CUDADLSS('/runtime', '/cache', preset=preset)


def function(path, name, env):
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), env)
    return env[name]


class Presets(unittest.TestCase):
    def test_default_keeps_old_abi_library_usable(self):
        lib = Library(setter=False)
        with construct(lib) as backend:
            self.assertEqual(backend.preset, 'DEFAULT')
        self.assertEqual(lib.destroyed, [123])

    def test_explicit_model_rejects_old_library_and_releases_handle(self):
        lib = Library(setter=False)
        with self.assertRaisesRegex(m.DLSSUnavailable, 'updated optional backend'):
            construct(lib, 'D')
        gc.collect()
        self.assertEqual(lib.destroyed, [123])

    def test_official_ids_and_immutable_model_selection(self):
        for name, value in [('D',4), ('E',5), ('F',6)]:
            lib = Library()
            with construct(lib, name) as backend:
                self.assertEqual(lib.selected, [value])
                self.assertEqual(backend.preset, name)
                with self.assertRaises(AttributeError): backend.preset = 'DEFAULT'
            self.assertEqual(lib.destroyed, [123])

    def test_setter_failure_releases_handle_exactly_once(self):
        lib = Library(reject=True)
        with self.assertRaisesRegex(m.DLSSUnavailable, 'injected selection failure'):
            construct(lib, 'D')
        gc.collect()
        self.assertEqual(lib.destroyed, [123])

    def test_unknown_model_fails_before_loading_library(self):
        with mock.patch.object(m.C, 'CDLL', side_effect=AssertionError('Unexpected library load')):
            for value in ('A', 'd', '', None, [], True):
                with self.subTest(value=value), self.assertRaises(m.DLSSInputError):
                    m.CUDADLSS('/runtime', '/cache', preset=value)

    def test_final_option_routes_scene_model_and_old_scene_default(self):
        calls = []
        env = {'pysuperluxcore': types.SimpleNamespace(RenderSession=types.SimpleNamespace(
                    AcknowledgeDenoisingFrame=object(), ReleaseDenoisingFrameDelivery=object(), SetDenoisingFrameHaltSPP=object())),
               'configuration': lambda *args: (calls.append(args) or object(), '')}
        resolve = function(ROOT/'engine/dlss_final.py', 'final_options', env)
        denoiser = types.SimpleNamespace(enabled=True, type='DLSS', temporal_enabled=False, dlss_preset='D')
        config = types.SimpleNamespace(external_process=False, use_filesaver=False, engine='PATH', effective_device=lambda:'OCL')
        scene = types.SimpleNamespace(superluxcore=types.SimpleNamespace(denoiser=denoiser, config=config))
        engine = types.SimpleNamespace(is_preview=False)
        prefs = types.SimpleNamespace(gpu_backend='CUDA', dlss_library='/library', dlss_runtime='/runtime')
        self.assertEqual(resolve(scene, engine, prefs)[1], '')
        self.assertEqual(calls[-1], ('/library','/runtime','D'))
        del denoiser.dlss_preset
        resolve(scene, engine, prefs)
        self.assertEqual(calls[-1][-1], 'DEFAULT')

    def test_reduced_final_accepts_full_frame_border_preserving_crop_settings(self):
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Options:
            render_mode: str = 'NATIVE'
            output_size: tuple = None
        env = {'replace': replace,
               'pysuperluxcore': types.SimpleNamespace(
                   RenderSession=types.SimpleNamespace(AcknowledgeDenoisingFrame=object(),
                       ReleaseDenoisingFrameDelivery=object(), SetDenoisingFrameHaltSPP=object()),
                   DenoisingImagePipeline=types.SimpleNamespace(supports_canonical_coverage=lambda: True)),
               'configuration': lambda *args: (Options(), '')}
        resolve = function(ROOT/'engine/dlss_final.py', 'final_options', env)
        denoiser = types.SimpleNamespace(enabled=True, type='DLSS', temporal_enabled=False,
                                         dlss_input_reduction='2')
        config = types.SimpleNamespace(external_process=False, use_filesaver=False,
                                       engine='PATH', effective_device=lambda: 'OCL')
        render = types.SimpleNamespace(use_border=True, use_crop_to_border=True,
            border_min_x=0., border_min_y=0., border_max_x=1., border_max_y=1.,
            resolution_x=1280, resolution_y=720, resolution_percentage=100)
        scene = types.SimpleNamespace(render=render,
            superluxcore=types.SimpleNamespace(denoiser=denoiser, config=config))
        engine = types.SimpleNamespace(is_preview=False)
        prefs = types.SimpleNamespace(gpu_backend='CUDA', dlss_library='/library', dlss_runtime='/runtime')
        for crop in (False, True):
            render.use_crop_to_border = crop
            before = vars(render).copy()
            options, reason = resolve(scene, engine, prefs)
            self.assertEqual(reason, '')
            self.assertEqual((options.render_mode, options.output_size), ('PERFORMANCE', (1280, 720)))
            self.assertEqual(vars(render), before)
        for field, value in [('border_min_x', .25), ('border_max_x', .75),
                             ('border_min_y', .25), ('border_max_y', .75)]:
            with self.subTest(field=field):
                old = getattr(render, field)
                setattr(render, field, value)
                self.assertIsNone(resolve(scene, engine, prefs)[0])
                self.assertIn('complete output raster', resolve(scene, engine, prefs)[1])
                setattr(render, field, old)

    def test_viewport_model_changes_reconstruction_configuration(self):
        calls = []
        worker = types.SimpleNamespace(_dlss_signature=(None,''),dlss_status='')
        def configure(options,reason=''):
            calls.append((options,reason));worker._dlss_signature=(options,reason);worker.dlss_status=reason
        worker.configure_dlss=configure
        engine = types.SimpleNamespace(session_worker=worker,session=None)
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Options:
            preset: str
            channels: int = 4
            render_mode: str = 'NATIVE'
            output_size: tuple = None
        prefs = types.SimpleNamespace(gpu_backend='CUDA', dlss_library='', dlss_runtime='')
        vp = types.SimpleNamespace(use_denoiser=True,denoiser='DLSS',device='OCL',dlss_preset='DEFAULT')
        scene = types.SimpleNamespace(camera=None,superluxcore=types.SimpleNamespace(viewport=vp))
        context = types.SimpleNamespace(scene=scene)
        env = {'os':os,'replace':replace,'utils':types.SimpleNamespace(in_material_shading_mode=lambda c:False,
                    is_valid_camera=lambda c:False, using_bidir_in_viewport=lambda s:False),
               'export':types.SimpleNamespace(blender_settings=None),
               'get_addon_preferences':lambda c:prefs,
               'dlss_viewport':types.SimpleNamespace(configuration=lambda lib,rt,preset,mode:(Options(preset,render_mode=mode),'')),
               'bpy':types.SimpleNamespace(path=types.SimpleNamespace(abspath=lambda p:p))}
        get_worker = function(ROOT/'engine/viewport.py','_worker',env)
        get_worker(engine,context);get_worker(engine,context)
        self.assertEqual(len(calls),1)
        vp.dlss_preset='D';get_worker(engine,context)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[-1][0].preset,'D')
        self.assertIs(engine.session_worker,worker)
        # SR size/preset changes preserve the worker and explicitly resize its
        # physical input. A failed SR backend returns to full configured input.
        changes=[];env['_submit_config_update']=lambda *args:changes.append(args)
        env['utils'].calc_filmsize=lambda *args:(1165,869)
        engine.session=object();engine.exporter=object();vp.dlss_render_mode='QUALITY'
        get_worker(engine,context)
        self.assertEqual(calls[-1][0].output_size,(1165,869))
        self.assertEqual(len(changes),1)
        worker.dlss_status='DLSS fallback: injected SDK failure'
        get_worker(engine,context)
        self.assertIsNone(calls[-1][0]);self.assertEqual(len(changes),2)
        get_worker(engine,context);self.assertEqual(len(changes),2)

    def test_model_update_only_redraws_without_tagging_physical_scene(self):
        calls=[]
        area=types.SimpleNamespace(type='VIEW_3D',tag_redraw=lambda:calls.append('redraw'))
        context=types.SimpleNamespace(window_manager=types.SimpleNamespace(windows=[types.SimpleNamespace(screen=types.SimpleNamespace(areas=[area]))]))
        update=function(ROOT/'properties/viewport.py','_update_dlss_preset',{})
        update(types.SimpleNamespace(id_data=types.SimpleNamespace(update_tag=lambda:self.fail('Physical scene tagged'))),context)
        self.assertEqual(calls,['redraw'])


if __name__ == '__main__': unittest.main(verbosity=2)
