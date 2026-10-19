"""Real worker function with fake backend descriptions: no unrelated Metal fills."""
import importlib.util
import os
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('worker_test_fakes',ROOT/'dev-tools/async_worker_unit_test.py')
fake=importlib.util.module_from_spec(spec);spec.loader.exec_module(fake)
if os.environ.get('SLC_WORKER_SOURCE'):
    fake.worker_mod=fake.load('baseline_worker',os.environ['SLC_WORKER_SOURCE'])


class PrefillTests(unittest.TestCase):
    def test_automatic_metal_selection_matches_core(self):
        for types,use_gpu,expected_fill in [
            (('OPENCL_GPU','METAL_GPU'),True,False),
            (('OPENCL_GPU','METAL_GPU'),False,True),
            (('OPENCL_GPU',),True,True),
            (('METAL_GPU','CUDA_GPU'),True,True),
            (('VULKAN_GPU',),True,True),
        ]:
            calls=[]
            props=fake.FakeProperties('renderengine.type','opencl.devices.select','opencl.gpu.use') << ('RTPATHOCL','',use_gpu)
            desc=fake.FakeProperties(*(f'opencl.device.{i}.type' for i in range(len(types)))) << types
            fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:desc
            fake.FakeProperty.GetBool=lambda prop:bool(prop.Get())
            fake.fake_pysuperluxcore.KernelCacheFill=lambda p:calls.append('fill')
            config=type('Config',(),{'HasCachedKernels':lambda s:False})()
            self.assertEqual(fake.worker_mod.precompile_kernels(props,config),expected_fill)
            self.assertEqual(bool(calls),expected_fill)

    def test_selected_metal_compiles_only_actual_session(self):
        for engine in ('PATHOCL','RTPATHOCL','TILEPATHOCL'):
            calls=[]
            props=fake.FakeProperties('renderengine.type','opencl.devices.select') << (engine,'01')
            desc=fake.FakeProperties('opencl.device.0.type','opencl.device.1.type') << ('OPENCL_GPU','METAL_GPU')
            fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:desc
            fake.fake_pysuperluxcore.KernelCacheFill=lambda *args:calls.append('fill')
            class Config:
                def HasCachedKernels(self):raise AssertionError('Metal must not consult an unrelated .ck stamp')
            self.assertFalse(fake.worker_mod.precompile_kernels(props,Config()))
            self.assertEqual(calls,[])

    def test_other_backends_preserve_fill_policy(self):
        for backend,expected in [('VULKAN_GPU',['RTPATHOCL']),('OPENCL_GPU',['PATHOCL','RTPATHOCL'])]:
            calls=[]
            props=fake.FakeProperties('renderengine.type','opencl.devices.select') << ('RTPATHOCL','1')
            desc=fake.FakeProperties('opencl.device.0.type') << (backend,)
            fake.fake_pysuperluxcore.GetOpenCLDeviceDescs=lambda:desc
            fake.fake_pysuperluxcore.KernelCacheFill=lambda p:calls.append(p.Get('kernelcachefill.renderengine.types').values)
            self.assertTrue(fake.worker_mod.precompile_kernels(props,type('Config',(),{'HasCachedKernels':lambda s:False})()))
            self.assertEqual(calls,[expected])


if __name__=='__main__':unittest.main(verbosity=2)
