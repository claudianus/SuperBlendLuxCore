"""Frame retirement must not leave owning native scenes/SDK capture in caches."""
import ast,gc,weakref
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
SOURCE=Path(__file__).resolve().parents[1]/'engine/final.py'
node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_close_final_resources')
env={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),env)
class Owned:pass
class Retirement(unittest.TestCase):
    def fixture(self,close_fault=False,stop_fault=False):
        events=[];scene=Owned();pipeline=Owned();refs=[weakref.ref(scene),weakref.ref(pipeline)]
        def close():
            events.append('close')
            if close_fault:raise RuntimeError('close failure')
        def stop():
            events.append('stop')
            if stop_fault:raise RuntimeError('stop failure')
        controller=NS(close=close,_source_scene=scene,pipeline=pipeline)
        engine=NS(final_dlss=controller,exporter=NS(final_dlss=controller),session=NS(IsStarted=lambda:True,Stop=stop))
        return engine,controller,events,refs
    def check(self,e,c,refs):
        gc.collect();self.assertIsNone(e.session);self.assertIsNone(e.final_dlss);self.assertIsNone(e.exporter.final_dlss)
        self.assertIsNone(c._source_scene);self.assertIsNone(c.pipeline);self.assertTrue(all(ref() is None for ref in refs))
    def test_normal_retirement_drops_scene_and_capture_even_if_controller_is_observed(self):
        e,c,events,refs=self.fixture();env['_close_final_resources'](e);self.check(e,c,refs);self.assertEqual(events,['close','stop'])
    def test_sdk_cleanup_failure_still_stops_session_and_releases_scene(self):
        e,c,events,refs=self.fixture(close_fault=True)
        with self.assertRaisesRegex(RuntimeError,'close failure'):env['_close_final_resources'](e)
        self.check(e,c,refs);self.assertEqual(events,['close','stop'])
    def test_session_stop_failure_still_detaches_owners(self):
        e,c,events,refs=self.fixture(stop_fault=True)
        with self.assertRaisesRegex(RuntimeError,'stop failure'):env['_close_final_resources'](e)
        self.check(e,c,refs)
    def test_non_dlss_session_and_repeated_retirement(self):
        events=[];e=NS(final_dlss=None,session=NS(IsStarted=lambda:True,Stop=lambda:events.append('stop')))
        env['_close_final_resources'](e);env['_close_final_resources'](e);self.assertIsNone(e.session);self.assertEqual(events,['stop'])
if __name__=='__main__':unittest.main(verbosity=2)
