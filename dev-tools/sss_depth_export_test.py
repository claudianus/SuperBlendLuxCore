"""Exercise the actual path-depth export with authored/native/Cycles limits.

Use only the depth prefix of _convert_path so this test runs without Blender;
the companion Blender render covers registration and complete configuration.
"""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('blender_settings', ROOT/'export/blender_settings.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)
tree = ast.parse((ROOT/'export/config.py').read_text())
func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_convert_path')
# The first non-depth block is the hybrid light-tracing selection. Keep the
# preceding production statements, including all volume export branches.
cut = next(i for i,n in enumerate(func.body) if isinstance(n,ast.If)
           and isinstance(n.test,ast.UnaryOp))
func.body = func.body[:cut]
namespace = {'blender_settings': settings}
exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])), str(ROOT/'export/config.py'),'exec'), namespace)


class Settings(SimpleNamespace):
    def is_property_set(self, name):
        return name in self.authored


def export(native_volume=-1, native_authored=False, cycles_volume=None):
    path = Settings(depth_total=12,depth_diffuse=4,depth_glossy=4,
                    depth_specular=12,depth_volume=native_volume,
                    authored={'depth_volume'} if native_authored else set())
    cycles = Settings(volume_bounces=cycles_volume or 0,
                      authored={'volume_bounces'} if cycles_volume is not None else set())
    config = SimpleNamespace(path=path)
    scene = SimpleNamespace(superluxcore=SimpleNamespace(config=config),cycles=cycles)
    definitions = {}
    namespace['_convert_path'](config, definitions, False, 'CPU', False, scene)
    return definitions


cases = [({},None),
         ({'native_authored':True},0),
         ({'native_volume':0,'native_authored':True},1),
         ({'native_volume':12,'native_authored':True},13),
         ({'cycles_volume':0},1),
         ({'cycles_volume':8},9),
         ({'native_authored':True,'cycles_volume':8},0),
         ({'native_volume':3,'native_authored':True,'cycles_volume':8},4)]
for args, expected in cases:
    got = export(**args)
    assert got.get('path.pathdepth.volume') == expected, (args,got,expected)
    assert got['path.pathdepth.total'] == 13 and got['path.pathdepth.diffuse'] == 5
print(f'PASS: {len(cases)} default and explicit path-depth contracts')
