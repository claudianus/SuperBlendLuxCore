"""Exercise the real viewport presentation branches after DLSS failure."""
import argparse,ast,json,unittest
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT/'engine/viewport.py');p.add_argument('--expect-failure',action='store_true');p.add_argument('--out',type=Path,required=True);args=p.parse_args()
fn=next(n for n in ast.parse(args.source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='view_draw')
start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='rendered_time' for t in n.targets))
end=next(i for i,n in enumerate(fn.body[start:],start) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='draw')
code=compile(ast.Module(body=fn.body[start:end+1],type_ignores=[]),str(args.source),'exec')
records=[]
for paused in (False,True):
 for requested,handled in [('DLSS',False),('DLSS',True),('OIDN',False),('OPTIX',False),(None,False)]:
  calls=[];vp=NS(use_denoiser=requested is not None,denoiser=requested,halt_time=5.,denoise_interactive=True,min_samples=1,get_denoiser=lambda c:requested)
  scene=NS(superluxcore=NS(viewport=vp));context=NS(scene=scene)
  session=NS(IsInPause=lambda:True,Pause=lambda:calls.append('pause'))
  fb=NS(denoised=False,_read_thread=None,consume_dlss_result=lambda *a:handled,consume_denoise_result=lambda *a:False,is_denoiser_active=lambda:False,start_denoiser=lambda *a:calls.append('oidn'),interactive_denoise_tick=lambda *a:calls.append('oidn') or True,update_async=lambda *a:calls.append('raw'),draw=lambda *a:None)
  e=NS(viewport_start_time=0.,tag_redraw=lambda:None)
  env=dict(engine=e,context=context,scene=scene,session=session,framebuffer=fb,worker=NS(phase='',dlss_status='DLSS fallback: injected NGX failure'),time=lambda:10. if paused else 1.,utils=NS(in_material_shading_mode=lambda c:False),_locked_session_call=lambda e,f:f())
  exec(code,env)
  expected=requested=='OIDN' or requested=='DLSS' and not handled
  passed=('oidn' in calls)==expected
  records.append(dict(paused=paused,requested=requested,dlss_presented=handled,calls=calls,passed=passed,status=env.get('status_message')))
args.out.write_text(json.dumps({'scope':'actual production viewport presentation branches; fake frame/worker failures, no GPU evaluation','records':records},indent=2)+'\n')
print([(r['paused'],r['requested'],r['dlss_presented'],r['passed']) for r in records])
assert all(r['passed'] for r in records) if not args.expect_failure else sum(not r['passed'] for r in records)==2
