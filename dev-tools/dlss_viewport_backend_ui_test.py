"""Production denoiser panel exposes CUDA selection without changing it."""
import argparse,ast,json
from pathlib import Path
from types import SimpleNamespace as NS
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]/'ui/render/viewport.py');p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-failure',action='store_true');a=p.parse_args()
cls=next(c for c in ast.parse(a.source.read_text()).body if isinstance(c,ast.ClassDef) and c.name.endswith('_denoiser'));draw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='draw');rows=[]
for selected,backend,device in [('DLSS','OPENCL','OCL'),('DLSS','CUDA','OCL'),('DLSS','CUDA','CPU'),('OIDN','OPENCL','OCL'),('OPTIX','CUDA','OCL')]:
 props=[];labels=[]
 class Layout:
  def column(self,*a,**k):return self
  def prop(self,obj,name,**k):props.append(name)
  def label(self,**k):labels.append(k['text'])
 v=NS(use_denoiser=True,denoiser=selected,device=device,can_use_optix_denoiser=lambda c:True,get_denoiser=lambda c:selected);pref=NS(gpu_backend=backend)
 ctx=NS(scene=NS(superluxcore=NS(viewport=v)));env=dict(utils=NS(get_addon_preferences=lambda c:pref),icons=NS(INFO=0))
 exec(compile(ast.Module(body=[draw],type_ignores=[]),str(a.source),'exec'),env);env['draw'](NS(layout=Layout()),ctx)
 expected=selected=='DLSS';warning=any('DLSS unavailable: select CUDA' in t for t in labels);passed=('gpu_backend' in props)==expected and warning==(expected and backend!='CUDA') and pref.gpu_backend==backend
 rows.append(dict(selected=selected,backend=backend,viewport_device=device,properties=props,labels=labels,passed=passed,backend_unchanged=pref.gpu_backend==backend))
a.out.write_text(json.dumps(dict(scope='actual production UI draw with fake layout; does not auto-switch renderer/backend',records=rows),indent=2)+'\n');print([(r['selected'],r['backend'],r['viewport_device'],r['passed']) for r in rows])
assert all(r['passed'] for r in rows) if not a.expect_failure else not all(r['passed'] for r in rows)
