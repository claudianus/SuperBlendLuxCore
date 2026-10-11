"""Real recorded VDB edits agree with fresh 720p CPU/Metal exports.

Checks transform/material edits and removal of a now-empty carrier. These
headless scene-edit tests do not claim GUI redraw or final convergence.
"""
import hashlib, importlib, json, os, tempfile, time
from pathlib import Path
import bpy
import numpy as np
import pysuperluxcore as slc

folder=Path(os.environ['SUPERLUXCORE_AUDIT_DIR']);folder.mkdir(parents=True,exist_ok=True)
package=next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
export=importlib.import_module(package+'.export')
recorded=importlib.import_module(package+'.export.recorded_scene').RecordedScene
persistent=importlib.import_module(package+'.export.caches.persistent_scene')
errors=importlib.import_module(package+'.utils.errorlog').SuperLuxCoreErrorLog
utils=importlib.import_module(package+'.utils')
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
s=bpy.context.scene
s.world=bpy.data.worlds.new('Live VDB white world');s.world.use_nodes=True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value=(1,1,1,1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=1
m=bpy.data.materials.new('Live VDB material');m.use_nodes=True;m.node_tree.nodes.clear()
out=m.node_tree.nodes.new('ShaderNodeOutputMaterial');p=m.node_tree.nodes.new('ShaderNodeVolumePrincipled')
p.inputs['Density'].default_value=.2;p.inputs['Color'].default_value=(0,0,0,1)
p.inputs['Density Attribute'].default_value='density';p.inputs['Color Attribute'].default_value=''
m.node_tree.links.new(p.outputs[0],out.inputs['Volume'])
data=bpy.data.volumes.new('Live VDB');data.filepath=str(Path(os.environ['SLC_VDB_FIXTURES'])/'named-attributes.vdb');data.grids.load();data.materials.append(m)
obj=bpy.data.objects.new('Live VDB',data);s.collection.objects.link(obj);data.render.space='OBJECT'
sequence_directory=None
sequence_live=os.environ.get('SLC_VDB_SEQUENCE_LIVE')=='1'
if sequence_live:
 sequence_directory=tempfile.TemporaryDirectory(prefix='slc-vdb-live-sequence-')
 for frame in [100,102]:
  os.link(data.filepath,Path(sequence_directory.name)/('smoke%04d.vdb'%frame))
 data.filepath=str(Path(sequence_directory.name)/'smoke0100.vdb')
 data.is_sequence=True;data.frame_start=10;data.frame_duration=3;data.frame_offset=99;data.sequence_mode='CLIP'
 s.frame_set(10)
bpy.ops.object.camera_add(location=(0,-6,0));s.camera=bpy.context.object
s.camera.rotation_euler=(1.5707963267948966,0,0);s.camera.data.type='ORTHO';s.camera.data.ortho_scale=4
s.render.resolution_x=1280;s.render.resolution_y=720;s.render.resolution_percentage=100
s.render.threads_mode='FIXED';s.render.threads=4
s.view_settings.view_transform='Standard';s.render.image_settings.file_format='OPEN_EXR';s.render.image_settings.color_depth='32'
cfg=s.superluxcore;assert cfg.config.spectral_enable
cfg.config.spectral_enable=False;cfg.config.engine='PATH';cfg.config.device=os.environ.get('SLC_VDB_DEVICE','CPU')
if cfg.config.device=='OCL':bpy.context.preferences.addons[package].preferences.gpu_backend='METAL'
cfg.config.path.use_clamping=False;cfg.config.path.auto_clamping=False
if os.environ.get('SLC_VDB_DISABLE_ADAPTIVE_DIAGNOSTIC')=='1':
 cfg.config.sobol_adaptive_strength=0
cfg.halt.enable=True;cfg.halt.use_samples=True;cfg.halt.samples=64
cfg.halt.use_noise_level=False;cfg.halt.use_noise_thresh=False;cfg.denoiser.enabled=False
s.render.engine='SUPERLUXCORE';bpy.context.view_layer.update()
records=[]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def fingerprint():
 return hashlib.sha256(json.dumps({'inputs':[[i.name,str(i.default_value)] for i in p.inputs if hasattr(i,'default_value')],
  'links':[[l.from_node.name,l.from_socket.name,l.to_node.name,l.to_socket.name] for l in m.node_tree.links],
  'matrix':[list(r) for r in obj.matrix_world],'space':data.render.space,
  'sequence':{'enabled':data.is_sequence,'frame':s.frame_current,'filepath':data.filepath}},sort_keys=True).encode()).hexdigest()
def save():
 (folder/'metrics.json').write_text(json.dumps({'complete':False,'records':records,'device':cfg.config.device,
  'resolution':[1280,720],'samples':64,'native_sha256':sha(slc.pysuperluxcore.__file__),
  'harness_sha256':sha(__file__),'volume_export_sha256':sha(importlib.import_module(package+'.export.volume').__file__),
  'sequence_live':sequence_live,'gui_redraw_verified':False,'full_goal_complete':False},indent=2)+'\n')
def fresh_session(seed=None):
 persistent.clear_all();ex=export.Exporter();scn,config=ex.export_scene(bpy.context.evaluated_depsgraph_get(),None)
 if seed is not None:config.Set(slc.Property('renderengine.seed',[seed]))
 return ex,scn,slc.RenderSession(slc.RenderConfig(config,scn))
def pixels(session,label):
 (folder/(label+'-scene.properties')).write_text(session.GetRenderConfig().GetScene().ToProperties().ToString())
 (folder/(label+'-config.properties')).write_text(session.GetRenderConfig().GetProperties().ToString())
 deadline=time.monotonic()+180
 while True:
  session.UpdateStats()
  # The configured halt is 64 eye SPP. Total pass also includes light paths
  # and can reach 64 while the restored volume has only a few eye samples.
  if session.GetStats().Get('stats.renderengine.pass.eye').GetInt()>=64:break
  assert time.monotonic()<deadline,'live VDB render timeout'
  time.sleep(.1)
 # A native worker can still be inside a multi-channel atomic splat after
 # the halt statistic is met. Read the final film only after all workers
 # finish; joining retains the session so subsequent scene edits can restart.
 session.WaitForDone();session.UpdateStats()
 values=np.empty(720*1280*3,np.float32)
 session.GetFilm().GetOutputFloat(slc.FilmOutputType.RGB,values,0,True)
 values=values.reshape(720,1280,3);assert np.isfinite(values).all()
 rgba=np.ones((720,1280,4),np.float32);rgba[...,:3]=values
 image=bpy.data.images.new(label,width=1280,height=720,float_buffer=True);image.pixels.foreach_set(rgba.ravel())
 image.save_render(str(folder/(label+'.exr')),scene=s)
 s.render.image_settings.file_format='PNG';png=folder/(label+'.png');image.save_render(str(png),scene=s)
 s.render.image_settings.file_format='OPEN_EXR';bpy.data.images.remove(image)
 return values,{'path':str(png),'sha256':sha(png),
  'workers_finished_before_read':True,
  'seed':session.GetRenderConfig().GetProperties().Get('renderengine.seed').GetInt(),
  'center_raw_std':float(values[240:480,480:720].std(dtype=np.float64)),
  'eye_spp':session.GetStats().Get('stats.renderengine.pass.eye').GetInt(),
  'light_spp':session.GetStats().Get('stats.renderengine.pass.light').GetInt(),
  'total_spp':session.GetStats().Get('stats.renderengine.pass').GetInt()}
def block_image(values):
 return values.reshape(45,16,80,16,3).mean(axis=(1,3),dtype=np.float64)
exporter,live_scene,live=fresh_session()
try:
 live.Start()
 cases=['initial','sequence-missing','sequence-restored','sequence-clipped'] if sequence_live else ['initial','moved-scaled','named-density-edit','empty-volume-output']
 for case in cases:
  if sequence_live:s.frame_set({'initial':10,'sequence-missing':11,'sequence-restored':12,'sequence-clipped':13}[case])
  elif case=='moved-scaled':obj.location=(.45,0,.1);obj.scale=(.65,.85,.75)
  elif case=='named-density-edit':p.inputs['Density Attribute'].default_value='artist_density';m.update_tag()
  elif case=='empty-volume-output':m.node_tree.links.remove(out.inputs['Volume'].links[0]);m.update_tag()
  bpy.context.view_layer.update();before=fingerprint();errors.clear(False)
  operations=[]
  if case!='initial':
   if not sequence_live and case!='moved-scaled':exporter.material_cache.changed_materials.add(m)
   flag=export.Change.OBJECT if sequence_live or case=='moved-scaled' else export.Change.MATERIAL
   jobs=exporter.update(bpy.context.evaluated_depsgraph_get(),None,flag)
   assert jobs and all(kind=='edit' for kind,_ in jobs),jobs
   operations=[op[0] for _,ops in jobs for op in ops]
   if case!='sequence-restored':assert 'DeleteObject' in operations,(case,operations)
   live.BeginSceneEdit()
   for _,ops in jobs:recorded.replay(live_scene,ops)
   if os.environ.get('SLC_VDB_PURGE_AFTER_EDIT')=='1':
    for method in ['RemoveUnusedMaterials','RemoveUnusedTextures','RemoveUnusedImageMaps']:
     getattr(live_scene,method)();operations.append(method)
   live.EndSceneEdit()
  a,apng=pixels(live,case+'-live')
  _,fresh_scene,fresh=fresh_session()
  try:
   fresh.Start();b,bpng=pixels(fresh,case+'-fresh')
   counts=(live_scene.GetObjectCount(),fresh_scene.GetObjectCount())
  finally:fresh.Stop()
  # Scene edits reset the sampler; compare with an independent fresh/fresh
  # repeat so sampling noise cannot be mistaken for a stale scene edit.
  # Same-seed repeats are correlated, especially at unchanged volume pixels.
  # Frame-seeded fresh exports otherwise exaggerate the live/fresh difference
  # against that correlated reference. Use an explicitly independent repeat.
  _,repeat_scene,repeat=fresh_session(seed=104729+1009*cases.index(case))
  try:
   repeat.Start();c,cpng=pixels(repeat,case+'-fresh-repeat')
  finally:repeat.Stop()
  assert fingerprint()==before and not errors.errors
  mean_a=a.mean(axis=(0,1),dtype=np.float64);mean_b=b.mean(axis=(0,1),dtype=np.float64)
  error=float(np.max(np.abs(mean_a-mean_b)/np.maximum(mean_b,1e-6)))
  mae=float(np.abs(a-b).mean(dtype=np.float64))
  repeat_mae=float(np.abs(b-c).mean(dtype=np.float64))
  block_mae=float(np.abs(block_image(a)-block_image(b)).mean())
  repeat_block_mae=float(np.abs(block_image(b)-block_image(c)).mean())
  passed=error<.003 and mae<1.5*repeat_mae+.001 and block_mae<1.5*repeat_block_mae+.0002
  empty=case in ['empty-volume-output','sequence-missing','sequence-clipped']
  assert counts[0]==counts[1]==(0 if empty else 1),(case,counts)
  if empty:assert np.max(np.abs(a-1))<1e-5
  records.append({'case':case,'device':cfg.config.device,'graph_sha256':before,'graph_unchanged':True,
   'live_fresh_relative_mean_error':error,'pixel_mae':mae,'fresh_repeat_pixel_mae':repeat_mae,
   'block16_mae':block_mae,'fresh_repeat_block16_mae':repeat_block_mae,'object_counts':counts,
   'recorded_operations':operations,'images':[apng,bpng,cpng],'passed':passed})
  save();print('VDB_LIVE_EDIT_PASS',case,error,mae,counts,flush=True)
  assert passed,(case,error,mae,repeat_mae,block_mae,repeat_block_mae)
  del a,b,c
finally:
 live.Stop();persistent.clear_all();cfg.config.spectral_enable=True
 if sequence_directory is not None:sequence_directory.cleanup()
proof=json.loads((folder/'metrics.json').read_text());proof['complete']=True
proof['temporary_sequence_removed']=sequence_directory is None or not Path(sequence_directory.name).exists()
(folder/'metrics.json').write_text(json.dumps(proof,indent=2)+'\n')
print('VDB_LIVE_EDIT_COMPLETE_REQUIRES_DIRECT_REVIEW',cfg.config.device,flush=True)
