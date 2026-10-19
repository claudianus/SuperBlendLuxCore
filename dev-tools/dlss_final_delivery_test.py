"""Lossless native final delivery, raw/AOV preservation and lifecycle gates.

The --dlss path calls the real NVIDIA backend. No fake guides or SDK substitute.
Control and reconstruction use identical native independent sample intervals.
"""
import argparse,hashlib,importlib.util,json,os,time
from pathlib import Path
import numpy as np

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name]=module;spec.loader.exec_module(module);return module
root=Path(__file__).resolve().parents[1]
m=load('final_delivery_fixture',root/'dev-tools/dlss_render_frame_test.py');s=m.slc
d=load('final_delivery_backend',root/'engine/dlss.py')
parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--dlss',action='store_true');args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
s.Init();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU');desc=s.GetOpenCLDeviceDescs()
mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
outputs={'RGBA':4,'SAMPLECOUNT':1,'ALPHA':1,'ALBEDO':3,'AVG_SHADING_NORMAL':3,'DEPTH':1,'POSITION':3,'DIRECT_DIFFUSE':3,'EMISSION':3,'OBJECT_ID':1}
scene,_,_=m.fixture()

def session(accumulated=True,halt=8):
    cfg=m.props(f'''renderengine.type = RTPATHOCL
renderengine.seed = 131
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = 96
film.height = 64
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
batch.haltspp = {halt}
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.lossless = 1
rtpath.denoisingframes.haltspp = {halt}
rtpath.denoisingframes.imagepipeline.enable = 1
rtpath.denoisingframes.imagepipeline.accumulated = {int(accumulated)}
rtpath.denoisingframes.tilesize = 128
path.pathdepth.total = 6
path.pathdepth.diffuse = 6
path.lighttracing.auto = 0
path.lighttracing.enable = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
''')
    for i,name in enumerate(outputs):
        cfg.Set(s.Property(f'film.outputs.{i}.type',name));cfg.Set(s.Property(f'film.outputs.{i}.filename','unused.png' if name=='OBJECT_ID' else 'unused.exr'))
    return s.RenderSession(s.RenderConfig(cfg,scene))

def get(native,after=0):
    deadline=time.monotonic()+120
    while True:
        frame=native.GetDenoisingFrame(after,100)
        if frame is not None:return frame
        if time.monotonic()>deadline:raise TimeoutError('Native final delivery')

def rejected(function):
    try:function()
    except RuntimeError:return
    raise AssertionError('Invalid/stale acknowledgement accepted')

def read_outputs(native):
    arrays={}
    for name,channels in outputs.items():
        uint=name in ('SAMPLECOUNT','OBJECT_ID')
        a=np.empty((64,96,channels),np.uint32 if uint else np.float32)
        getter=native.GetFilm().GetOutputUInt if uint else native.GetFilm().GetOutputFloat
        getter(s.FilmOutputType.names[name],a,0,False);arrays[name]=a
    return arrays

records=[];captures={}
for mode in ['control','reconstruction']:
    native=session(mode=='reconstruction');backend=None;consumer=None;pipeline=s.DenoisingImagePipeline();frames=[]
    if args.dlss and mode=='reconstruction':
        backend=d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SLC_DLSS_TEST_CACHE'],library=os.environ['SLC_DLSS_TEST_LIBRARY']);consumer=d.RendererDLSS(backend)
    try:
        native.Start();after=0
        for i in range(1,9):
            frame=get(native,after);assert frame['frame_id']==after+1
            assert frame['lossless_delivery'] and frame['complete']
            assert frame['accumulated_eye_samples']==i,(mode,i,frame['accumulated_eye_samples'])
            assert np.all(frame['sample_count']==1)
            before=read_outputs(native)
            if i==1:
                time.sleep(.1)
                repeat=native.GetDenoisingFrame(0,0);assert repeat['frame_id']==frame['frame_id']
                assert native.GetDenoisingFrame(frame['frame_id'],20) is None,'Producer outran the consumer'
            if i>1:rejected(lambda:native.AcknowledgeDenoisingFrame(previous))
            if consumer:
                image=consumer.process(frame);result=pipeline.process(frame,image,reset=consumer.last_reset)
                assert np.isfinite(result).all();np.save(args.out/'dlss.npy',result)
            if mode=='reconstruction':
                raw_pipeline=s.DenoisingImagePipeline().process(frame)
                reference=np.empty((64,96,4),np.float32)
                native.GetFilm().GetOutputFloat(s.FilmOutputType.RGBA_IMAGEPIPELINE,reference,0,True)
                np.testing.assert_array_equal(raw_pipeline,reference)
            after_outputs=read_outputs(native)
            for name in outputs:np.testing.assert_array_equal(before[name],after_outputs[name],err_msg=name)
            frames.append({'id':frame['frame_id'],'raw_prefix_samples':i,'jitter':frame['jitter'],'guides_sha256':hashlib.sha256(frame['guides'].tobytes()).hexdigest(),'color_sha256':hashlib.sha256(frame['color'].tobytes()).hexdigest()})
            previous=frame;after=frame['frame_id']
            native.UpdateStats();native.AcknowledgeDenoisingFrame(frame)
        deadline=time.monotonic()+3
        while not native.HasDone() and time.monotonic()<deadline:time.sleep(.01)
        assert native.HasDone(),'Final sample cap did not halt'
        assert native.GetDenoisingFrame(after,20) is None
        captures[mode]=read_outputs(native)
        assert np.all(captures[mode]['SAMPLECOUNT']==8)
        np.savez_compressed(args.out/(mode+'.npz'),**captures[mode])
        records.append({'case':mode,'frames':frames,'sdk_evaluations':backend.stats()['frames'] if backend else 0,'canonical_channels_unchanged_by_processing':True,'sample_cap_exact':8})
    finally:
        if native.IsStarted():native.Stop()
        if backend:backend.close()
for name in outputs:np.testing.assert_array_equal(captures['control'][name],captures['reconstruction'][name],err_msg=name)

native=session(halt=0)
try:
    native.Start();native.SetDenoisingFrameHaltSPP(4);after=0
    for target in (4,8):
        native.SetDenoisingFrameHaltSPP(target)
        while after<target:
            frame=get(native,after);assert frame['frame_id']==after+1
            after=frame['frame_id'];assert frame['accumulated_eye_samples']==after
            native.UpdateStats();native.AcknowledgeDenoisingFrame(frame)
        deadline=time.monotonic()+2
        while not native.HasDone() and time.monotonic()<deadline:time.sleep(.01)
        assert native.HasDone() and native.GetDenoisingFrame(after,20) is None
    # Raising a parked cap must preserve every raw/AOV contribution.
    raised=read_outputs(native)
    for name in outputs:np.testing.assert_array_equal(raised[name],captures['control'][name],err_msg=name)
    native.SetDenoisingFrameHaltSPP(0)
    frame=get(native,after);assert frame['accumulated_eye_samples']==9
    # Lowering below an already complete, withheld sample cannot undo it or
    # produce an additional sample after acknowledging it.
    native.SetDenoisingFrameHaltSPP(3)
    native.UpdateStats();native.AcknowledgeDenoisingFrame(frame)
    deadline=time.monotonic()+2
    while not native.HasDone() and time.monotonic()<deadline:time.sleep(.01)
    assert native.HasDone() and native.GetDenoisingFrame(frame['frame_id'],20) is None
    assert np.all(read_outputs(native)['SAMPLECOUNT']==9)
    records.append({'case':'dynamic-halt-cap','raised_parked_4_to_8_without_reset':True,
                    'raw8_all10_channels_bit_exact_to_fixed_cap':True,
                    'disabled_to_sample9':True,'lowered_below_withheld_sample_without_extra':True})
finally:
    if native.IsStarted():native.Stop()

native=session(halt=100000)
try:
    native.Start();first=get(native)
    native.BeginSceneEdit();native.GetRenderConfig().GetScene().Parse(m.props('scene.camera.lookat.orig = 0.1 -5 2.2'));native.EndSceneEdit()
    new=get(native,first['frame_id']);assert new['accumulated_eye_samples']==1
    rejected(lambda:native.AcknowledgeDenoisingFrame(first))
    native.Parse(m.props('film.width = 81\nfilm.height = 59'))
    resized=get(native,new['frame_id']);assert resized['color'].shape==(59,81,4) and resized['accumulated_eye_samples']==1
    rejected(lambda:native.AcknowledgeDenoisingFrame(new))
    start=time.monotonic();native.Stop();elapsed=time.monotonic()-start;assert elapsed<2
    records.append({'case':'edit-resize-stop-with-unacknowledged-frame','stop_seconds':elapsed,'deadline_seconds':2,'stale_leases_rejected':True})
finally:
    if native.IsStarted():native.Stop()

native=session(halt=100000)
try:
    native.Start();first=get(native);native.ReleaseDenoisingFrameDelivery()
    new=get(native,first['frame_id']);assert not new['lossless_delivery']
    records.append({'case':'release-to-latest-fallback','frames_continue':True})
finally:
    if native.IsStarted():native.Stop()
report={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device':device,'cases':records,'raw_aov_control_bit_exact':list(outputs),'scope':'Actual fixed-scene coherent delivery/accumulated context, lifecycle and optional real NGX. Not full final Blender/animation/SR/material/motion/alpha support or high-SPP quality/speed proof.'}
(args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
