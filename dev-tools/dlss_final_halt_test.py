"""Final animation/layer guards on RNA groups without Python methods."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'engine/final.py'

def halt(enable=True, samples=False):
    return NS(enable=enable, use_samples=samples, use_time=False,
              use_noise_thresh=False, use_noise_level=False)

def layer(name, override=None, use=True):
    return NS(name=name, use=use, superluxcore=NS(halt=override or halt(False)))

class Halts(unittest.TestCase):
    def setUp(self):
        self.errors = []
        env = {'SuperLuxCoreErrorLog': NS(add_error=self.errors.append)}
        function = next(node for node in ast.parse(SOURCE.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == '_check_halt_conditions')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), env)
        self.check = env['_check_halt_conditions']

    def scene(self, global_halt, layers):
        return NS(superluxcore=NS(halt=global_halt), view_layers=layers)

    def test_two_layers_inherit_global_without_rna_convenience_method(self):
        self.check(NS(is_animation=False), self.scene(halt(samples=True), [layer('A'), layer('B')]))
        self.assertEqual(self.errors, [])

    def test_single_animation_requires_an_actual_halt(self):
        with self.assertRaisesRegex(Exception, 'Missing halt condition'):
            self.check(NS(is_animation=True), self.scene(halt(), [layer('Animation')]))
        self.assertIn('Animation', self.errors[0])

    def test_explicit_empty_layer_override_cannot_fall_back_to_global(self):
        with self.assertRaisesRegex(Exception, 'Missing halt condition'):
            self.check(NS(is_animation=False), self.scene(halt(samples=True),
                [layer('Valid'), layer('Unbounded', halt())]))
        self.assertEqual(len(self.errors), 1)
        self.assertIn('Unbounded', self.errors[0])

    def test_valid_layer_overrides_work_with_global_disabled(self):
        self.check(NS(is_animation=True), self.scene(halt(False),
            [layer('A', halt(samples=True)), layer('B', halt(samples=True))]))
        self.assertEqual(self.errors, [])

    def test_interactive_still_and_disabled_layers_do_not_require_a_halt(self):
        self.check(NS(is_animation=False), self.scene(halt(False), [layer('Still')]))
        self.check(NS(is_animation=True), self.scene(halt(samples=True),
            [layer('Valid'), layer('Disabled', halt(), use=False)]))
        self.assertEqual(self.errors, [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
