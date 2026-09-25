"""Miscellaneous utilities.

The advantage of placing objects here rather than in __init__.py is that these
objects will be available to utils submodules, even if utils is not fully
built, which avoids "ImportError: cannot import name 'xxx' from partially
initialised module "bl_ext.blc_dbg.superluxcore.utils".
"""

def get_name_with_lib(datablock):
    """
    Format the name for display similar to Blender,
    with an "L" as prefix if from a library
    """
    text = datablock.name
    if datablock.library:
        # text += ' (Lib: "%s")' % datablock.library.name
        text = "L " + text
    return text


def pluralize(format_str, amount):
    formatted = format_str % amount
    if amount != 1:
        formatted += "s"
    return formatted


# Light/world settings shared by the Cycles and the native conversion
# path (or purely organizational). Setting them alone must not switch a
# datablock to the native interpretation.
_SHARED_LIGHT_WORLD_PROPS = {
    "use_cycles_settings", "importance", "link_groups", "lightgroup",
    "rna_type", "name",
}


def resolve_use_cycles_settings(sl_props):
    """Effective "Use Cycles Settings" for a light/world prop group.

    An explicitly stored flag is honored as-is. If it was never set -
    e.g. a Cycles-authored .blend where the whole property group is at
    defaults - the datablock gets Cycles semantics, unless native-only
    SuperLuxCore settings were authored on it (old files saved while
    the native path was the default).
    """
    if sl_props.is_property_set("use_cycles_settings"):
        return sl_props.use_cycles_settings
    return not any(
        sl_props.is_property_set(p.identifier)
        for p in sl_props.bl_rna.properties
        if p.identifier not in _SHARED_LIGHT_WORLD_PROPS
    )


