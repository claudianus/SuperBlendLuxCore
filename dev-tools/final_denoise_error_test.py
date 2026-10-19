"""A failed native denoise must not replace Combined or claim success."""
import argparse,ast,json
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]/'draw/final.py');p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-failure',action='store_true');a=p.parse_args()
cls=next(n for n in ast.parse(a.source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='FrameBufferFinal')
methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('_refresh_denoiser','_denoised_to_combined')]
errors=[];statuses=[];resume=[]
env=dict(np=np,plc=NS(FilmOutputType=NS(RGBA_IMAGEPIPELINE='rgba',RGB_IMAGEPIPELINE='rgb')),time=lambda:10.,sleep=lambda t:None,SuperLuxCoreDenoiser=NS(refresh=False),SuperLuxCoreDisplaySettings=NS(paused=False),get_denoiser_imgpipeline_props=lambda *args:None,SuperLuxCoreErrorLog=NS(add_error=errors.append))
exec(compile(ast.Module(body=methods,type_ignores=[]),str(a.source),'exec'),env)
class Rect:
 def __init__(self,values):self.pixels=np.asarray(values,dtype=np.float32)
 def foreach_get(self,b):b[:]=self.pixels.ravel()
 def foreach_set(self,b):self.pixels=np.asarray(b).copy()
raw=np.array([.1,.2,.3,1.,.7,.6,.5,1.],np.float32)
layer=NS(passes={'Combined':NS(rect=Rect(raw),channels=4),'DENOISED':NS(rect=Rect(np.zeros(8)),channels=4)})
film=NS(AsyncExecuteImagePipeline=lambda i:None,HasDoneAsyncExecuteImagePipeline=lambda:(_ for _ in ()).throw(RuntimeError('injected GPU image pipeline failure')))
s=NS(Parse=lambda p:None,IsStarted=lambda:True,IsInPause=lambda:False,Pause=lambda:None,Resume=lambda:resume.append(True),GetFilm=lambda:film,GetStats=lambda:NS(Get=lambda k:NS(GetInt=lambda:4)))
e=NS(final_dlss=None,has_denoiser=lambda:True,DENOISED_OUTPUT_NAME='DENOISED',aov_imagepipelines={'DENOISED':1},session=s,is_animation=False,update_stats=lambda *args:statuses.append(args))
scene=NS(superluxcore=NS(denoiser=NS(periodic_refresh=True,periodic_interval=5.,to_combined=True)))
fb=NS(_width=2,_height=1,_transparent=True,denoiser_last_samples=1,denoiser_last_time=0.,denoiser_last_elapsed_time=0,_import_aov=lambda *a,**k:None)
env['_refresh_denoiser'](fb,e,s,scene,layer,True);env['_denoised_to_combined'](fb,e,scene,layer)
result=dict(raw_Combined_preserved=bool(np.array_equal(layer.passes['Combined'].rect.pixels,raw)),failed_samples_not_marked_success=fb.denoiser_last_samples==0,error_reported=bool(errors),no_success_status=not any(x[0]=='Denoiser Done' for x in statuses),errors=errors,statuses=statuses)
a.out.write_text(json.dumps(result,indent=2)+'\n');print(result)
checks=[result[k] for k in ['raw_Combined_preserved','failed_samples_not_marked_success','error_reported','no_success_status']]
assert all(checks) if not a.expect_failure else not all(checks)
