"""벡터 반사·굴절·감싸기와 Mix 계수의 실제 CPU·GPU 영상을 검증한다."""
import os
from pathlib import Path
import bpy
import numpy as np
try:
    bpy.context.scene.render.engine='SUPERLUXCORE'
except TypeError:
    bpy.ops.preferences.addon_enable(module='superluxcore')
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
s=bpy.context.scene; s.world=bpy.data.worlds.new('검증 월드'); s.world.use_nodes=True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0
bpy.ops.mesh.primitive_plane_add(size=30); plane=bpy.context.object
m=bpy.data.materials.new('벡터 검증'); m.use_nodes=True; plane.data.materials.append(m)
bpy.ops.object.camera_add(location=(0,0,3)); cam=bpy.context.object; cam.data.lens=65; s.camera=cam
s.render.resolution_x=128; s.render.resolution_y=72; s.render.resolution_percentage=100
s.view_settings.view_transform='Standard'; s.render.image_settings.file_format='OPEN_EXR'; s.render.image_settings.color_depth='32'
s.cycles.samples=32; s.cycles.use_denoising=False
folder=Path(os.environ.get('SUPERLUXCORE_VALIDATION_DIR','/tmp/superluxcore-vector-regression')); folder.mkdir(parents=True,exist_ok=True)
def graph(case):
    n=m.node_tree.nodes; l=m.node_tree.links; n.clear()
    out=n.new('ShaderNodeOutputMaterial'); em=n.new('ShaderNodeEmission'); pos=n.new('ShaderNodeNewGeometry')
    source=n.new('ShaderNodeVectorMath'); source.operation='ADD'; l.new(pos.outputs['Position'],source.inputs[0]); source.inputs[1].default_value=(.7,-.4,-.8)
    if case[0]=='VECTOR':
        op,normal,eta=case[1:]; node=n.new('ShaderNodeVectorMath'); node.operation=op
        l.new(source.outputs[0],node.inputs[0]); node.inputs[1].default_value=normal
        node.inputs[2].default_value=(-.2,-.5,.25)
        if op=='REFRACT': node.inputs['Scale'].default_value=eta
        result=node.outputs['Vector']
    else:
        _,kind,mode,clamp,factor=case
        node=n.new('ShaderNodeMix'); node.data_type=kind; node.factor_mode=mode; node.clamp_factor=clamp
        def socket(name,typ): return next(v for v in node.inputs if v.name==name and v.bl_idname.startswith(typ) and v.enabled)
        socket('Factor','NodeSocketVector' if mode=='NON_UNIFORM' else 'NodeSocketFloat').default_value=factor
        typ='NodeSocketVector' if kind=='VECTOR' else 'NodeSocketFloat'
        if kind=='VECTOR':
            l.new(source.outputs[0],socket('A',typ)); socket('B',typ).default_value=(.2,.6,-.1)
        else:
            sep=n.new('ShaderNodeSeparateXYZ'); l.new(source.outputs[0],sep.inputs[0]); l.new(sep.outputs['X'],socket('A',typ)); socket('B',typ).default_value=.2
        result=next(v for v in node.outputs if v.enabled and v.bl_idname.startswith(typ))
    scale=n.new('ShaderNodeVectorMath'); scale.operation='SCALE'; scale.inputs['Scale'].default_value=.1; l.new(result,scale.inputs[0])
    offset=n.new('ShaderNodeVectorMath'); offset.operation='ADD'; offset.inputs[1].default_value=(.5,.5,.5); l.new(scale.outputs[0],offset.inputs[0]); l.new(offset.outputs[0],em.inputs['Color']); l.new(em.outputs[0],out.inputs['Surface'])
    bpy.context.view_layer.update()
def render(engine,tag):
    s.render.engine=engine
    if engine=='SUPERLUXCORE':
        cfg=s.superluxcore; cfg.config.engine='PATH'; cfg.config.device=os.environ.get('DEV','CPU'); cfg.config.spectral_enable=False
        cfg.halt.enable=True; cfg.halt.use_time=False; cfg.halt.use_noise_thresh=False; cfg.halt.use_samples=True; cfg.halt.samples=32
        cfg.config.path.use_clamping=False; cfg.config.path.auto_clamping=False; cfg.denoiser.enabled=False; cam.data.superluxcore.imagepipeline.tonemapper.enabled=False
    path=folder/(tag+'_'+os.environ.get('DEV','CPU')+'_'+engine+'.exr'); s.render.filepath=str(path); bpy.ops.render.render(write_still=True)
    im=bpy.data.images.load(str(path),check_existing=False); a=np.array(im.pixels[:],dtype=np.float32).reshape(72,128,4)[4:-4,4:-4,:3]; bpy.data.images.remove(im); return a
cases=[('VECTOR','REFLECT',(0,0,2),0),('VECTOR','REFLECT',(0,0,0),0),('VECTOR','REFRACT',(0,0,2),.66),('VECTOR','REFRACT',(0,0,2),2),('VECTOR','REFRACT',(0,0,0),.66),('VECTOR','WRAP',(1,2,3),0),('VECTOR','WRAP',(-.2,-.5,.25),0)]
operations=bpy.types.ShaderNodeVectorMath.bl_rna.properties['operation'].enum_items.keys()
if 'ROUND' in operations: cases.append(('VECTOR','ROUND',(0,0,0),0))
for kind,mode in (('FLOAT','UNIFORM'),('VECTOR','UNIFORM'),('VECTOR','NON_UNIFORM')):
    for clamp in (False,True):
        for factor in (-.5,1.5):
            cases.append(('MIX',kind,mode,clamp,(factor,.3,1.2) if mode=='NON_UNIFORM' else factor))
for index,case in enumerate(cases):
    graph(case); tag=str(index); cy=render('CYCLES',tag); lx=render('SUPERLUXCORE',tag); error=np.abs(cy-lx)
    print('VECTOR',case,'MAE',error.mean(),'P99',np.quantile(error,.99),flush=True)
    # 감싸기·반올림 경계의 불연속은 서로 다른 샘플 위치로 소수 픽셀이 달라진다.
    percentile=.95 if case[0]=='VECTOR' and case[1] in {'WRAP','ROUND'} else .99
    assert np.isfinite(lx).all() and error.mean()<.0002 and np.quantile(error,percentile)<.001, (case,error.mean(),error.max())
print('벡터·Mix 영상 검사',len(cases),'개 통과',flush=True)
