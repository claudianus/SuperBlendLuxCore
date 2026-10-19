"""Stock Blender UI -> addon exporter -> CUDA -> DLSS -> actual view_draw.

Procedural opaque matte fixture only. The supervisor owns the display, RAM
limit, deadline and process teardown. Software GL is a functional UI gate,
never a workstation latency/performance comparison.
"""
from pathlib import Path
import hashlib
import ctypes as C
import importlib
import json
import os
import sys
import threading
import time
import traceback

import bpy
import gpu
import numpy as np
from mathutils import Matrix, Quaternion, Vector

profile=Path(os.environ['BLENDER_USER_RESOURCES'])
out=Path(os.environ['SLC_DLSS_VIEWPORT_OUT']);out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(profile/'extensions/.local/lib/python3.13/site-packages'))
package='bl_ext.user_default.superluxcore'
bpy.context.preferences.filepaths.temporary_directory=os.environ['TMPDIR']
bpy.ops.preferences.addon_enable(module=package)
import pysuperluxcore as slc
vpmod=importlib.import_module(package+'.engine.viewport')
fbmod=importlib.import_module(package+'.draw.viewport')
preferences=bpy.context.preferences.addons[package].preferences
preferences.gpu_backend='CUDA'
preferences.dlss_library=os.environ['SLC_DLSS_TEST_LIBRARY']
preferences.dlss_runtime=os.environ['SLC_DLSS_TEST_RUNTIME']
for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
scene=bpy.context.scene;scene.render.engine='SUPERLUXCORE'
scene.superluxcore.config.device='OCL'
# Explicit small RGB fixture configuration, not a change to user defaults.
scene.superluxcore.config.spectral_enable=False
settings=scene.superluxcore.viewport
settings.device='OCL';settings.use_bidir=False;settings.add_light_tracing=False
settings.use_denoiser=True;settings.denoiser='DLSS';settings.pixel_size='1';settings.halt_time=300

def matte(name,color):
    material=bpy.data.materials.new(name)
    tree=bpy.data.node_groups.new(name,type='superluxcore_material_nodes')
    node=tree.nodes.new('SuperLuxCoreNodeMatMatte');node.inputs['Diffuse Color'].default_value=color
    target=tree.nodes.new('SuperLuxCoreNodeMatOutput')
    tree.links.new(node.outputs['Material'],target.inputs['Material'])
    material.superluxcore.node_tree=tree
    return material

white=matte('DLSS enclosed room',(.65,.65,.65));blue=matte('DLSS blue',(.025,.1,.55))
bpy.ops.mesh.primitive_cube_add(size=2,location=(0,0,3))
room=bpy.context.object;room.name='Closed matte guide coverage';room.scale=(8,8,5);room.data.materials.append(white)
for center,radius,material in [((-1.2,0,1),1,white),((1.2,.8,1.5),1.5,blue)]:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=24,radius=radius,location=center)
    obj=bpy.context.object;obj.data.materials.append(material)
    for polygon in obj.data.polygons:polygon.use_smooth=True
bpy.ops.object.light_add(type='AREA',location=(0,-1,5.5))
light=bpy.context.object;light.data.energy=1500;light.data.size=4
camera=bpy.data.cameras.new('DLSS camera');cam=bpy.data.objects.new('DLSS camera',camera);scene.collection.objects.link(cam)
cam.location=(0,-5,2.2);cam.rotation_euler=(Vector((0,.5,1.5))-cam.location).to_track_quat('-Z','Y').to_euler();scene.camera=cam
bpy.context.view_layer.update()
area=max((a for a in bpy.context.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.width*a.height)
window=bpy.context.window;space=area.spaces.active;region=space.region_3d
space.overlay.show_overlays=False
region.view_rotation=cam.matrix_world.to_quaternion()
region.view_distance=5.5;region.view_location=cam.location+region.view_rotation@Vector((0,0,-5.5));region.view_perspective='PERSP'
base=region.view_rotation.copy()
start=time.monotonic();last_tick=start;stage='startup';engine=None;other=None;active=None;finished=None
draws=[];uploads=[];actions=[];gaps=[];configurations=[]
capture_requested=None;capture_error=None;gpu_captures={};inside_dlss_upload=False
test_fallback=os.environ.get('SLC_DLSS_TEST_FALLBACK')=='1'
runtime_path=preferences.dlss_runtime
runtime_session=None
record={'blender':bpy.app.version_string,'build_hash':bpy.app.build_hash.decode(),
        'native_sha256':hashlib.file_digest(Path(slc.pysuperluxcore.__file__).open('rb'),'sha256').hexdigest(),
        'graphics':{'renderer':gpu.platform.renderer_get(),'vendor':gpu.platform.vendor_get(),'backend':gpu.platform.backend_type_get()},
        'scope':'Actual stock Blender view_update/view_draw, CUDA/NGX, native image pipeline and GPU upload on a procedural enclosed matte RGB fixture. Xvfb/software GL only validates functionality; not heavy-scene responsiveness, final/animation or quality/speed promotion.'}
original_draw=vpmod.view_draw
def draw(e,context,depsgraph):
    global engine,capture_requested,capture_error
    engine=e
    if stage=='finishing':
        if e.framebuffer:e.framebuffer.draw(context,depsgraph.scene_eval)
        return
    t=time.monotonic()
    try:
        result=original_draw(e,context,depsgraph)
        if capture_requested is not None:
            label=capture_requested;capture_requested=None
            try:
                x,y,w,h=gpu.state.viewport_get()
                fb=e.framebuffer
                assert (w,h)==(fb._width,fb._height),('Capture must use full-resolution film',w,h,fb._width,fb._height)
                pixels=np.array(gpu.state.active_framebuffer_get().read_color(x,y,w,h,4,0,'FLOAT')).reshape(h,w,4)
                np.save(out/('gpu-'+label+'.npy'),pixels)
                np.save(out/('upload-'+label+'.npy'),fb._last_pixels)
                assert np.isfinite(pixels).all() and np.max(pixels[:,:,:3])>0,'Actual view_draw framebuffer is black or nonfinite'
                # The quad covers the full region from (0,0). Compare every
                # pixel; the live framebuffer may still store half floats.
                maximum=float(np.abs(pixels[:,:,:3]-fb._last_pixels).max())
                gl=C.CDLL('libGL.so.1');binding=C.c_int()
                gl.glGetIntegerv(0x8CA6,C.byref(binding))
                attachment=0x8CE0 if binding.value else 0x0402
                properties={}
                for name,token in [('red_bits',0x8212),('green_bits',0x8213),('blue_bits',0x8214),('component_type',0x8211)]:
                    value=C.c_int();gl.glGetFramebufferAttachmentParameteriv(0x8CA9,attachment,token,C.byref(value));properties[name]=value.value
                (out/('gpu-'+label+'-diagnostic.json')).write_text(json.dumps({'upload_max_abs':maximum,'source_min_max':[float(fb._last_pixels.min()),float(fb._last_pixels.max())],'framebuffer':properties,'texture_format':fb._texture.format},indent=2)+'\n')
                # Retain the strict .002 float32 offscreen gate. The addon
                # owns pixel projection and restores the host matrices.
                off=gpu.types.GPUOffScreen(w,h,format='RGBA32F')
                old_blend=gpu.state.blend_get();old_depth=gpu.state.depth_test_get()
                old_projection=gpu.matrix.get_projection_matrix().copy()
                try:
                    with off.bind():
                        gpu.state.viewport_set(0,0,w,h)
                        gpu.state.blend_set('NONE');gpu.state.depth_test_set('NONE')
                        gpu.state.active_framebuffer_get().clear(color=(0,0,0,1))
                        with gpu.matrix.push_pop():
                            gpu.matrix.load_matrix(Matrix.Identity(4))
                            gpu.matrix.load_projection_matrix(Matrix(((2/w,0,0,-1),(0,2/h,0,-1),(0,0,-1,0),(0,0,0,1))))
                            fb.draw()
                        controlled=np.array(gpu.state.active_framebuffer_get().read_color(0,0,w,h,4,0,'FLOAT')).reshape(h,w,4)
                    np.save(out/('gpu-'+label+'-controlled.npy'),controlled)
                    controlled_max=float(np.abs(controlled[:,:,:3]-fb._last_pixels).max())
                    assert controlled_max<.002,('Controlled GPU draw differs from matching upload',controlled_max)
                finally:
                    off.free();gpu.state.viewport_set(x,y,w,h)
                    gpu.matrix.load_projection_matrix(old_projection)
                    gpu.state.blend_set(old_blend);gpu.state.depth_test_set(old_depth)
                # The host framebuffer can store 16-bit floats even though the
                # upload/offscreen textures are float32. Allow that storage ULP,
                # while keeping the existing .002 float32 blit bound unchanged.
                ulp=(np.spacing(np.abs(controlled[:,:,:3]).astype(np.float16)).astype(np.float32)
                     if properties['red_bits']==16 else 0)
                excess=float(np.maximum(np.abs(pixels[:,:,:3]-controlled[:,:,:3])-ulp,0).max())
                assert excess<.002,('Actual view_draw exceeds framebuffer precision and float32 blit bound',excess)
                gpu_captures[label]={'size':[w,h],'rgb_mean':float(pixels[:,:,:3].mean()),
                                     'live_region_max_abs':maximum,
                                     'live_half_ulp_excess_max_abs':excess,
                                     'controlled_upload_max_abs':controlled_max,'finite':True}
            except Exception:capture_error=traceback.format_exc()
        return result
    finally:draws.append({'time':t-start,'stage':stage,'seconds':time.monotonic()-t})
vpmod.view_draw=draw
original_consume=fbmod.FrameBuffer.consume_dlss_result
def consume(fb,e,worker,session):
    global inside_dlss_upload
    previous=(fb._dlss_last_frame_id,fb._dlss_last_scene_epoch)
    inside_dlss_upload=True
    try:result=original_consume(fb,e,worker,session)
    finally:inside_dlss_upload=False
    if result and previous!=(fb._dlss_last_frame_id,fb._dlss_last_scene_epoch):
        pixels=fb._last_pixels;assert pixels is not None and np.isfinite(pixels).all()
        now=time.monotonic()
        uploads.append({'time':now-start,'stage':stage,'frame_id':fb._dlss_last_frame_id,
                        'epoch':fb._dlss_last_scene_epoch,'sequence':worker.mutation_seq,'size':[fb._width,fb._height],
                        'finite':True,'rgb_mean':float(pixels[:,:,:3].mean())})
        if active and active.get('visible_latency_seconds') is None and worker.mutation_seq>active['previous_sequence']:
            if active['kind']!='resize' or (fb._width,fb._height)==tuple(e.last_viewport_size):
                active['visible_latency_seconds']=now-active['requested_at']
    return result
fbmod.FrameBuffer.consume_dlss_result=consume
original_accept=fbmod.FrameBuffer._accept_pixels
def accept(fb,data,width,height,force=False,mut_seq=None,**kwargs):
    result=original_accept(fb,data,width,height,force,mut_seq,**kwargs)
    if (result and stage=='fallback' and not inside_dlss_upload and engine and
            engine.session_worker._dlss_worker is None and np.isfinite(data).all() and np.max(data)>0):
        record['runtime_fallback']={'ordinary_pixels_accepted':True,'status':engine.session_worker.dlss_status,'size':[width,height]}
    return result
fbmod.FrameBuffer._accept_pixels=accept

def finish(error=None):
    global stage,finished
    if stage=='finishing':return
    stage='finishing';record['status']='failed' if error else 'passed';record['error']=error
    try:
        if engine and engine.framebuffer and engine.framebuffer._last_pixels is not None:
            pixels=engine.framebuffer._last_pixels
            np.save(out/'settled.npy',pixels)
            record['settled_size']=[engine.framebuffer._width,engine.framebuffer._height]
        bpy.ops.screen.screenshot(filepath=str(out/'viewport.png'))
    except Exception:record['screenshot_error']=traceback.format_exc()
    finished={'done':False}
    def drain():
        try:
            if engine:
                fb=engine.framebuffer
                if fb:
                    fb.reset_denoiser()
                    for thread in (fb._read_thread,fb._denoiser_thread):
                        if thread:thread.join(20);assert not thread.is_alive(),'Film worker did not drain'
                worker=engine.session_worker
                if worker:
                    worker.shutdown();worker._thread.join(30)
                    assert not worker._thread.is_alive(),'Session worker did not drain'
            record['workers_reaped']=not any(t.name.startswith('SuperLuxCore') for t in threading.enumerate())
            assert record['workers_reaped'],'Residual addon worker'
        except Exception:record['status']='failed';record['teardown_error']=traceback.format_exc()
        finally:finished['done']=True
    threading.Thread(target=drain,name='DLSSViewportTestCleanup',daemon=True).start()

def request(kind):
    global active
    active={'kind':kind,'previous_sequence':engine.session_worker.mutation_seq,'requested_at':time.monotonic(),'visible_latency_seconds':None}
    actions.append(active)

def tick():
    global last_tick,stage,other,capture_requested,active,runtime_session
    now=time.monotonic();gaps.append(now-last_tick);last_tick=now
    try:
        if stage=='finishing':
            if finished['done']:
                record.update({'uploads':uploads,'actions':[{k:v for k,v in a.items() if k!='requested_at'} for a in actions],
                               'draws':draws,'timer_gaps':gaps,'gpu_captures':gpu_captures,'wall_seconds':now-start})
                (out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
                if not record.get('workers_reaped'):
                    # A native compile/evaluation can outlive the teardown
                    # deadline. Do not unload Blender underneath that thread;
                    # leave termination/reaping to the external supervisor.
                    return .1
                bpy.ops.wm.quit_blender();return None
            return .05
        if now-start>150:raise TimeoutError('Actual Blender DLSS viewport deadline')
        if capture_error:raise AssertionError(capture_error)
        if engine and engine.session_worker:
            error=engine.session_worker.pop_error()
            if error:raise RuntimeError(str(error))
        if stage=='startup':
            if len(uploads)<4:return .05
            if 'static' not in gpu_captures:
                capture_requested='static';area.tag_redraw();return .05
            np.save(out/'static.npy',engine.framebuffer._last_pixels)
            stage='orbit';request('orbit');region.view_rotation=base@Quaternion((0,0,1),.025);area.tag_redraw()
        elif stage=='orbit' and active['visible_latency_seconds'] is not None:
            count=sum(a['kind']=='orbit' for a in actions)
            if count<4:
                request('orbit');region.view_rotation=base@Quaternion((0,0,1),.025*(-1 if count%2 else 1));area.tag_redraw()
            else:
                stage='resize';request('resize')
                pointers={a.as_pointer() for a in window.screen.areas}
                with bpy.context.temp_override(window=window,area=area):bpy.ops.screen.area_split(direction='VERTICAL',factor=.8)
                other=next(a for a in window.screen.areas if a.as_pointer() not in pointers);other.spaces.active.shading.type='SOLID'
                area.tag_redraw()
        elif stage=='resize' and active['visible_latency_seconds'] is not None:
            if sum(a['kind']=='resize' for a in actions)==1:
                request('resize')
                with bpy.context.temp_override(window=window,area=area):
                    bpy.ops.screen.area_join(source_xy=(area.x+area.width//2,area.y+area.height//2),target_xy=(other.x+other.width//2,other.y+other.height//2))
                area.tag_redraw()
            else:
                assert all(a['visible_latency_seconds'] is not None for a in actions)
                assert len({tuple(u['size']) for u in uploads})>=2,'No resized DLSS upload'
                if test_fallback:
                    active=None;stage='fallback';runtime_session=engine.session
                    preferences.dlss_runtime=str(out/'runtime-not-installed');area.tag_redraw()
                elif 'settled' not in gpu_captures:
                    capture_requested='settled';area.tag_redraw()
                else:finish()
        elif stage=='fallback' and record.get('runtime_fallback'):
            assert engine.session is runtime_session,'Runtime path edit restarted the physical renderer'
            if 'fallback' not in gpu_captures:
                capture_requested='fallback';area.tag_redraw();return .05
            preferences.dlss_runtime=runtime_path;stage='recover';area.tag_redraw()
        elif stage=='recover' and uploads[-1]['stage']=='recover':
            assert engine.session is runtime_session,'Runtime restoration restarted the physical renderer'
            if 'settled' not in gpu_captures:
                capture_requested='settled';area.tag_redraw();return .05
            record['dlss_recovered_after_runtime_restore']=True
            record['runtime_transitions_preserved_native_session']=True;finish()
    except Exception:
        traceback.print_exc();finish(traceback.format_exc())
    return .05

space.shading.type='RENDERED'
bpy.app.timers.register(tick,first_interval=.2)
