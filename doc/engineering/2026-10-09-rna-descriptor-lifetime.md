# RNA descriptor lifetime during render-engine changes

The legacy settings bridge retained `PropertyRNA` wrappers in a module-level
class cache. A Blender 5.2.1 Cycles → SuperLuxCore render transition reproduced
invalid enum warnings and a native crash in `RNA_property_enum_get`, reached
from `LuxCoreLegacyBridge.__getattribute__` while reading the evaluated camera
image pipeline. Python exception handling cannot catch that invalid pointer.

Look up the current RNA definition for each bridged attribute access rather
than keeping a descriptor across render transitions. Legacy storage precedence
and read-only conversion are unchanged.

Validation: the real upstream `HALL_BENCH.blend` bridge regression passed all
checks using the isolated 2.11.17 native runtime. The 2.11.18 normal-vector
fixture then completed ten conditions on both CPU and Metal, switching engines
for each 1280×720 Normal-pass render. This establishes the tested transition;
it is not a proof that every Blender RNA owner has the same lifetime.

The crash trace was at `properties/legacy.py:187`, `engine/final.py:30`, then
Blender `RNA_property_enum_get`. The bridge regression log is preserved at
`../../../test-scenes/validation-2026-10-09/rna-descriptor-lifetime/legacy-v17.log`.
