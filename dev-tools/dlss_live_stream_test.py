"""Actual CUDA renderer -> asynchronous DLSS worker; no Blender/GL presentation."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import types

import numpy as np

here=Path(__file__).resolve();root=here.parents[1]
package=types.ModuleType('live_dlss_engine');package.__path__=[str(root/'engine')];sys.modules[package.__name__]=package
from live_dlss_engine.dlss import CUDADLSS
from live_dlss_engine.dlss_stream import DLSSFrameWorker
spec=importlib.util.spec_from_file_location('live_stream_fixture',here.with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--large',action='store_true')
parser.add_argument('--image-pipeline',action='store_true')
args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
s.Init();scene,_,_=m.fixture();width,height=(1280,720) if args.large else (96,64)
cfg=m.props(f'''
renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
film.width = {width}
film.height = {height}
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.tilesize = 128
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
path.pathdepth.total = 8
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
''')
desc=s.GetOpenCLDeviceDescs();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','CUDA_GPU')
mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'))
assert mask.count('1')==1,'This bounded interop test requires one selected GPU'
cfg.Set(s.Property('opencl.devices.select',mask))
if args.image_pipeline:
    cfg.Set(s.Property('rtpath.denoisingframes.imagepipeline.enable',True))
    cfg.Set(s.Property('film.imagepipelines.0.0.type','TONEMAP_LINEAR'))
    cfg.Set(s.Property('film.imagepipelines.0.0.scale',.5))
config=s.RenderConfig(cfg,scene);session=s.RenderSession(config)
class OwnerLock:
    def __init__(self):self.native=threading.Lock();self.owner=None
    def acquire(self,blocking=True):
        acquired=self.native.acquire(blocking)
        if acquired:self.owner=threading.get_ident()
        return acquired
    def release(self):self.owner=None;self.native.release()
    def __enter__(self):self.acquire();return self
    def __exit__(self,*_):self.release()
lock=OwnerLock();state=[session,1];backend_threads=[];closed=threading.Event();evaluating=threading.Event()
hold_after_evaluate=threading.Event();evaluation_finished=threading.Event();release_evaluate=threading.Event()
class Backend:
    def __init__(self):
        backend_threads.append(threading.get_ident())
        self.backend=CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SLC_DLSS_TEST_CACHE'],library=os.environ['SLC_DLSS_TEST_LIBRARY'])
    def process(self,frame):
        evaluating.set()
        try:
            pixels=self.backend.process(frame)
            if hold_after_evaluate.is_set():
                evaluation_finished.set()
                assert release_evaluate.wait(10), 'Post-SDK teardown barrier deadline'
            return pixels
        finally:evaluating.clear()
    def close(self):
        try:self.backend.close()
        finally:backend_threads.append(threading.get_ident());closed.set()
pipeline_checks=[]
class Postprocessor:
    def __init__(self):self.native=s.DenoisingImagePipeline()
    def process(self,packet,pixels,reset=False):
        assert lock.owner!=threading.get_ident(),'Native postprocessing acquired the session edit lock'
        result=self.native.process(packet,pixels,reset=reset)
        expected=pixels.copy();expected[:,:,:3]*=.5
        maximum=float(np.abs(result-expected).max())
        assert maximum==0,('Incorrect or repeated image-pipeline application',maximum)
        pipeline_checks.append({'frame_id':packet['frame_id'],'max_abs':maximum,'reset':reset})
        return result
notifications=[]
worker=DLSSFrameWorker(lambda:tuple(state),lock,Backend,
                       Postprocessor if args.image_pipeline else None,
                       lambda:notifications.append(threading.get_ident()));records=[]
def receive(w,h):
    end=time.monotonic()+30
    while time.monotonic()<end:
        error=worker.pop_error()
        if error:raise AssertionError(error)
        result=worker.take(*state)
        if result is None:time.sleep(.005);continue
        assert result.pixels.shape==(h,w,4) and np.isfinite(result.pixels).all()
        assert np.all(result.pixels[:,:,3]==1)
        assert result.image_pipeline_applied==args.image_pipeline
        assert not records or result.frame_id>records[-1]['frame_id']
        records.append({'frame_id':result.frame_id,'scene_epoch':result.scene_epoch,'mutation_sequence':result.mutation_sequence,'size':[w,h],
                        'image_pipeline_applied':result.image_pipeline_applied})
        if len(records) in (4,9):np.save(args.out/('static.npy' if len(records)==4 else 'orbit.npy'),result.pixels)
        print('stream frame',records[-1],flush=True)
        return result
    raise TimeoutError('No matching live DLSS result')
try:
    session.Start();worker.start()
    for _ in range(4):receive(width,height)
    for angle in np.linspace(-.08,.08,5):
        x,y=5*math.sin(angle),-5*math.cos(angle)
        with lock:
            session.BeginSceneEdit()
            scene.Parse(m.props(f'scene.camera.lookat.orig = {x} {y} 2.2\nscene.camera.lookat.target = 0 0.5 1.5\nscene.camera.up = 0 0 1\nscene.camera.fieldofview = 45'))
            session.EndSceneEdit();state[1]+=1
        receive(width,height)
    with lock:
        session.Parse(m.props('film.width = 97\nfilm.height = 65'));state[1]+=1
    receive(97,65)
    # Deterministically release a completed real SDK evaluation while the
    # session owner still holds its edit/Stop lock. The worker must close its
    # backend without waiting to publish an obsolete image through that lock.
    hold_after_evaluate.set()
    assert evaluation_finished.wait(5), 'No completed real SDK evaluation at teardown barrier'
    in_flight=evaluating.is_set()
    with lock:
        state[0]=None;state[1]+=1
        start=time.monotonic();worker.shutdown();signal_time=time.monotonic()-start
        release_evaluate.set()
        assert worker.join(15),'DLSS worker waited for the held session lock'
        session.Stop()
    assert closed.is_set() and len(set(backend_threads))==1 and backend_threads[0]!=threading.get_ident()
    assert worker.take(session,state[1]) is None
    assert worker.pop_error() is None
    assert notifications and all(t!=threading.get_ident() for t in notifications)
    report={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'stream_sha256':hashlib.sha256((root/'engine/dlss_stream.py').read_bytes()).hexdigest(),'frames':records,'image_pipeline_checks':pipeline_checks,'presentation_notifications':len(notifications),'shutdown_signal_seconds':signal_time,'backend_call_in_flight_at_shutdown':in_flight,'sdk_evaluation_completed_before_shutdown':True,'post_sdk_test_barrier_used':True,'session_lock_held_until_worker_joined':True,'worker_joined':True,'backend_closed_on_owning_thread':True,'scope':'Actual CUDA renderer and NGX on separate contexts with bounded asynchronous host transfers, optional faithful native image pipeline, camera edits and resize. A test barrier holds a completed SDK result for deterministic lock/teardown verification; this does not prove cancellation of an executing NGX kernel. No Blender view_draw, heavy scene, resident interop or speed comparison.'}
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
finally:
    worker.shutdown();release_evaluate.set()
    with lock:
        state[0]=None
        if session.IsStarted():session.Stop()
    assert worker.join(15),'Residual DLSS worker'
