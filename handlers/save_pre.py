import bpy
from bpy.app.handlers import persistent
from ..utils import misc


@persistent
def handler(_):
    """Freeze each light/world's current interpretation into the file.

    Untouched datablocks resolve via the file context (LuxCore-authored
    -> native, foreign -> Cycles). Pinning the resolved value into
    use_cycles_settings at save time makes reopening the file reproduce
    the same mode regardless of the file's engine history. Datablocks
    that already carry the flag (runtime pin or manual toggle) are left
    alone."""
    for coll in (bpy.data.lights, bpy.data.worlds):
        for datablock in coll:
            if datablock.library is not None:
                continue
            try:
                props = datablock.superluxcore
                if not props.is_property_set("use_cycles_settings"):
                    props.use_cycles_settings = misc.use_cycles_compat(props)
            except (AttributeError, TypeError):
                pass
