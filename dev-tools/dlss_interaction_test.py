"""Interaction budgets must deliver a fresh coherent preview and restore quality."""
import ast
import importlib.util
import math
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'engine/viewport.py'
nodes = ast.parse(SOURCE.read_text()).body
names = {'_dlss_interaction_active', '_interaction_film_scale', '_submit_film_scale', '_restore_interaction',
         '_submit_config_update', '_dlss_render_size'}
constants = {'_RT_ENGINES', '_INTERACTION_DOWNSCALE_PIXELS', '_INTERACTION_DOWNSCALE_FACTOR',
             '_DLSS_INTERACTION_PIXELS', '_DLSS_PREVIEW_MAX_WAIT_S', '_DYN_RES_TAIL_S'}
selected = [n for n in nodes if isinstance(n, ast.FunctionDef) and n.name in names or
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)]


class Properties:
    def __init__(self): self.values = {}
    def Get(self, name, default):
        return types.SimpleNamespace(GetString=lambda: str(self.values.get(name, default[0])))

    def Set(self, value):
        if isinstance(value,Properties):self.values.update(value.values)
        else:self.values[value[0]] = value[1]


class Interaction(unittest.TestCase):
    def setUp(self):
        self.clock = 1.
        self.env = {'math': math, 'time': lambda: self.clock,
                    'pysuperluxcore': types.SimpleNamespace(Properties=Properties, Property=lambda *v: v)}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), self.env)
        self.parsed, self.reductions, self.redraws = [], [], []
        self.worker = types.SimpleNamespace(_dlss_signature=(object(), ''), mutation_seq=4, phase='',
            submit_parse=self.parsed.append, submit_resolution_reduction=self.reductions.append)
        self.engine = types.SimpleNamespace(_engine_type='RTPATHOCL', session_worker=self.worker,
            last_viewport_size=(1165, 869), _film_scale=2, _dyn_res_until=.4, _dyn_res_active=True,
            session=object(), tag_redraw=lambda: self.redraws.append(True))
        self.fb = types.SimpleNamespace(_dlss_owner=None, _width=582, _height=434)

    def restore(self): self.env['_restore_interaction'](self.engine, self.worker, self.fb)

    def test_coherent_preview_has_real_pixel_budget(self):
        for size, scale in [((320,180),1), ((1165,869),2), ((3840,2160),4), ((7680,4320),8)]:
            self.engine.last_viewport_size=size
            self.assertEqual(self.env['_interaction_film_scale'](self.engine),scale)
        self.worker._dlss_signature=(None,'missing runtime')
        self.engine.last_viewport_size=(1165,869)
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),1)
        self.engine.last_viewport_size=(3840,2160)
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),2)
        self.engine._engine_type='PATHOCL'
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),1)

    def test_tail_does_not_discard_inflight_preview(self):
        self.restore()
        self.assertEqual(self.parsed,[])
        self.assertTrue(self.engine._dyn_res_active)
        self.assertEqual(len(self.redraws),1)

    def test_sr_preview_uses_source_size_and_restores_configured_sr_input(self):
        self.worker._dlss_signature=(types.SimpleNamespace(input_size=lambda size:(777,579)), '')
        self.fb._dlss_owner=(id(self.engine.session),4)
        self.fb._width=1165;self.fb._height=869
        self.fb._dlss_last_source_size=(388,289)
        self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':777,'film.height':579})
        self.assertFalse(self.engine._dyn_res_active)

    def test_sr_budget_counts_traced_pixels(self):
        self.worker._dlss_signature=(types.SimpleNamespace(input_size=lambda size:(582,434)), '')
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),1)

    def test_quality_sr_does_not_skip_the_native_interaction_budget(self):
        # Actual GenmaB Quality input: below512Ki, but larger than Native's
        # 582x434 moving preview. It must also enter a coherent preview.
        self.worker._dlss_signature=(types.SimpleNamespace(
            input_size=lambda size:tuple(round(v/1.5) for v in size)), '')
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),2)
        self.env['_submit_film_scale'](self.engine,self.worker,1)
        self.parsed.clear()
        self.env['_submit_film_scale'](self.engine,self.worker,2)
        self.assertEqual(self.parsed[0].values,{'film.width':388,'film.height':289})
        self.engine.last_viewport_size=(640,480)
        self.assertEqual(self.env['_interaction_film_scale'](self.engine),1)

    def test_native_preview_divisors_preserved_at_odd_sizes_and_cap_boundaries(self):
        for width,height,expected in [(721,727,1),(723,727,2),(1165,869,2),
                                      (1921,1081,2),(2049,1025,4),
                                      (3840,2160,4),(7680,4320,8)]:
            self.engine.last_viewport_size=(width,height)
            self.assertEqual(self.env['_interaction_film_scale'](self.engine),expected)

    def test_quality_resize_restores_actual_input_not_just_display_dimensions(self):
        self.worker._dlss_signature=(types.SimpleNamespace(
            input_size=lambda size:tuple(round(v/1.5) for v in size)), '')
        config=Properties();config.values={'film.width':932,'film.height':869,
                                          'path.pathdepth.total':25};queued=[]
        self.env['utils']=types.SimpleNamespace(calc_filmsize=lambda *args:(932,869))
        self.engine.exporter=types.SimpleNamespace(get_restart_config_props=lambda:config)
        self.worker.submit_config=queued.append
        self.env['_submit_config_update'](self.engine,self.worker,None,None)
        self.assertEqual(queued[0].values,{'film.width':310,'film.height':289,
                                         'path.pathdepth.total':25})
        # SR already presents at the full display size. An older/wrong input
        # must not release the preview hold merely because the display fits.
        self.fb._width,self.fb._height=932,869
        self.fb._dlss_owner=(id(self.engine.session),4)
        self.fb._dlss_last_source_size=(621,579)
        self.clock=1.5;self.restore();self.assertEqual(self.parsed,[])
        self.fb._dlss_last_source_size=(310,289)
        self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':621,'film.height':579})
        self.assertFalse(self.engine._dyn_res_active)
        self.assertEqual(config.values,{'film.width':932,'film.height':869,
                                        'path.pathdepth.total':25})

    def test_stale_owner_wrong_size_and_pending_edit_cannot_release(self):
        self.fb._dlss_owner=(id(self.engine.session),3)
        self.restore(); self.assertEqual(self.parsed,[])
        self.fb._dlss_owner=(id(self.engine.session),4)
        self.fb._width=1165
        self.restore(); self.assertEqual(self.parsed,[])
        self.fb._width=582; self.worker.phase='Applying scene edits'
        self.restore(); self.assertEqual(self.parsed,[])
        self.worker.phase=''; self.engine._deferred_edit_jobs=([('edit', ['camera'])],True)
        self.restore(); self.assertEqual(self.parsed,[])
        self.engine._deferred_edit_jobs=None
        self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':1165,'film.height':869})
        self.assertEqual(self.reductions,[0])
        self.assertFalse(self.engine._dyn_res_active)
        self.restore(); self.assertEqual(len(self.parsed),1)

    def test_stalled_or_failed_producer_restores_bounded_full_film(self):
        self.engine.last_viewport_size=(900,700)
        self.clock=10.41
        self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':900,'film.height':700})
        self.assertEqual(self.reductions,[0])

    def test_edit_and_resize_setup_do_not_consume_the_first_preview(self):
        # Actual heavy-scene setup can consume the former five-second
        # hold before even the first coherent preview is available.
        self.clock=5.5
        self.restore()
        self.assertEqual(self.parsed,[])
        self.fb._dlss_owner=(id(self.engine.session),4)
        self.restore()
        self.assertEqual(self.engine._film_scale,1)

    def test_disabled_dlss_keeps_ordinary_tail(self):
        self.worker._dlss_signature=(None,'disabled')
        self.restore()
        self.assertEqual(self.engine._film_scale,1)
        self.assertEqual(self.reductions,[0])

    def test_active_motion_keeps_preview_until_tail(self):
        self.clock=.2
        self.fb._dlss_owner=(id(self.engine.session),4)
        self.restore()
        self.assertEqual(self.parsed,[])

    def test_config_resize_previews_then_restores_the_new_full_region(self):
        config=Properties();config.values={'film.width':932,'film.height':869,'path.pathdepth.total':25};queued=[]
        self.env['utils']=types.SimpleNamespace(calc_filmsize=lambda *args:(932,869))
        self.engine.exporter=types.SimpleNamespace(get_restart_config_props=lambda:config)
        self.worker.submit_config=queued.append
        self.env['_submit_config_update'](self.engine,self.worker,None,None)
        self.assertEqual(self.engine.last_viewport_size,(932,869))
        self.assertEqual(self.engine._film_scale,2)
        self.assertTrue(self.engine._dyn_res_active)
        self.assertEqual(queued[0].values,{'film.width':466,'film.height':434,'path.pathdepth.total':25})
        self.assertEqual(config.values,{'film.width':932,'film.height':869,'path.pathdepth.total':25})
        self.assertEqual(self.parsed,[])
        self.fb._width,self.fb._height=466,434
        self.fb._dlss_owner=(id(self.engine.session),self.worker.mutation_seq)
        self.clock=1.5;self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':932,'film.height':869})


class OrdinaryResize(unittest.TestCase):
    setUp = Interaction.setUp
    restore = Interaction.restore

    def configure(self, size, enabled=True, engine='RTPATHOCL', backend='METAL', target=None):
        self.engine._engine_type=engine
        self.worker._dlss_signature=(None,'disabled')
        self.engine._film_scale=1
        self.engine._dyn_res_active=False
        config=Properties();config.values={'film.width':size[0],'film.height':size[1],
                                          'path.pathdepth.total':25,'renderengine.type':target or engine}
        queued=[]
        self.env['utils']=types.SimpleNamespace(calc_filmsize=lambda *args:size,
            get_addon_preferences=lambda context:types.SimpleNamespace(gpu_backend=backend))
        self.engine.exporter=types.SimpleNamespace(get_restart_config_props=lambda:config)
        self.worker.submit_config=queued.append
        scene=types.SimpleNamespace(superluxcore=types.SimpleNamespace(
            viewport=types.SimpleNamespace(reduce_resolution_on_edit=enabled)))
        self.env['_submit_config_update'](self.engine,self.worker,scene,None)
        return config,queued

    def test_large_metal_resize_previews_and_restores_exact_latest_full_film(self):
        original,queued=self.configure((3733,2310))
        self.assertEqual(queued[0].values,{'film.width':1866,'film.height':1155,
                                         'path.pathdepth.total':25,'renderengine.type':'RTPATHOCL'})
        self.assertEqual(original.values,{'film.width':3733,'film.height':2310,
                                         'path.pathdepth.total':25,'renderengine.type':'RTPATHOCL'})
        self.assertEqual(self.engine._film_scale,2)
        self.assertTrue(self.engine._dyn_res_active)
        self.clock=1.5;self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':3733,'film.height':2310})
        self.assertFalse(self.engine._dyn_res_active)

    def test_disabled_preview_small_view_and_cpu_keep_full_exported_dimensions(self):
        for size,enabled,engine in [((3733,2310),False,'RTPATHOCL'),
                                    ((1280,720),True,'RTPATHOCL'),
                                    ((3733,2310),True,'RTPATHCPU'),
                                    ((3733,2310),True,'PATHOCL')]:
            self.setUp()
            original,queued=self.configure(size,enabled,engine)
            self.assertIs(queued[0],original)
            self.assertEqual(self.parsed,[])
            self.assertFalse(self.engine._dyn_res_active)

    def test_engine_switches_do_not_temporarily_resize_cpu_or_classic_targets(self):
        for target in ('RTPATHCPU','PATHCPU','PATHOCL','BIDIRCPU'):
            self.setUp()
            original,queued=self.configure((3733,2310),target=target)
            self.assertIs(queued[0],original)
            self.assertFalse(self.engine._dyn_res_active)

    def test_nonresize_quality_config_keeps_full_physical_input(self):
        self.engine.last_viewport_size=(3733,2310)
        original,queued=self.configure((3733,2310))
        self.assertIs(queued[0],original)
        self.assertFalse(self.engine._dyn_res_active)

    def test_nonmetal_backends_do_not_enter_an_unverified_resize_path(self):
        for backend in ('CUDA','OPENCL','VULKAN'):
            self.setUp()
            original,queued=self.configure((3733,2310),backend=backend)
            self.assertIs(queued[0],original)
            self.assertFalse(self.engine._dyn_res_active)

    def test_burst_restores_latest_region_and_keeps_exported_quality_fields(self):
        self.configure((3733,2310))
        self.clock=1.2
        original,queued=self.configure((3623,2311))
        self.assertEqual(queued[0].values,{'film.width':1811,'film.height':1155,
                                         'path.pathdepth.total':25,'renderengine.type':'RTPATHOCL'})
        self.assertEqual(self.engine.last_viewport_size,(3623,2311))
        self.clock=1.5;self.restore();self.assertEqual(self.parsed,[])
        self.clock=1.7;self.restore()
        self.assertEqual(self.parsed[0].values,{'film.width':3623,'film.height':2311})
        self.assertEqual(original.values['path.pathdepth.total'],25)


class CoherentCUDAResize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('dlss_resize_fakes',ROOT/'dev-tools/async_worker_unit_test.py')
        cls.fake=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.fake)
        cls.fake.FakeProperty.GetBool=lambda prop:bool(prop.Get())
        cls.fake.FakeProperty.__str__=lambda prop:repr((prop.name,prop.values))

    def test_only_coherent_cuda_dimension_edits_preserve_the_session(self):
        f=self.fake
        f.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:f.FakeProperties('opencl.device.0.type')<<('CUDA_GPU',)
        for coherent in (False,True):
            worker=f.worker_mod.SessionWorker()
            try:
                def config(width):
                    return f.FakeProperties('renderengine.type','film.width','film.height',
                        'rtpath.denoisingframes.enable','opencl.devices.select')<<('RTPATHOCL',width,48,coherent,'1')
                worker.submit_start(f.FakeScene(),config(64))
                self.assertTrue(f.wait_until(lambda:worker.session is not None))
                session=worker.session;sequence=worker.mutation_seq
                worker.submit_config(config(96))
                self.assertTrue(f.wait_until(lambda:worker.mutation_seq>sequence and not worker._lifecycle_busy))
                self.assertEqual(worker.session is session,coherent)
                self.assertEqual('Stop' in session.log,not coherent)
            finally:
                worker.shutdown();worker._thread.join(3)
                self.assertFalse(worker._thread.is_alive())


if __name__=='__main__': unittest.main(verbosity=2)
