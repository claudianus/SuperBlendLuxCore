# SPDX-License-Identifier: Apache-2.0
"""Live Blender RNA export: valid zero sockets and real unsupported group."""
import hashlib, importlib, json, os
from pathlib import Path
import bpy, pysuperluxcore as native
package=next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
reader=importlib.import_module(package+'.export.cycles_node_reader')
log=importlib.import_module(package+'.utils.errorlog').SuperLuxCoreErrorLog
root=Path(os.environ['SUPERLUXCORE_AUDIT_DIR']);root.mkdir(parents=True,exist_ok=True)
rows=[]
for kind,socket,key,value in [('ShaderNodeSubsurfaceScattering','Scale','subsurfaceradius',0.0),('ShaderNodeSubsurfaceScattering','Roughness','specularroughness',0.0),('ShaderNodeBsdfSheen','Roughness','sheenroughness',0.0),('ShaderNodeSubsurfaceScattering','Scale','subsurfaceradius',.2),('ShaderNodeSubsurfaceScattering','Roughness','specularroughness',.2),('ShaderNodeBsdfSheen','Roughness','sheenroughness',.2),('mix_group','Fac','amount',0.0),('invert_group','Fac','color',0.0),('broken_group','Scale','subsurfaceradius',1.0)]:
 mat=bpy.data.materials.new(kind+socket+str(value));mat.use_nodes=True;n=mat.node_tree.nodes;l=mat.node_tree.links;n.clear();props=native.Properties();log.clear(False)
 if kind in ('mix_group','invert_group','broken_group'):
  group=bpy.data.node_groups.new('existing zero group','ShaderNodeTree');out_socket=group.interface.new_socket(name='Constant',in_out='OUTPUT',socket_type='NodeSocketFloat');out_socket.default_value=0.0
  if kind!='broken_group':group.nodes.new('NodeGroupOutput')
  gn=n.new('ShaderNodeGroup');gn.node_tree=group
  target=n.new('ShaderNodeMixShader' if kind=='mix_group' else ('ShaderNodeInvert' if kind=='invert_group' else 'ShaderNodeSubsurfaceScattering'))
  l.new(gn.outputs['Constant'],target.inputs[socket])
  if kind=='mix_group':
   for i in (1,2):
    e=n.new('ShaderNodeEmission');l.new(e.outputs[0],target.inputs[i])
  if kind=='invert_group':target.inputs['Color'].default_value=(.2,.4,.6,1)
 else:
  target=n.new(kind);assert target.inputs.get(socket) is not None,(kind,socket);target.inputs[socket].default_value=value
 before=tuple((a.from_node.name,a.from_socket.name,a.to_node.name,a.to_socket.name) for a in l)
 result=reader._node(target,target.outputs[0],props,mat,'zero_check')
 if kind=='invert_group':actual=result;expected=[.2,.4,.6];passed=isinstance(actual,list) and max(abs(a-b) for a,b in zip(actual,expected))<1e-6
 elif kind == 'ShaderNodeSubsurfaceScattering' and socket == 'Scale' and value == 0.0:actual=props.Get('scene.materials.zero_check.type').GetString();expected='matte';passed=actual == expected
 else:
  if kind == 'ShaderNodeBsdfSheen' and props.Get('scene.materials.zero_check.type').GetString() == 'openpbr':key='fuzzroughness'
  actual=props.Get('scene.materials.zero_check.'+key).GetFloat();expected=value;passed=abs(actual-expected)<1e-6
 warnings=[w.message for w in log.warnings];errors=[e.message for e in log.errors]
 if kind=='broken_group':passed=passed and any('사용 가능한 그룹 출력이 없음' in w for w in warnings)
 else:passed=passed and not warnings
 assert before==tuple((a.from_node.name,a.from_socket.name,a.to_node.name,a.to_socket.name) for a in l)
 rec={'case':kind+'_'+socket+'_'+str(value),'passed':passed and not errors,'actual':actual,'expected':expected,'warnings':warnings,'errors':errors,'graph_unchanged':True,'reader_sha256':hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),'native_version':native.Version()};rows.append(rec)
 (root/'metrics.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n');print('ZERO_EXPORT',rec,flush=True)
 if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE')!='1':assert rec['passed'],rec
print('ZERO_EXPORT_COMPLETE',len(rows),sum(r['passed'] for r in rows),flush=True)
