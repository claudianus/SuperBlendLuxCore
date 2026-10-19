"""Actual independent GPU paths through glass, mirrors and the environment.

The matched-IOR filter and reflected plane have analytical guide endpoints.
Baseline mode records raw frames from an older binary without relaxing gates.
"""
import argparse,importlib.util,json,os,sys,time,hashlib
from pathlib import Path
import numpy as np

def load(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
root=Path(__file__).resolve().parents[1]
m=load('path_features_fixture',root/'dev-tools/dlss_render_frame_test.py');s=m.slc
d=load('path_features_dlss',root/'engine/dlss.py')
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--baseline',action='store_true');p.add_argument('--reference',type=Path);p.add_argument('--dlss',action='store_true');p.add_argument('--large',action='store_true');p.add_argument('--motion',action='store_true');p.add_argument('--capture-frames',type=int,default=8);p.add_argument('--preservation-grid',action='store_true');p.add_argument('--extended',action='store_true');p.add_argument('--translucent',action='store_true');p.add_argument('--cases',nargs='+');args=p.parse_args();args.out.mkdir(exist_ok=True,parents=True)
s.Init();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU')
desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
records=[]
def plane(scene,name,material,y,forward=False,normal=None):
    points=[(-100,y,-100),(100,y,-100),(100,y,100),(-100,y,100)]
    triangles=[(0,2,1),(0,3,2)] if forward else [(0,1,2),(0,2,3)]
    if normal is None:scene.DefineMesh(name,points,triangles)
    else:scene.DefineMesh(name,points,triangles,[normal]*4)
    scene.Parse(m.props(f'scene.objects.{name}.shape = {name}\nscene.objects.{name}.material = {material}'))

cases=['matte','matched-ior-filter','mirror','rough-glass','openpbr-transmission','background','mirror-background','unsupported']
if args.extended:cases+=['mirror-tilted-normal','unsupported-sss']
if args.translucent:cases+=['translucent','translucent-colored','translucent-backside']
if args.cases:
    assert set(args.cases)<=set(cases),('Unknown cases',args.cases)
    cases=[case for case in cases if case in args.cases]
for case in cases:
    unsupported=case.startswith('unsupported')
    scene,_,_=m.fixture(plane=True)
    if case=='background':scene.DeleteObject('wall')
    elif case!='matte':
        if case in ('matched-ior-filter','rough-glass'):
            props='scene.materials.front.type = '+('glass' if case=='matched-ior-filter' else 'roughglass')+'\n'
            props+='scene.materials.front.kr = 0 0 0\nscene.materials.front.kt = 0.8 0.6 0.4\nscene.materials.front.interiorior = 1\n'
            if case=='rough-glass':props+='scene.materials.front.distribution = ggx\nscene.materials.front.uroughness = 0.6\nscene.materials.front.vroughness = 0.6\n'
        elif case.startswith('mirror'):
            props='scene.materials.front.type = mirror\nscene.materials.front.kr = 0.7 0.7 0.7\n'
            if case in ('mirror','mirror-tilted-normal'):plane(scene,'reflected','white',-8,True)
        elif case=='openpbr-transmission':
            props='scene.materials.front.type = openpbr\nscene.materials.front.transmissionweight = 1\nscene.materials.front.specularroughness = 0.001\n'
        elif case=='unsupported-sss':props='scene.materials.front.type = openpbr\nscene.materials.front.subsurfaceweight = 1\n'
        elif case.startswith('translucent'):
            kr,kt={'translucent':('0.5 0.5 0.5','0.5 0.5 0.5'),
                   'translucent-colored':('1.2 -0.1 0.25','0.9 0.5 1.2'),
                   'translucent-backside':('0.2 0.4 0.6','0.3 0.5 0.7')}[case]
            props=f'scene.materials.front.type = mattetranslucent\nscene.materials.front.kr = {kr}\nscene.materials.front.kt = {kt}\n'
        else:props='scene.materials.front.type = velvet\n'
        scene.Parse(m.props(props));plane(scene,'front','front',0,forward=case=='translucent-backside',normal=(0,-np.sqrt(.99),.1) if case=='mirror-tilted-normal' else None)
    w,h=(320,180) if args.preservation_grid else ((1280,720) if args.large and case=='matched-ior-filter' else (64,48))
    cfg=m.props(f'''renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = {w}
film.height = {h}
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.tilesize = 128
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
    session=s.RenderSession(s.RenderConfig(cfg,scene));frames=[];after=0;end=time.monotonic()+120;backend=None
    if args.dlss and not unsupported:backend=d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SLC_DLSS_TEST_CACHE'],library=os.environ['SLC_DLSS_TEST_LIBRARY'])
    class Capture:
        frame=None
        def process(self,frame):
            frame.native();self.frame=frame
            return frame.color.copy()  # Contract inspection only, never a DLSS result.
    inspected=Capture()
    consumer=d.RendererDLSS(backend or inspected) if not args.baseline and not args.reference and not unsupported else None
    try:
        session.Start()
        for i in range(args.capture_frames):
            packet=None
            while packet is None:
                if time.monotonic()>end:raise TimeoutError(case)
                packet=session.GetDenoisingFrame(after,100)
            after=packet['frame_id'];g=packet['guides'];color=packet['color']
            assert packet['complete'] and np.all(packet['sample_count']==1)
            assert np.isfinite(g).all() and np.isfinite(color).all()
            if not args.baseline:
                assert packet['guide_version']==2 and np.all(g[:,:,19]==2)
                if unsupported:assert np.all(g[:,:,7]==2)
                else:
                    assert np.all(g[:,:,7]==1),(case,np.unique(g[:,:,7],return_counts=True))
                    assert np.all(g[:,:,23]==0)
                if case=='matched-ior-filter':
                    np.testing.assert_allclose(g[:,:,:3],np.broadcast_to([.52,.39,.26],g[:,:,:3].shape),atol=2e-6)
                    np.testing.assert_allclose(g[:,:,4:7],np.broadcast_to([.8,.6,.4],g[:,:,4:7].shape),atol=2e-6)
                    np.testing.assert_allclose(g[:,:,12+1],0,atol=1e-5)
                    assert np.all(g[:,:,15]>np.linalg.norm(g[:,:,12:15]-[0,-5,1],axis=2))
                    np.testing.assert_allclose(np.linalg.norm(g[:,:,8:11],axis=2),.6,atol=2e-6)
                    assert np.all(g[:,:,31]==2)
                elif case=='mirror':
                    np.testing.assert_allclose(g[:,:,:3],.455,atol=2e-6)
                    assert np.all(g[:,:,27]==1) and np.all(g[:,:,31]==1)
                    np.testing.assert_allclose(g[:,:,25],8,atol=2e-5)
                elif case=='mirror-tilted-normal':
                    normal=np.array([0,-np.sqrt(.99),.1])
                    np.testing.assert_allclose(g[:,:,28:31],np.broadcast_to(normal,g[:,:,28:31].shape),atol=1e-6)
                    first=g[:,:,12:15].astype(np.float64);incoming=first-[0,-5,1]
                    incoming/=np.linalg.norm(incoming,axis=2,keepdims=True)
                    reflected=incoming-2*np.sum(incoming*normal,axis=2,keepdims=True)*normal
                    length=(-8-first[:,:,1])/reflected[:,:,1]
                    second=first+reflected*length[:,:,None]
                    virtual=second-2*np.sum((second-first)*normal,axis=2,keepdims=True)*normal
                    np.testing.assert_allclose(g[:,:,24:27],virtual,atol=3e-4)
                    assert np.all(g[:,:,27]==1)
                elif case=='background':assert np.all(g[:,:,27]==2)
                elif case=='mirror-background':assert np.all(g[:,:,27]==3)
                elif case.startswith('translucent'):
                    # Lambert reflection plus energy-conserving diffuse transmission
                    # under a white environment: clamp(Kr)+clamp(Kt)*(1-clamp(Kr)).
                    expected={'translucent':[.75,.75,.75],
                              'translucent-colored':[1.,.5,1.],
                              'translucent-backside':[.44,.7,.88]}[case]
                    np.testing.assert_allclose(g[:,:,:3],np.broadcast_to(expected,g[:,:,:3].shape),atol=2e-6)
                    assert not g[:,:,4:7].any()
                    np.testing.assert_allclose(g[:,:,3],1,atol=1e-7)
                    np.testing.assert_allclose(np.linalg.norm(g[:,:,8:11],axis=2),1,atol=2e-6)
                    np.testing.assert_allclose(g[:,:,13],0,atol=2e-5)
            before=hashlib.sha256(color.tobytes()+g.tobytes()).hexdigest()
            if consumer:
                result=consumer.process(packet);assert np.isfinite(result).all()
                assert hashlib.sha256(color.tobytes()+g.tobytes()).hexdigest()==before
                if backend and args.large and case=='matched-ior-filter':
                    np.save(args.out/'filter-dlss.npy',result);np.save(args.out/'filter-raw.npy',color)
            name=f'{case}-{after:05d}.npy';np.save(args.out/name,color)
            frames.append(dict(id=after,file=name,jitter=packet['jitter'],color_sha256=hashlib.sha256(color.tobytes()).hexdigest(),status={str(v):int(n) for v,n in zip(*np.unique(g[:,:,7],return_counts=True))}))
            (args.out/(case+'-frames.json')).write_text(json.dumps(frames,indent=2)+'\n')
        actions=[]
        if args.motion and not args.baseline and (case in ('matched-ior-filter','mirror','background','mirror-background','mirror-tilted-normal') or case.startswith('translucent')):
            held=packet;held_hash=hashlib.sha256(held['color'].tobytes()+held['guides'].tobytes()).hexdigest()
            for x in (.1,-.1,.2,0.):
                session.BeginSceneEdit()
                scene.Parse(m.props(f'scene.camera.lookat.orig = {x} -5 1\nscene.camera.lookat.target = {x} 0 1\nscene.camera.up = 0 0 1\nscene.camera.fieldofview = 45'))
                session.EndSceneEdit()
                deadline=time.monotonic()+20
                while True:
                    new=session.GetDenoisingFrame(after,100)
                    if new is not None:
                        after=new['frame_id']
                        if abs(new['camera_to_world'][0,3]-x)<1e-5:break
                    if time.monotonic()>deadline:raise TimeoutError(case+' camera')
                result=consumer.process(new);assert np.isfinite(result).all()
                assert not consumer.last_reset,(case,'Continuous camera edit reset history')
                actions.append(dict(kind='camera',x=x,id=after,history_reset=False))
            for width,height in ((w+17,h+11),(w,h)):
                session.Parse(m.props(f'film.width = {width}\nfilm.height = {height}'))
                deadline=time.monotonic()+20
                while True:
                    new=session.GetDenoisingFrame(after,100)
                    if new is not None:
                        after=new['frame_id']
                        if new['color'].shape[:2]==(height,width):break
                    if time.monotonic()>deadline:raise TimeoutError(case+' resize')
                result=consumer.process(new);assert np.isfinite(result).all()
                assert consumer.last_reset,(case,'Resize kept incompatible history')
                actions.append(dict(kind='resize',size=[width,height],id=after,history_reset=True))
            assert hashlib.sha256(held['color'].tobytes()+held['guides'].tobytes()).hexdigest()==held_hash
        if args.reference:
            old=json.loads((args.reference/'result.json').read_text())
            previous=next(r for r in old['cases'] if r['case']==case)['frames']
            compared=[]
            for frame in frames:
                previous_frame=next((f for f in previous if f['id']==frame['id']),None)
                if not previous_frame:continue
                assert tuple(previous_frame['jitter'])==tuple(frame['jitter']),(case,frame['id'],'Jitter mismatch',previous_frame['jitter'],frame['jitter'])
                a=np.load(args.reference/previous_frame['file'],allow_pickle=False);z=np.load(args.out/frame['file'],allow_pickle=False)
                assert np.array_equal(a,z),(case,frame['id'],float(np.abs(a-z).max()))
                compared.append(frame['id'])
            assert len(compared)>=2,(case,'Not enough matched raw frames',compared)
        else:compared=[]
        records.append(dict(case=case,size=[w,h],frames=frames,matched_raw_bit_exact_ids=compared,dlss_frames=backend.stats()['frames'] if backend else 0,motion_resize=actions))
        print('PATH_FEATURES',case,[f['id'] for f in frames],compared,flush=True)
    finally:
        if session.IsStarted():session.Stop()
        if backend:backend.close()
    (args.out/'result.json').write_text(json.dumps({'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device':device,'baseline':args.baseline,'cases':records,'scope':'Actual independent paths; analytical matched-IOR/filter/mirror features and strict matched raw preservation. Static materials/geometry, camera motion unit tests separate; not general scene support or final animation quality.'},indent=2)+'\n')
