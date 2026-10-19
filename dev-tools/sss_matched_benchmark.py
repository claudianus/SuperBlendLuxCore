"""Matched CPU/raw SSS fixture, finite per-pixel budget, no denoising/clamping.

Both engines use the same authored scene and optical inputs, RGB, thread
count and pixel filter. Their BSSRDF parameterizations are distinct: measure
convergence against an independent reference for each model, never treat a
Cycles image as ground truth for the OpenPBR bulk transport.
"""
import importlib
import math
import os
from pathlib import Path
import time

fixture=Path(__file__).with_name('sss_blender_test.py')
prefix=fixture.read_text().split('# Verify the real Blender RNA state')[0]
assert prefix.count('materials = []')==1
exec(compile(prefix,str(fixture),'exec'))
# Capture the loaded payload before rendering; separately record dependency
# reconciliation/removal instead of losing the completed raw film receipt.
native_identity_before=hashlib.sha256(native.read_bytes()).hexdigest()
benchmark_identity_before=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
fixture_identity_before=hashlib.sha256(fixture.read_bytes()).hexdigest()

engine=os.environ.get('SLC_SSS_ENGINE','SUPERLUXCORE')
seed=int(os.environ.get('SLC_SSS_SEED','17'))
samples=cfg.halt.samples
assert math.isqrt(samples)**2==samples
cfg.config.spectral_enable=os.environ.get('SLC_SSS_SPECTRAL','0')=='1'
cfg.config.path.hybridbackforward_enable=False
cfg.config.filter_enabled=False
cfg.config.use_tiles=True
cfg.config.tile.path_sampling_aa_size=math.isqrt(samples)
cfg.config.tile.multipass_enable=False
cfg.config.tile.size=32
cfg.halt.enable=False
for material in materials:
    material.node_tree.nodes.get('Principled BSDF').subsurface_method='RANDOM_WALK'
s.cycles.samples=samples
s.cycles.device='CPU'
s.cycles.seed=seed
s.cycles.use_animated_seed=False
s.cycles.use_adaptive_sampling=False
s.cycles.use_denoising=False
fidelity_before=dict(cycles_filter_glossy=float(s.cycles.blur_glossy),
    cycles_clamp_direct=float(s.cycles.sample_clamp_direct),
    cycles_clamp_indirect=float(s.cycles.sample_clamp_indirect))
s.cycles.blur_glossy=0
s.cycles.sample_clamp_direct=0
s.cycles.sample_clamp_indirect=0
s.cycles.use_fast_gi=False
s.cycles.caustics_reflective=True
s.cycles.caustics_refractive=True
s.cycles.use_guiding=False
cfg.config.psr_auto=False
cfg.config.psr_sigma=0
cfg.config.psr_halflife=0
cfg.config.path.cycles_filter_glossy=0
cfg.config.guiding_enable=False

s.cycles.pixel_filter_type='BOX'
s.render.filter_size=1
s.cycles.max_bounces=12
s.cycles.diffuse_bounces=4
s.cycles.glossy_bounces=4
s.cycles.transmission_bounces=12
cfg.config.path.depth_total=12
cfg.config.path.depth_diffuse=4
cfg.config.path.depth_glossy=4
cfg.config.path.depth_specular=12

s.render.engine=engine

# Canonical authored inputs exclude object names/pointers and sample budgets.
# Both engines construct this same scene; compare the digest before using a
# reference image, rather than inferring matching inputs from a screenshot.
bpy.context.view_layer.update()
def scalar_or_list(value):
    try:return [float(x) for x in value]
    except TypeError:return float(value)
def numeric_inputs(node):
    values={}
    for index,socket in enumerate(node.inputs):
        if not hasattr(socket,'default_value'):continue
        try:values[str(index)+':'+socket.name]=scalar_or_list(socket.default_value)
        except (TypeError,ValueError):continue
    return values
mesh_inputs=[]
light_inputs=[]
for obj in s.objects:
    matrix=[[float(x) for x in row] for row in obj.matrix_world]
    if obj.type=='MESH':
        vertices=[tuple(float(x) for x in v.co) for v in obj.data.vertices]
        faces=[]
        for polygon in obj.data.polygons:
            coordinates=[vertices[i] for i in polygon.vertices]
            # Vertex/face numbering may vary between Blender BMesh builds.
            # Canonicalize the exact coordinate loops, preserving winding;
            # do not quantize or accept geometrically different inputs.
            loop=min(tuple(coordinates[i:]+coordinates[:i]) for i in range(len(coordinates)))
            faces.append((loop,bool(polygon.use_smooth)))
        mesh_inputs.append(dict(matrix=matrix,vertices=sorted(vertices),faces=sorted(faces),
            material=materials.index(obj.active_material) if obj.active_material in materials else 'floor'))
    elif obj.type=='LIGHT':
        light_inputs.append(dict(matrix=matrix,type=obj.data.type,energy=float(obj.data.energy),
            color=[float(x) for x in obj.data.color],size=float(obj.data.size),shape=obj.data.shape))
material_inputs=[]
for mat in materials:
    native_node=next(n for n in mat.superluxcore.node_tree.nodes if n.bl_idname=='SuperLuxCoreNodeMatOpenPBR')
    cycle_node=mat.node_tree.nodes.get('Principled BSDF')
    material_inputs.append(dict(native=numeric_inputs(native_node),cycles=numeric_inputs(cycle_node),
        native_subsurface=bool(native_node.use_subsurface),native_preset=native_node.sss_preset,
        cycles_method=cycle_node.subsurface_method))
canonical=lambda rows:sorted(rows,key=lambda row:json.dumps(row,sort_keys=True))
authored_inputs=dict(size=[s.render.resolution_x,s.render.resolution_y],
    camera=dict(matrix=[[float(x) for x in row] for row in s.camera.matrix_world],
        type=s.camera.data.type,ortho_scale=float(s.camera.data.ortho_scale),lens=float(s.camera.data.lens),
        shift_x=float(s.camera.data.shift_x),shift_y=float(s.camera.data.shift_y),dof=bool(s.camera.data.dof.use_dof),
        clip_start=float(s.camera.data.clip_start),clip_end=float(s.camera.data.clip_end)),
    meshes=canonical(mesh_inputs),lights=canonical(light_inputs),materials=material_inputs,
    floor=numeric_inputs(floor.node_tree.nodes.get('Principled BSDF')),
    world=dict(color=scalar_or_list(s.world.node_tree.nodes['Background'].inputs['Color'].default_value),
               strength=float(s.world.node_tree.nodes['Background'].inputs['Strength'].default_value)))
authored_text=json.dumps(authored_inputs,sort_keys=True,separators=(',',':'))
authored_sha=hashlib.sha256(authored_text.encode()).hexdigest()
(OUT/'authored-scene.json').write_text(authored_text)

original_convert=config_export.convert
def configure(*args,**kwargs):
    props=original_convert(*args,**kwargs)
    props.Set(slc.Property('renderengine.seed',seed))
    if 'SLC_SSS_FASTLOOP' in os.environ:
        props.Set(slc.Property('path.sss.fastloop.enable',os.environ['SLC_SSS_FASTLOOP']=='1'))
    if 'SLC_SSS_GUIDING' in os.environ:
        props.Set(slc.Property('path.sss.guiding.enable',os.environ['SLC_SSS_GUIDING']=='1'))
    props.Set(slc.Property('film.outputs.ssscount.type','SAMPLECOUNT'))
    props.Set(slc.Property('film.outputs.ssscount.filename',str(OUT/'samples.exr')))
    props.Set(slc.Property('film.outputs.sssraw.type','RGB'))
    props.Set(slc.Property('film.outputs.sssraw.filename',str(OUT/'core-raw.exr')))
    props.Set(slc.Property('path.lighttracing.auto',False))
    props.Set(slc.Property('path.lighttracing.enable',False))
    props.Set(slc.Property('path.hybridbackforward.enable',False))
    props.Set(slc.Property('path.mnee.auto',False))
    props.Set(slc.Property('path.mnee.enable',False))
    props.Set(slc.Property('path.photongi.caustic.auto',False))
    props.Set(slc.Property('path.photongi.caustic.enabled',False))
    props.Set(slc.Property('path.photongi.indirect.enabled',False))
    for key in ['path.regularization.sigma','path.regularization.halflife',
                'path.filterglossy','path.clamping.cycles.direct',
                'path.clamping.cycles.indirect','path.clamping.variance.maxvalue']:
        props.Set(slc.Property(key,0.0))
    props.Set(slc.Property('path.regularization.auto',False))

    props.Set(slc.Property('tile.multipass.enable',False))
    props.Set(slc.Property('batch.haltspp',0))
    (OUT/'exported.cfg').write_text(str(props))
    return props
config_export.convert=configure

framebuffer=importlib.import_module(PACKAGE+'.draw.final').FrameBufferFinal
original_draw=framebuffer.draw
capture={}
def draw(self,engine,session,scene,render_stopped):
    if render_stopped:
        film=session.GetFilm()
        counts=np.empty((film.GetHeight(),film.GetWidth()),np.uint32)
        film.GetOutputUInt(slc.FilmOutputType.SAMPLECOUNT,counts,0,False)
        np.save(OUT/'samples.npy',counts)
        capture['sample_min']=int(counts.min())
        capture['sample_max']=int(counts.max())
        capture['sample_sum']=int(counts.sum(dtype=np.uint64))
        raw=np.empty((film.GetHeight(),film.GetWidth(),3),np.float32)
        film.GetOutputFloat(slc.FilmOutputType.RGB,raw,0,False)
        capture['raw_buffer']=raw
    return original_draw(self,engine,session,scene,render_stopped)
framebuffer.draw=draw
original_start=slc.RenderSession.Start
def start(self):
    native_config=self.GetRenderConfig()
    native_props=native_config.GetProperties()
    checked={key:native_props.Get(key).GetFloat() for key in
             ['path.regularization.sigma','path.regularization.halflife',
              'path.filterglossy','path.clamping.cycles.direct',
              'path.clamping.cycles.indirect','path.clamping.variance.maxvalue']}
    assert all(value==0 for value in checked.values()),checked
    capture['native_fidelity']=checked
    (OUT/'effective.cfg').write_text(str(native_props))
    if os.environ.get('SLC_SSS_EXPORT_NATIVE')=='1':
        export_dir=OUT/'native-scene'
        export_dir.mkdir(exist_ok=True)
        self.GetRenderConfig().Export(str(export_dir))
        (export_dir/'authored-scene.json').write_text(authored_text)
    t=time.monotonic()
    result=original_start(self)
    capture['preparation_seconds']=time.monotonic()-t
    return result
slc.RenderSession.Start=start
s.render.engine=engine
errors.clear(False)
s.render.filepath=str(OUT/'render.exr')
t=time.monotonic()
bpy.ops.render.render(write_still=True)
elapsed=time.monotonic()-t
image=bpy.data.images.load(str(OUT/'render.exr'),check_existing=False)
pixels=np.array(image.pixels[:],np.float32).reshape(s.render.resolution_y,s.render.resolution_x,4)
bpy.data.images.remove(image)
np.save(OUT/'linear.npy',pixels[:,:,:3])
if 'raw_buffer' in capture:
    raw=capture.pop('raw_buffer')
    np.save(OUT/'core-raw.npy',raw)
    capture['core_raw_matches_exr']=bool(np.array_equal(raw,pixels[:,:,:3]))
    capture['core_raw_exr_max_error']=float(np.max(np.abs(raw-pixels[:,:,:3])))
    assert capture['core_raw_matches_exr'],capture['core_raw_exr_max_error']
s.render.image_settings.file_format='PNG'
s.render.image_settings.color_depth='8'
bpy.data.images['Render Result'].save_render(str(OUT/'render.png'),scene=s)
if engine=='CYCLES':
    capture.update(sample_min=samples,sample_max=samples,
                   sample_sum=samples*s.render.resolution_x*s.render.resolution_y,
                   sample_accounting='Cycles fixed samples, adaptive disabled')
else:
    assert capture.get('sample_min')==samples and capture.get('sample_max')==samples,capture
assert not cfg.denoiser.enabled and not s.cycles.use_denoising
assert s.cycles.blur_glossy==s.cycles.sample_clamp_direct==s.cycles.sample_clamp_indirect==0
assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==benchmark_identity_before,'Benchmark source changed during render'
assert hashlib.sha256(fixture.read_bytes()).hexdigest()==fixture_identity_before,'Fixture source changed during render'
record=dict(comparison_contract='sss-unregularized-v2',authored_scene_sha256=authored_sha,
            benchmark_source_sha256=benchmark_identity_before,fixture_source_sha256=fixture_identity_before,
            raw_controls=dict(denoising=False,adaptive_sampling=False),
            fidelity_before=fidelity_before,
            cycles_fidelity=dict(filter_glossy=float(s.cycles.blur_glossy),
                clamp_direct=float(s.cycles.sample_clamp_direct),
                clamp_indirect=float(s.cycles.sample_clamp_indirect),
                caustics_reflective=bool(s.cycles.caustics_reflective),caustics_refractive=bool(s.cycles.caustics_refractive),
                fast_gi=bool(s.cycles.use_fast_gi),denoising=bool(s.cycles.use_denoising),guiding=bool(s.cycles.use_guiding),
                adaptive_sampling=bool(s.cycles.use_adaptive_sampling)),
            engine=engine,threads=s.render.threads,size=[s.render.resolution_x,s.render.resolution_y],
            spp=samples,seed=seed,spectral=bool(engine=='SUPERLUXCORE' and cfg.config.spectral_enable),
            seconds=elapsed,finite=bool(np.isfinite(pixels).all()),
            native_sha256=native_identity_before,
            native_present_after_render=native.exists(),
            native_file_sha256_after_render=hashlib.sha256(native.read_bytes()).hexdigest() if native.exists() else None,
            rr_throughput=os.environ.get('SUPERLUXCORE_SSS_RR_THROUGHPUT') is not None,
            shadow_volume=os.environ.get('SUPERLUXCORE_SSS_SHADOW_VOLUME') is not None,
            deferred_boundary=os.environ.get('SUPERLUXCORE_SSS_DEFER_BOUNDARY') is not None,
            legacy_sss_rr=os.environ.get('SUPERLUXCORE_SSS_LEGACY_RR') is not None,
            dwivedi=os.environ.get('SUPERLUXCORE_SSS_DWIVEDI') is not None,
            dwivedi_classic=os.environ.get('SUPERLUXCORE_SSS_DWIVEDI_CLASSIC'),
            dwivedi_forward=os.environ.get('SUPERLUXCORE_SSS_DWIVEDI_FORWARD'),
            configured_sss_guiding=os.environ.get('SLC_SSS_GUIDING','native default'),
            configured_sss_fastloop=os.environ.get('SLC_SSS_FASTLOOP','native default'),
            mean_rgb=pixels[:,:,:3].mean(axis=(0,1),dtype=np.float64).tolist(),max_rgb=float(pixels[:,:,:3].max()),
            errors=[e.message for e in errors.errors],**capture)
# Geometric first-hit regions are identical for both engines. Masks separate
# the three bulk objects and thin parts from the bright background/floor.
depsgraph=bpy.context.evaluated_depsgraph_get()
mask=np.zeros(pixels.shape[:2],np.uint8)
width,height=s.render.resolution_x,s.render.resolution_y
camera=s.camera.matrix_world
direction=camera.to_quaternion() @ Vector((0,0,-1))
for y in range(height):
    for x in range(width):
        origin=camera @ Vector((((x+.5)/width-.5)*s.camera.data.ortho_scale,
                               ((y+.5)/height-.5)*s.camera.data.ortho_scale*height/width,
                               -s.camera.data.clip_start))
        hit,_,_,_,obj,_=s.ray_cast(depsgraph,origin,direction)
        if hit and obj.active_material in materials:
            mask[y,x]=materials.index(obj.active_material)+1+(3 if obj.dimensions.y<.01 else 0)
np.save(OUT/'regions.npy',mask)
record['region_pixels']={str(i):int(np.count_nonzero(mask==i)) for i in range(7)}
record['cycles_device']=s.cycles.device
record['host']=dict(version=bpy.app.version_string,build_hash=bpy.app.build_hash.decode())
(OUT/'result.json').write_text(json.dumps(record,indent=2))
assert record['finite'] and not record['errors'],record
print('MATCHED_SSS_RESULT',json.dumps(record),flush=True)
