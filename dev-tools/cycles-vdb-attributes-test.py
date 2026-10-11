"""Unchanged Cycles VDB shaders: named fields, missing fields and instances.

Exact grid-edge reconstruction and Generated volume context remain separate
native-engine work. RGB gates compare transport meaning; spectral frames
are retained for direct review, not pixel equality with RGB Cycles.
"""
import hashlib, importlib, json, os
from pathlib import Path
import bpy
import numpy as np
import pysuperluxcore
from mathutils import Matrix, Vector

folder=Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True,exist_ok=True)
fixtures=Path(os.environ['SLC_VDB_FIXTURES'])
package=next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module=='superluxcore')
reader=importlib.import_module(package+'.export.cycles_node_reader')
volume_export=importlib.import_module(package+'.export.volume')

def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def graph(material):
 def tree_data(tree):
  nodes=[]
  for node in tree.nodes:
   inputs=[]
   for s in node.inputs:
    if not hasattr(s,'default_value'):continue
    v=s.default_value
    if not isinstance(v,(float,int,str,bool)):v=list(v)
    inputs.append([s.identifier,v])
   extra={}
   if node.bl_idname=='ShaderNodeMath':extra['operation']=node.operation
   if node.bl_idname=='ShaderNodeAttribute':extra['attribute']=node.attribute_name
   if node.bl_idname=='ShaderNodeGroup':extra['tree']=tree_data(node.node_tree)
   nodes.append([node.name,node.bl_idname,inputs,extra])
  return [sorted(nodes),sorted([l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier] for l in tree.links)]
 return hashlib.sha256(json.dumps(tree_data(material.node_tree),sort_keys=True).encode()).hexdigest()

bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
scene.world=bpy.data.worlds.new('VDB reference world');scene.world.use_nodes=True
background=scene.world.node_tree.nodes['Background']
background.inputs['Color'].default_value=(1,1,1,1)
background.inputs['Strength'].default_value=1
bpy.ops.object.camera_add(location=(0,-7,0))
scene.camera=bpy.context.object;scene.camera.rotation_euler=(1.5707963267948966,0,0)
scene.camera.data.type='ORTHO';scene.camera.data.ortho_scale=4
scene.render.resolution_x=1280;scene.render.resolution_y=720;scene.render.resolution_percentage=100
scene.render.threads_mode='FIXED';scene.render.threads=int(os.environ.get('SLC_VDB_THREADS','4'))
assert 1<=scene.render.threads<=8
samples=int(os.environ.get('SLC_VDB_SAMPLES','64'));assert 1<=samples<=256
scene.cycles.samples=samples;scene.cycles.use_denoising=False
scene.view_settings.view_transform='Standard'
scene.render.film_transparent=False
scene.render.image_settings.color_mode='RGB'
bpy.context.preferences.filepaths.save_version=0
slc=scene.superluxcore
slc.config.engine='PATH';slc.config.path.use_clamping=False;slc.config.path.auto_clamping=False
slc.halt.enable=True;slc.halt.use_samples=True;slc.halt.samples=samples;slc.denoiser.enabled=False
assert slc.config.spectral_enable
if os.environ.get('SLC_VDB_GPU_ONLY')=='1':slc.devices.use_native_cpu=False

objects=[]
def make_object(name,file,material):
 data=bpy.data.volumes.new(name+' data');data.filepath=str(fixtures/file);data.grids.load()
 obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);data.materials.append(material)
 data.render.space='WORLD';objects.append(obj);return obj

def material_for(case):
 m=bpy.data.materials.new(case);m.use_nodes=True
 t=m.node_tree;t.nodes.clear();out=t.nodes.new('ShaderNodeOutputMaterial');p=t.nodes.new('ShaderNodeVolumePrincipled')
 p.inputs['Density'].default_value=.2;p.inputs['Color'].default_value=(0,0,0,1)
 p.inputs['Density Attribute'].default_value='density';p.inputs['Color Attribute'].default_value=''
 p.inputs['Temperature Attribute'].default_value='temperature'
 t.links.new(p.outputs[0],out.inputs['Volume'])
 return m,p

# Metadata and socket tests use real VDB files and Blender RNA. No production
# writes or mocked grid reader. Verify independent affine mappings at an
# interior index point and separate namespaces for shared group nodes.
probe_mat,probe_node=material_for('Attribute export probe')
probe_obj=make_object('Attribute export probe','named-attributes.vdb',probe_mat)
probe=[]
for names in [('density','color','temperature'),('artist_density','artist_color','artist_temperature'),('missing_density','missing_color','missing_temperature')]:
 for s,n in zip(['Density Attribute','Color Attribute','Temperature Attribute'],names):probe_node.inputs[s].default_value=n
 probe_node.inputs['Blackbody Intensity'].default_value=1
 props=pysuperluxcore.Properties()
 context=volume_export._GridContext(probe_obj,'probe_instance',scene,Matrix.Translation((2,1,0)))
 with volume_export._with_grid_context(context):
  defs=volume_export._material_volume_defs(probe_obj,'probe_instance',props)
  assert reader._socket(probe_node.inputs['Density Attribute'],props,probe_mat,probe_obj.name,None)==names[0]
  vi=probe_mat.node_tree.nodes.new('ShaderNodeVolumeInfo')
  assert reader._node(vi,vi.outputs['Flame'],props,probe_mat,obj_name=probe_obj.name)==0
  probe_mat.node_tree.nodes.remove(vi)
 requested={props.Get(n).GetString() for n in props.GetAllNames('scene.textures.') if n.endswith('.openvdb.grid')}
 expected=set(names) if not names[0].startswith('missing') else set()
 assert requested==expected and context.used==expected,(requested,expected)
 assert volume_export.grid_context_key()==''
 probe.append({'attribute_names':names,'grids':sorted(requested),'missing_principled_is_neutral':not expected,'complete':True})
probe_obj.hide_render=True

# Test fixed Volume Info names on a file with no standard grids.
missing_mat,_=material_for('Missing standard names probe')
missing_obj=make_object('Missing standard names probe','missing-standard-density.vdb',missing_mat)
vi=missing_mat.node_tree.nodes.new('ShaderNodeVolumeInfo')
ctx=volume_export._GridContext(missing_obj,'missing_fixed',scene,missing_obj.matrix_world)
with volume_export._with_grid_context(ctx):
 for output in ['Density','Color','Flame','Temperature']:
  value=reader._node(vi,vi.outputs[output],pysuperluxcore.Properties(),missing_mat,obj_name=missing_obj.name)
  assert value==([0.,0.,0.] if output=='Color' else 0.)
assert not ctx.used
missing_obj.hide_render=True

# Different per-grid transforms must not reuse density's AABB, and use the
# evaluated instance matrix, not bpy.data.objects[name].matrix_world.
trans_mat,_=material_for('Independent affine probe')
trans_obj=make_object('Independent affine probe','independent-grid-transforms.vdb',trans_mat)
instance_matrix=Matrix.Translation((3,-1,.2))@Matrix.Rotation(.31,4,'Z')@Matrix.Diagonal((1.3,.8,1.1,1))
ctx=volume_export._GridContext(trans_obj,'different_instance',scene,instance_matrix)
points=[]
with volume_export._with_grid_context(ctx):
 for grid in ['density','artist_density']:
  defs=volume_export.attribute_grid_defs(grid,trans_obj.name)
  info=ctx.info(grid);bounds=info[1];a=volume_export._index_to_object(info)
  index=Vector((7,11,13));world=instance_matrix@a@index
  # matrix_to_list exports column-major, as the native property parser does.
  flat=defs['mapping.transformation'];mapping=Matrix([flat[i:i+4] for i in range(0,16,4)]).transposed()
  got=mapping@world;expected=Vector([(index[i]-bounds[i])/(bounds[i+3]-bounds[i]) for i in range(3)])
  assert (got-expected).length<2e-6,(grid,got,expected)
  points.append({'grid':grid,'world':list(world),'normalized':list(got),'expected':list(expected)})
trans_obj.hide_render=True

dead_mat,dead_p=material_for('Dead explicit attribute topology probe')
dead_obj=make_object('Dead explicit attribute topology probe','named-attributes.vdb',dead_mat)
dead_p.inputs['Density'].default_value=0;dead_p.inputs['Blackbody Intensity'].default_value=1
dead_p.inputs['Temperature Attribute'].default_value='absent_temperature'
dead_vi=dead_mat.node_tree.nodes.new('ShaderNodeVolumeInfo')
dead_zero=dead_mat.node_tree.nodes.new('ShaderNodeMath');dead_zero.operation='MULTIPLY';dead_zero.inputs[1].default_value=0
dead_add=dead_mat.node_tree.nodes.new('ShaderNodeMath');dead_add.operation='ADD';dead_add.inputs[1].default_value=7000
dead_mat.node_tree.links.new(dead_vi.outputs['Density'],dead_zero.inputs[0])
dead_mat.node_tree.links.new(dead_zero.outputs[0],dead_add.inputs[0])
dead_mat.node_tree.links.new(dead_add.outputs[0],dead_p.inputs['Temperature'])
dead_ctx=volume_export._GridContext(dead_obj,'dead_explicit_grid',scene,dead_obj.matrix_world)
dead_props=pysuperluxcore.Properties()
with volume_export._with_grid_context(dead_ctx):
 dead_shader=volume_export._material_volume_defs(dead_obj,'dead_explicit_grid',dead_props)
assert dead_ctx.used=={'density'} and not volume_export._used_shader_grids(dead_props,dead_shader,dead_ctx)
dead_obj.hide_render=True

identity={'complete':False,'fixtures':{p.name:sha(p) for p in fixtures.glob('*.vdb')},'resolution':[1280,720],'samples':samples,'cpu_threads':scene.render.threads,
 'native_sha256':sha(pysuperluxcore.pysuperluxcore.__file__),'reader_sha256':sha(reader.__file__),
 'volume_export_sha256':sha(volume_export.__file__),'harness_sha256':sha(__file__),
 'probes':probe,'affine_points':points,'records':[],'comparisons':[],
 'full_goal_complete':False,'production_convergence_acceptance':False}
def save(): (folder/'metrics.json').write_text(json.dumps(identity,indent=2)+'\n')
save();print('VDB_ATTRIBUTE_EXPORT_PROBES_PASS',flush=True)
if os.environ.get('SLC_VDB_PROBE_ONLY')=='1':
 identity['complete']=True;save();raise SystemExit(0)

cases=os.environ.get('SLC_VDB_CASES','standard-density,artist-density,missing-density,artist-color,shared-instances,affine-grid,artist-temperature,missing-temperature').split(',')
for case in cases:
 for obj in objects:obj.hide_render=True
 material,p=material_for(case);tree=material.node_tree
 file='affine-grid.vdb' if case=='affine-grid' else 'independent-grid-transforms.vdb' if case=='shared-instances' else 'named-attributes.vdb'
 obj=make_object(case,file,material)
 if case in ['artist-density','artist-color','shared-instances','affine-grid']:p.inputs['Density Attribute'].default_value='artist_density'
 if case=='missing-density':
  p.inputs['Density Attribute'].default_value='absent_density';p.inputs['Color Attribute'].default_value='color'
 if case=='artist-color':
  p.inputs['Color'].default_value=(1,1,1,1);p.inputs['Color Attribute'].default_value='artist_color';p.inputs['Density'].default_value=.25
 background.inputs['Strength'].default_value=1
 scene.camera.location=(0,-7,0);scene.camera.data.ortho_scale=4
 if case=='shared-instances':
  # One group tree, material and Volume datablock used by two actual collection
  # instances. The originals live in an unlinked source collection.
  group=bpy.data.node_groups.new('Shared volume group','ShaderNodeTree')
  group.interface.new_socket(name='Volume',in_out='OUTPUT',socket_type='NodeSocketShader')
  gp=group.nodes.new('ShaderNodeVolumePrincipled');go=group.nodes.new('NodeGroupOutput')
  gp.inputs['Density'].default_value=.2;gp.inputs['Color'].default_value=(0,0,0,1)
  gp.inputs['Density Attribute'].default_value='artist_density';gp.inputs['Color Attribute'].default_value=''
  group.links.new(gp.outputs[0],go.inputs['Volume'])
  tree.nodes.remove(p);g=tree.nodes.new('ShaderNodeGroup');g.node_tree=group
  tree.links.new(g.outputs[0],tree.nodes.get('Material Output').inputs['Volume'])
  source=bpy.data.collections.new('VDB source collection')
  scene.collection.objects.unlink(obj);source.objects.link(obj)
  obj.data.render.space='OBJECT'
  for i,(location,scale,angle) in enumerate([((-3,0,-1.2),(.8,.8,.8),-.2),((.1,0,-1.2),(.65,.9,.75),.35)]):
   inst=bpy.data.objects.new('VDB collection instance '+str(i),None);inst.instance_type='COLLECTION';inst.instance_collection=source
   scene.collection.objects.link(inst);inst.location=location;inst.scale=scale;inst.rotation_euler.z=angle;objects.append(inst)
  scene.camera.data.ortho_scale=8
 thermal=case in ['artist-temperature','missing-temperature']
 if thermal:
  background.inputs['Strength'].default_value=0
  p.inputs['Density'].default_value=0 if case=='artist-temperature' else .2
  p.inputs['Blackbody Intensity'].default_value=1
  p.inputs['Temperature'].default_value=7000
  p.inputs['Temperature Attribute'].default_value='artist_temperature' if case=='artist-temperature' else 'absent_temperature'
  # Zero-extinction emission uses temperature topology. The missing-temperature
  # test retains real density; a dead Density*0 cannot request VDB topology.
  vi=tree.nodes.new('ShaderNodeVolumeInfo');zero=tree.nodes.new('ShaderNodeMath');zero.operation='MULTIPLY';zero.inputs[1].default_value=0
  add=tree.nodes.new('ShaderNodeMath');add.operation='ADD';add.inputs[1].default_value=7000
  tree.links.new(vi.outputs['Density'],zero.inputs[0]);tree.links.new(zero.outputs[0],add.inputs[0]);tree.links.new(add.outputs[0],p.inputs['Temperature'])
  control_attribute=tree.nodes.new('ShaderNodeAttribute');control_attribute.attribute_name='artist_temperature'
  control_scale=tree.nodes.new('ShaderNodeMath');control_scale.operation='MULTIPLY';control_scale.inputs[1].default_value=7000
  tree.links.new(control_attribute.outputs['Fac'],control_scale.inputs[0])
 bpy.context.view_layer.update()
 fingerprint=graph(material)
 scene.render.engine='CYCLES';bpy.ops.wm.save_as_mainfile(filepath=str(folder/(case+'.blend')))
 modes=[('CYCLES','CPU',False),('SUPERLUXCORE','CPU',False),('SUPERLUXCORE','OCL',False)]
 if case in ['artist-color','shared-instances','affine-grid','artist-temperature','missing-temperature'] and os.environ.get('SLC_VDB_DISABLE_SPECTRAL')!='1':
  modes.extend([('SUPERLUXCORE','CPU',True),('SUPERLUXCORE','OCL',True)])
 if os.environ.get('SLC_VDB_SPECTRAL_ONLY')=='1':modes=[m for m in modes if m[0]=='CYCLES' or m[2]]
 if os.environ.get('SLC_VDB_CPU_ONLY')=='1':modes=[m for m in modes if m[1]=='CPU']
 if os.environ.get('SLC_VDB_GPU_ONLY')=='1':modes=[m for m in modes if m[0]=='CYCLES' or m[1]=='OCL']
 reference=None
 for engine,device,spectral in modes:
  scene.render.engine=engine
  if engine=='SUPERLUXCORE':
   slc.config.device=device;slc.config.spectral_enable=spectral
   if device=='OCL':bpy.context.preferences.addons[package].preferences.gpu_backend='METAL'
  label=case+'-'+engine.lower()+'-'+device.lower()+('-spectral' if spectral else '-rgb')
  variants=['field','explicit-attribute-control'] if thermal or case=='artist-color' else ['field']
  field_mean=None
  for variant in variants:
   if variant=='explicit-attribute-control':
    if thermal:
     p.inputs['Temperature Attribute'].default_value=''
     if case=='artist-temperature':tree.links.new(control_scale.outputs[0],p.inputs['Temperature'])
    else:
     p.inputs['Color Attribute'].default_value=''
     p.inputs['Color'].default_value=(.2,.5,.8,1)
   expected_graph=graph(material)
   if variant=='field':assert expected_graph==fingerprint
   scene.render.image_settings.file_format='OPEN_EXR';scene.render.image_settings.color_depth='32'
   scene.render.filepath=str(folder/(label+'-'+variant+'.exr'))
   bpy.ops.render.render(write_still=True)
   assert graph(material)==expected_graph
   image=bpy.data.images.load(scene.render.filepath,check_existing=False)
   pixels=np.asarray(image.pixels[:],dtype=np.float32).reshape(720,1280,4)[...,:3];bpy.data.images.remove(image)
   assert np.isfinite(pixels).all(),label
   # Average the full frame for transformed instances; erode the other slab
   # interiors to avoid spatial reconstruction/silhouette filter differences.
   body=pixels if case=='shared-instances' else pixels[130:590,410:840]
   mean=body.mean(axis=(0,1),dtype=np.float64)
   if thermal:assert np.min(mean)>1e-5,(label,variant,'black emission frame',mean)
   scene.render.image_settings.file_format='PNG';png=folder/(label+'-'+variant+'.png')
   bpy.data.images['Render Result'].save_render(str(png),scene=scene)
   identity['records'].append({'case':case,'engine':engine,'device':device,'spectral':spectral,'variant':variant,
    'graph_sha256':expected_graph,'authored_graph_unchanged':True,'mean':mean.tolist(),'finite':True,
    'png':str(png),'png_sha256':sha(png)})
   if variant=='field':
    field_mean=mean
    if engine=='CYCLES':reference=mean
    elif not spectral and not thermal:
     error=float(np.max(np.abs(mean-reference)/np.maximum(reference,1e-6)))
     limit=.03 if case!='artist-color' else .05
     identity['comparisons'].append({'case':case,'engine':engine,'device':device,'kind':'cycles-rgb-transport-mean',
      'relative_error':error,'limit':limit,'passed':error<limit})
     save()
     # Keep the original failed five-percent transport diagnostic visible.
     # An independently authored equivalent shader isolates field conversion
     # from any wider colored-volume transport difference.
     if case!='artist-color':assert error<limit,(label,mean,reference,error)
   else:
    error=float(np.max(np.abs(mean-field_mean)/np.maximum(field_mean,1e-6)))
    identity['comparisons'].append({'case':case,'engine':engine,'device':device,'spectral':spectral,
     'kind':'independent-authored-attribute-temperature-control' if thermal else 'independent-authored-constant-color-control','relative_error':error,'limit':.02,'passed':error<.02})
    save();assert error<.02,(label,mean,field_mean,error)
    if thermal:
     p.inputs['Temperature Attribute'].default_value='artist_temperature' if case=='artist-temperature' else 'absent_temperature'
     tree.links.new(add.outputs[0],p.inputs['Temperature'])
    else:
     p.inputs['Color Attribute'].default_value='artist_color'
     p.inputs['Color'].default_value=(1,1,1,1)
   save();print('VDB_FRAME_PASS',label,variant,mean,flush=True)
   del pixels,body
 slc.config.spectral_enable=True
 assert graph(material)==fingerprint
identity['complete']=True
identity['remaining_colored_volume_transport_gap']=[x for x in identity['comparisons'] if not x['passed']]
save()
print('VDB_ATTRIBUTE_RENDER_COMPLETE_REQUIRES_DIRECT_REVIEW',len(identity['records']),flush=True)
