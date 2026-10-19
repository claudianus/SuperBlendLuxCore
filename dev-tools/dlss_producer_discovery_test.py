"""Bounded hardware discovery: refresh, failure recovery and native reloads."""
import ast
from pathlib import Path
import types
import unittest


class Discovery(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.calls = 0
        self.available = True
        self.error = None
        case = self

        class Value:
            def __init__(self, value): self.value = value
            def GetBool(self): return bool(self.value)
            def GetString(self): return str(self.value)

        class Properties:
            def __init__(self, values): self.values = values
            def Get(self, name): return Value(self.values[name])
            def GetAllUniqueSubNames(self, prefix): return ['opencl.device.0']

        def devices():
            case.calls += 1
            if case.error: raise case.error
            return Properties({'opencl.device.0.type': 'CUDA_GPU' if case.available else 'OPENCL_GPU'})

        self.native = types.SimpleNamespace(
            DenoisingImagePipeline=object,
            GetPlatformDesc=lambda: Properties({'compile.LUXRAYS_ENABLE_CUDA': True}),
            GetOpenCLDeviceDescs=devices,
        )
        source = ast.parse((Path(__file__).resolve().parents[1]/'engine/dlss_viewport.py').read_text())
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('producer_available', '_query_producer_available')]
        self.env = {'pysuperluxcore': self.native, 'monotonic': lambda: self.now}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'discovery', 'exec'), self.env)
        self.check = self.env['producer_available']

    def test_draws_reuse_one_query_until_expiry(self):
        for self.now in [0., .01, .2, .999]:
            self.assertEqual(self.check(), (True, ''))
        self.assertEqual(self.calls, 1)
        self.now = 1.
        self.assertTrue(self.check()[0])
        self.assertEqual(self.calls, 2)

    def test_device_removal_is_observed_at_refresh(self):
        self.assertTrue(self.check()[0])
        self.available = False
        self.now = 1.
        self.assertFalse(self.check()[0])
        self.assertEqual(self.calls, 2)

    def test_absent_device_recovers_without_addon_reload(self):
        self.available = False
        self.assertFalse(self.check()[0])
        self.available = True
        self.now = .5
        self.assertFalse(self.check()[0])
        self.now = 1.
        self.assertTrue(self.check()[0])
        self.assertEqual(self.calls, 2)

    def test_query_error_is_bounded_and_retried(self):
        self.error = RuntimeError('device unavailable')
        self.assertEqual(self.check(), (False, 'device unavailable'))
        self.error = None
        self.assertFalse(self.check()[0])
        self.assertEqual(self.calls, 1)
        self.now = 1.
        self.assertTrue(self.check()[0])
        self.assertEqual(self.calls, 2)

    def test_native_api_change_invalidates_immediately(self):
        self.assertTrue(self.check()[0])
        def changed(): raise KeyError('new device list')
        self.native.GetOpenCLDeviceDescs = changed
        self.assertFalse(self.check()[0])

    def test_native_capability_change_invalidates_immediately(self):
        self.assertTrue(self.check()[0])
        del self.native.DenoisingImagePipeline
        self.assertFalse(self.check()[0])

    def test_non_cuda_never_queries_drivers(self):
        for backend in ['METAL', 'CPU', 'OPENCL']:
            self.assertFalse(self.check(backend)[0])
        self.assertEqual(self.calls, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
