"""Matched native images for direct/instance/motion base-mesh staging reuse.

Run the same script with immutable before/after native profiles. Compare every
stored output bitwise, and inspect the captured native unique-payload log for the
expected pointer-identity count. Equal vertex counts alone never authorize reuse.
"""
from pathlib import Path
import argparse,hashlib,json,os,sys,time
import numpy as np
sys.path.insert(0,os.environ['SLC_DLSS_RENDER_MODULE'])
import pysuperluxcore as s


def props(text):
    p=s.Properties();p.SetFromString(text);return p


def transform(x):
    a=np.eye(4,dtype=np.float32);a[0,3]=x
    return a.reshape(-1,order='F').tolist()


def fixture(case):
    scene=s.Scene()
    scene.Parse(props('''
scene.camera.lookat.orig=0 -8 2
scene.camera.lookat.target=0 0 1
scene.camera.up=0 0 1
scene.camera.fieldofview=55
scene.camera.shutteropen=0
scene.camera.shutterclose=1
scene.lights.environment.type=constantinfinite
scene.lights.environment.color=0.2 0.3 0.4
scene.textures.vertexcolor.type=hitpointcolor
scene.textures.vertexcolor.dataindex=0
scene.materials.colored.type=matte
scene.materials.colored.kd=vertexcolor
scene.materials.blue.type=matte
scene.materials.blue.kd=0.05 0.2 0.7
'''))
    definitions=['base','other'] if case=='distinct-same-count' else ['base']
    for index,name in enumerate(definitions):
        points=np.array([(-.7,0,0),(.7,0,0),(.7,0,2),(-.7,0,2)],np.float32)
        if index:points[:,0]+=2
        normals=np.tile(np.array((0,-1,0),np.float32),(4,1))
        uvs=np.array([(0,0),(1,0),(1,1),(0,1)],np.float32)
        colors=np.array([(.6,.1,.05),(.1,.6,.05),(.05,.1,.6),(.6,.6,.05)],np.float32)
        if index:colors=colors[::-1].copy();uvs=uvs[:,::-1].copy()
        scene.DefineMeshExt(name,points,np.array([(0,1,2),(0,2,3)],np.uint32),normals,[uvs,uvs*.5],[colors],[np.ones(4,np.float32)],generated_transformation=np.eye(4,dtype=np.float32))
        scene.SetMeshVertexAOV(name,0,[.1,.2,.3,.4]);scene.SetMeshTriangleAOV(name,0,[.25,.75])
    def obj(name,shape='base',x=None,motion=False):
        p=props('scene.objects.'+name+'.shape='+shape+'\nscene.objects.'+name+'.material=colored')
        if motion:
            for i,position in enumerate((-2.,-1.5)):
                p.Set(s.Property('scene.objects.'+name+'.motion.%d.time'%i,float(i)))
                p.Set(s.Property('scene.objects.'+name+'.motion.%d.transformation'%i,transform(position)))
        elif x is not None:p.Set(s.Property('scene.objects.'+name+'.transformation',transform(x)))
        scene.Parse(p)
    if case=='direct-first':
        obj('a_direct');obj('b_direct');obj('z_instance',x=2)
    elif case=='instance-first':
        obj('a_instance',x=-2);obj('b_instance',x=2);obj('z_direct');obj('zz_direct')
    elif case=='motion-first':
        obj('a_motion',motion=True);obj('z_direct');obj('zz_instance',x=2)
    elif case=='distinct-same-count':
        obj('a_direct');obj('b_other',shape='other');obj('z_instance',x=-2)
    else:raise ValueError(case)
    return scene,len(definitions)


def render(case,engine,size,diagnostic_out=None):
    scene,unique=fixture(case);w,h=size
    p=props('''
native.threads.count=4
opencl.native.threads.count=0
opencl.task.count=8192
sampler.type=TILEPATHSAMPLER
tile.size=64
tilepath.sampling.aa.size=2
tile.multipass.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
film.hw.enable=0
renderengine.seed=131
path.pathdepth.total=6
path.lighttracing.auto=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.indirect.enabled=0
path.photongi.caustic.enabled=0
path.spectral.enable=0
pathocl.wavefront=off
''')
    for name,value in [('renderengine.type',engine),('film.width',w),('film.height',h)]:p.Set(s.Property(name,value))
    if engine.endswith('OCL'):
        dev=s.GetOpenCLDeviceDescs();mask=''.join('1' if dev.Get(n+'.type').GetString()==os.environ['SLC_DLSS_RENDER_DEVICE'] else '0' for n in dev.GetAllUniqueSubNames('opencl.device'));assert mask.count('1')==1;p.Set(s.Property('opencl.devices.select',mask))
    outputs=[('RGBA',4),('ALBEDO',3),('AVG_SHADING_NORMAL',3),('DEPTH',1),('POSITION',3),('UV',2),('MATERIAL_ID',1),('OBJECT_ID',1),('SAMPLECOUNT',1)]
    for i,(name,_) in enumerate(outputs):
        p.Set(s.Property('film.outputs.%d.type'%i,name))
        p.Set(s.Property('film.outputs.%d.filename'%i,'unused.png' if name in ['MATERIAL_ID','OBJECT_ID'] else 'unused.exr'))
    config=s.RenderConfig(p,scene);session=s.RenderSession(config)
    try:
        session.Start();end=time.monotonic()+120
        while not session.HasDone():
            if time.monotonic()>end:raise TimeoutError('Geometry staging test did not halt')
            time.sleep(.005)
        arrays={}
        for name,channels in outputs:
            integer=name in ['MATERIAL_ID','OBJECT_ID','SAMPLECOUNT'];a=np.empty((h,w,channels),np.uint32 if integer else np.float32)
            get=session.GetFilm().GetOutputUInt if integer else session.GetFilm().GetOutputFloat;get(getattr(s.FilmOutputType,name),a,0,False);arrays[name]=a
        if diagnostic_out is not None:
            np.savez_compressed(diagnostic_out,**arrays)
        print(json.dumps({'case':case,'sample_counts':np.unique(arrays['SAMPLECOUNT']).tolist(),'rgba_nonfinite':int(np.count_nonzero(~np.isfinite(arrays['RGBA'])))}),flush=True)
        # Default subpixel jitter can redistribute a few GPU samples to an
        # adjacent pixel in the unchanged baseline (observed3/5 pairs at720p).
        # Preserve and compare that exact distribution; do not conceal it with
        # fixed jitter or claim a uniform per-pixel four-sample reference.
        assert np.all(arrays['SAMPLECOUNT']>0)
        assert int(arrays['SAMPLECOUNT'].sum(dtype=np.uint64))==4*w*h
        assert np.isfinite(arrays['RGBA']).all(), 'Nonfinite canonical radiance'
        assert np.any(arrays['RGBA'][:,:,:3]>0)
        return arrays,unique
    finally:
        if session.IsStarted():session.Stop()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--engine',default='TILEPATHOCL');p.add_argument('--compare',type=Path);a=p.parse_args();assert not a.out.exists();a.out.mkdir(parents=True)
    s.Init();rows=[];native=Path(s.pysuperluxcore.__file__)
    for case in ['direct-first','instance-first','motion-first','distinct-same-count']:
        print('GEOMETRY_STAGING_CASE '+case,flush=True);data,unique=render(case,a.engine,(1280,720),a.out/(case+'-diagnostic.npz'));np.savez_compressed(a.out/(case+'.npz'),**data);(a.out/(case+'-diagnostic.npz')).unlink()
        if a.compare:
            with np.load(a.compare/(case+'.npz')) as before:
                assert set(before.files)==set(data)
                for name,value in data.items():np.testing.assert_array_equal(value,before[name],err_msg=case+':'+name)
        counts,freq=np.unique(data['SAMPLECOUNT'],return_counts=True)
        rows.append({'case':case,'expected_unique_base_meshes':unique,'expected_vertices':4*unique,'expected_triangles':2*unique,'channels':list(data),'average_samples':4,'sample_histogram':dict(zip(map(str,counts.tolist()),freq.tolist())),'uniform_four_samples':bool(np.all(data['SAMPLECOUNT']==4)),'bit_exact_control':bool(a.compare)})
        (a.out/'result.json').write_text(json.dumps({'native_sha256':hashlib.file_digest(native.open('rb'),'sha256').hexdigest(),'engine':a.engine,'checks':rows,'scope':__doc__},indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':rows}),flush=True)
