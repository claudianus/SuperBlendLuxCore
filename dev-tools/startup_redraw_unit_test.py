"""Startup progress polling must not repaint idle work or retain closed engines."""
import ast
import gc
from pathlib import Path
from types import SimpleNamespace
import unittest
import weakref
source=Path(__file__).resolve().parents[1]/'engine/viewport.py'
node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_schedule_startup_redraw')
class Engine:pass
class StartupPolling(unittest.TestCase):
 def setUp(self):
  self.timers=[];self.draws=[];self.engine=Engine()
  self.engine.session_worker=SimpleNamespace(is_starting=True,phase='Building scene',progress=None)
  self.engine.tag_redraw=lambda:self.draws.append(True)
  self.env={'bpy':SimpleNamespace(app=SimpleNamespace(timers=SimpleNamespace(register=lambda fn,**kw:self.timers.append((fn,kw))))) }
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),self.env);self.schedule=self.env['_schedule_startup_redraw']
 def test_burst_and_idle_share_one_timer_only_progress_changes_draw(self):
  for _ in range(100):self.schedule(self.engine)
  self.assertEqual(len(self.timers),1);fn,options=self.timers[0];self.assertEqual(options,{'first_interval':.1})
  for _ in range(100):self.assertEqual(fn(),.1)
  self.assertFalse(self.draws);self.engine.session_worker.phase='Compiling kernels'
  self.assertEqual(fn(),.1);self.assertEqual(len(self.draws),1)
  self.engine.session_worker.progress=(1,2);self.assertEqual(fn(),.1);self.assertEqual(len(self.draws),2)
  self.assertEqual(fn(),.1);self.assertEqual(len(self.draws),2)
 def test_completed_or_stopped_start_does_not_rearm(self):
  self.schedule(self.engine);self.engine.session_worker.is_starting=False
  self.assertIsNone(self.timers[0][0]());self.assertFalse(self.engine._startup_redraw_pending);self.assertFalse(self.draws)
 def test_closed_engine_is_not_retained_by_repeating_timer(self):
  self.schedule(self.engine);ref=weakref.ref(self.engine);self.engine=None;gc.collect()
  self.assertIsNone(ref());self.assertIsNone(self.timers[0][0]())
 def test_deleted_rna_is_safe(self):
  class Dead(Engine):
   gone=False
   def __getattribute__(self,name):
    if name=='session_worker' and object.__getattribute__(self,'gone'):raise ReferenceError('RNA freed')
    return object.__getattribute__(self,name)
  e=Dead();e.session_worker=self.engine.session_worker;self.schedule(e);e.gone=True
  self.assertIsNone(self.timers[0][0]())
 def test_nonweak_legacy_wrapper_uses_only_one_short_callback(self):
  e=SimpleNamespace(session_worker=self.engine.session_worker,tag_redraw=lambda:self.draws.append(True))
  self.schedule(e);self.assertIsNone(self.timers[0][0]());self.assertFalse(e._startup_redraw_pending);self.assertFalse(self.draws)
if __name__=='__main__':unittest.main(verbosity=2)
