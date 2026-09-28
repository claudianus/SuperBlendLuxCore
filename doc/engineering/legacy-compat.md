# Legacy upstream file compatibility

> Engineering note for SuperBlendLuxCore — extracted from AGENTS.md.
> Feature/user-facing docs live in `doc/features/` (SuperLuxCore) or `doc/` (SuperBlendLuxCore).

## Legacy upstream file compatibility (verified 2026-09)

- Upstream BlendLuxCore files store every prop group under the
  `"luxcore"` ID key (`world["luxcore"]["gain"]`, `mat["luxcore"]
  ["node_tree"]`, `scene["luxcore"]["config"]`) and node types under
  `LuxCore*`/`luxcore_*` names. Registered PointerProperty group
  members NEVER surface in `id["<prop>"]` — RNA groups live in their
  own storage; `id["..."]` only contains unregistered/ID-property data.
  An RNA `luxcore` alias prop therefore reads defaults, NOT the file's
  stored dict — `properties/legacy.py` reads the raw
  `IDPropertyGroup` instead (enums come back as ints, converted via
  `prop.enum_items` value matching; resolved pointers like
  `["node_tree"]` arrive as real datablocks, dangling ones as empty
  groups → None).
- `LuxCoreLegacyBridge.__getattribute__` on each root group resolves
  prop reads: authored `superluxcore` value (is_property_set, pointers
  need non-empty group via _group_has_authored_leaf) > stored
  `luxcore` value > RNA default. Reads never write.
- `utils.misc.use_cycles_compat` / `material_use_cycles_nodes` decide
  light/world/material interpretation: explicit `use_cycles_settings`
  flag (RNA-set pin/toggle, or a `use_cycles_settings` member persisted
  by old files as unregistered ID-prop storage) > authored `luxcore`/
  `superluxcore` data -> native > untouched datablocks -> the file
  context (see cycles-compat.md).
- Load handlers must not write to datablocks: `compatibility.run()`
  (node/socket rewriting) no longer runs on load — it stays available
  through `SUPERLUXCORE_OT_convert_to_v23`. Cache paths
  (photongi/envlight/dlsc) and `filesaver_path` resolve lazily at
  export; LOL UI resets go through `_setif_changed`.
- Node aliases: `nodes/__init__.py` registers one flattened sibling
  class per SuperLuxCore node/socket/tree class under the upstream
  bl_idname; `utils.node` maps both name families (`legacy_idname`,
  `TREE_TYPE_CANONICAL`, TREE_TYPES includes both).
- Alias visibility (2026-10): registered NodeTree types appear in the
  node editor's tree-type dropdown, so the 3 legacy tree aliases used
  to show as 3 indistinguishable duplicates. Aliases now get
  `poll(cls, context)` = "file contains a node group of this legacy
  type" — hidden in normal files, present (labeled "(Legacy)") when a
  file actually has legacy trees. Alias nodes get
  `poll = ntree.bl_idname in legacy tree types` so the Add menu/search
  stays deduplicated too. Verified: `rna_SpaceNodeEditor_tree_type_itemf`
  only applies `type->poll` when a real bContext exists — the static
  `enum_items` accessor and `tree_type` assignment bypass it.
- Mixed trees: `utils.node.get_active_output/get_output_nodes` accept
  BOTH spellings of the output type (canonical output inside a legacy
  `luxcore_*_nodes` tree). NodeCategory polls compare via
  `TREE_TYPE_CANONICAL` so Shift+A works inside legacy trees;
  `SUPERLUXCORE_MT_node_tree.custom_draw` lists legacy trees under
  their canonical type.
- Regression: `dev-tools/e46_legacy_bridge_test.py` (HALL_BENCH),
  `dev-tools/e45_cycles_light_defaults_test.py` (Cycles fallback),
  `dev-tools/e48_datablock_mode_resolution_test.py` (alias polls,
  mixed-tree outputs).

## Legacy alias registration — do NOT subclass (Blender 5.2, fixed 2026-09)

`nodes.new("<any SuperLuxCore node>")` failed for EVERY addon node
("Cannot add node of type ...", Add menu empty — interactive AND
background). Root cause was the legacy-alias machinery: each alias was
created as `type(legacy, (cls,), ...)` — a SUBCLASS of the real node
class registered under a different bl_idname. In Blender 5.2 that
orphans the base class's RNA python binding (`pyrna_find_class` returns
NULL for 'SuperLuxCoreNodeMatMirror' even though the class exists in
bpy.types) so node-type resolution dies before `poll` is ever called.
Registering the alias against plain `bpy.types.Node` instead leaves the
parent fully working — bisected 1:1 (alias on mirror breaks ONLY
mirror).

Fix (nodes/__init__.py `_register_legacy_idname_aliases`):
- Aliases are flattened siblings, not subclasses: registered bpy bases
  (e.g. SuperLuxCoreNodeMaterial) are inlined — their own attrs copied
  into the alias dict, their bases spliced in — so the alias keeps full
  behavior (props/methods/prefix) without touching the parent's RNA.
- `walk()` needs a `seen` set: `(Mixin, bpy.types.Node)` diamond bases
  made every class yield twice → each alias registered twice
  ("registered before" spam).
- `_rebind_super_cells`: zero-arg `super()` captures the DEFINING class
  in a `__class__` closure cell — copied methods raised TypeError on
  alias instances. The cell is retargeted to the alias before
  register_class so super() resolves down the alias's own base chain
  (which mirrors the canonical tail MRO).
- `bpy.types.LuxCoreX`/`dir(bpy.types)` is NOT a reliable probe — addon
  node RNA structs don't show up there even when fully functional; test
  via `nodes.new`/`node_groups.new` only.

Regression: `dev-tools/e47_legacy_node_alias_test.py` (canonical
creation under aliases, legacy alias exports identical props, no double
registration).

