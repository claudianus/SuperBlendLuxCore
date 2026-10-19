"""Exact-session startup for opt-in coherent frames; ordinary CUDA unchanged."""
import importlib.util
import ast
from pathlib import Path
import types
import unittest

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dlss_config_fakes',root/'dev-tools/async_worker_unit_test.py')
fake=importlib.util.module_from_spec(spec);spec.loader.exec_module(fake)

class Prefill(unittest.TestCase):
    def test_producer_capability_is_independent_of_sdk_paths(self):
        source=ast.parse((root/'engine/dlss_viewport.py').read_text())
        functions=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in ('producer_available','_query_producer_available')]
        class Value:
            def __init__(self,value):self.value=value
            def GetBool(self):return bool(self.value)
            def GetString(self):return str(self.value)
        class Properties:
            def __init__(self,values):self.values=values
            def Get(self,name):return Value(self.values[name])
            def GetAllUniqueSubNames(self,prefix):return ['opencl.device.0']
        native=types.SimpleNamespace(DenoisingImagePipeline=object,
            GetPlatformDesc=lambda:Properties({'compile.LUXRAYS_ENABLE_CUDA':True}),
            GetOpenCLDeviceDescs=lambda:Properties({'opencl.device.0.type':'CUDA_GPU'}))
        env={'pysuperluxcore':native,'monotonic':lambda:0.};exec(compile(ast.Module(body=functions,type_ignores=[]),'producer_capability','exec'),env)
        self.assertEqual(env['producer_available']('CUDA'),(True,''))
        self.assertFalse(env['producer_available']('METAL')[0])
        native.GetOpenCLDeviceDescs=lambda:Properties({'opencl.device.0.type':'OPENCL_GPU'})
        self.assertFalse(env['producer_available']('CUDA')[0])
    def test_dlss_rt_skips_unrelated_program_and_stamp(self):
        fake.FakeProperty.GetBool=lambda prop:bool(prop.Get())
        fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:fake.FakeProperties('opencl.device.0.type')<<('CUDA_GPU',)
        fills=[];stamps=[]
        fake.fake_pysuperluxcore.KernelCacheFill=lambda props:fills.append(props)
        class Config:
            def HasCachedKernels(self):stamps.append(True);return False
        for engine,coherent,expected in [('RTPATHOCL',True,False),('RTPATHOCL',False,True),('PATHOCL',True,True)]:
            fills.clear();stamps.clear()
            props=fake.FakeProperties('renderengine.type','opencl.devices.select','rtpath.denoisingframes.enable')<<(engine,'1',coherent)
            self.assertEqual(fake.worker_mod.precompile_kernels(props,Config()),expected)
            self.assertEqual(bool(fills),expected)
            self.assertEqual(bool(stamps),expected)

if __name__=='__main__':unittest.main(verbosity=2)
