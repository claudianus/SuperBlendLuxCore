"""Artist-visible denoising waits for camera samples and never blocks the UI."""
import ast,os,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS

source=Path(os.environ.get('SLC_READINESS_SOURCE',str(Path(__file__).resolve().parents[1]/'draw/viewport.py')))
cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='FrameBuffer')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='interactive_denoise_tick')
env={'time':time,'_session_lock':lambda e:e.lock}
exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),env)
class Property:
 def __init__(self,value):self.value=value
 def GetInt(self):return self.value
class Stats:
 def __init__(self,eye,total):self.eye,self.total=eye,total
 def Get(self,name):
  if name=='stats.renderengine.pass.eye':
   if self.eye is None:raise RuntimeError('No eye statistics yet')
   return Property(self.eye)
  if name=='stats.renderengine.pass':return Property(self.total)
  raise AssertionError(name)
class Readiness(unittest.TestCase):
 def fixture(self,eye,total):
  launched=[];fb=NS(_pending_reset=False,_interactive_denoise=False,_denoiser_thread=None,
    _denoise_box=None,_last_interactive_denoise=0.,INTERACTIVE_DENOISE_INTERVAL=1.,
    consume_denoise_result=lambda *a,**k:False,is_denoiser_active=lambda:False,
    start_denoiser=lambda e:launched.append(True))
  engine=NS(lock=threading.Lock(),session=NS(GetStats=lambda:Stats(eye,total)))
  return fb,engine,launched
 def tick(self,fb,e,min_samples=1):return env['interactive_denoise_tick'](fb,e,min_samples)
 def test_many_light_samples_do_not_denoise_an_unsampled_camera(self):
  fb,e,started=self.fixture(0,500);self.assertFalse(self.tick(fb,e));self.assertEqual(started,[])
 def test_user_threshold_counts_camera_samples_only(self):
  fb,e,started=self.fixture(3,500);self.assertFalse(self.tick(fb,e,4));self.assertEqual(started,[])
  e.session.GetStats=lambda:Stats(4,500);self.assertFalse(self.tick(fb,e,4));self.assertEqual(started,[True])
 def test_missing_camera_statistics_do_not_fall_back_to_light_work(self):
  fb,e,started=self.fixture(None,500);self.assertFalse(self.tick(fb,e));self.assertEqual(started,[])
 def test_busy_session_returns_without_waiting_or_native_read(self):
  fb,e,started=self.fixture(4,500);called=[];e.session.GetStats=lambda:called.append(True)
  e.lock.acquire()
  try:
   before=time.monotonic();self.assertFalse(self.tick(fb,e));self.assertLess(time.monotonic()-before,.05)
  finally:e.lock.release()
  self.assertEqual(called,[]);self.assertEqual(started,[])
 def test_first_eligible_denoise_keeps_raw_until_result_arrives(self):
  fb,e,started=self.fixture(1,1);self.assertFalse(self.tick(fb,e));self.assertEqual(started,[True])
  fb.consume_denoise_result=lambda *a,**k:True;self.assertTrue(self.tick(fb,e));self.assertTrue(fb._interactive_denoise)
 def test_pending_edit_does_not_launch_stale_work(self):
  fb,e,started=self.fixture(10,500);fb._pending_reset=True;self.assertFalse(self.tick(fb,e));self.assertEqual(started,[])
if __name__=='__main__':unittest.main(verbosity=2)
