"""Real Blender evaluated meshes: baseline/candidate byte-exact export payloads."""
from pathlib import Path
import os
SCOPE = "Actual evaluated Blender mesh payloads and motion metadata; twelve flat/smooth/custom-normal, instancing and motion-map conditions."
fixture=Path(os.environ['SLC_FINAL_SETUP']);source=fixture.read_text()
exec(compile(source[:source.index('layer = scene.view_layers[0]')],str(fixture),'exec'),globals())
import ast
from types import SimpleNamespace as NS
module=importlib.import_module(PACKAGE+'.export.mesh_converter')
baseline=Path(os.environ['SLC_MESH_WELD_BASELINE'])
node=next(n for n in ast.parse(baseline.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='convert')
namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(baseline),'exec'),module.__dict__,namespace);old=namespace['convert']
class Capture:
 def __init__(self):self.calls=[]
 def DefineMeshExt(self,**kwargs):self.calls.append(('mesh',kwargs))
 def SetMeshVertexAOV(self,*args):self.calls.append(('vertex-aov',args))
 def SetMeshTriangleAOV(self,*args):self.calls.append(('face-aov',args))
def equal(a,b):
 if isinstance(a,np.ndarray):
  assert isinstance(b,np.ndarray) and a.dtype==b.dtype and a.shape==b.shape
  assert a.tobytes()==b.tobytes()
 elif isinstance(a,dict):
  assert a.keys()==b.keys()
  for k in a:equal(a[k],b[k])
 elif isinstance(a,(list,tuple)):
  assert len(a)==len(b)
  for x,y in zip(a,b):equal(x,y)
 else:assert a==b,(a,b)
# A smooth bent grid with split seams, two material regions, corner/point
# colors, UV seams and generic scalar/vector attributes.
n=20;verts=[(x/n*2-1,y/n*2-1,.1*np.sin(x*.2)*np.cos(y*.3)) for y in range(n+1) for x in range(n+1)];faces=[]
for y in range(n):
 for x in range(n):
  i=y*(n+1)+x;faces.append((i,i+1,i+n+2,i+n+1))
mesh=bpy.data.meshes.new('weld-preservation-grid');mesh.from_pydata(verts,[],faces);mesh.update()
obj=bpy.data.objects.new('weld-preservation',mesh);scene.collection.objects.link(obj)
for m in list(bpy.data.materials)[:2]:mesh.materials.append(m)
for p in mesh.polygons:p.use_smooth=True;p.material_index=p.index%2
uv=mesh.uv_layers.new(name='UVMap');values=np.array([(loop.vertex_index%7/7,loop.vertex_index%11/11+(loop.index%3)*.1) for loop in mesh.loops],np.float32);uv.data.foreach_set('uv',values.ravel())
for domain in ('POINT','CORNER'):
 color=mesh.color_attributes.new(name='color-'+domain,type='FLOAT_COLOR',domain=domain)
 colors=np.random.default_rng(43).random((len(color.data),4),dtype=np.float32);color.data.foreach_set('color',colors.ravel())
for name,domain,kind,prop,width in [('point-value','POINT','FLOAT','value',1),('loop-value','CORNER','FLOAT','value',1),('face-value','FACE','FLOAT','value',1),('point-vector','POINT','FLOAT_VECTOR','vector',3)]:
 attr=mesh.attributes.new(name,kind,domain);data=np.linspace(-.2,.9,len(attr.data)*width,dtype=np.float32);attr.data.foreach_set(prop,data)
obj.superluxcore.enable_motion_blur=True
bpy.context.view_layer.update();depsgraph=bpy.context.evaluated_depsgraph_get();rows=[]
for normal_mode in ('smooth','flat','custom'):
 for p in mesh.polygons:p.use_smooth=normal_mode!='flat'
 if normal_mode=='custom':
  mesh.normals_split_custom_set([(0., .2 if loop.index%3 else -.2, .98) for loop in mesh.loops])
 mesh.update();bpy.context.view_layer.update()
 for instancing in (False,True):
  for motion in (False,True):
   exporter=NS(motion_blur_enabled=motion,stats=NS(export_time_meshes=NS(value=0.)))
   a,b=Capture(),Capture()
   args=(obj,'weld-preservation',depsgraph,None,False,instancing,obj.matrix_world,exporter)
   x=old(*args[:3],a,*args[4:]);y=module.convert(*args[:3],b,*args[4:])
   equal(a.calls,b.calls)
   # Compare every data member, including topology signatures/motion maps.
   equal(vars(x),vars(y))
   rows.append({'normal_mode':normal_mode,'instancing':instancing,'motion':motion,'native_calls':len(a.calls),'bit_exact_payloads_and_motion_metadata':True})
report={'passed':True,'blender':bpy.app.version_string,'cases':rows,'scope':SCOPE,'baseline_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
