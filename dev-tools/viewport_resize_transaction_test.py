"""A resized raster and its camera must become visible as one worker mutation.

Exercises production submission/worker methods with deterministic scheduling.
Actual camera projection and heavy-scene delivery are separate native/UI gates.
"""
import ast
from enum import IntFlag
import importlib.util
import inspect
import os
from pathlib import Path
import threading
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

fake=load('transaction_fakes',ROOT/'dev-tools/async_worker_unit_test.py')
fake.FakeProperty.__str__=lambda p:repr((p.name,p.values))
fake.FakeProperty.GetBool=lambda p:bool(p.Get())
fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:fake.FakeProperties('opencl.device.0.type')<<('METAL_GPU',)
fake.fake_pysuperluxcore.RT_FILM_RESOLUTION_POLICY_VERSION=1
worker_source=Path(os.environ.get('SLC_TRANSACTION_WORKER',ROOT/'engine/session_worker.py'))
Worker=load('transaction_worker',worker_source).SessionWorker
vp_source=Path(os.environ.get('SLC_TRANSACTION_VIEWPORT',ROOT/'engine/viewport.py'))


def props(width=64):
 return fake.FakeProperties('renderengine.type','film.width','film.height','opencl.devices.select')<<('RTPATHOCL',width,48,'1')


def camera(token):return [('Parse',(fake.FakeProperties('scene.camera.token')<<(token,),),{})]


def submit_pair(worker,config,ops):
 if hasattr(worker,'submit_config_and_edit'):worker.submit_config_and_edit(config,ops)
 else:
  worker.submit_config(config);worker.submit_edit(ops)


class WorkerTransactions(unittest.TestCase):
 def start(self, config=None):
  worker=Worker();self.addCleanup(self.stop,worker)
  scene=fake.FakeScene();scene.camera_token=0;original=scene.Parse
  def parse(value):
   if value.IsDefined('scene.camera.token'):scene.camera_token=value.Get('scene.camera.token').Get()
   original(value)
  scene.Parse=parse
  worker.submit_start(scene,config if config is not None else props());self.assertTrue(fake.wait_until(lambda:worker.session is not None))
  return worker,scene,worker.session
 def stop(self,w):w.shutdown();w._thread.join(3);self.assertFalse(w._thread.is_alive())

 def test_reader_cannot_observe_new_raster_with_old_camera(self):
  w,scene,s=self.start();seq=w.mutation_seq
  entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
  snapshots=[];original=s.Parse
  def parse(value):
   snapshots.append((value.Get('film.width').Get(),scene.camera_token))
   entered.set();assert release.wait(2);original(value)
  s.Parse=parse
  submit_pair(w,props(128),camera(7))
  self.assertTrue(entered.wait(2))
  acquired=w.session_lock.acquire(blocking=False)
  if acquired:w.session_lock.release()
  self.assertFalse(acquired,'Reader acquired a partially applied transaction')
  release.set()
  self.assertTrue(fake.wait_until(lambda:w.mutation_seq>seq and not w._lifecycle_busy))
  self.assertEqual(snapshots,[(128,7)],'Resized raster was prepared with the old camera')
  self.assertEqual(w.mutation_seq,seq+1,'One camera/raster update must publish one epoch')
  self.assertIs(w.session,s)
  self.assertEqual(scene.camera_token,7)

 def test_pending_batch_retains_all_scene_deltas_and_latest_plain_config(self):
  w,scene,s=self.start();seq=w.mutation_seq
  seen=[];original=scene.Parse
  def parse(value):
   if value.IsDefined('scene.camera.token'):seen.append(value.Get('scene.camera.token').Get())
   original(value)
  scene.Parse=parse
  with w._cond:
   submit_pair(w,props(128),camera(1));submit_pair(w,props(192),camera(2));w.submit_config(props(256))
  self.assertTrue(fake.wait_until(lambda:scene.camera_token==2 and not w._lifecycle_busy))
  self.assertEqual(w._config_props.Get('film.width').Get(),256)
  self.assertEqual(seen,[1,2])
  self.assertEqual(w.mutation_seq,seq+1)
  self.assertIs(w.session,s)

 def test_unchanged_dimensions_still_apply_camera_once(self):
  w,scene,s=self.start();seq=w.mutation_seq
  submit_pair(w,props(),camera(9))
  self.assertTrue(fake.wait_until(lambda:scene.camera_token==9))
  self.assertEqual(w.mutation_seq,seq+1)
  self.assertNotIn('Parse',s.log)

 def test_coherent_cuda_retains_session_and_one_camera_raster_epoch(self):
  original=fake.fake_pysuperluxcore.GetOpenCLDeviceDescs
  self.addCleanup(setattr,fake.fake_pysuperluxcore,'GetOpenCLDeviceDescs',original)
  fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:fake.FakeProperties('opencl.device.0.type')<<('CUDA_GPU',)
  previous=props();previous.Set(fake.FakeProperty('rtpath.denoisingframes.enable',[True]))
  current=props(128);current.Set(fake.FakeProperty('rtpath.denoisingframes.enable',[True]))
  w,scene,s=self.start(previous);seq=w.mutation_seq
  submit_pair(w,current,camera(13))
  self.assertTrue(fake.wait_until(lambda:scene.camera_token==13 and not w._lifecycle_busy))
  self.assertIs(w.session,s);self.assertNotIn('Stop',s.log)
  self.assertEqual(w.mutation_seq,seq+1)

 def test_full_restart_applies_camera_before_new_session_start(self):
  w,scene,s=self.start();config=props(128);config.Set(fake.FakeProperty('path.pathdepth.total',[9]))
  submit_pair(w,config,camera(4))
  self.assertTrue(fake.wait_until(lambda:w.session is not s and not w._lifecycle_busy))
  self.assertIn('Stop',s.log);self.assertEqual(scene.camera_token,4)
  self.assertEqual(w.session.config.props.Get('path.pathdepth.total').Get(),9)

 def test_scene_failure_invalidates_session_and_retires_worker_cleanly(self):
  w,scene,s=self.start()
  def fail():raise RuntimeError('injected camera delta failure')
  scene.Fail=fail
  submit_pair(w,props(128),[('Fail',(),{})])
  self.assertTrue(fake.wait_until(lambda:w._error is not None))
  self.assertTrue(fake.wait_until(lambda:w.session is None))
  self.assertIn('Stop',s.log);self.assertIsNone(w.scene)

 def test_pair_during_start_keeps_latest_config_and_camera_together(self):
  entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
  original=fake.fake_pysuperluxcore.RenderConfig
  class Blocking(original):
   def __init__(self,*args):entered.set();assert release.wait(2);super().__init__(*args)
  fake.fake_pysuperluxcore.RenderConfig=Blocking
  self.addCleanup(setattr,fake.fake_pysuperluxcore,'RenderConfig',original)
  w=Worker();self.addCleanup(self.stop,w);self.addCleanup(release.set);scene=fake.FakeScene();seen=[]
  original_parse=scene.Parse
  def parse(value):
   if value.IsDefined('scene.camera.token'):seen.append(value.Get('scene.camera.token').Get())
   original_parse(value)
  scene.Parse=parse
  w.submit_start(scene,props());self.assertTrue(entered.wait(2))
  submit_pair(w,props(128),camera(11));w.submit_config(props(256));release.set()
  self.assertTrue(fake.wait_until(lambda:seen==[11] and not w._lifecycle_busy))
  self.assertEqual(w._config_props.Get('film.width').Get(),256)
  self.assertIsNone(w._pending_config)


class Change(IntFlag):
 CONFIG=1;CAMERA=2;MATERIAL=4;IMAGEPIPELINE=8;HALT=16
 REQUIRES_SCENE_EDIT=CAMERA|MATERIAL
 REQUIRES_SESSION_PARSE=IMAGEPIPELINE|HALT


class Submission(unittest.TestCase):
 def setUp(self):
  nodes=ast.parse(vp_source.read_text()).body
  selected=[n for n in nodes if isinstance(n,ast.FunctionDef) and n.name in ('_submit_config_update','_submit_jobs')]
  self.calls=[];self.jobs=[('edit',camera(42))]
  native=types.SimpleNamespace(Properties=fake.FakeProperties,
   Property=lambda name,value:fake.FakeProperty(name,[value]))
  self.env={'time':lambda:1.,'_DYN_RES_TAIL_S':.4,'pysuperluxcore':native,
   '_dlss_interaction_active':lambda e:False,'_interaction_film_scale':lambda e:1,
   '_submit_film_scale':lambda *a:None,'_dyn_res_value':lambda pixels:16,
   'FrameBuffer':types.SimpleNamespace(HOLD_LAST_FRAME_CAMERA_S=.3),
   'utils':types.SimpleNamespace(calc_filmsize=lambda *a:(128,48),get_addon_preferences=lambda *a:types.SimpleNamespace(gpu_backend='METAL')),
   'export':types.SimpleNamespace(Change=Change)}
  exec(compile(ast.Module(body=selected,type_ignores=[]),str(vp_source),'exec'),self.env)
  exporter=types.SimpleNamespace(get_restart_config_props=lambda:props(128),update=lambda *a:list(self.jobs))
  self.engine=types.SimpleNamespace(_engine_type='RTPATHOCL',last_viewport_size=(64,48),exporter=exporter)
  self.worker=types.SimpleNamespace(submit_config=lambda p:self.calls.append(('config',p)),
    submit_config_and_edit=lambda p,o:self.calls.append(('pair',p,list(o))),submit_edit=lambda o:self.calls.append(('edit',o)),
    submit_parse=lambda p:self.calls.append(('parse',p)),submit_resolution_reduction=lambda v:None)
  self.fb=types.SimpleNamespace(_width=64,_height=48,_pending_reset=True,_pending_reset_deadline=100,
   begin_reset=lambda *a,**kw:None,reset_denoiser=lambda:None)
  self.engine.framebuffer=self.fb
  self.scene=types.SimpleNamespace(superluxcore=types.SimpleNamespace(viewport=types.SimpleNamespace(reduce_resolution_on_edit=True)))

 def dispatch(self,changes):
  fn=self.env['_submit_config_update']
  if 'depsgraph' in inspect.signature(fn).parameters:
   return fn(self.engine,self.worker,self.scene,None,object(),changes)
  fn(self.engine,self.worker,self.scene,None)
  if changes&Change.CAMERA:
   self.fb.begin_reset(engine=self.engine)
   self.env['_submit_jobs'](self.engine,self.worker,self.fb,self.jobs,True)
  return False

 def test_resize_camera_is_not_deferred_by_its_own_config_reset(self):
  self.dispatch(Change.CONFIG|Change.CAMERA)
  immediate=[c for c in self.calls if c[0] in ('pair','edit')]
  self.assertEqual(len(immediate),1,'Resized-raster camera was paced behind its own pending reset')
  self.assertIsNone(getattr(self.engine,'_deferred_edit_jobs',None))

 def test_prior_independent_scene_and_parse_deltas_are_not_lost(self):
  old_parse=fake.FakeProperties('film.gamma')<<(2.2,)
  self.engine._deferred_edit_jobs=([('edit',camera(1)),('parse',old_parse)],False)
  self.dispatch(Change.CONFIG|Change.CAMERA)
  pairs=[c for c in self.calls if c[0]=='pair']
  self.assertEqual(len(pairs),1)
  self.assertEqual([op[1][0].Get('scene.camera.token').Get() for op in pairs[0][2]],[1,42])
  self.assertEqual(self.calls[-1],('parse',old_parse))

 def test_config_only_and_nonresize_camera_preserve_ordinary_path(self):
  self.dispatch(Change.CONFIG)
  self.assertEqual([c[0] for c in self.calls],['config'])
  self.calls.clear();self.engine.last_viewport_size=(128,48)
  self.dispatch(Change.CONFIG|Change.CAMERA)
  self.assertNotIn('pair',[c[0] for c in self.calls])

 def test_coherent_dlss_pair_keeps_dense_input(self):
  reductions=[]
  self.worker.submit_resolution_reduction=reductions.append
  self.env['_dlss_interaction_active']=lambda engine:True
  self.env['_dlss_render_size']=lambda engine,*size:size
  self.dispatch(Change.CONFIG|Change.CAMERA)
  self.assertEqual(reductions,[0],'Coherent DLSS input became sparse during resize')
  self.assertEqual(len([c for c in self.calls if c[0]=='pair']),1)


if __name__=='__main__':unittest.main(verbosity=2)
