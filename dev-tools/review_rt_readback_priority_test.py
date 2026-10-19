"""A GPU runtime override must not queue behind a film read; real edits stay guarded."""
import importlib.util
import os
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('priority_fakes', ROOT/'dev-tools/async_worker_unit_test.py')
fake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fake)
fake.FakeProperty.__str__ = lambda prop: repr((prop.name, prop.values))
fake.FakeProperty.GetBool = lambda prop: bool(prop.Get())
fake.fake_pysuperluxcore.GetOpenCLDeviceDescs = lambda: fake.FakeProperties('opencl.device.0.type') << ('METAL_GPU',)
fake.fake_pysuperluxcore.RT_FILM_RESOLUTION_POLICY_VERSION = 1
if os.environ.get('SLC_WORKER_SOURCE'):
    fake.worker_mod = fake.load('priority_baseline', os.environ['SLC_WORKER_SOURCE'])


def props(engine='RTPATHOCL'):
    return fake.FakeProperties('renderengine.type', 'film.width', 'film.height',
                               'opencl.devices.select') << (engine, 128, 72, '1')


class ReadbackPriority(unittest.TestCase):
    def start(self, engine='RTPATHOCL'):
        worker = fake.worker_mod.SessionWorker()
        self.addCleanup(self.stop, worker)
        worker.submit_start(fake.FakeScene(), props(engine))
        self.assertTrue(fake.wait_until(lambda: worker.session is not None))
        return worker, worker.session

    def stop(self, worker):
        worker.shutdown()
        worker._thread.join(3)
        self.assertFalse(worker._thread.is_alive())

    def config_done(self, worker, config):
        done = threading.Event()
        original = worker._execute
        def execute(job):
            try:
                return original(job)
            finally:
                if job[0] == 'config':
                    done.set()
        worker._execute = execute
        worker.submit_config(config)
        self.assertTrue(done.wait(1), 'Config job did not finish')

    def test_gpu_override_and_restore_advance_while_read_holds_lock(self):
        worker, session = self.start()
        called = threading.Event()
        values = []
        def reduction(value):
            values.append(value)
            called.set()
        session.SetRuntimeResolutionReduction = reduction
        generation = worker.mutation_seq
        with worker.session_lock:
            for value in (4, 0):
                called.clear()
                worker.submit_resolution_reduction(value)
                self.assertTrue(called.wait(.5), 'GPU atomic override blocked behind readback')
        self.assertEqual(values, [4, 0])
        self.assertEqual(worker.mutation_seq, generation)
        self.assertIs(worker.session, session)
        self.assertEqual(session.log, ['Start'])

    def test_cpu_sampler_update_still_waits_for_read_lock(self):
        worker, session = self.start('RTPATHCPU')
        called = threading.Event()
        session.SetRuntimeResolutionReduction = lambda value: called.set()
        with worker.session_lock:
            worker.submit_resolution_reduction(4)
            self.assertFalse(called.wait(.05), 'CPU sampler update lost its lock')
        self.assertTrue(called.wait(1))
        self.assertEqual(session.log, ['Start'])

    def test_identical_gpu_config_preserves_frame_generation_and_pause(self):
        worker, session = self.start()
        session.paused = True
        generation = worker.mutation_seq
        self.config_done(worker, props())
        self.assertIs(worker.session, session)
        self.assertEqual(worker.mutation_seq, generation)
        self.assertTrue(session.paused)
        self.assertEqual(session.log, ['Start'])

    def test_identical_exported_config_restores_a_partially_resized_live_film(self):
        worker, session = self.start()
        live = [128, 72]
        original = session.Parse
        def parse(config):
            original(config)
            for axis, name in enumerate(('film.width', 'film.height')):
                if config.IsDefined(name):
                    live[axis] = config.Get(name).Get()
        session.Parse = parse
        preview = fake.FakeProperties('film.width', 'film.height') << (64, 36)
        worker._do_parse(preview)
        generation = worker.mutation_seq
        self.assertEqual(live, [64, 36])
        self.config_done(worker, props())
        self.assertEqual(live, [128, 72])
        self.assertEqual(worker.mutation_seq, generation + 1)
        self.assertEqual(session.log, ['Start', 'Parse', 'Parse'])

    def test_changed_gpu_config_still_waits_and_invalidates_old_frame(self):
        worker, session = self.start()
        done = threading.Event()
        original = session.Parse
        def parse(config):
            original(config)
            done.set()
        session.Parse = parse
        generation = worker.mutation_seq
        config = props()
        config.Set(fake.FakeProperty('film.width', [256]))
        with worker.session_lock:
            worker.submit_config(config)
            self.assertFalse(done.wait(.05))
        self.assertTrue(done.wait(1))
        self.assertTrue(fake.wait_until(lambda: worker.mutation_seq > generation))
        self.assertEqual(session.log, ['Start', 'Parse'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
