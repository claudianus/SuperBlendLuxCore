"""Actual RTPATH GPU independent-frame leases, edits, resize and raw accumulation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

spec=importlib.util.spec_from_file_location('rt_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--large',action='store_true');parser.add_argument('--capture',action='store_true')
parser.add_argument('--stress',action='store_true')
parser.add_argument('--interactive',action='store_true',help='Exercise bounded viewport GPU submission during edit/resize stress')
parser.add_argument('--dlss',action='store_true',help='Process live renderer leases with the optional CUDA backend')
args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True);s.Init()
scene,_,_=m.fixture();w,h=(1280,720) if args.large else (64,48)
cfg=m.props(f'''
renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
film.width = {w}
film.height = {h}
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
rtpath.denoisingframes.enable = 1
rtpath.interactive.gpu = {int(args.interactive)}
rtpath.denoisingframes.tilesize = 128
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
film.outputs.1.type = POSITION
film.outputs.1.filename = unused-position.exr
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
desc=s.GetOpenCLDeviceDescs();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU')
mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask;cfg.Set(s.Property('opencl.devices.select',mask));config=s.RenderConfig(cfg,scene);session=s.RenderSession(config)
assert config.GetProperties().Get('rtpath.interactive.gpu',[False]).GetBool()==args.interactive
records=[];previous=0;first=None;first_hash=None
capture_records=[]
backend=None
if args.capture or args.dlss:
    dlss_spec=importlib.util.spec_from_file_location('rt_dlss',Path(__file__).parents[1]/'engine/dlss.py')
    dlss=importlib.util.module_from_spec(dlss_spec);sys.modules[dlss_spec.name]=dlss;dlss_spec.loader.exec_module(dlss)

    class Capture:
        def process(self,frame):
            filename='frame-%04d.npz'%len(capture_records)
            np.savez_compressed(args.out/filename,**{name:getattr(frame,name) for name in (
                'color','depth','diffuse','specular','normal_roughness','motion','specular_motion')})
            capture_records.append(dict(file=filename,frame_id=frame.frame_id,scene_serial=frame.scene_serial,
                jitter=frame.jitter,reset=frame.reset,independent_samples=True,
                jitter_semantics='ngx-compensation',
                raw_sha256=hashlib.sha256(frame.color.tobytes()).hexdigest(),
                motion_max_pixels=float(np.abs(frame.motion).max())))
            return frame.color  # Contract capture only; this is not a denoised image.
    if args.dlss:
        backend=dlss.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SLC_DLSS_TEST_CACHE'],
                             library=os.environ['SLC_DLSS_TEST_LIBRARY'])
    consumer=dlss.RendererDLSS(backend if backend else Capture())


def next_frame(width,height,predicate=lambda p:True):
    global previous
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        packet=session.GetDenoisingFrame(previous,100)
        if packet is None:continue
        assert packet['frame_id']>previous
        previous=packet['frame_id']
        if packet['color'].shape[:2]!=(height,width) or not predicate(packet):continue
        assert packet['complete'] and packet['independent_samples']
        assert np.all(packet['sample_count']==1),np.unique(packet['sample_count'],return_counts=True)
        assert np.all(packet['guides'][:,:,7]==1),np.unique(packet['guides'][:,:,7],return_counts=True)
        assert np.isfinite(packet['color']).all() and np.isfinite(packet['guides']).all()
        assert not packet['color'].flags.writeable and not packet['guides'].flags.writeable
        position=packet['guides'][:,:,12:15].astype(np.float64)
        camera=position@packet['world_to_camera'][:3,:3].T+packet['world_to_camera'][:3,3]
        homogeneous=np.concatenate([camera,np.ones((*camera.shape[:2],1))],axis=2)
        raster=homogeneous@packet['camera_to_raster'].T
        px=raster[:,:,0]/raster[:,:,3];py=height-raster[:,:,1]/raster[:,:,3]
        xx,yy=np.meshgrid(np.arange(width)+.5+packet['jitter'][0],np.arange(height)+.5+packet['jitter'][1])
        error=max(float(np.abs(px-xx).max()),float(np.abs(py-yy).max()))
        assert error<.002,('packet camera/jitter mismatch',error)
        records.append({'id':previous,'size':[width,height],'epoch':packet['scene_epoch'],'jitter':packet['jitter'],
                        'complete':True,'projection_max_error_pixels':error,
                        'raw_sha256':hashlib.sha256(packet['color'].tobytes()).hexdigest()})
        print('frame',previous,(width,height),'projection error',error,flush=True)
        if args.capture or args.dlss:
            sdk_frame, _ = consumer._prepare(packet, None, False)
            centre_x, centre_y = np.meshgrid(np.arange(width)+.5, np.arange(height)+.5)
            compensation_error=max(float(np.abs(px+sdk_frame.jitter[0]-centre_x).max()),
                                   float(np.abs(py+sdk_frame.jitter[1]-centre_y).max()))
            assert compensation_error<.002,('NGX sample compensation mismatch',compensation_error)
            records[-1]['ngx_compensation_max_error_pixels']=compensation_error
            records[-1]['ngx_jitter']=sdk_frame.jitter
            before=hashlib.sha256(packet['color'].tobytes()).hexdigest()
            output=consumer.process(packet)
            if args.dlss:
                assert np.isfinite(output).all() and np.array_equal(output[:,:,3],packet['color'][:,:,3])
                assert hashlib.sha256(packet['color'].tobytes()).hexdigest()==before
                records[-1]['dlss_stats']=backend.stats()
                if width>=1280:
                    label='static' if len(records)<=4 else 'moved'
                    np.save(args.out/('live-'+label+'-dlss.npy'),output)
                    np.save(args.out/('live-'+label+'-raw.npy'),packet['color'])
        return packet
    raise TimeoutError('No matching complete independent frame')


try:
    session.Start()
    for i in range(4 if args.large else 8):
        packet=next_frame(w,h)
        if first is None:
            first=packet;first_hash=hashlib.sha256(packet['color'].tobytes()).hexdigest()
    assert len({r['raw_sha256'] for r in records})==len(records)
    session.UpdateStats()
    canonical_count=np.empty((h,w),np.uint32)
    session.GetFilm().GetOutputUInt(s.FilmOutputType.SAMPLECOUNT,canonical_count,0,False)
    assert np.min(canonical_count)>=len(records),'Canonical raw accumulation was reset each frame'
    epoch=packet['scene_epoch']
    session.BeginSceneEdit()
    scene.Parse(m.props('scene.camera.lookat.orig = 0.1 -5 2.2\nscene.camera.lookat.target = 0 0.5 1.5\nscene.camera.up = 0 0 1\nscene.camera.fieldofview = 45'))
    session.EndSceneEdit()
    immediate=session.GetDenoisingFrame(0,0)
    assert immediate is None or abs(float(immediate['camera_to_world'][0,3])-.1)<1e-5,'Pre-edit frame remained in the current publisher slot'
    packet=next_frame(w,h,lambda p:abs(float(p['camera_to_world'][0,3])-.1)<1e-5)
    assert packet['scene_epoch']==epoch,'Continuous camera edit unnecessarily reset the scene epoch'
    if args.stress:
        for angle in np.linspace(-.12,.12,8):
            x,y=5*np.sin(angle),-5*np.cos(angle)
            session.BeginSceneEdit()
            scene.Parse(m.props(f'scene.camera.lookat.orig = {x} {y} 2.2\nscene.camera.lookat.target = 0 0.5 1.5\nscene.camera.up = 0 0 1\nscene.camera.fieldofview = 45'))
            session.EndSceneEdit()
            packet=next_frame(w,h,lambda p:abs(float(p['camera_to_world'][0,3])-x)<1e-5)
            assert packet['scene_epoch']==epoch
        session.BeginSceneEdit()
        scene.Parse(m.props('scene.materials.white.kd = 0.4 0.55 0.7'))
        session.EndSceneEdit()
        packet=next_frame(w,h)
        assert packet['scene_epoch']>epoch,'Material edit reused the previous lighting/material history'
        epoch=packet['scene_epoch']
    session.Parse(m.props('film.width = 97\nfilm.height = 65'))
    immediate=session.GetDenoisingFrame(0,0)
    assert immediate is None or immediate['color'].shape[:2]==(65,97),'Pre-resize frame remained in the current publisher slot'
    packet=next_frame(97,65)
    assert packet['scene_epoch']>epoch
    assert hashlib.sha256(first['color'].tobytes()).hexdigest()==first_hash,'Leased frame mutated after later frames/edits/resize'
    session.Stop()
    assert hashlib.sha256(first['color'].tobytes()).hexdigest()==first_hash,'Leased frame was freed at stop'
    # Natural completion must keep the RT sync worker responsive until Stop;
    # WaitForDone must not try to join that worker before sending its stop.
    halt_cfg=s.Properties(cfg)
    halt_cfg.Set(s.Property('film.width',64));halt_cfg.Set(s.Property('film.height',48))
    halt_cfg.Set(s.Property('batch.haltspp',4))
    halt_session=s.RenderSession(s.RenderConfig(halt_cfg,scene))
    try:
        halt_session.Start()
        halt_session.WaitForDone()
        assert halt_session.HasDone()
    finally:
        if halt_session.IsStarted():halt_session.Stop()
    report={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'frames':records,
            'canonical_raw_accumulates':True,'read_only_leases_survive_edit_resize_stop':True,
            'halt_waitfordone_stop':True,
            'publisher_invalidated_at_edit_resize':True,
            'orbit_and_material_history_stress':args.stress,
            'interactive_gpu_submission':args.interactive,
            'live_cuda_dlss_processed':args.dlss,
            'scope':'Actual independent GPU frame delivery; static geometry and camera edit/resize. Optional live CUDA DLSS validation; Blender presentation and general motion/continuation still pending.'}
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.capture:
        (args.out/'capture.json').write_text(json.dumps({'native_sha256':report['native_sha256'],
            'consumer_sha256':hashlib.sha256((Path(__file__).parents[1]/'engine/dlss.py').read_bytes()).hexdigest(),
            'provenance':f'Procedural fixture authored in dlss_render_frame_test.py; actual independent {device} GPU frames; no user scene assets',
            'frames':capture_records},indent=2)+'\n')
finally:
    if session.IsStarted():session.Stop()
    if backend is not None:backend.close()
