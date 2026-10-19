"""Image-map vector inputs must survive direct and composed GPU evaluation.

A unit scale around an image is semantically identical to the direct image.
Constant explicit coordinates make the expected albedo independent of camera
jitter, lighting variance, and image orientation. Diagnostic mode retains failed
results without treating successful capture as a quality pass.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_vector_fixture', root / 'dev-tools/dlss_render_frame_test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.slc
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--diagnostic', action='store_true')
parser.add_argument('--spectral', action='store_true', help='Gate semantic identity, not an RGB-to-spectral numerical reference')
parser.add_argument('--image-coordinates', action='store_true', help='Image output used as raw coordinates for a second image')
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
s.Init()
desc = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if desc.Get(n+'.type').GetString() == 'METAL_GPU' else '0'
               for n in desc.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
pixels = np.zeros((32,32,3),np.uint8)
pixels[:,:,:] = [20,90,170]
pixels[:,16:,0] = 235
image = args.out / 'horizontal-regions.ppm'
image.write_bytes(b'P6\n32 32\n255\n' + pixels.tobytes())
color = np.array([20,90,170],np.float64)/255
scalar = float(color @ np.array([.212671,.715160,.072169]))
coordinates = args.out / 'coordinates.ppm'
coordinates.write_bytes(b'P6\n32 32\n255\n' + np.tile(np.array([32,32,0],np.uint8),(32,32,1)).tobytes())
coordinate_graph = (f'scene.textures.coord.type=imagemap\nscene.textures.coord.file={coordinates.resolve()}\n'
                    'scene.textures.coord.colorspace=nop\nscene.textures.coord.storage=float\n'
                    'scene.textures.coord.vector=0.125 0.125 0' if args.image_coordinates else '')
vector = 'coord' if args.image_coordinates else '0.125 0.125 0'
rows = []
for consumer in ('matte-color', 'openpbr-color', 'openpbr-float'):
    for composed in (False,True):
        for engine in ('TILEPATHCPU','TILEPATHOCL'):
            label = consumer + ('-scale-' if composed else '-direct-') + engine
            texture = 'identity' if composed else 'pic'
            material = ('scene.materials.wall.type=matte\nscene.materials.wall.kd='+texture
                        if consumer == 'matte-color' else
                        'scene.materials.wall.type=openpbr\n'
                        'scene.materials.wall.specularweight=0\n'
                        'scene.materials.wall.basecolor=' + (texture if consumer == 'openpbr-color' else '1 1 1') + '\n'
                        'scene.materials.wall.baseweight=' + (texture if consumer == 'openpbr-float' else '1'))
            scene = s.Scene()
            scene.Parse(m.props(f'''
scene.camera.lookat.orig=0 -5 0
scene.camera.lookat.target=0 0 0
scene.camera.up=0 0 1
scene.camera.fieldofview=45
{coordinate_graph}
scene.textures.pic.type=imagemap
scene.textures.pic.file={image.resolve()}
scene.textures.pic.colorspace=nop
scene.textures.pic.gamma=1
scene.textures.pic.storage=float
scene.textures.pic.vector={vector}
scene.textures.identity.type=scale
scene.textures.identity.texture1=pic
scene.textures.identity.texture2=1
{material}
scene.lights.env.type=constantinfinite
scene.lights.env.color=1 1 1
'''))
            scene.DefineMesh('wall',[(-4,1,-3),(4,1,-3),(4,1,3),(-4,1,3)],
                             [(0,1,2),(0,2,3)],None,[(0.,0.),(1.,0.),(1.,1.),(0.,1.)])
            scene.Parse(m.props('scene.objects.wall.shape=wall\nscene.objects.wall.material=wall'))
            cfg=m.props(f'''
renderengine.type={engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
opencl.devices.select={mask}
film.width=96
film.height=64
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
tile.size=32
tile.multipass.enable=0
tilepath.sampling.aa.size=1
path.pathdepth.total=4
path.lighttracing.auto=0
path.lighttracing.enable=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.caustic.enabled=0
path.photongi.indirect.enabled=0
path.spectral.enable={int(args.spectral)}
''')
            channels={'RGB':3,'ALBEDO':3,'SAMPLECOUNT':1}
            for i,name in enumerate(channels):
                cfg.Set(s.Property(f'film.outputs.{i}.type',name))
                cfg.Set(s.Property(f'film.outputs.{i}.filename','unused.exr'))
            session=s.RenderSession(s.RenderConfig(cfg,scene))
            try:
                session.Start()
                deadline=time.monotonic()+90
                while not session.HasDone():
                    assert time.monotonic()<deadline,label
                    time.sleep(.01)
                session.Stop()
                arrays={}
                for name,n in channels.items():
                    uint=name=='SAMPLECOUNT'
                    a=np.zeros((64,96,n),np.uint32 if uint else np.float32)
                    getter=session.GetFilm().GetOutputUInt if uint else session.GetFilm().GetOutputFloat
                    getter(s.FilmOutputType.names[name],a,0,False)
                    assert np.isfinite(a).all(),(label,name)
                    arrays[name]=a
                assert np.all(arrays['SAMPLECOUNT']==1),label
                expected=np.full(3,scalar) if consumer=='openpbr-float' else color
                error=float(np.max(np.abs(arrays['ALBEDO']-expected)))
                row={'case':label,'engine':engine,'consumer':consumer,'composed_identity_scale':composed,
                     'expected_albedo':None if args.spectral else expected.tolist(),'mean_albedo':arrays['ALBEDO'].mean((0,1),dtype=np.float64).tolist(),
                     'max_abs_albedo_error':error,'tolerance':1e-5,'analytic_gate_passed':None if args.spectral else error<1e-5}
                rows.append(row)
                np.savez_compressed(args.out/(label+'.npz'),**arrays)
                (args.out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n')
                print(json.dumps(row),flush=True)
                if not args.diagnostic and not args.spectral:
                    assert row['analytic_gate_passed'],row
            finally:
                if session.IsStarted():session.Stop()
identities=[]
for consumer in ('matte-color','openpbr-color','openpbr-float'):
    for engine in ('TILEPATHCPU','TILEPATHOCL'):
        with np.load(args.out/(consumer+'-direct-'+engine+'.npz')) as direct, np.load(args.out/(consumer+'-scale-'+engine+'.npz')) as identity:
            errors={k:float(np.abs(direct[k]-identity[k]).max()) for k in ('RGB','ALBEDO')}
        passed=all(e<1e-5 for e in errors.values())
        identities.append({'consumer':consumer,'engine':engine,'max_abs_errors':errors,'tolerance':1e-5,'passed':passed})
        if args.spectral:
            for row in rows:
                if row['consumer']==consumer and row['engine']==engine:
                    row.update(analytic_gate_passed=passed,gate_kind='unit_scale_identity',max_abs_albedo_error=errors['ALBEDO'])
report={'passed':all(r['analytic_gate_passed'] for r in rows) and all(r['passed'] for r in identities),'spectral':args.spectral,'image_coordinates':args.image_coordinates,'semantic_identities':identities,'artifact_capture_complete':True,
        'diagnostic_only':args.diagnostic,'cases':rows,'scope':__doc__,
        'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),
        'performance_eligible':False}
if not args.diagnostic:assert report['passed'],report
(args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
