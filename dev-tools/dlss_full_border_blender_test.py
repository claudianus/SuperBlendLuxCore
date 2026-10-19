"""Actual Blender full-border export and physical-SR policy contract; no NGX run."""
from pathlib import Path
import os
SCOPE = 'Actual Blender RNA/camera/native config/framebuffer, exact full border vs disabled; CUDA discovery only is shimmed for policy inspection, no native session/NGX is started.'
fixture = Path(os.environ['SLC_FINAL_SETUP']); source = fixture.read_text()
exec(compile(source[:source.index('layer = scene.view_layers[0]')], str(fixture), 'exec'), globals())
from types import SimpleNamespace as NS
utils = importlib.import_module(PACKAGE+'.utils')
camera = importlib.import_module(PACKAGE+'.export.camera')
export = importlib.import_module(PACKAGE+'.export')
viewport_options = importlib.import_module(PACKAGE+'.engine.dlss_viewport').DLSSViewportOptions
original_configuration = final_dlss.configuration
final_dlss.configuration = lambda *args: (viewport_options('', '', ''), '')
prefs = NS(gpu_backend='CUDA', dlss_library='', dlss_runtime='')
input_border = {name:getattr(scene.render,name) for name in
                ('use_border','use_crop_to_border','border_min_x','border_max_x','border_min_y','border_max_y')}
settings.denoiser.enabled = True; settings.denoiser.type = 'DLSS'
settings.denoiser.dlss_trace_reduction = '2'; settings.denoiser.dlss_input_reduction = '1'
settings.denoiser.temporal_enabled = False; settings.denoiser.to_combined = True
for layer in scene.view_layers:
 for name in dir(layer):
  if name.startswith('use_pass_') and name not in ('use_pass_combined','use_pass_cryptomatte_accurate'):setattr(layer,name,False)
 for name in slc.FilmOutputType.names:
  if hasattr(layer.superluxcore.aovs,name.lower()):setattr(layer.superluxcore.aovs,name.lower(),False)
 layer.superluxcore.aovs.lpe_list.clear()
settings.lightgroups.custom.clear()
scene.render.border_min_x=scene.render.border_min_y=0.
scene.render.border_max_x=scene.render.border_max_y=1.
render_fields=('use_border','use_crop_to_border','border_min_x','border_max_x','border_min_y','border_max_y','resolution_x','resolution_y','resolution_percentage','pixel_aspect_x','pixel_aspect_y')
def snapshot():return {name:getattr(scene.render,name) for name in render_fields}
def inspect_contract():
 bpy.context.view_layer.update()
 props=camera.convert(export.Exporter(),scene,None)
 config_props=config.convert(export.Exporter(),scene)
 assert config_props.IsDefined('film.width')
 f=framebuffer(scene)
 return {'camera':str(props),'film':list(utils.calc_filmsize(scene)),
         'config_film':[config_props.Get('film.width').GetInt(),config_props.Get('film.height').GetInt()],
         'framebuffer':[f._width,f._height],'framebuffer_border':list(f._border)}
rows=[];crop_rows=[]
try:
 for camera_type in ('PERSP','ORTHO'):
  scene.camera.data.type=camera_type
  scene.camera.data.shift_x=.17;scene.camera.data.shift_y=-.11
  scene.render.pixel_aspect_x=1.2;scene.render.pixel_aspect_y=.9
  for percentage in (50,100):
   scene.render.resolution_percentage=percentage;scene.render.use_border=False
   reference=inspect_contract()
   for crop in (False,True):
    scene.render.use_border=True;scene.render.use_crop_to_border=crop
    before=snapshot();current=inspect_contract();assert current==reference,(current,reference)
    old_device=settings.config.device
    settings.config.device='OCL'
    try:options,reason=final_dlss.final_options(scene,NS(is_preview=False),prefs)
    finally:settings.config.device=old_device
    assert options is not None and options.trace_reduction==2 and not reason,(options,reason)
    assert list(options.output_size)==reference['film'] and snapshot()==before
    rows.append({'camera_type':camera_type,'resolution_percentage':percentage,'crop':crop,'film':reference['film'],'camera_properties':reference['camera'],'config_and_framebuffer_equal':True,'physical_half_selected':True,'artist_render_settings_unchanged':True})
   for field,value in [('border_min_x',.25),('border_min_y',.25),('border_max_x',.75),('border_max_y',.75)]:
    original=getattr(scene.render,field);setattr(scene.render,field,value);before=snapshot();old_device=settings.config.device;settings.config.device='OCL'
    try:options,reason=final_dlss.final_options(scene,NS(is_preview=False),prefs)
    finally:settings.config.device=old_device
    assert options.trace_reduction==1 and 'original raster' in reason and snapshot()==before
    crop_rows.append({'camera_type':camera_type,'percentage':percentage,'edge':field,'kept_native':True})
    setattr(scene.render,field,original)
 report={'passed':True,'blender':bpy.app.version_string,'source_scene':'original GenmaB (unsaved)' if KEEP_SCENE else 'two diffuse cubes','input_border':input_border,'full_frame_conditions':rows,'actual_crop_conditions':crop_rows,'scope':SCOPE,'native_sha256':hashlib.file_digest(native.open('rb'),'sha256').hexdigest(),'policy_source_sha256':hashlib.sha256(Path(final_dlss.__file__).read_bytes()).hexdigest(),'native_render_started':False}
 (OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':True,'full_conditions':len(rows),'actual_crops':len(crop_rows),'source_scene':report['source_scene']}),flush=True)
finally:final_dlss.configuration=original_configuration
