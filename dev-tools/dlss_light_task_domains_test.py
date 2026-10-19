"""Actual LT/VC-enabled native frames and dense/queued/light-only coverage.

Keep raw arrays for matching frame ID and jitter across native builds. Floating
light splats may differ between repeated executions; record those differences
without weakening the existing bit-exact eye-only regression tests.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np

spec=importlib.util.spec_from_file_location('task_domain_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
parser=argparse.ArgumentParser()
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--frames',type=int,default=24)
parser.add_argument('--cases',nargs='+')
parser.add_argument('--metadata-only',action='store_true',help='Retain frame IDs/times/metrics without duplicate raw arrays')
args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
s.Init();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU')
descs=s.GetOpenCLDeviceDescs()
mask=''.join('1' if descs.Get(n+'.type').GetString()==device else '0' for n in descs.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
cases=[('rt-lt','RTPATHOCL',False,.25,False,'off'),
       ('rt-vc','RTPATHOCL',True,.25,False,'off'),
       ('rt-vc-wide','RTPATHOCL',True,.75,False,'off'),
       ('tile-vc','TILEPATHOCL',True,.25,False,'off'),
       ('path-vc','PATHOCL',True,.25,False,'off'),
       ('path-vc-queued','PATHOCL',True,.25,False,'on'),
       ('path-light-only','PATHOCL',False,1.,True,'off')]
if args.cases:
    assert set(args.cases)<={c[0] for c in cases}
    cases=[c for c in cases if c[0] in args.cases]
records=[]
for name,engine,vc,fraction,only,wavefront in cases:
    scene,_,_=m.fixture()
    cfg=m.props(f'''renderengine.type = {engine}
renderengine.seed = 131
sampler.type = {'SOBOL' if engine=='PATHOCL' else 'TILEPATHSAMPLER'}
native.threads.count = 4
opencl.native.threads.count = 0
opencl.devices.select = {mask}
opencl.task.count = 32768
film.width = 96
film.height = 64
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
batch.haltspp = 16
tile.size = 128
tile.multipass.enable = 0
tilepath.sampling.aa.size = 1
rtpath.denoisingframes.enable = {int(engine=='RTPATHOCL')}
rtpath.denoisingframes.tilesize = 128
path.pathdepth.total = 6
path.pathdepth.diffuse = 6
path.pathdepth.glossy = 6
path.pathdepth.specular = 6
path.lighttracing.auto = 0
path.lighttracing.enable = 1
path.lighttracing.only = {int(only)}
path.lighttracing.taskfraction = {fraction}
path.hybridbackforward.enable = 0
path.vertexconnection.enable = {int(vc)}
path.vertexconnection.connects = 0
path.vertexconnection.pool = 4
path.vertexconnection.adaptive = 0
path.vertexconnection.reuse = 0
path.vertexconnection.mergeradius = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
pathocl.wavefront = {wavefront}
''')
    (args.out/(name+'-config.txt')).write_text(str(cfg))
    session=s.RenderSession(s.RenderConfig(cfg,scene));packets=[];frames=[];t0=time.monotonic()
    try:
        session.Start();deadline=time.monotonic()+120
        if engine=='RTPATHOCL':
            after=0
            for _ in range(args.frames):
                packet=None
                while packet is None:
                    if time.monotonic()>deadline:raise TimeoutError(name)
                    packet=session.GetDenoisingFrame(after,100)
                after=packet['frame_id'];g=packet['guides'];color=packet['color']
                assert packet['complete'] and np.all(packet['sample_count']==1)
                assert np.isfinite(g).all() and np.isfinite(color).all()
                assert np.any(color[:,:,:3]>0), name
                assert np.all(g[:,:,7]==1), (name,np.unique(g[:,:,7],return_counts=True))
                packets.append(packet)
                frames.append({'id':after,'jitter':packet['jitter'],'completed_time':packet['completed_time'],'rgb_mean':color[:,:,:3].mean(axis=(0,1)).tolist()})
        else:
            while True:
                session.UpdateStats()
                if session.HasDone():break
                if time.monotonic()>deadline:raise TimeoutError(name)
                time.sleep(.02)
            color=np.empty((64,96,4),np.float32)
            session.GetFilm().GetOutputFloat(s.FilmOutputType.RGBA,color,0,False)
            assert np.isfinite(color).all() and np.any(color[:,:,:3]>0), name
            np.save(args.out/(name+'-color.npy'),color)
    finally:
        if session.IsStarted():session.Stop()
    for packet in ([] if args.metadata_only else packets):
        label=f"{name}-{packet['frame_id']:05d}"
        np.savez_compressed(args.out/(label+'.npz'),color=packet['color'],guides=packet['guides'],sample_count=packet['sample_count'])
    record={'case':name,'engine':engine,'vertex_connection':vc,'light_fraction':fraction,'light_only':only,'wavefront':wavefront,'frames':frames,'wall_seconds':time.monotonic()-t0,'finite_nonblack':True}
    records.append(record)
    report={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device':device,'cases':records,'scope':'Declared deterministic diagnostic scene/settings with LT/VC enabled. Raw RGB repeatability must be measured, not assumed. Regular PATHOCL film sample counts may overshoot; no strict ordinary-film timing/quality claim.'}
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'case':name,'frames':len(frames),'ids':[f['id'] for f in frames],'wall_seconds':record['wall_seconds']}),flush=True)
