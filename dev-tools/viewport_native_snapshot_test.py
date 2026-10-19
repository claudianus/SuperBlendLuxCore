"""Native display snapshots retain applied-camera identity without black flashes."""
import importlib.util,time,threading,types,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('visual_fakes',ROOT/'dev-tools/review_viewport_visual_test.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
class Snapshots(unittest.TestCase):
 def setUp(self):
  self.env=base.load();self.fb=self.env['FrameBuffer'].__new__(self.env['FrameBuffer']);f=self.fb
  f._width=f._height=2;f._transparent=False;f._pending_reset=True;f._pending_reset_deadline=0;f._reset_mut_seq=1;f._shown_mut_seq=1;f._interactive_denoise=False;f._last_pixels=np.ones((2,2,3),np.float32);f._texture=object();f._snapshot_session=None;f._snapshot_epoch=0;f._last_snapshot=None;f._read_thread=None;f._output_type='RGB';f._last_update=0
 def meta(self,applied=2,requested=2,ready=True,token=11):return dict(ready=ready,copied=ready,camera_supported=True,requested=requested,applied=applied,session_token=token,metadata=None)
 def accept(self,meta,data=None,**kwargs):return self.fb._accept_pixels(np.zeros(12,np.float32) if data is None else data,2,2,mut_seq=2,snapshot=meta,**kwargs)
 def test_empty_film_never_replaces_held_texture_after_deadline(self):
  held=self.fb._last_pixels;self.assertFalse(self.accept(self.meta(ready=False)));self.assertIs(self.fb._last_pixels,held);self.assertTrue(self.fb._pending_reset)
 def test_force_cannot_publish_uncopied_native_buffer(self):self.assertFalse(self.accept(self.meta(ready=False),force=True))
 def test_genuine_black_camera_frame_is_accepted(self):
  self.assertTrue(self.accept(self.meta()));self.assertFalse(self.fb._last_pixels.any());self.assertFalse(self.fb._pending_reset)
 def test_earlier_completed_camera_refreshes_but_does_not_satisfy_reset(self):
  self.assertTrue(self.accept(self.meta(applied=2,requested=3),np.ones(12,np.float32)));self.assertTrue(self.fb._pending_reset);self.assertEqual(self.fb._last_snapshot['applied'],2)
  self.assertTrue(self.accept(self.meta(applied=3,requested=3)));self.assertFalse(self.fb._pending_reset)
 def test_camera_epoch_cannot_move_backwards_within_session(self):
  self.assertTrue(self.accept(self.meta(applied=3,requested=3)));self.assertFalse(self.accept(self.meta(applied=2,requested=3)))
 def test_new_session_can_restart_camera_epoch(self):
  self.assertTrue(self.accept(self.meta(applied=9,requested=9)));self.assertTrue(self.accept(self.meta(applied=1,requested=1,token=12)))
 def test_legacy_without_native_snapshot_retains_existing_path(self):self.assertTrue(self.accept(None,np.ones(12,np.float32)))
 def test_async_fetch_carries_native_identity_without_UI_native_calls(self):
  lock=threading.Lock();worker=types.SimpleNamespace(session_lock=lock,mutation_seq=2);calls=[]
  values={'snapshot.width':2,'snapshot.height':2,'snapshot.ready':True,'snapshot.copied':True,'snapshot.camera.supported':True,'snapshot.camera.requested':3,'snapshot.camera.applied':2}
  class Film:
   def GetWidth(self):return 2
   def GetHeight(self):return 2
   def GetOutputFloatSnapshot(self,typ,data,index,execute):
    assert lock.locked();calls.append(threading.current_thread().name);data[:]=.5
    def get(key):
     v=values[key];return types.SimpleNamespace(GetInt=lambda:v,GetBool=lambda:v,GetUnsignedLongLong=lambda:v)
    return types.SimpleNamespace(Get=get)
  session=types.SimpleNamespace(GetFilm=lambda:Film(),UpdateStats=lambda:None);engine=types.SimpleNamespace(session=session,session_worker=worker)
  self.assertTrue(self.fb.start_async_update(session,engine));thread=self.fb._read_thread;thread.join(2);self.assertFalse(thread.is_alive());self.assertTrue(self.fb.consume_async_update(session,engine));self.assertEqual(calls,['SuperLuxCoreViewportReadback']);self.assertEqual(self.fb._last_snapshot['applied'],2);self.assertTrue(self.fb._pending_reset)
 def test_force_with_owned_snapshot_keeps_epoch_metadata(self):
  self.assertTrue(self.accept(self.meta(),force=True));self.assertEqual(self.fb._last_snapshot['applied'],2)
if __name__=='__main__':unittest.main(verbosity=2)
