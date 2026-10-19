"""Functional Stop deadline during a deep transparent GPU tile, not a benchmark."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,time
root=Path(__file__).resolve().parents[1]
sp=importlib.util.spec_from_file_location('cancel_fixture',root/'dev-tools/dlss_render_frame_test.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-slow',action='store_true');p.add_argument('--layers',type=int,default=32768);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
def stage(name):
    (a.out/'stage.json').write_text(json.dumps({'stage':name,'monotonic':time.monotonic()})+'\n')
stage('initializing_native');s.Init();stage('building_scene')
device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU');desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
scene,_,_=m.fixture(plane=True);scene.DeleteObject('wall');scene.Parse(m.props('scene.materials.transparent.type = null\nscene.materials.white.emission = 1 0.5 0.25'))
vertices=[];triangles=[]
for i in range(a.layers):
    y=-4+i*(1000.0/a.layers);base=len(vertices)
    vertices.extend([(-10000,y,-10000),(10000,y,-10000),(10000,y,10000),(-10000,y,10000)])
    triangles.extend([(base,base+1,base+2),(base,base+2,base+3)])
scene.DefineMesh('stack',vertices,triangles);del vertices,triangles
scene.DefineMesh('receiver',[(-10000,1000,-10000),(10000,1000,-10000),(10000,1000,10000),(-10000,1000,10000)],[(0,1,2),(0,2,3)])
scene.Parse(m.props('scene.objects.stack.shape = stack\nscene.objects.stack.material = transparent\nscene.objects.receiver.shape = receiver\nscene.objects.receiver.material = white'))
cfg=m.props(f'''renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = 1
film.height = 1
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.tilesize = 8
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
stage('starting_session');session=s.RenderSession(s.RenderConfig(cfg,scene));started=time.monotonic();session.Start();startup=time.monotonic()-started
stage('stopping');started=time.monotonic();session.Stop();elapsed=time.monotonic()-started;stage('stopped')
result={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device':device,'layers':a.layers,'startup_seconds':startup,'stop_seconds':elapsed,'stop_deadline_seconds':2.0,'expect_slow':a.expect_slow,'stopped':not session.IsStarted(),'scope':'Stop while first deep transparent tile is pending. Two-second functional cancellation deadline; no frame/DLSS output or speed ratio.'}
(a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
assert result['stopped']
if a.expect_slow:assert elapsed>2,'Slow-stop hypothesis not reproduced; do not claim this repro'
else:assert elapsed<=2,'Tile completion ignored the Stop request until the full path ended'
