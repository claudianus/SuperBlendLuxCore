"""Miscellaneous utilities.

The advantage of placing objects here rather than in __init__.py is that these
objects will be available to utils submodules, even if utils is not fully
built, which avoids "ImportError: cannot import name 'xxx' from partially
initialised module "bl_ext.blc_dbg.superluxcore.utils".
"""

import bpy

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


# Light/world settings shared by the Cycles-compatible and the native
# conversion path (or purely organizational). Setting them alone does
# not mark a datablock as LuxCore-authored.
_SHARED_LIGHT_WORLD_PROPS = {
    "use_cycles_settings", "importance", "link_groups", "lightgroup",
    "rna_type", "name",
}


def _has_authored_light_world_settings(sl_props, key):
    """True when LuxCore-native settings were authored under `key`
    ("superluxcore" or "luxcore") on the owning datablock.

    The two storages behave differently:
    - "luxcore" (upstream files): unregistered legacy data loaded as a
      plain ID-property dict, so membership in `id["luxcore"]` is the
      authored signal.
    - "superluxcore" (registered RNA): group members never appear in
      `id["superluxcore"]`, so is_property_set() is the authored signal.
      Pointer props only count when they hold real content, not when
      they were merely materialized by an access."""
    try:
        prop_defs = {p.identifier: p for p in sl_props.bl_rna.properties}
    except Exception:
        prop_defs = {}
    if key == "luxcore":
        try:
            stored = sl_props.id_data.get(key)
        except Exception:
            return False
        if not stored:
            return False
        for name in stored.keys():
            if name in _SHARED_LIGHT_WORLD_PROPS:
                continue
            prop = prop_defs.get(name)
            if prop is None:
                continue
            member = stored[name]
            if prop.type == "POINTER":
                if member is None:
                    continue
                # Unresolved pointers and empty prop-group storage
                # aren't authored content.
                if member.__class__.__name__ == "IDPropertyGroup" \
                        and not len(member):
                    continue
            elif prop.type == "COLLECTION":
                if not len(member):
                    continue
            return True
        return False

    for name, prop in prop_defs.items():
        if name in _SHARED_LIGHT_WORLD_PROPS:
            continue
        try:
            if not sl_props.is_property_set(name):
                continue
            if prop.type == "POINTER":
                value = getattr(sl_props, name)
                if value is None:
                    continue
                # An empty prop-group (materialized by access, never
                # assigned) is not authored content.
                if isinstance(value, bpy.types.PropertyGroup) \
                        and not _group_has_authored_leaf(value):
                    continue
            return True
        except Exception:
            continue
    return False


def _group_has_authored_leaf(group):
    """True when any leaf prop of a nested RNA group was assigned.
    Nested group pointers recurse; empty groups count as un-authored."""
    try:
        props = group.bl_rna.properties
    except Exception:
        return True  # non-group payload: treat as content
    for prop in props:
        name = prop.identifier
        if name in ("rna_type", "name"):
            continue
        try:
            if prop.type == "POINTER":
                value = getattr(group, name)
                if value is not None and isinstance(
                        value, bpy.types.PropertyGroup) \
                        and _group_has_authored_leaf(value):
                    return True
            elif prop.type == "COLLECTION":
                if len(getattr(group, name)):
                    return True
            elif group.is_property_set(name):
                return True
        except Exception:
            continue
    return False


# Whether the file currently loaded in this session was authored under
# SuperLuxCore (i.e. contains at least one SUPERLUXCORE scene). Datablocks
# that came with such a file and carry no authored settings resolve to
# the native path; datablocks of a foreign-authored file fall back to
# Cycles. Recomputed at register() and on load_post/factory-startup.
_file_authored_luxcore = False

# session_uids of lights/worlds that already existed (loaded or seeded
# at registration). Newly appearing uids are runtime-created datablocks
# and get their interpretation pinned by the authoring engine.
_known_light_world_uids = set()

# False until the file context was successfully established (register()
# runs in a restricted context without bpy.data; the first depsgraph
# tick or load_post then performs the real refresh).
_context_initialized = False


def refresh_file_context():
    """Recompute the file-level context and snapshot existing
    lights/worlds so datablocks that came with the file are never
    mistaken for runtime-created ones. No-op in restricted contexts
    (bpy.data unavailable during addon registration) - the next
    load_post or the first depsgraph tag then establishes context."""
    global _file_authored_luxcore, _context_initialized
    try:
        scenes = bpy.data.scenes
    except AttributeError:
        return
    _file_authored_luxcore = any(
        scene.render.engine == "SUPERLUXCORE" for scene in scenes
    )
    _known_light_world_uids.clear()
    for coll in (bpy.data.lights, bpy.data.worlds):
        _known_light_world_uids.update(d.session_uid for d in coll)
    _context_initialized = True


def tag_new_light_world(engine):
    """Pin the interpretation of newly created lights/worlds to the
    engine that authored them (called from depsgraph_update_post).

    The stored use_cycles_settings flag survives save/load, so a
    datablock created under a foreign engine keeps the Cycles
    interpretation even if the file later becomes LuxCore-authored
    (and vice versa). Idempotent: each datablock is tagged once."""
    if not _context_initialized:
        # Addon enabled while a file was open: establish the context
        # first so pre-existing datablocks are treated as load-era.
        refresh_file_context()
        if not _context_initialized:
            return
    cycles = engine != "SUPERLUXCORE"
    for coll in (bpy.data.lights, bpy.data.worlds):
        for d in coll:
            uid = d.session_uid
            if uid in _known_light_world_uids:
                continue
            _known_light_world_uids.add(uid)
            if d.library is not None:
                continue
            try:
                # Never overwrite an explicit write that happened
                # between creation and this tick.
                if not d.superluxcore.is_property_set(
                        "use_cycles_settings"):
                    d.superluxcore.use_cycles_settings = cycles
            except (AttributeError, TypeError):
                pass


def use_cycles_compat(sl_props):
    """True: the light/world datablock resolves to the Cycles-compatible
    translation layer (Blender energy/color/shape are converted
    faithfully).

    False: the datablock drives the native conversion. Resolution order:

    1. An explicitly stored use_cycles_settings flag wins - either
       written to the registered RNA group (current files, and the
       pin set by tag_new_light_world) or found in the raw ID storage
       (older files where the member was never unregistered).
    2. Any authored LuxCore settings - under "luxcore" (upstream files)
       or "superluxcore" - force the native path.
    3. Untouched datablocks follow the file context: datablocks loaded
       with a LuxCore-authored file stay native, foreign-authored
       datablocks use the Cycles fallback.
    """
    try:
        owner = sl_props.id_data
    except AttributeError:
        owner = None

    try:
        if sl_props.is_property_set("use_cycles_settings"):
            return bool(sl_props.use_cycles_settings)
    except Exception:
        pass

    for key in ("superluxcore", "luxcore"):
        try:
            stored = owner.get(key) if owner is not None else None
        except Exception:
            stored = None
        if stored is not None and "use_cycles_settings" in stored:
            return bool(stored["use_cycles_settings"])

    if _has_authored_light_world_settings(sl_props, "luxcore"):
        return False
    if _has_authored_light_world_settings(sl_props, "superluxcore"):
        return False
    return not _file_authored_luxcore


def material_use_cycles_nodes(mat):
    """True when the material exports through the Cycles translation
    layer.

    A LuxCore node tree always takes precedence (the bridge in
    properties/legacy.py resolves 'luxcore' storage transparently).
    A Blender tree is only the fallback for materials that carry no
    LuxCore tree. The one exception: older files that stored
    'use_cycles_nodes' alongside a LuxCore tree keep that explicit
    choice. A stored False is ignored - it was the old default and
    must not disable the automatic fallback."""
    if mat.superluxcore.node_tree is None:
        return getattr(mat, "node_tree", None) is not None
    for key in ("superluxcore", "luxcore"):
        stored = mat.get(key)
        if stored is not None and "use_cycles_nodes" in stored \
                and stored["use_cycles_nodes"]:
            return True
    return False


