"""Bounded streaming ownership, backpressure and stale-edit cancellation."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest

import numpy as np

root = Path(__file__).parents[1]
package = types.ModuleType('stream_fixture');package.__path__ = [str(root/'engine')]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location('history_fixture', Path(__file__).with_name('dlss_renderer_history_test.py'))
history = importlib.util.module_from_spec(spec);spec.loader.exec_module(history)
from stream_fixture.dlss_stream import DLSSFrameWorker


def wait(predicate):
    end = time.monotonic()+3
    while time.monotonic() < end:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('Worker deadline')


class Session:
    def __init__(self):self.packet = None
    def GetDenoisingFrame(self, after, timeout):
        assert timeout == 0
        p = self.packet
        return p if p is not None and p['frame_id'] > after else None


class Backend:
    def __init__(self):
        self.entered = threading.Event();self.release = threading.Event()
        self.release.set();self.ids=[];self.closed=threading.Event();self.thread_ids=[]
    def process(self, frame):
        self.thread_ids.append(threading.get_ident());self.ids.append(frame.frame_id)
        self.entered.set()
        assert self.release.wait(3), 'Fake SDK deadline'
        return frame.color.copy()
    def close(self):
        self.thread_ids.append(threading.get_ident());self.closed.set()


class Stream(unittest.TestCase):
    def setUp(self):
        self.lock=threading.Lock();self.session=Session();self.sequence=1
        self.backends=[];self.factories=[]
        def factory():
            self.factories.append(threading.get_ident())
            backend=Backend();self.backends.append(backend);return backend
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,factory)
    def tearDown(self):
        for b in self.backends:b.release.set()
        self.worker.shutdown();self.assertTrue(self.worker.join(3))
        self.assertTrue(all(b.closed.is_set() for b in self.backends))
    def result(self):return self.worker.take(self.session,self.sequence)
    def test_sr_target_is_forwarded_and_source_dimensions_are_retained(self):
        class Upscaler(Backend):
            def process(backend,frame):
                self.assertEqual(frame.output_size,(64,64))
                return np.repeat(np.repeat(super(Upscaler,backend).process(frame),2,axis=0),2,axis=1)
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,
            lambda:Upscaler(),output_size=(64,64))
        self.session.packet=history.packet();self.worker.start()
        results=[];wait(lambda:(results.append(self.result()) or results[-1] is not None))
        self.assertEqual(results[-1].source_size,(32,32))
        self.assertEqual(results[-1].pixels.shape,(64,64,4))
    def test_latest_only_and_owned_backend_thread(self):
        self.session.packet=history.packet();self.worker.start()
        wait(lambda:self.backends and self.backends[0].ids==[1])
        first=[]
        wait(lambda:(first.append(self.result()) or first[-1] is not None))
        self.assertEqual(first[-1].frame_id,1)
        b=self.backends[0];b.entered.clear();b.release.clear()
        self.session.packet=history.packet(2);self.assertTrue(b.entered.wait(3))
        # Eight intermediate frames are never queued by this consumer.
        self.session.packet=history.packet(10);b.release.set()
        wait(lambda:b.ids==[1,2,10])
        latest=[]
        wait(lambda:(latest.append(self.result()) or latest[-1] is not None and latest[-1].frame_id==10))
        self.assertIsNone(self.result())
        self.worker.shutdown();self.assertTrue(self.worker.join(3))
        self.assertEqual(set(b.thread_ids),set(self.factories))
        self.assertNotEqual(self.factories[0],threading.get_ident())
    def test_edit_discards_inflight_result_without_holding_session_lock(self):
        self.session.packet=history.packet();self.worker.start()
        wait(lambda:self.backends and self.backends[0].ids==[1])
        wait(lambda:self.result() is not None)
        b=self.backends[0];b.entered.clear();b.release.clear()
        self.session.packet=history.packet(2);self.assertTrue(b.entered.wait(3))
        self.assertTrue(self.lock.acquire(timeout=.1),'SDK evaluation held the session/edit lock')
        try:self.sequence+=1
        finally:self.lock.release()
        b.release.set();time.sleep(.04)
        self.assertIsNone(self.result(),'Pre-edit result was published')
        self.session.packet=history.packet(11,x=1)
        wait(lambda:self.result() is not None)
    def test_stop_drops_pending_pixels_and_releases_backend(self):
        self.session.packet=history.packet();self.worker.start()
        wait(lambda:self.backends and self.backends[0].ids==[1])
        b=self.backends[0];b.entered.clear();b.release.clear()
        self.session.packet=history.packet(2);self.assertTrue(b.entered.wait(3))
        start=time.monotonic();self.worker.shutdown()
        self.assertLess(time.monotonic()-start,.1)
        self.assertFalse(self.worker.join(.01))
        self.assertIsNone(self.result())
        b.release.set();self.assertTrue(self.worker.join(3));self.assertTrue(b.closed.is_set())

    def test_stop_can_finish_while_session_edit_still_owns_lock(self):
        self.session.packet=history.packet();self.worker.start()
        wait(lambda:self.result() is not None)
        b=self.backends[0];b.entered.clear();b.release.clear()
        self.session.packet=history.packet(2);self.assertTrue(b.entered.wait(3))
        self.assertTrue(self.lock.acquire(timeout=.1))
        try:
            # The session owner can still be draining an edit/Stop when the
            # SDK returns. Teardown must not wait for that unrelated lock.
            self.sequence+=1;self.worker.shutdown();b.release.set()
            self.assertTrue(self.worker.join(.5), 'SDK worker waited for the session edit lock')
            self.assertTrue(b.closed.is_set())
            self.assertIsNone(self.result())
        finally:self.lock.release()

    def test_read_lock_does_not_drop_the_only_completed_frame(self):
        entered=threading.Event();release=threading.Event();returned=threading.Event()
        class Postprocessor:
            def process(self, packet, pixels, reset=False):
                entered.set()
                assert release.wait(3), 'Postprocessor deadline'
                returned.set()
                return pixels
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,
                                    self.worker._backend_factory,Postprocessor)
        self.session.packet=history.packet();self.worker.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.lock:
                release.set();self.assertTrue(returned.wait(3))
                # Simulate an ordinary film reader owning the session lock
                # after SDK/postprocessing completion, with no new input frame.
                time.sleep(.04)
            results=[]
            wait(lambda:(results.append(self.result()) or results[-1] is not None))
            self.assertEqual(results[-1].frame_id,1)
            np.testing.assert_array_equal(results[-1].pixels,self.session.packet['color'])
            self.assertEqual(self.backends[0].ids,[1], 'Completed frame was evaluated twice')
        finally:release.set()

    def test_edit_while_publication_waits_discards_completed_pixels(self):
        entered=threading.Event();release=threading.Event();returned=threading.Event()
        class Postprocessor:
            def process(self, packet, pixels, reset=False):
                entered.set()
                assert release.wait(3), 'Postprocessor deadline'
                returned.set()
                return pixels
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,
                                    self.worker._backend_factory,Postprocessor)
        self.session.packet=history.packet();self.worker.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.lock:
                release.set();self.assertTrue(returned.wait(3));time.sleep(.04)
                self.sequence+=1
            time.sleep(.04)
            self.assertIsNone(self.result(),'Completed pre-edit pixels escaped the publication check')
            self.session.packet=history.packet(2,epoch=2)
            results=[]
            wait(lambda:(results.append(self.result()) or results[-1] is not None))
            self.assertEqual(results[-1].frame_id,2)
        finally:release.set()

    def test_shutdown_interrupts_waiting_publication(self):
        entered=threading.Event();release=threading.Event();returned=threading.Event()
        class Postprocessor:
            def process(self, packet, pixels, reset=False):
                entered.set()
                assert release.wait(3), 'Postprocessor deadline'
                returned.set()
                return pixels
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,
                                    self.worker._backend_factory,Postprocessor)
        self.session.packet=history.packet();self.worker.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.lock:
                release.set();self.assertTrue(returned.wait(3));time.sleep(.04)
                self.worker.shutdown()
                self.assertTrue(self.worker.join(.5),'Shutdown waited for the publication lock')
                self.assertTrue(self.backends[0].closed.is_set())
                self.assertIsNone(self.result())
        finally:release.set()
    def test_unavailable_backend_is_not_recreated_for_each_frame(self):
        attempts=[]
        def unavailable():
            attempts.append(1);raise RuntimeError('Runtime unavailable')
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,unavailable)
        self.session.packet=history.packet();self.worker.start()
        error=[]
        wait(lambda:(error.append(self.worker.pop_error()) or error[-1] is not None))
        self.assertEqual(error[-1],('RuntimeError','Runtime unavailable'))
        self.session.packet=history.packet(20);time.sleep(.04)
        self.assertEqual(attempts,[1]);self.assertIsNone(self.result())
        with self.lock:self.session=Session();self.session.packet=history.packet()
        wait(lambda:len(attempts)==2)

    def test_session_swap_closes_old_backend_and_resets_frame_ids(self):
        self.session.packet=history.packet(100);self.worker.start()
        wait(lambda:self.result() is not None)
        old=self.backends[0]
        with self.lock:
            self.session=Session();self.session.packet=history.packet(1);self.sequence+=1
        result=[]
        wait(lambda:(result.append(self.result()) or result[-1] is not None))
        self.assertEqual(result[-1].frame_id,1)
        self.assertTrue(old.closed.is_set());self.assertEqual(len(self.backends),2)

    def test_bad_guides_release_the_failed_lease_and_recover(self):
        import gc,weakref
        p=history.packet();p['guides'][0,0,7]=3
        guide=weakref.ref(p['guides']);self.session.packet=p;self.worker.start();del p
        errors=[]
        wait(lambda:(errors.append(self.worker.pop_error()) or errors[-1] is not None))
        self.assertEqual(errors[-1][0],'DLSSInputError')
        self.session.packet=None;gc.collect()
        # Error publication can wake the main thread before Python has left
        # its except suite. The lease must be released when that suite ends.
        wait(lambda:guide() is None)
        self.session.packet=history.packet(2)
        wait(lambda:self.result() is not None)

    def test_postprocessing_runs_outside_edit_lock_and_tags_display_stage(self):
        entered=threading.Event();release=threading.Event();calls=[]
        class Postprocessor:
            def process(self, packet, pixels, reset=False):
                calls.append((packet['frame_id'], reset, threading.get_ident()))
                entered.set()
                assert release.wait(3), 'Postprocessor deadline'
                return pixels*.25
        factory=self.worker._backend_factory
        self.worker=DLSSFrameWorker(lambda:(self.session,self.sequence),self.lock,
                                    factory,Postprocessor)
        self.session.packet=history.packet();self.worker.start()
        self.assertTrue(entered.wait(3))
        self.assertTrue(self.lock.acquire(timeout=.1),'Postprocessing held the session edit lock')
        try:self.sequence+=1
        finally:self.lock.release()
        release.set();time.sleep(.04)
        self.assertIsNone(self.result(),'Pre-edit postprocessed result was published')
        self.session.packet=history.packet(2,epoch=2)
        result=[]
        wait(lambda:(result.append(self.result()) or result[-1] is not None))
        self.assertTrue(result[-1].image_pipeline_applied)
        np.testing.assert_array_equal(result[-1].pixels,self.session.packet['color']*.25)
        self.assertTrue(calls[0][1] and calls[-1][1])
        self.assertNotEqual(calls[0][2],threading.get_ident())


if __name__=='__main__':unittest.main()
