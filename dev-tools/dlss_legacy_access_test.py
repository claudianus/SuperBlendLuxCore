"""Real Blender RNA preservation for the viewport legacy-property fast path.

Load only the bridge module, in a factory profile without the addon or native
renderer. Run once per supplied before/candidate source; compare JSON records.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import bpy

source=Path(os.environ['SLC_LEGACY_SOURCE'])
out=Path(os.environ['SLC_LEGACY_OUT'])
spec=importlib.util.spec_from_file_location('slc_legacy_access_under_test', source)
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class LegacyAccessChild(bridge.LuxCoreLegacyBridge,bpy.types.PropertyGroup):
    strength:bpy.props.FloatProperty(default=2.0)

class LegacyAccessItem(bpy.types.PropertyGroup):
    strength:bpy.props.FloatProperty(default=3.0)

class LegacyAccessRoot(bridge.LuxCoreLegacyBridge,bpy.types.PropertyGroup):
    amount:bpy.props.FloatProperty(default=1.25)
    mode:bpy.props.EnumProperty(items=[('FIRST','First','',7),('SECOND','Second','',13)],default='FIRST')
    enabled:bpy.props.BoolProperty(default=False)
    tint:bpy.props.FloatVectorProperty(size=3,default=(.1,.2,.3))
    child:bpy.props.PointerProperty(type=LegacyAccessChild)
    items:bpy.props.CollectionProperty(type=LegacyAccessItem)
    target:bpy.props.PointerProperty(type=bpy.types.Object)

records=[]
def check(name,actual,expected):
    assert actual==expected,(name,actual,expected)
    records.append({'name':name,'value':actual})
def observe(name,read):
    # Compare existing behavior independently for compatibility paths whose
    # full upstream contract is not assumed by this fast-path test.
    try:value=read()
    except Exception as exc:value={'error':type(exc).__name__}
    records.append({'name':name,'value':value})

def raw_snapshot(group):
    def val(v):
        if hasattr(v,'keys'):return {k:val(v[k]) for k in v.keys()}
        if isinstance(v,bpy.types.ID):return ('ID',v.name)
        if hasattr(v,'to_list'):return v.to_list()
        if isinstance(v,(list,tuple)):return [val(x) for x in v]
        return v
    return val(group)

for c in (LegacyAccessChild,LegacyAccessItem,LegacyAccessRoot):bpy.utils.register_class(c)
bpy.types.Scene.superluxcore=bpy.props.PointerProperty(type=LegacyAccessRoot)
scene=bpy.context.scene;root=scene.superluxcore
try:
    check('fresh scalar',root.amount,1.25)
    check('fresh enum',root.mode,'FIRST')
    check('fresh child',root.child.strength,2.0)
    check('fresh collection',len(root.items),0)
    check('fresh pointer',root.target,None)
    check('method callable',callable(root.path_from_id),True)
    check('root path',root.path_from_id(),'superluxcore')
    # Independent cost attribution: count real descriptor lookups. No timing
    # comparison or renderer performance ratio is inferred from this count.
    original=bridge._prop_def;count=[0]
    def counted(*a):count[0]+=1;return original(*a)
    bridge._prop_def=counted
    for _ in range(100):
        assert root.amount==1.25 and root.child.strength==2.0
    no_legacy_queries=count[0];bridge._prop_def=original
    scene['luxcore']={'unrelated':8}
    check('missing member',root.amount,1.25)
    root.amount=4.5
    check('missing member authored',root.amount,4.5)
    root.property_unset('amount')
    scene['luxcore']={'amount':8.5,'mode':13,'enabled':1,'tint':[.25,.5,.75],
                     'child':{'strength':12.0},'items':[{'strength':9.0},{'strength':10.0}]}
    stored_before=raw_snapshot(scene['luxcore'])
    check('legacy scalar',root.amount,8.5)
    check('legacy enum integer',root.mode,'SECOND')
    check('legacy bool',root.enabled,True)
    check('legacy vector',list(root.tint),[.25,.5,.75])
    observe('legacy child baseline behavior',lambda:root.child.strength)
    observe('legacy collection baseline behavior',lambda:[x.strength for x in root.items])
    root.amount=0.0
    check('authored zero wins',root.amount,0.0)
    root.property_unset('amount')
    check('unset restores legacy',root.amount,8.5)
    root.enabled=False
    check('authored false wins',root.enabled,False)
    root.property_unset('enabled')
    child=super(bridge.LuxCoreLegacyBridge,root).__getattribute__('child')
    child.strength=6.0
    check('authored nested leaf wins',root.child.strength,6.0)
    # A nested bridge must never read a root member of the same name.
    scene['luxcore']['strength']=99.0
    check('nested root collision ignored',child.strength,6.0)
    child.property_unset('strength')
    check('nested unset default',child.strength,2.0)
    observe('empty group baseline restored',lambda:root.child.strength)
    native_items=super(bridge.LuxCoreLegacyBridge,root).__getattribute__('items')
    native_items.add().strength=4.0
    check('authored collection wins',[x.strength for x in root.items],[4.0])
    native_items.clear()
    observe('cleared collection baseline restored',lambda:[x.strength for x in root.items])
    obj=bpy.data.objects.new('legacy-target',None);scene.collection.objects.link(obj)
    scene['luxcore']['target']=obj
    observe('resolved legacy ID baseline behavior',lambda:root.target.name if root.target else None)
    other=bpy.data.objects.new('authored-target',None);scene.collection.objects.link(other);root.target=other
    check('authored ID wins',root.target.name,other.name)
    root.property_unset('target')
    observe('unset ID baseline restored',lambda:root.target.name if root.target else None)
    scene['luxcore']['target']={}
    check('unresolved legacy ID',root.target,None)
    # Refresh descriptors through real engine switches, retaining live values.
    scene['luxcore']['mode']=13
    for engine in ['CYCLES','BLENDER_EEVEE','CYCLES']:
        scene.render.engine=engine
        check('engine '+engine,root.mode,'SECOND')
    scene['luxcore']['mode']=999
    check('invalid enum default',root.mode,'FIRST')
    scene['luxcore']['mode']='SECOND'
    check('string enum',root.mode,'SECOND')
    # Reads cannot create/write stored upstream values, including missing keys.
    before=raw_snapshot(scene['luxcore'])
    for _ in range(10):
        root.amount;root.tint;root.mode;root.enabled;root.child.strength;root.items;root.target
    check('legacy storage read-only',raw_snapshot(scene['luxcore']),before)
    del scene['luxcore']
    check('legacy removed live',root.amount,1.25)
    scene['luxcore']={'amount':21.0}
    check('legacy added live',root.amount,21.0)
    scene['luxcore']['amount']=22.0
    check('legacy edited live',root.amount,22.0)
    out.write_text(json.dumps({'passed':True,'checks':records,'no_legacy_descriptor_queries_200_values':no_legacy_queries,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},indent=2)+'\n')
    print('Legacy RNA checks passed:',len(records),'no-legacy RNA queries:',no_legacy_queries,flush=True)
finally:
    del bpy.types.Scene.superluxcore
    for c in (LegacyAccessRoot,LegacyAccessItem,LegacyAccessChild):bpy.utils.unregister_class(c)
