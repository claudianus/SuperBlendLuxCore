"""Direct versus worker-staged native scene: exact720p raw preservation."""
from pathlib import Path
import argparse,ast,hashlib,importlib.util,json,os,threading,sys
import numpy as np
here=Path(__file__).parent

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

m=load('staged_native_mesh',here/'geometry_staging_test.py');r=load('staged_scene_commands',Path(os.environ.get('SLC_DLSS_TEST_ADDON',str(here.parent)))/'export/recorded_scene.py')
p=argparse.ArgumentParser();p.add_argument('--mode',choices=['direct','staged'],required=True);p.add_argument('--compare',type=Path);p.add_argument('--engine',choices=['TILEPATHCPU','TILEPATHOCL'],required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--grid-fixture',type=Path,required=True);args=p.parse_args();assert not args.out.exists();args.out.mkdir(parents=True)
# Reuse the immutable large-grid fixture; do not execute its CLI runner.
base_fixture=m.fixture;nodes=ast.parse(args.grid_fixture.read_text()).body;node=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name=='fixture');scope={'np':np,'base_fixture':base_fixture};exec(compile(ast.Module(body=[node],type_ignores=[]),str(args.grid_fixture),'exec'),scope);original_fixture=scope['fixture'];m.fixture=original_fixture
factory=m.s.Scene;m.s.Init();records=[];payloads=[];build_threads=[]

def staged_fixture(case):
 def deferred(*constructor_args):
  assert len(constructor_args)<=2
  policy=constructor_args[1] if len(constructor_args)==2 else m.s.Properties()
  return r.DeferredScene(factory,m.s.Properties,policy)
 m.s.Scene=deferred
 try:scene,unique=original_fixture(case)
 finally:m.s.Scene=factory
 assert isinstance(scene,r.DeferredScene) and scene.synchronous_reason is None
 assert scene.IsMaterialDefined('colored') and scene.IsMaterialDefined('blue')
 assert scene.IsTextureDefined('vertexcolor') and scene.IsMeshDefined('base')
 assert scene.GetObjectCount()>0
 output=[];errors=[]
 def build():
  build_threads.append(threading.get_ident())
  try:output.append(scene._build_pending_scene())
  except BaseException as e:errors.append(e)
 thread=threading.Thread(target=build);thread.start();thread.join(90)
 assert not thread.is_alive(),'Native build did not finish';assert not errors,errors
 assert output[0] is not None;payloads.append(scene);return output[0],unique

try:
 for case in ['direct-first','instance-first','motion-first','distinct-same-count','grid-128','grid-384']:
  # Material defaults use a process-global atomic index. Run each path in a
  # separate fresh process, with the same scene creation sequence.
  m.fixture=staged_fixture if args.mode=='staged' else original_fixture
  data,_=m.render(case,args.engine,(1280,720))
  np.savez_compressed(args.out/(case+'.npz'),**data)
  hashes={key:hashlib.sha256(v.tobytes()).hexdigest() for key,v in data.items()}
  if args.compare:
   with np.load(args.compare/(case+'.npz')) as old:
    assert set(old.files)==set(data)
    for key,value in data.items():
     np.testing.assert_array_equal(old[key],value,err_msg=case+':'+key)
  records.append({'case':case,'all_byte_exact':bool(args.compare),'channels':hashes})
  while payloads:payloads.pop().close()
 assert all(t!=threading.get_ident() for t in build_threads)
 result={'passed':True,'cases':records,'mode':args.mode,'engine':args.engine,'native_sha256':hashlib.file_digest(Path(m.s.pysuperluxcore.__file__).open('rb'),'sha256').hexdigest(),'build_on_worker_verified':args.mode=='staged','scope':__doc__+' Independent fresh processes preserve default material IDs. No timing or general quality claim.'};(args.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

finally:
 m.s.Scene=factory
 while payloads:payloads.pop().close()
