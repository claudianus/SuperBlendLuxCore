# SPDX-License-Identifier: Apache-2.0
"""Private Metal hybrid extension of the unchanged-Cycles 720p diagnostic.

The existing harness is extended only in this process. Its authored graph and
shipping adapter remain separate from experimental native transport. Use the
complete isolated profile/identity and SUPERLUXCORE_BSSRDF_DEVICE=METALHYBRID.
"""
import ast
import hashlib
import json
import os
from pathlib import Path

assert os.environ['SUPERLUXCORE_BSSRDF_DEVICE'] == 'METALHYBRID'
source = Path(__file__).with_name('cycles-bssrdf-experimental-test.py')
text = source.read_text()


class DeviceExtension(ast.NodeTransformer):
    def __init__(self):
        self.counts = {'allowed_modes': 0, 'adjoint_modes': 0, 'engine_table': 0,
                       'device_flag': 0, 'hybrid_comparisons': 0, 'light_enable': 0}

    def visit_Tuple(self, node):
        self.generic_visit(node)
        values = [n.value if isinstance(n, ast.Constant) else None for n in node.elts]
        if values == ['CPU', 'METAL', 'LIGHTCPU', 'CPUHYBRID']:
            node.elts.append(ast.Constant('METALHYBRID'))
            self.counts['allowed_modes'] += 1
        elif values == ['LIGHTCPU', 'CPUHYBRID']:
            node.elts.append(ast.Constant('METALHYBRID'))
            self.counts['adjoint_modes'] += 1
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], ast.Eq):
            rhs = node.comparators[0]
            if isinstance(rhs, ast.Constant) and rhs.value in ('METAL', 'CPUHYBRID'):
                count = 'device_flag' if rhs.value == 'METAL' else 'hybrid_comparisons'
                self.counts[count] += 1
                return ast.copy_location(ast.Compare(left=node.left, ops=[ast.In()],
                    comparators=[ast.Tuple(elts=[rhs, ast.Constant('METALHYBRID')], ctx=ast.Load())]), node)
        return node

    def visit_Dict(self, node):
        self.generic_visit(node)
        keys = [n.value if isinstance(n, ast.Constant) else None for n in node.keys]
        if keys == ['CPU', 'METAL', 'LIGHTCPU', 'CPUHYBRID']:
            node.keys.append(ast.Constant('METALHYBRID'))
            node.values.append(ast.Constant('PATHOCL'))
            self.counts['engine_table'] += 1
        if 'path.lighttracing.enable' in keys:
            i = keys.index('path.lighttracing.enable')
            assert isinstance(node.values[i], ast.Constant) and node.values[i].value is False
            node.values[i] = ast.Compare(left=ast.Name(id='device', ctx=ast.Load()),
                ops=[ast.Eq()], comparators=[ast.Constant('METALHYBRID')])
            node.keys.append(ast.Constant('pathocl.wavefront'))
            node.values.append(ast.Call(func=ast.Attribute(value=ast.Attribute(
                value=ast.Name(id='os', ctx=ast.Load()), attr='environ', ctx=ast.Load()),
                attr='get', ctx=ast.Load()), args=[ast.Constant('SUPERLUXCORE_BSSRDF_WAVEFRONT'),
                ast.Constant('off')], keywords=[]))
            node.keys.append(ast.Constant('opencl.native.threads.count'))
            node.values.append(ast.Constant(0))
            self.counts['light_enable'] += 1
        return node


extension = DeviceExtension()
tree = ast.fix_missing_locations(extension.visit(ast.parse(text)))
assert extension.counts == {'allowed_modes': 1, 'adjoint_modes': 1, 'engine_table': 1,
                            'device_flag': 1, 'hybrid_comparisons': 3, 'light_enable': 1}, extension.counts
folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
patched = ast.unparse(tree) + '\n'
(folder / 'private-device-harness.py').write_text(patched)
(folder / 'private-device-harness-identity.json').write_text(json.dumps({
    'original_harness_sha256': hashlib.sha256(text.encode()).hexdigest(),
    'extension_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'private_harness_sha256': hashlib.sha256(patched.encode()).hexdigest(),
    'changes': extension.counts, 'production_acceptance': False}, indent=2) + '\n')
try:
    # The original fixture requires its source-harness directory explicitly.
    # Keep that provenance; the separate hashes above identify this extension.
    exec(compile(tree, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})
finally:
    report = folder / 'experimental-export.json'
    if report.exists():
        data = json.loads(report.read_text())
        data.update(cpu_hybrid=False, gpu_hybrid=True, production_acceptance=False,
                    wavefront=os.environ.get('SUPERLUXCORE_BSSRDF_WAVEFRONT', 'off'))
        report.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
