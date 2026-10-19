"""Physical SR policy and failure recovery; real CUDA/Blender gates are separate."""
import ast
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import numpy as np

SOURCE=Path(__file__).resolve().parents[1]/'engine/dlss_final.py'
class Prop:
    def __init__(self,name,value):self.name,self.value=name,value
    def GetInt(self,*args):return int(self.value)
    def GetBool(self):return bool(self.value)
    def GetString(self):return self.value
    def GetSize(self):return 1
class Props:
    def __init__(self,**data):self.data=data
    def Get(self,name,default=None):return Prop(name,self.data.get(name,default[0] if default else None))
    def Set(self,p):self.data[p.name]=p.value;return self
    def IsDefined(self,name):return name in self.data
    def GetAllNames(self):return list(self.data)
class Backend:
    def close(self):pass
class Consumer:
    def __init__(self,b):self.last_reset=True
    def reset(self):pass
class Pipeline:
    supports_upscaling=staticmethod(lambda:True)
@dataclass(frozen=True)
class Options:
    render_mode:str='NATIVE'
    output_size:tuple=None
    trace_reduction:int=1

def load():
    nodes=[n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
    api=NS(Property=Prop,Properties=Props,DenoisingImagePipeline=Pipeline,
        FilmOutputType=NS(names={'RGB':1,'ALPHA':2,'ALBEDO':3}),
        RenderSession=NS(AcknowledgeDenoisingFrame=True,ReleaseDenoisingFrameDelivery=True,SetDenoisingFrameHaltSPP=True))
    env={'np':np,'replace':replace,'pysuperluxcore':api,'RendererDLSS':Consumer,'DLSSInputError':ValueError,
         'configuration':lambda *args:(Options(),''),
         'blender_settings':NS(transparent_film=lambda s:s.render.film_transparent or s.camera_transparent)}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),env)
    return env

def scene():
    den=NS(enabled=True,type='DLSS',temporal_enabled=False,to_combined=True,dlss_trace_reduction='2',dlss_input_reduction='1')
    config=NS(external_process=False,use_filesaver=False,engine='PATH',effective_device=lambda:'OCL')
    return NS(superluxcore=NS(config=config,denoiser=den,lightgroups=NS(custom=[])),
              render=NS(resolution_x=1280,resolution_y=720,resolution_percentage=100,film_transparent=False,use_border=False,
                        use_crop_to_border=False,border_min_x=0.,border_min_y=0.,border_max_x=1.,border_max_y=1.),
              camera_transparent=False,view_layers=[NS(use=True,use_pass_combined=True,use_pass_z=False,use_pass_cryptomatte_accurate=True,
                  superluxcore=NS(aovs=NS(lpe_list=[])))])
class Policy(unittest.TestCase):
    def setUp(self):self.e=load()
    def test_half_is_opt_in_and_native_saved_mode_stays_native(self):
        s=scene();del s.superluxcore.denoiser.dlss_trace_reduction
        opt,reason=self.e['final_options'](s,NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
        self.assertEqual((opt.trace_reduction,opt.render_mode,reason),(1,'NATIVE',''))
    def test_opaque_beauty_selects_physical_half(self):
        opt,reason=self.e['final_options'](scene(),NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
        self.assertEqual((opt.trace_reduction,opt.output_size,reason),(2,(1280,720),''))
    def test_all_canonical_requirements_keep_native(self):
        changes=[lambda s:setattr(s.render,'film_transparent',True),lambda s:setattr(s,'camera_transparent',True),
                 lambda s:(setattr(s.render,'use_border',True),setattr(s.render,'border_min_x',.25)),lambda s:setattr(s.render,'resolution_x',1279),
                 lambda s:setattr(s.superluxcore.denoiser,'to_combined',False),
                 lambda s:setattr(s.view_layers[0],'use_pass_z',True),
                 lambda s:setattr(s.view_layers[0].superluxcore.aovs,'rgb',True),
                 lambda s:s.view_layers[0].superluxcore.aovs.lpe_list.append(NS(expression='C.*L')),
                 lambda s:s.superluxcore.lightgroups.custom.append(object())]
        for change in changes:
            s=scene();change(s)
            with self.subTest(change=change):
                opt,reason=self.e['final_options'](s,NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
                self.assertEqual(opt.trace_reduction,1);self.assertTrue(reason.startswith('Full-resolution'))
    def test_exact_full_frame_border_keeps_half_and_artist_settings(self):
        for crop in (False,True):
            for percentage in (50,100):
                s=scene();s.render.use_border=True;s.render.use_crop_to_border=crop;s.render.resolution_percentage=percentage
                before=vars(s.render).copy()
                opt,reason=self.e['final_options'](s,NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
                self.assertEqual(reason,'');self.assertEqual(opt.trace_reduction,2)
                self.assertEqual(opt.output_size,(1280*percentage//100,720*percentage//100))
                self.assertEqual(vars(s.render),before)
    def test_every_actual_crop_edge_retains_original_raster(self):
        for crop in (False,True):
            for field,value in [('border_min_x',.25),('border_min_y',.25),('border_max_x',.75),('border_max_y',.75)]:
                s=scene();s.render.use_border=True;s.render.use_crop_to_border=crop;setattr(s.render,field,value)
                before=vars(s.render).copy()
                opt,reason=self.e['final_options'](s,NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
                self.assertEqual(opt.trace_reduction,1);self.assertIn('original raster',reason)
                self.assertEqual(vars(s.render),before)
    def test_near_full_border_is_not_promoted_to_physical_half(self):
        s=scene();s.render.use_border=True;s.render.border_max_x=float(np.nextafter(np.float32(1),np.float32(0)))
        opt,reason=self.e['final_options'](s,NS(is_preview=False),NS(gpu_backend='CUDA',dlss_library='',dlss_runtime=''))
        self.assertEqual(opt.trace_reduction,1);self.assertIn('original raster',reason)
    def controller(self):return self.e['FinalDLSS'](Backend(),transparent=False,trace_reduction=2,output_size=(1280,720))
    def props(self):return Props(**{'renderengine.type':'PATHOCL','film.width':1280,'film.height':720,'batch.haltspp':4})
    def test_repeated_configuration_does_not_quarter_dimensions(self):
        c=self.controller();p=self.props()
        for _ in range(2):
            # Engine name may be rebuilt by config.convert on each call.
            p.data['renderengine.type']='PATHOCL'
            self.assertEqual(c.configure(p,p),'')
            self.assertEqual((p.data['film.width'],p.data['film.height']),(640,360))
    def test_unsupported_transport_does_not_shrink_film(self):
        c=self.controller();p=self.props();p.data['path.restir.gi.enable']=True
        self.assertIn('original engine',c.configure(p,p))
        self.assertEqual((p.data['film.width'],p.data['film.height']),(1280,720))
        self.assertEqual(c.trace_reduction,1,'Rejected SR must not try recovering an unstarted reduced film')
        self.assertFalse(c.restore_native(NS()))
    def test_geometry_pipeline_and_holdout_keep_target_raw(self):
        for kind in ('TONEMAP_LINEAR','BACKGROUND_IMG'):
            c=self.controller();p=self.props();p.data['film.imagepipelines.0.0.type']=kind
            self.assertEqual(c.configure(p,p),'')
            self.assertEqual(c.trace_reduction,2 if kind=='TONEMAP_LINEAR' else 1)
        c=self.controller();p=self.props();c.configure(p,p)
        c.prepare_scene(NS(ToProperties=lambda:Props(**{'scene.materials.test.holdout.enable':True})),p)
        self.assertEqual(c.trace_reduction,1);self.assertEqual(p.data['film.width'],1280)
    def test_late_primary_pipeline_keeps_its_full_target_geometry(self):
        c=self.controller();p=self.props();self.assertEqual(c.configure(p,p),'')
        self.assertEqual(c.trace_reduction,2)
        # The exporter merges the actual camera pipeline after config.convert.
        p.data['film.imagepipelines.000.2.type']='MIST'
        c.prepare_scene(NS(ToProperties=lambda:Props()),p)
        self.assertEqual(c.trace_reduction,1)
        self.assertEqual((p.data['film.width'],p.data['film.height']),(1280,720))
    def test_failed_coverage_inspection_keeps_native(self):
        def failed():raise RuntimeError('test')
        c=self.controller();p=self.props();c.configure(p,p);c.prepare_scene(NS(ToProperties=failed),p)
        self.assertEqual(c.trace_reduction,1)
    def recovery_fixture(self,fail=False):
        c=self.controller();c._source_scene=object();events=[];props=self.props()
        old=NS(IsInPause=lambda:True,ReleaseDenoisingFrameDelivery=lambda:events.append('release'),
               Resume=lambda:events.append('resume'),Stop=lambda:events.append('stop'),
               GetRenderConfig=lambda:NS(GetProperties=lambda:props))
        engine=NS(session=old)
        def config(p,scene):
            self.assertIsNone(engine.session,'Old session must be detached before allocation')
            self.assertIs(scene,c._source_scene)
            events.append('new-config')
            if fail:raise RuntimeError('start failure')
            return p
        new=NS(Start=lambda:events.append('start'),Pause=lambda:events.append('pause'))
        self.e['pysuperluxcore'].RenderConfig=config
        self.e['pysuperluxcore'].RenderSession=lambda config:new
        return c,engine,events,props,new
    def test_restore_releases_old_session_before_full_resource_allocation(self):
        c,engine,events,props,new=self.recovery_fixture()
        self.assertTrue(c.restore_native(engine));self.assertIs(engine.session,new)
        self.assertEqual(events,['release','resume','stop','new-config','start','pause'])
        self.assertEqual((props.data['film.width'],props.data['film.height']),(1280,720))
        self.assertFalse(props.data['rtpath.denoisingframes.lossless'])
        self.assertTrue(c.native_restored);self.assertFalse(c.restore_native(engine))
    def test_failed_restore_never_claims_native_or_keeps_failed_session(self):
        c,engine,events,props,new=self.recovery_fixture(fail=True)
        with self.assertRaisesRegex(RuntimeError,'start failure'):c.restore_native(engine)
        self.assertEqual(c.trace_reduction,2);self.assertFalse(c.native_restored)
        self.assertIsNone(engine.session);self.assertIn('stop',events)
    def test_cancel_never_restarts_full_render(self):
        c=self.controller();c.invalidate(NS(),'cancelled',release=False)
        self.assertEqual(c.trace_reduction,2);self.assertFalse(c.native_restored)

if __name__=='__main__':unittest.main(verbosity=2)
