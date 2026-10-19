"""Real Junk Shop UI orbit/area-resize probe in an isolated stock Blender.

Invoked by run_review_metal_startup_blender.py. Measures actual view_draw,
Blender timer gaps, post-edit framebuffer uploads and final settled frame.
No geometry, texture, bounce, sampling or material quality reductions.
"""
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import traceback

import bpy
import numpy as np
from mathutils import Quaternion, Vector

PROFILE=Path(os.environ['BLENDER_USER_RESOURCES'])
sys.path.insert(0,str(PROFILE/'extensions/.local/lib/python3.13/site-packages'))
PACKAGE='bl_ext.user_default.superluxcore'
bpy.context.preferences.filepaths.temporary_directory=os.environ['TMPDIR']
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D': area.spaces.active.shading.type='SOLID'
bpy.ops.preferences.addon_enable(module=PACKAGE)
import pysuperluxcore as slc
vp=importlib.import_module(PACKAGE+'.engine.viewport')
fbmod=importlib.import_module(PACKAGE+'.draw.viewport')
swmod=importlib.import_module(PACKAGE+'.engine.session_worker')
OUT=Path(os.environ['SUPERLUXCORE_AUDIT_DIR']);OUT.mkdir(parents=True,exist_ok=True)
DEV=os.environ.get('DEV','CPU')
scene=bpy.context.scene
scene.render.engine='SUPERLUXCORE'
scene.superluxcore.config.device=DEV
scene.superluxcore.viewport.device=DEV
scene.superluxcore.viewport.halt_time=600
bpy.context.preferences.addons[PACKAGE].preferences.gpu_backend='METAL'
area=max((a for a in bpy.context.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.width*a.height)
window=bpy.context.window_manager.windows[0]
space=area.spaces.active;rv=space.region_3d
space.overlay.show_overlays=False
cam=scene.camera
rv.view_rotation=cam.matrix_world.to_quaternion()
rv.view_distance=8
rv.view_location=cam.matrix_world.translation + rv.view_rotation @ Vector((0,0,-8))
rv.view_perspective='PERSP'
base_rotation=rv.view_rotation.copy()
initial_width=area.width
start=time.monotonic();last_tick=start;stage='startup';stage_start=start;index=0
engine=None;active=None;draws=[];gaps=[];actions=[];uploads=[];failure=None
resize_other=None
config_transitions=[]
source=Path(bpy.data.filepath)
record={'scene':str(source),'scene_sha256':hashlib.file_digest(source.open('rb'),'sha256').hexdigest(),
        'blender':bpy.app.version_string,'device':DEV,
        'objects':len(scene.objects),'materials':len(bpy.data.materials),'images':len(bpy.data.images),
        'source_polygons':sum(len(m.polygons) for m in bpy.data.meshes),
        'source_texels':sum(i.size[0]*i.size[1] for i in bpy.data.images),
        'native_sha256':hashlib.file_digest(Path(slc.pysuperluxcore.__file__).open('rb'),'sha256').hexdigest(),
        'viewport_pixel_size':scene.superluxcore.viewport.pixel_size,
        'viewport_denoiser':scene.superluxcore.viewport.get_denoiser(bpy.context)}
identity=json.loads(Path(os.environ['SLC_CANDIDATE_IDENTITY']).read_text())
assert record['native_sha256']==identity['installed_native_sha256']
record['viewport_sha256']=hashlib.file_digest(Path(fbmod.__file__).open('rb'),'sha256').hexdigest()
assert record['viewport_sha256']==identity['viewport_sha256']
record['engine_viewport_sha256']=hashlib.file_digest(Path(vp.__file__).open('rb'),'sha256').hexdigest()
assert record['engine_viewport_sha256']==identity['engine_viewport_sha256']
record['session_worker_sha256']=hashlib.file_digest(Path(importlib.import_module(PACKAGE+'.engine.session_worker').__file__).open('rb'),'sha256').hexdigest()
assert record['session_worker_sha256']==identity['session_worker_sha256']
original_config=swmod.SessionWorker._do_config
def config(worker,props):
    old=worker.session;previous=worker._config_props;t=time.monotonic()
    names=set(props.GetAllNames())
    changed=sorted(n for n in names|set(previous.GetAllNames())
                   if previous is not None and (not previous.IsDefined(n) or not props.IsDefined(n)
                       or str(previous.Get(n))!=str(props.Get(n)))) if previous is not None else []
    try:return original_config(worker,props)
    finally:config_transitions.append({'time':t-start,'seconds':time.monotonic()-t,
        'changed':changed,'same_session':old is not None and worker.session is old})
swmod.SessionWorker._do_config=config
original_draw=vp.view_draw
def draw(e,context,depsgraph):
    global engine
    if stage=='finishing':
        # Screenshot operators may request a redraw. Keep the held image
        # visible while preventing any new native read/denoise work.
        if e.framebuffer:e.framebuffer.draw(context,depsgraph.scene_eval)
        return
    engine=e;t=time.monotonic()
    try:return original_draw(e,context,depsgraph)
    finally:draws.append({'time':t-start,'stage':stage,'seconds':time.monotonic()-t})
vp.view_draw=draw
original_accept=fbmod.FrameBuffer._accept_pixels
def accept(self,data,width,height,force=False,mut_seq=None,**kwargs):
    ok=original_accept(self,data,width,height,force,mut_seq,**kwargs)
    if ok:
        now=time.monotonic()
        uploads.append({'time':now-start,'stage':stage,'width':width,'height':height,'mutation_seq':mut_seq})
        matches_resize=(active is not None and (active['kind']!='resize' or
            active.get('area_width_after') is not None and width in
            (active['area_width_after'],active['area_width_after']//2)))
        if matches_resize and active.get('visible_latency_s') is None and mut_seq is not None and mut_seq>active['mutation_at_request'] and np.any(data[::max(1,len(data)//4096)]>0):
            active['visible_latency_s']=now-active['request_monotonic']
    return ok
fbmod.FrameBuffer._accept_pixels=accept


def percentile(values,p):return float(np.percentile(values,p)) if values else None
def finish(error=None):
    global failure,stage
    # Stats may be busy behind the background read. Retry on the next UI
    # tick instead of treating nonblocking lock failure as a missing device.
    if not error and engine and engine.session:
        lock=engine.session_worker.session_lock
        if not lock.acquire(blocking=False):return False
        try:
            stats=engine.session.GetStats()
            record['devices']={n:stats.Get(n).GetString() for n in stats.GetAllNames() if n.startswith('stats.renderengine.devices')}
        finally:lock.release()
    failure=error;stage='finishing'
    try:
        if not error and DEV=='OCL':assert any('Metal' in v for v in record.get('devices',{}).values()),'actual Metal device not confirmed'
        if engine and engine.framebuffer and engine.framebuffer._last_pixels is not None:
            image=engine.framebuffer._last_pixels
            record['settled_film']={'shape':list(image.shape),'finite':bool(np.isfinite(image).all()),'rgb_mean':image[:,:,:3].mean(axis=(0,1)).tolist()}
            if image.shape[2]==4:
                record['settled_film']['alpha_min_max']=[float(image[:,:,3].min()),float(image[:,:,3].max())]
                record['settled_film']['alpha_mean']=float(image[:,:,3].mean())
            record['settled_film']['nonfinite_values']=int(np.count_nonzero(~np.isfinite(image)))
            assert record['settled_film']['finite'] and max(record['settled_film']['rgb_mean'])>0
        bpy.ops.screen.screenshot(filepath=str(OUT/'viewport.png'))
    except Exception:
        if not error:error=traceback.format_exc()
    measured=[d['seconds'] for d in draws if d['stage'] in ('orbit','resize','settle')]
    timer=[g['seconds'] for g in gaps if g['stage'] in ('orbit','resize','settle')]
    lat=[a['visible_latency_s'] for a in actions if a.get('visible_latency_s') is not None]
    record.update({'status':'failed' if error else 'passed','error':error,'startup_first_image_s':next((u['time'] for u in uploads),None),
        'draw_count':len(measured),'draw_p95_ms':1000*percentile(measured,95) if measured else None,'draw_max_ms':1000*max(measured) if measured else None,
        'timer_gap_p95_ms':1000*percentile(timer,95) if timer else None,'timer_gap_max_ms':1000*max(timer) if timer else None,
        'actions':actions,'post_edit_visible_count':len(lat),'visible_latency_p95_ms':1000*percentile(lat,95) if lat else None,
        'actual_region_sizes':sorted({(u['width'],u['height']) for u in uploads}),'draws':draws,'timer_gaps':gaps,'uploads':uploads,
        'config_transitions':config_transitions})
    for a in actions:a.pop('request_monotonic',None)
    teardown={'done':False}
    def drain():
        try:
            if engine:
                fb=engine.framebuffer
                if fb:
                    fb.reset_denoiser()
                    for thread in (fb._read_thread,fb._denoiser_thread):
                        if thread:thread.join(30);assert not thread.is_alive(),'frame worker did not drain'
                worker=engine.session_worker
                if worker:
                    if (DEV=='CPU' or not record.get('settled_film',{}).get('finite',True)) and worker.session is not None:
                        with worker.session_lock:
                            sess=worker.session
                            if not sess.IsInPause():sess.Pause()
                            film=sess.GetFilm();w,h=film.GetWidth(),film.GetHeight()
                            diagnostic={}
                            for label,output,execute in [('cached_pipeline',slc.FilmOutputType.RGB_IMAGEPIPELINE,False),
                                    ('raw_rgb',slc.FilmOutputType.RGB,False),
                                    ('albedo',slc.FilmOutputType.ALBEDO,False),
                                    ('normal',slc.FilmOutputType.AVG_SHADING_NORMAL,False),
                                    ('fresh_pipeline',slc.FilmOutputType.RGB_IMAGEPIPELINE,True)]:
                                values=np.zeros(w*h*3,np.float32)
                                film.GetOutputFloat(output,values,0,execute)
                                bad=~np.isfinite(values);indices=np.flatnonzero(bad)
                                valid=values[~bad]
                                diagnostic[label]={'nonfinite_values':int(bad.sum()),
                                    'first_bad_indices':indices[:12].tolist(),
                                    'finite_min_max':[float(valid.min()),float(valid.max())] if valid.size else None}
                            record['nonfinite_diagnostic']=diagnostic
                            stages={}
                            for label,plugins in [('nop',['NOP']),('infill',['VIEWPORT_INFILL']),
                                    ('smooth',['VIEWPORT_SMOOTH']),('infill_smooth',['VIEWPORT_INFILL','VIEWPORT_SMOOTH']),
                                    ('full',['VIEWPORT_INFILL','VIEWPORT_SMOOTH','VIEWPORT_TEMPORAL'])]:
                                film.DeleteAllImagePipelines()
                                props=slc.Properties()
                                for i,plugin in enumerate(plugins):
                                    props.Set(slc.Property(f'film.imagepipelines.0.{i}.type',plugin))
                                sess.Parse(props)
                                values=np.zeros(w*h*3,np.float32)
                                film.GetOutputFloat(slc.FilmOutputType.RGB_IMAGEPIPELINE,values,0,True)
                                bad=np.flatnonzero(~np.isfinite(values))
                                stages[label]={'nonfinite_values':int(bad.size),'first_bad_indices':bad[:12].tolist()}
                            record['nonfinite_pipeline_stages']=stages
                    worker.shutdown();worker._thread.join(30)
                    assert not worker._thread.is_alive(),'session worker did not stop'
            record['owned_workers_drained']=True
        except Exception:
            record['status']='failed';record['error']=traceback.format_exc()
            if engine and engine.session_worker:
                engine.session_worker.shutdown();engine.session_worker._thread.join(30)
                record['owned_workers_drained']=not engine.session_worker._thread.is_alive()
        finally:teardown['done']=True
    def quit_when_drained():
        if not teardown['done']:return .05
        (OUT/'heavy-viewport.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
        space.shading.type='SOLID'
        bpy.ops.wm.quit_blender();return None
    threading.Thread(target=drain,name='ReviewOwnedTeardown',daemon=True).start()
    bpy.app.timers.register(quit_when_drained,first_interval=.05)
    return True


def tick():
    global last_tick,stage,stage_start,index,active,resize_other
    now=time.monotonic();gaps.append({'stage':stage,'seconds':now-last_tick});last_tick=now
    try:
        if stage=='startup':
            if engine and engine.session and engine.framebuffer and engine.framebuffer._last_pixels is not None:
                stage='warmup';stage_start=now
            elif now-start>480:raise TimeoutError('viewport startup has no image after 480s')
        elif stage=='warmup' and now-stage_start>2:
            stage='orbit';stage_start=now;index=0
        elif stage=='orbit' and now-stage_start>=index*.15:
            if index>=30:
                stage='resize';stage_start=now;index=0
            else:
                active={'kind':'orbit','index':index,'time':now-start,'request_monotonic':now,
                    'mutation_at_request':engine.session_worker.mutation_seq,'visible_latency_s':None}
                actions.append(active)
                rv.view_rotation=Quaternion((0,0,1),.20*math.sin(index*.3))@base_rotation
                area.tag_redraw();index+=1
        elif stage=='resize' and now-stage_start>=index*.3:
            if active is not None and active['kind']=='resize':
                active['area_width_after']=area.width
                assert area.width!=active['area_width_before'], 'area resize did not change actual region geometry'
            if index in (13,14) and active is not None:
                # Keep both sides of the policy-boundary resize visible.
                # Under shared rendering a burst can coalesce completely;
                # verify the intermediate image, then request the final one.
                expected_width=active.get('area_width_after')
                ready=(engine.framebuffer._width==expected_width and
                       active.get('visible_latency_s') is not None and
                       not engine.session_worker._lifecycle_busy)
                if not ready:
                    if now-active['request_monotonic']>30:
                        raise TimeoutError('resize checkpoint has no current-size film after 30s')
                    return .02
                pixels=engine.framebuffer._last_pixels
                assert np.isfinite(pixels).all(),'nonfinite intermediate resize film'
                record.setdefault('resize_checkpoints',[]).append({
                    'index':active['index'],'width':expected_width,
                    'height':engine.framebuffer._height,'time':now-start,'finite':True})
            if index>=14:
                stage='settle';stage_start=now
            else:
                before=area.width
                active={'kind':'resize','index':index,'time':now-start,'request_monotonic':now,
                    'mutation_at_request':engine.session_worker.mutation_seq,'visible_latency_s':None,'area_width_before':before}
                actions.append(active)
                with bpy.context.temp_override(window=window,area=area):
                    if index%2==0:
                        old_areas={a.as_pointer() for a in window.screen.areas}
                        # Twelve size-only changes within the same sampling
                        # bucket, then two changes crossing its threshold.
                        active['operator_result']=list(bpy.ops.screen.area_split(direction='VERTICAL',factor=.97 if index<12 else .75))
                        resize_other=next(a for a in window.screen.areas if a.as_pointer() not in old_areas)
                        resize_other.spaces.active.shading.type='SOLID'
                    else:
                        active['operator_result']=list(bpy.ops.screen.area_join(
                            source_xy=(area.x+area.width//2,area.y+area.height//2),
                            target_xy=(resize_other.x+resize_other.width//2,resize_other.y+resize_other.height//2)))
                area.tag_redraw();index+=1
        elif stage=='settle' and now-stage_start>4:
            expected=tuple(engine.last_viewport_size)
            current=(engine.framebuffer._width,engine.framebuffer._height)
            ready=(active is not None and active.get('visible_latency_s') is not None
                   and current==expected and not engine.session_worker._lifecycle_busy)
            if (os.environ.get('SLC_ALLOW_SHARED_VALIDATION')=='1' and
                    not ready and now-stage_start<30):
                # Shared runs are correctness-only, with measured latency.
                # Keep the exclusive four-second observation unchanged.
                return .02
            assert active is not None and active.get('visible_latency_s') is not None,'last resize never became visible'
            assert current==expected,('final film has stale dimensions',current,expected)
            assert not engine.session_worker._lifecycle_busy,'final session restart still in flight'
            record['final_expected_film']=list(expected)
            assert len({(u['width'],u['height']) for u in uploads if u['stage']=='resize'})>=2,'no resized film uploads'
            assert any(d['stage']=='orbit' for d in draws),'no real viewport orbit draws'
            size_edits=[c for c in config_transitions if c['changed'] and set(c['changed'])<={'film.width','film.height'}]
            if DEV=='OCL':
                assert size_edits and all(c['same_session'] for c in size_edits),'Metal size edit rebuilt the session'
            else:
                assert all(not c['same_session'] for c in config_transitions),'CPU must retain restart path'
            if finish():return None
        if now-start>540:raise TimeoutError('viewport probe exceeded deadline')
    except Exception:
        traceback.print_exc();finish(traceback.format_exc());return None
    return .02


space.shading.type='RENDERED'
bpy.app.timers.register(tick,first_interval=.02)
