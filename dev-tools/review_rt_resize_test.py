"""RT dimension-only config edits must resize the live session, not rebuild it."""
import importlib.util
import ast
import os
from pathlib import Path
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resize_fakes', ROOT/'dev-tools/async_worker_unit_test.py')
fake = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake)
fake.FakeProperty.__str__ = lambda prop: repr((prop.name, prop.values))
fake.FakeProperty.GetBool = lambda prop: bool(prop.Get())
if os.environ.get('SLC_WORKER_SOURCE'):
    fake.worker_mod = fake.load('resize_baseline', os.environ['SLC_WORKER_SOURCE'])
Worker = fake.worker_mod.SessionWorker


def props(engine='RTPATHOCL', width=64, height=48, gain=1):
    return fake.FakeProperties('renderengine.type', 'film.width', 'film.height',
                               'film.imagepipelines.0.0.value', 'opencl.devices.select') << (engine, width, height, gain, '1')


class ResizeTests(unittest.TestCase):
    def setUp(self):
        fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:fake.FakeProperties('opencl.device.0.type') << ('METAL_GPU',)
        fake.fake_pysuperluxcore.RT_FILM_RESOLUTION_POLICY_VERSION = 1

    def start(self, config):
        worker = Worker(); self.addCleanup(self.stop, worker)
        worker.submit_start(fake.FakeScene(), config)
        self.assertTrue(fake.wait_until(lambda: worker.session is not None))
        return worker, worker.session

    def stop(self, worker):
        worker.shutdown(); worker._thread.join(3)
        self.assertFalse(worker._thread.is_alive())

    def apply(self, worker, config):
        seq = worker.mutation_seq
        worker.submit_config(config)
        self.assertTrue(fake.wait_until(lambda: worker.mutation_seq > seq and not worker._lifecycle_busy))

    def test_rt_size_only_keeps_session_and_acceleration_owner(self):
        for engine in ('RTPATHOCL',):
            with self.subTest(engine=engine):
                worker, session = self.start(props(engine))
                scene = worker.scene
                self.apply(worker, props(engine, width=128, height=80))
                self.assertIs(worker.session, session)
                self.assertIs(worker.scene, scene)
                self.assertEqual(session.log, ['Start', 'Parse'])
                self.assertEqual(worker._config_props.Get('film.width').Get(), 128)

    def test_paused_resize_resumes_before_parse(self):
        worker, session = self.start(props())
        session.paused = True
        self.apply(worker, props(width=96))
        self.assertIs(worker.session, session)
        self.assertEqual(session.log, ['Start', 'Resume', 'Parse'])

    def test_coalesced_identical_rt_config_never_restarts(self):
        worker, session = self.start(props())
        generation = worker.mutation_seq
        worker._do_config(props())
        self.assertIs(worker.session, session)
        self.assertEqual(worker.mutation_seq, generation)
        self.assertEqual(session.log, ['Start'])

    def test_rt_policy_boundary_resize_keeps_session_and_forwards_policy(self):
        def policy(width, reduction, preview, step):
            result = props(width=width)
            for name, value in [('rtpath.resolutionreduction', reduction),
                                ('rtpath.resolutionreduction.preview', preview),
                                ('rtpath.resolutionreduction.preview.step', step)]:
                result.Set(fake.FakeProperty(name, [value]))
            return result
        worker, session = self.start(policy(64, 8, 16, 2))
        parsed = []
        original = session.Parse
        session.Parse = lambda value: (parsed.append(value), original(value))[-1]
        for width, reduction, preview, step in [(128, 16, 32, 1), (64, 8, 16, 3),
                                                 (64, 4, 8, 2)]:
            self.apply(worker, policy(width, reduction, preview, step))
            self.assertIs(worker.session, session)
            self.assertNotIn('Stop', session.log)
            self.assertEqual(parsed[-1].Get('film.width').Get(), width)
            self.assertEqual(parsed[-1].Get('rtpath.resolutionreduction').Get(), reduction)
            self.assertEqual(parsed[-1].Get('rtpath.resolutionreduction.preview').Get(), preview)
            self.assertEqual(parsed[-1].Get('rtpath.resolutionreduction.preview.step').Get(), step)

    def test_rt_policy_update_does_not_hide_other_config_changes(self):
        def policy(gain):
            value = props(width=128, gain=gain)
            value.Set(fake.FakeProperty('rtpath.resolutionreduction', [16]))
            return value
        worker, session = self.start(policy(1))
        self.apply(worker, policy(2))
        self.assertIsNot(worker.session, session)
        self.assertIn('Stop', session.log)

    def test_old_native_policy_api_retains_restart(self):
        fake.fake_pysuperluxcore.RT_FILM_RESOLUTION_POLICY_VERSION = 0
        previous, current = props(), props(width=128)
        previous.Set(fake.FakeProperty('rtpath.resolutionreduction', [8]))
        current.Set(fake.FakeProperty('rtpath.resolutionreduction', [16]))
        worker, session = self.start(previous)
        self.apply(worker, current)
        self.assertIsNot(worker.session, session)
        self.assertIn('Stop', session.log)

    def test_nonfilm_config_changes_and_non_rt_keep_restart(self):
        for engine, change in [('RTPATHCPU', {'gain': 2}), ('RTPATHOCL', {'gain': 2}),
                               ('RTPATHCPU', {'width': 128}), ('PATHCPU', {'width': 128}), ('PATHOCL', {'width': 128})]:
            with self.subTest(engine=engine, change=change):
                worker, session = self.start(props(engine))
                self.apply(worker, props(engine, **change))
                self.assertIsNot(worker.session, session)
                self.assertIn('Stop', session.log)

    def test_unvalidated_gpu_backend_keeps_restart(self):
        fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:fake.FakeProperties('opencl.device.0.type') << ('OPENCL_GPU',)
        worker, session = self.start(props())
        self.apply(worker, props(width=128))
        self.assertIsNot(worker.session, session)

    def test_new_config_property_is_not_silently_dropped(self):
        worker, session = self.start(props())
        new = props(width=128); new.Set(fake.FakeProperty('film.subregion', [0, 63, 0, 47]))
        self.apply(worker, new)
        self.assertIsNot(worker.session, session)
        self.assertEqual(worker._config_props.Get('film.subregion').values, [0, 63, 0, 47])

    def test_failed_parse_drops_unusable_session(self):
        worker, session = self.start(props()); session.fail_parse = True
        worker.submit_config(props(width=128))
        self.assertTrue(fake.wait_until(lambda: worker._error is not None))
        self.assertTrue(fake.wait_until(lambda: worker.session is None))
        self.assertIn('Stop', session.log)

    def test_scale_restore_tracks_latest_config_size_in_both_ui_paths(self):
        path=Path(os.environ.get('SLC_VIEWPORT_SOURCE',ROOT/'engine/viewport.py'))
        nodes=ast.parse(path.read_text()).body
        functions={n.name:n for n in nodes if isinstance(n,ast.FunctionDef)}
        self.assertIn('_submit_config_update',functions)
        for name in ('view_update','view_draw'):
            calls=[n for n in ast.walk(functions[name]) if isinstance(n,ast.Call)]
            self.assertTrue(any(isinstance(n.func,ast.Name) and n.func.id=='_submit_config_update' for n in calls))
            self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr=='submit_config' for n in calls))
        env={'utils':types.SimpleNamespace(calc_filmsize=lambda *args:(640,400)),
             '_dlss_interaction_active':lambda engine:False,
             '_dlss_render_size':lambda engine,w,h:(w,h),
             'pysuperluxcore':types.SimpleNamespace(Properties=fake.FakeProperties,
                 Property=lambda name,value:fake.FakeProperty(name,[value]))}
        chosen=[functions[n] for n in ('_submit_config_update','_submit_film_scale')]
        exec(compile(ast.Module(body=chosen,type_ignores=[]),str(path),'exec'),env)
        config=props(width=640,height=400);queued=[];parsed=[]
        engine=types.SimpleNamespace(last_viewport_size=(1920,1080),_film_scale=2,
            exporter=types.SimpleNamespace(get_restart_config_props=lambda:config))
        worker=types.SimpleNamespace(submit_config=queued.append,submit_parse=parsed.append)
        env['_submit_config_update'](engine,worker,None,None)
        env['_submit_film_scale'](engine,worker,1)
        self.assertEqual(engine.last_viewport_size,(640,400))
        self.assertIs(queued[0],config)
        self.assertEqual(parsed[0].Get('film.width').Get(),640)
        self.assertEqual(parsed[0].Get('film.height').Get(),400)


if __name__ == '__main__': unittest.main(verbosity=2)
