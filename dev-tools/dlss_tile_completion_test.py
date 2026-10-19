"""Real GPU regression: transparent intersections must finish before tile merge."""
import argparse,hashlib,importlib.util,json,os,sys,time
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[1]
sp=importlib.util.spec_from_file_location('completion_fixture',root/'dev-tools/dlss_render_frame_test.py')
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-incomplete',action='store_true')
p.add_argument('--engine',choices=('RTPATHOCL','TILEPATHOCL','TILEPATHCPU'),default='RTPATHOCL')
a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
s.Init();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU');desc=s.GetOpenCLDeviceDescs()
mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
records=[];control=None
for layers in (0,20):
    scene,_,_=m.fixture(plane=True)
    scene.Parse(m.props('scene.materials.transparent.type = null\nscene.materials.white.emission = 1 0.5 0.25'))
    for i in range(layers):
        y=-4.0+i*.3;name='layer'+str(i)
        scene.DefineMesh(name,[(-100,y,-100),(100,y,-100),(100,y,100),(-100,y,100)],[(0,1,2),(0,2,3)])
        scene.Parse(m.props(f'scene.objects.{name}.shape = {name}\nscene.objects.{name}.material = transparent'))
    cfg=m.props(f'''renderengine.type = {a.engine}
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = 64
film.height = 48
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.tilesize = 32
path.pathdepth.total = 2
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
    if a.engine!='RTPATHOCL':
        cfg.Set(m.props('''native.threads.count = 1
tilepath.sampling.aa.size = 1
tile.multipass.enable = 0
tile.size.x = 32
tile.size.y = 32
batch.haltspp = 1
film.outputs.1.type = SAMPLECOUNT
film.outputs.1.filename = unused-count.png
'''))
    session=s.RenderSession(s.RenderConfig(cfg,scene));frames=[];after=0;deadline=time.monotonic()+90
    try:
        session.Start()
        for i in range(3 if a.engine=='RTPATHOCL' else 1):
            if a.engine=='RTPATHOCL':
                packet=None
                while packet is None:
                    assert time.monotonic()<deadline,'Transparent tile completion deadline'
                    packet=session.GetDenoisingFrame(after,100)
            else:
                while not session.HasDone():
                    assert time.monotonic()<deadline,'Final transparent tile completion deadline'
                    time.sleep(.01)
                color=np.empty((48,64,4),np.float32);counts=np.empty((48,64),np.uint32)
                session.GetFilm().GetOutputFloat(s.FilmOutputType.RGBA,color,0,False)
                session.GetFilm().GetOutputUInt(s.FilmOutputType.SAMPLECOUNT,counts,0,False)
                g=np.zeros((48,64,32),np.float32)
                packet={'frame_id':1,'jitter':None,'complete':bool(np.all(counts==1)),'color':color,'sample_count':counts,'guides':g}
            after=packet['frame_id'];counts=packet['sample_count'];color=packet['color'];g=packet['guides']
            frames.append({'id':after,'jitter':packet['jitter'],'complete':packet['complete'],'missing_pixels':int(np.count_nonzero(counts!=1)),
                           'count_values':{str(int(v)):int(n) for v,n in zip(*np.unique(counts,return_counts=True))},'rgb_mean':color[:,:,:3].mean(axis=(0,1)).tolist(),
                           'rgba_finite':bool(np.isfinite(color).all()),'guide_status':{str(int(v)):int(n) for v,n in zip(*np.unique(g[:,:,7],return_counts=True))}})
            if i==0:
                np.savez_compressed(a.out/f'layers-{layers}.npz',color=color,guides=g,sample_count=counts)
                if layers==0:control=color.copy()
                else:frames[-1]['control_max_abs']=float(np.abs(control-color).max())
            assert np.isfinite(color).all() and np.isfinite(g).all()
            if not a.expect_incomplete or layers==0:
                assert packet['complete'] and np.all(counts==1),(layers,frames[-1])
                if a.engine=='RTPATHOCL':assert np.all(g[:,:,7]==1),np.unique(g[:,:,7],return_counts=True)
        records.append({'layers':layers,'frames':frames})
        if a.expect_incomplete and layers:assert any(f['missing_pixels']>0 for f in frames),'Baseline hypothesis disproved'
    finally:
        if session.IsStarted():session.Stop()
        result={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device':device,'engine':a.engine,'expect_incomplete':a.expect_incomplete,'cases':records,'scope':'Transparent intersection completion, existing physical transport/depth unchanged; no SDK. Ordinary final-film tests do not request guides.'}
        (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
