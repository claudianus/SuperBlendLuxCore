"""Existing Cycles Bump direction contract, including linked inputs and data use."""
import importlib, importlib.metadata, json, os, math
from pathlib import Path
import bpy
import numpy as np
native=importlib.import_module('pysuperluxcore')
assert native.Version()==importlib.metadata.version('pysuperluxcore')
package=next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
log=importlib.import_module(package+'.utils.errorlog').SuperLuxCoreErrorLog
folder=Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR','/tmp/slc-bump-contract'));folder.mkdir(parents=True,exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
if os.environ.get('SUPERLUXCORE_AUDIT_SMOOTH') == '1':
 bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=32,radius=.8)
 plane=bpy.context.object
 for face in plane.data.polygons:face.use_smooth=True
else:
 bpy.ops.mesh.primitive_plane_add(size=2)
 plane=bpy.context.object;plane.scale.y=9/16
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
mat=bpy.data.materials.new('Existing Cycles Bump');mat.use_nodes=True;plane.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0,0,4));s=bpy.context.scene;s.camera=bpy.context.object
s.camera.data.type='ORTHO';s.camera.data.ortho_scale=2
s.render.resolution_x,s.render.resolution_y=1280,720;s.render.resolution_percentage=100
s.render.image_settings.file_format='OPEN_EXR';s.render.image_settings.color_depth='32';s.render.image_settings.color_mode='RGBA'
s.view_settings.view_transform='Standard';s.cycles.samples=16;s.cycles.use_denoising=False
cfg=s.superluxcore;cfg.config.device='OCL' if os.environ.get('DEV')=='OCL' else 'CPU'
if cfg.config.device=='OCL':bpy.context.preferences.addons[package].preferences.gpu_backend='METAL'
cfg.config.spectral_enable=os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL')=='1'
cfg.halt.enable=cfg.halt.use_samples=True;cfg.halt.samples=16;cfg.halt.use_noise_level=False;cfg.halt.use_noise_thresh=False
cfg.denoiser.enabled=False;cfg.config.path.use_clamping=False;cfg.config.path.auto_clamping=False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled=False
layer=s.view_layers[0];layer.use_pass_normal=True
ct=bpy.data.node_groups.new('Existing Cycles Normal compositor','CompositorNodeTree')
ct.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
rl=ct.nodes.new('CompositorNodeRLayers');rl.layer=layer.name;co=ct.nodes.new('NodeGroupOutput');ct.links.new(rl.outputs['Normal'],co.inputs['Image'])
s.compositing_node_group=ct;s.render.use_compositing=True
conditions=('constant_distance','linked_distance','spatial_distance','linked_normal','chained','vector_math','mix_output','strength_two','strength_negative','invert','backface','filter_half','filter_two','backface_normal','backface_chain','backface_math','backface_mix','filter_chain')
if cfg.config.spectral_enable:conditions=('spatial_distance','linked_normal','chained','vector_math','mix_output','backface')
if os.environ.get('SUPERLUXCORE_AUDIT_CASES'):conditions=tuple(os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','))
records=[]
for condition in conditions:
 plane.rotation_euler.x=math.pi if condition.startswith('backface') else 0.;bpy.context.view_layer.update()
 nodes,links=mat.node_tree.nodes,mat.node_tree.links;nodes.clear()
 uv=nodes.new('ShaderNodeTexCoord');split=nodes.new('ShaderNodeSeparateXYZ');links.new(uv.outputs['UV'],split.inputs[0])
 height=nodes.new('ShaderNodeMath');height.operation='MULTIPLY';links.new(split.outputs['X'],height.inputs[0]);links.new(split.outputs['X'],height.inputs[1])
 bump=nodes.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.2;bump.inputs['Strength'].default_value=.8
 links.new(height.outputs[0],bump.inputs['Height']);value=bump.outputs['Normal']
 if condition=='linked_distance':
  distance=nodes.new('ShaderNodeValue');distance.outputs[0].default_value=.2;links.new(distance.outputs[0],bump.inputs['Distance'])
 if condition=='spatial_distance':
  distance=nodes.new('ShaderNodeMath');distance.operation='MULTIPLY_ADD';distance.inputs[1].default_value=.3;distance.inputs[2].default_value=.05
  links.new(split.outputs['Y'],distance.inputs[0]);links.new(distance.outputs[0],bump.inputs['Distance'])
 if condition in {'linked_normal','mix_output','backface_normal','backface_mix'}:
  nm=nodes.new('ShaderNodeNormalMap');nm.inputs['Color'].default_value=(.65,.6,.9,1.)
  if condition in {'linked_normal','backface_normal'}:links.new(nm.outputs['Normal'],bump.inputs['Normal'])
  else:
   mix=nodes.new('ShaderNodeMixRGB');mix.inputs[0].default_value=.35;links.new(value,mix.inputs[1]);links.new(nm.outputs['Normal'],mix.inputs[2]);value=mix.outputs[0]
 if condition in {'chained','backface_chain','filter_chain'}:
  first=nodes.new('ShaderNodeBump');first.inputs['Distance'].default_value=.12;first.inputs['Strength'].default_value=.7
  links.new(split.outputs['Y'],first.inputs['Height']);links.new(first.outputs['Normal'],bump.inputs['Normal'])
  if condition=='filter_chain':
   first.inputs['Filter Width'].default_value=.5;bump.inputs['Filter Width'].default_value=2.
   first.inputs['Distance'].default_value=.012;bump.inputs['Distance'].default_value=.012
   for source,target in ((split.outputs['Y'],first.inputs['Height']),(split.outputs['X'],bump.inputs['Height'])):
    phase=nodes.new('ShaderNodeMath');phase.operation='MULTIPLY';phase.inputs[1].default_value=20.;links.new(source,phase.inputs[0])
    wave=nodes.new('ShaderNodeMath');wave.operation='SINE';links.new(phase.outputs[0],wave.inputs[0]);links.new(wave.outputs[0],target)
 if condition in {'vector_math','backface_math'}:
  arithmetic=nodes.new('ShaderNodeVectorMath');arithmetic.operation='NORMALIZE';links.new(value,arithmetic.inputs[0]);value=arithmetic.outputs[0]
 if condition=='strength_two':bump.inputs['Strength'].default_value=2.
 if condition=='strength_negative':bump.inputs['Strength'].default_value=-.5
 if condition=='invert':bump.invert=True
 if condition in {'filter_half','filter_two'}:bump.inputs['Filter Width'].default_value=.5 if condition=='filter_half' else 2.
 surface=nodes.new('ShaderNodeBsdfDiffuse');links.new(value,surface.inputs['Normal']);out=nodes.new('ShaderNodeOutputMaterial');links.new(surface.outputs[0],out.inputs['Surface'])
 snapshot=[(n.bl_idname,n.name,[(i.name,i.is_linked,tuple(i.default_value) if hasattr(i.default_value,'__len__') else i.default_value) for i in n.inputs if hasattr(i,'default_value')]) for n in nodes]
 pixels={}
 for engine in ('CYCLES','SUPERLUXCORE'):
  s.render.engine=engine;log.clear(False);path=folder/(condition+'_'+engine+'.exr');s.render.filepath=str(path)
  bpy.ops.render.render(write_still=True);im=bpy.data.images.load(str(path),check_existing=False)
  pixels[engine]=np.asarray(im.pixels[:],dtype=np.float32).reshape(720,1280,4)[8:-8,8:-8,:3].copy();bpy.data.images.remove(im)
  s.render.image_settings.file_format='PNG';bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')),scene=s);s.render.image_settings.file_format='OPEN_EXR'
 assert snapshot==[(n.bl_idname,n.name,[(i.name,i.is_linked,tuple(i.default_value) if hasattr(i.default_value,'__len__') else i.default_value) for i in n.inputs if hasattr(i,'default_value')]) for n in nodes]
 delta=np.abs(pixels['CYCLES']-pixels['SUPERLUXCORE'])
 rec={'condition':condition,'native_version':native.Version(),'spectral':bool(cfg.config.spectral_enable),'finite':bool(np.isfinite(pixels['SUPERLUXCORE']).all()),'mae':float(delta.mean()),'p99':float(np.quantile(delta,.99)),'errors':[e.message for e in log.errors],'warnings':[w.message for w in log.warnings]}
 rec['passed']=rec['finite'] and not rec['errors'] and rec['mae']<.005 and all(w=='Light-probe-volume backface culling is Eevee-only - ignored' for w in rec['warnings'])
 records.append(rec);(folder/'metrics.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');print('Bump contract check',rec,flush=True)
 assert rec['finite'] and not rec['errors'],rec
 if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE')!='1':assert rec['passed'],rec
print('Bump contract checks complete',len(records),sum(r['passed'] for r in records),flush=True)
