"""Exact tuple welding order, seams and deformation mapping regression checks."""
import ast
from pathlib import Path
import unittest
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / 'export/mesh_converter.py'
node = next(n for n in ast.parse(SOURCE.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == '_weld_loop_keys')
env = {'np': np}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), env)
weld = env['_weld_loop_keys']


class Welding(unittest.TestCase):
    def check(self, parts):
        keys = np.concatenate(parts, axis=1)
        unique, rep, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
        actual_rep, actual_inv = weld(parts)
        np.testing.assert_array_equal(rep, actual_rep)
        np.testing.assert_array_equal(inv.ravel(), actual_inv)
        np.testing.assert_array_equal(unique, keys[actual_rep])
        self.assertEqual(actual_inv.dtype, np.dtype(np.uint32))
        self.assertEqual(actual_rep.dtype, np.dtype(np.intp))
        return rep, inv.ravel(), actual_rep, actual_inv

    def test_empty_single_and_all_duplicate(self):
        for count in (0, 1, 17):
            with self.subTest(count=count):
                self.check([np.zeros((count, 1), np.uint32), np.zeros((count, 3), np.uint32)])

    def test_unsigned_numeric_order_and_float_bit_seams(self):
        bits = np.array([0xffffffff, 256, 255, 1, 0, 65536, 0x80000000,
                         0x7fc00001, 0x7fc00002, 0x7f800000], np.uint32)
        # Byte order must agree across uint32 byte boundaries; signed zero and
        # distinct NaN payloads must never merge into a common float value.
        keys = np.column_stack((np.tile(bits, 2), np.repeat(bits, 2)))
        self.check([keys[:, :1], keys[:, 1:]])

    def test_random_duplicate_attributes_and_many_layers(self):
        rng = np.random.default_rng(4301)
        for count in (2, 31, 4096):
            for width in (4, 6, 13, 32):
                with self.subTest(count=count, width=width):
                    values = rng.integers(0, 2**32, (max(1, count//3), width), dtype=np.uint32)
                    keys = values[rng.integers(0, len(values), count)]
                    self.check([keys[:, :1], keys[:, 1:4], keys[:, 4:]])

    def test_strided_fortran_and_endian_inputs(self):
        rng = np.random.default_rng(4302)
        keys = rng.integers(0, 300, (1024, 12), dtype=np.uint32)
        for data in (keys[::2, ::2], np.asfortranarray(keys), keys.astype('>u4')):
            with self.subTest(strides=data.strides, dtype=data.dtype.str):
                self.check([data[:, :1], data[:, 1:]])

    def test_earliest_loop_and_material_deformation_maps(self):
        rng = np.random.default_rng(4303)
        source = rng.integers(0, 2**32, (79, 8), dtype=np.uint32)
        keys = source[rng.integers(0, len(source), 600)]
        rep, inv, actual_rep, actual_inv = self.check([keys[:, :1], keys[:, 1:]])
        triangles = rng.integers(0, len(keys), (117, 3), dtype=np.uint32)
        motion = rng.standard_normal((3, len(keys), 3)).astype(np.float32)
        for material in range(4):
            rows = np.arange(len(triangles)) % 4 == material
            old_used = np.unique(inv[triangles[rows]])
            new_used = np.unique(actual_inv[triangles[rows]])
            np.testing.assert_array_equal(old_used, new_used)
            np.testing.assert_array_equal(motion[:, rep[old_used]], motion[:, actual_rep[new_used]])
        for idx in range(len(rep)):
            self.assertEqual(rep[idx], np.flatnonzero(inv == idx)[0])


if __name__ == '__main__':
    unittest.main()
