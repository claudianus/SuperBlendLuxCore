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
s.cycles.use_adaptive_sampling=False
s.cycles.use_denoising=False
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
record=dict(engine=engine,threads=s.render.threads,size=[s.render.resolution_x,s.render.resolution_y],
            spp=samples,seed=seed,spectral=bool(engine=='SUPERLUXCORE' and cfg.config.spectral_enable),
            seconds=elapsed,finite=bool(np.isfinite(pixels).all()),
            native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
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
