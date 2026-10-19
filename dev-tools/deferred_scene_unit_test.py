"""Ownership/order/cancellation of initial scene construction, without bpy."""
from pathlib import Path
import gc
import importlib.util
import tempfile
import threading
import time
import unittest
import weakref
import numpy as np

p=Path(__file__).parent
spec=importlib.util.spec_from_file_location('deferred_fakes',p/'async_worker_unit_test.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
D=f.recorded_mod.DeferredScene
files=f.recorded_mod.temporary_image_files

class Scene(f.FakeScene):
    def __init__(self,*args):
        super().__init__();self.thread=threading.get_ident();self.events=[]
    def Parse(self,props):
        self.events.append(('Parse',tuple((n,tuple(props.Get(n).values)) for n in props.GetAllNames())))
    def DefineMeshExt(self,*args,**kw):
        points=kw.get('points',args[1] if len(args)>1 else None)
        self.events.append(('mesh',float(points.sum()),threading.get_ident()))
    def DefineBlenderStrands(self,*args):
        self.events.append(('hair',threading.get_ident()));return False
    def UpdateObjectTransformation(self,name,value):
        self.events.append(('transform',name,value))
    def GetLightCount(self):return 17

def props(value):return f.FakeProperties('probe')<<(value,)
def stage(factory=Scene):return D(factory,f.FakeProperties,props(3))
def config():return f.FakeProperties('renderengine.type')<<('RTPATHCPU',)

def wait(pred):
    if not f.wait_until(pred,3):raise AssertionError('Worker did not reach the expected state')

class Ownership(unittest.TestCase):
    def tearDown(self):
        self.assertEqual(files.readers,{})
        self.assertEqual(files.pending,set())

    def test_mutable_properties_and_numpy_are_owned_before_worker_runs(self):
        s=stage();a=np.arange(12,dtype=np.float32).reshape(4,3);q=props(7)
        s.Parse(q);s.DefineMeshExt(name='mesh',points=a,triangles=np.array([[0,1,2]],np.uint32))
        q.Set(f.FakeProperty('probe',[99]));a.fill(-1)
        output=[];t=threading.Thread(target=lambda:output.append(s._build_pending_scene()));t.start();t.join(3)
        self.assertFalse(t.is_alive());native=output[0]
        self.assertEqual(native.events[0],('Parse',(('probe',(7,)),)))
        self.assertEqual(native.events[1][1],66.0)
        self.assertNotEqual(native.thread,threading.get_ident());s.close()

    def test_native_qualified_property_names_answer_leaf_queries(self):
        class QualifiedProperties(f.FakeProperties):
            def GetAllUniqueSubNames(self,prefix):
                return [prefix+'.'+x for x in super().GetAllUniqueSubNames(prefix)]
        q=QualifiedProperties('scene.materials.red.type')<<('matte',)
        q.Set(f.FakeProperty('scene.textures.color.type',['constfloat3']))
        q.Set(f.FakeProperty('scene.objects.obj.vertices',[0.,0.,0.]))
        q.Set(f.FakeProperty('scene.objects.obj.material',['red']))
        s=stage();s._track_props(q)
        self.assertTrue(s.IsMaterialDefined('red'))
        self.assertTrue(s.IsTextureDefined('color'))
        self.assertTrue(s.IsMeshDefined('InlinedMesh-obj'))
        self.assertEqual(s.GetObjectCount(),1);s.close()

    def test_wrapper_finalizer_defers_delete_until_scene_retires(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper=tempfile.NamedTemporaryFile(delete=False,dir=tmp);path=Path(wrapper.name)
            weakref.finalize(wrapper,files.remove,str(path));wrapper.close()
            s=stage();s.pin_files([str(path)]);del wrapper;gc.collect()
            self.assertTrue(path.exists());s.close();self.assertFalse(path.exists())

    def test_image_cleanup_waits_for_all_scene_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'owned.png';path.write_bytes(b'packed image')
            a,b=stage(),stage();a.pin_files([str(path)]);b.pin_files([str(path)])
            files.remove(str(path));self.assertTrue(path.exists())
            a.close();self.assertTrue(path.exists())
            b.close();self.assertFalse(path.exists());b.close()

    def test_hair_native_false_and_exact_order_are_preserved_on_main_thread(self):
        s=stage();s.Parse(props(7));self.assertIsNone(s.GetLightCount())
        self.assertFalse(s.DefineBlenderStrands('zero-length',[]))
        self.assertEqual(s.synchronous_reason,'DefineBlenderStrands')
        native=s._build_pending_scene();self.assertEqual([x[0] for x in native.events],['Parse','hair'])
        self.assertEqual(native.thread,threading.get_ident());self.assertEqual(s.GetLightCount(),17);s.close()

    def test_unknown_native_value_uses_sync_compatibility_path(self):
        class NativeTransform:pass
        transform=NativeTransform();s=stage();s.Parse(props(1))
        s.UpdateObjectTransformation('obj',transform)
        native=s._build_pending_scene();self.assertIs(native.events[-1][-1],transform)
        self.assertEqual(native.thread,threading.get_ident());s.close()

    def test_worker_constructs_on_worker_and_owns_files_until_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(b'payload')
            s=stage();s.pin_files([str(path)]);s.Parse(props(7));files.remove(str(path))
            worker=f.worker_mod.SessionWorker()
            try:
                worker.submit_start(s,config());wait(lambda:worker.session is not None)
                self.assertIs(worker.scene,s._native);self.assertEqual(worker.scene_light_count,17)
                self.assertNotEqual(worker.scene.thread,threading.get_ident());self.assertTrue(path.exists())
                worker.submit_config(config());wait(lambda:not worker._lifecycle_busy)
                self.assertTrue(path.exists());worker.submit_stop();wait(lambda:worker.scene is None)
                self.assertFalse(path.exists())
            finally:worker.shutdown();worker._thread.join(3);self.assertFalse(worker._thread.is_alive())

    def test_queued_stop_discards_snapshots_without_constructing(self):
        constructed=[]
        def factory(*a):constructed.append(True);return Scene()
        s=stage(factory);s.DefineMeshExt(name='m',points=np.ones((64,3),np.float32))
        reference=weakref.ref(s._ops[0][2]['points']);worker=f.worker_mod.SessionWorker()
        try:
            with worker._cond:
                worker.submit_start(s,config());worker.submit_stop()
            wait(lambda:worker._starting==0);gc.collect()
            self.assertFalse(constructed);self.assertIsNone(reference())
        finally:worker.shutdown();worker._thread.join(3);self.assertFalse(worker._thread.is_alive())

    def test_active_stop_cancels_between_commands_and_releases_last_args(self):
        entered,release=threading.Event(),threading.Event();seen=[]
        class SlowScene(Scene):
            def DefineMeshExt(self,*a,**kw):
                seen.append(kw['name']);entered.set();release.wait(2)
        s=stage(SlowScene);s.DefineMeshExt(name='first',points=np.ones((64,3),np.float32));s.DefineMeshExt(name='second',points=np.ones((64,3),np.float32))
        refs=[weakref.ref(op[2]['points']) for op in s._ops];worker=f.worker_mod.SessionWorker()
        try:
            worker.submit_start(s,config());self.assertTrue(entered.wait(2));worker.submit_stop();release.set()
            wait(lambda:worker._starting==0);self.assertIsNone(worker.session);self.assertEqual(seen,['first']);gc.collect()
            self.assertTrue(all(r() is None for r in refs))
        finally:release.set();worker.shutdown();worker._thread.join(3);self.assertFalse(worker._thread.is_alive())

    def test_native_error_closes_file_pins_and_does_not_publish(self):
        class BadScene(Scene):
            def Parse(self,props):raise RuntimeError('native initial scene failure')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(b'payload')
            s=stage(BadScene);s.pin_files([str(path)]);s.Parse(props(7));files.remove(str(path));worker=f.worker_mod.SessionWorker()
            try:
                worker.submit_start(s,config());wait(lambda:worker._starting==0)
                self.assertIsNone(worker.session);self.assertFalse(path.exists());self.assertIsNotNone(worker.pop_error())
            finally:worker.shutdown();worker._thread.join(3);self.assertFalse(worker._thread.is_alive())

if __name__=='__main__':unittest.main(verbosity=2)
