"""
Recording proxy for pysuperluxcore.Scene used by the async session worker.

The viewport update path (Exporter._update_scene) runs on Blender's main
thread because it needs the depsgraph, but the real pysuperluxcore scene is
owned by the session worker thread, which performs
BeginSceneEdit/EndSceneEdit and session restarts. Calling into the real
scene from the main thread would race the worker (and a long call there
would freeze the UI).

RecordedScene records every mutation as ``(name, args, kwargs)`` tuples.
The worker replays them on the real scene inside a single scene-edit
block (SessionWorker). Definition queries the export code performs
mid-update (IsMeshDefined and friends) are answered from a shadow state
updated while recording.

The shadow state is deliberately conservative: a name the proxy has not
seen defined reports False. A false negative only makes the caller
define the resource again — SuperLuxCore re-defines an existing mesh,
material, texture or image map in place — while a false positive would
skip a needed definition and corrupt the scene, so the proxy never
claims a name it did not record.

This module must not import bpy: it is exercised by worker-adjacent unit
tests without a Blender runtime.
"""


# Scene methods that mutate state and are replayed on the real scene.
_MUTATORS = (
    "Parse",
    "DefineImageMap",
    "DefineMesh",
    "DefineMeshExt",
    "DefineStrands",
    "DefineBlenderStrands",
    "DefineBlenderCurveStrands",
    "SetMeshVertexAOV",
    "SetMeshTriangleAOV",
    "SetMeshVertexMotion",
    "SetStrandsVertexMotion",
    "SetMeshAppliedTransformation",
    "DuplicateObject",
    "DeleteObjects",
    "DeleteLights",
    "UpdateObjectTransformation",
    "UpdateObjectMaterial",
    "DeleteObject",
    "DeleteLight",
    "RemoveUnusedImageMaps",
    "RemoveUnusedTextures",
    "RemoveUnusedMaterials",
    "RemoveUnusedMeshes",
    "Save",
    "SaveMesh",
)

# Mutators whose first argument is a defined mesh/shape name.
_MESH_DEFINERS = (
    "DefineMesh",
    "DefineMeshExt",
    "DefineStrands",
    "DefineBlenderStrands",
    "DefineBlenderCurveStrands",
)

# Mutators that return a boolean success value to the caller.
_BOOL_RETURNS = (
    "DefineMesh",
    "DefineMeshExt",
    "DefineStrands",
    "DefineBlenderStrands",
    "DefineBlenderCurveStrands",
)


def _first_arg(args, kwargs, name="name"):
    """First positional arg, or the ``name`` kwarg (DefineMeshExt style)."""
    if args:
        return args[0]
    return kwargs.get(name)


class RecordedScene:
    def __init__(self):
        self._ops = []
        # Shadow sets of names that are *known* to be defined. See the
        # module docstring: under-approximation is safe, over- is not.
        self._meshes = set()
        self._objects = set()
        self._lights = set()
        self._materials = set()
        self._textures = set()
        self._imagemaps = set()

    # ------------------------------------------------------------------
    # Recording + shadow bookkeeping
    # ------------------------------------------------------------------

    def _record(self, name, args, kwargs):
        self._ops.append((name, args, kwargs))
        self._track(name, args, kwargs)
        return True if name in _BOOL_RETURNS else None

    def _track(self, name, args, kwargs):
        if name == "Parse":
            self._track_props(args[0])
        elif name in _MESH_DEFINERS:
            mesh = _first_arg(args, kwargs)
            if mesh is not None:
                self._meshes.add(mesh)
        elif name == "DefineImageMap":
            self._imagemaps.add(_first_arg(args, kwargs))
        elif name == "DuplicateObject":
            # (srcName, dstName, ...) — the destination is a new object
            self._objects.add(args[1])
        elif name == "DeleteObject":
            # The mesh stays alive (it may be shared); only the object goes.
            self._objects.discard(args[0])
        elif name == "DeleteObjects":
            self._objects -= set(args[0])
        elif name == "DeleteLight":
            self._lights.discard(args[0])
        elif name == "DeleteLights":
            self._lights -= set(args[0])
        elif name == "RemoveUnusedMeshes":
            # Survivors depend on live reference counts; conservatively
            # forget everything (callers re-define, which is safe).
            self._meshes.clear()
        elif name == "RemoveUnusedMaterials":
            self._materials.clear()
        elif name == "RemoveUnusedTextures":
            self._textures.clear()
        elif name == "RemoveUnusedImageMaps":
            self._imagemaps.clear()

    def _track_props(self, props):
        """Extract the names a ``Scene.Parse`` call would define."""
        self._objects |= set(props.GetAllUniqueSubNames("scene.objects"))
        self._lights |= set(props.GetAllUniqueSubNames("scene.lights"))
        self._materials |= set(
            props.GetAllUniqueSubNames("scene.materials")
        )
        self._textures |= set(props.GetAllUniqueSubNames("scene.textures"))
        self._meshes |= set(props.GetAllUniqueSubNames("scene.shapes"))
        # Implicit meshes created by object definitions.
        for obj_name in props.GetAllUniqueSubNames("scene.objects"):
            prefix = "scene.objects." + obj_name + "."
            if props.IsDefined(prefix + "ply"):
                self._meshes.add(props.Get(prefix + "ply").GetString())
            elif props.IsDefined(prefix + "vertices"):
                self._meshes.add("InlinedMesh-" + obj_name)

    # ------------------------------------------------------------------
    # Worker interface
    # ------------------------------------------------------------------

    def drain(self):
        """Return the recorded op list and clear it for the next batch."""
        ops, self._ops = self._ops, []
        return ops

    @staticmethod
    def replay(scene, ops):
        """Apply recorded ops on the real scene (worker thread, inside
        BeginSceneEdit/EndSceneEdit)."""
        for name, args, kwargs in ops:
            getattr(scene, name)(*args, **kwargs)

    # ------------------------------------------------------------------
    # Recorded mutators (installed below)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Shadowed queries
    # ------------------------------------------------------------------

    def IsMeshDefined(self, name):
        return name in self._meshes

    def IsTextureDefined(self, name):
        return name in self._textures

    def IsMaterialDefined(self, name):
        return name in self._materials

    def IsImageMapDefined(self, name):
        return name in self._imagemaps

    def GetLightCount(self):
        return len(self._lights)

    def GetObjectCount(self):
        return len(self._objects)


def _make_mutator(name):
    def method(self, *args, **kwargs):
        return self._record(name, args, kwargs)

    method.__name__ = name
    return method


for _name in _MUTATORS:
    setattr(RecordedScene, _name, _make_mutator(_name))


class _TemporaryFileOwner:
    """Pure file ownership; cleanup can outlive Blender's image wrappers."""
    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.readers = {}
        self.pending = set()

    def pin(self, paths):
        paths = tuple(set(paths))
        with self.lock:
            for path in paths:
                self.readers[path] = self.readers.get(path, 0) + 1
        return _FileLease(self, paths)

    def remove(self, path):
        with self.lock:
            self.pending.add(path)
            self._remove_if_unused(path)

    def _remove_if_unused(self, path):
        if path in self.pending and not self.readers.get(path):
            import os
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            self.pending.discard(path)

    def release(self, paths):
        with self.lock:
            for path in paths:
                count = self.readers.get(path, 0)
                if count <= 1:
                    self.readers.pop(path, None)
                else:
                    self.readers[path] = count - 1
                try:
                    self._remove_if_unused(path)
                except OSError:
                    # Keep the owned path pending for a subsequent cleanup.
                    # A cleanup failure must not resurrect a retired scene.
                    import traceback
                    traceback.print_exc()


class _FileLease:
    def __init__(self, owner, paths):
        self.owner, self.paths = owner, paths

    def close(self):
        paths, self.paths = self.paths, ()
        if paths:
            self.owner.release(paths)

    def __del__(self):
        self.close()


# Preserve leases across addon source reloads while an old worker retires.
if "temporary_image_files" not in globals():
    temporary_image_files = _TemporaryFileOwner()


class DeferredScene(RecordedScene):
    """Owned initial scene commands, materialized by the session worker.

    Only data snapshots enter this queue. A caller needing a native return
    value (hair tessellation, saves, unknown methods/types) falls back to the
    synchronous path in exact command order. Final renders do not use this
    class. File pins remain with the worker-owned scene across config edits.
    """
    _IMMEDIATE = frozenset(("DefineStrands", "DefineBlenderStrands",
                            "DefineBlenderCurveStrands", "Save", "SaveMesh"))

    def __init__(self, factory, properties_type, image_policy):
        super().__init__()
        self._factory = factory
        self._properties_type = properties_type
        self._native = None
        self._files = None
        self._closed = False
        self.synchronous_reason = None
        self._image_policy = self._snapshot(image_policy)

    def _snapshot(self, value):
        from array import array
        if isinstance(value, self._properties_type):
            result = self._properties_type()
            result.Set(value)
            return result
        if value is None or isinstance(value, (str, bytes, int, float, bool)):
            return value
        if isinstance(value, array):
            return array(value.typecode, value)
        if isinstance(value, (list, tuple)):
            return type(value)(self._snapshot(item) for item in value)
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise TypeError("Scene command dictionary keys must be strings")
            return {key: self._snapshot(item) for key, item in value.items()}
        if type(value).__module__.split('.')[0] == 'numpy':
            if value.dtype.hasobject:
                raise TypeError("Scene command object arrays are not transferable")
            return value.copy(order='C') if value.ndim else value.item()
        raise TypeError("Scene command needs synchronous input: " + type(value).__name__)

    def _record(self, name, args, kwargs):
        if self._closed:
            raise RuntimeError("Initial scene commands have been retired")
        if self._native is not None:
            return getattr(self._native, name)(*args, **kwargs)
        if name not in self._IMMEDIATE:
            try:
                owned_args, owned_kwargs = self._snapshot(args), self._snapshot(kwargs)
            except TypeError:
                pass
            else:
                return super()._record(name, owned_args, owned_kwargs)
        self.synchronous_reason = name
        return getattr(self._build_pending_scene(), name)(*args, **kwargs)

    def _track_props(self, props):
        # Native Properties returns fully qualified prefixes; Python test
        # doubles may return leaves. Public Scene queries take leaf names.
        def names(prefix):
            start = prefix + "."
            return [name[len(start):] if name.startswith(start) else name
                    for name in props.GetAllUniqueSubNames(prefix)]
        for prefix, values in (("scene.objects", self._objects),
                               ("scene.lights", self._lights),
                               ("scene.materials", self._materials),
                               ("scene.textures", self._textures),
                               ("scene.shapes", self._meshes)):
            values.update(names(prefix))
        for name in names("scene.objects"):
            prefix = "scene.objects." + name + "."
            if props.IsDefined(prefix + "ply"):
                self._meshes.add(props.Get(prefix + "ply").GetString())
            elif props.IsDefined(prefix + "vertices"):
                self._meshes.add("InlinedMesh-" + name)

    def pin_files(self, paths):
        if self._files is not None:
            raise RuntimeError("Initial scene files already pinned")
        self._files = temporary_image_files.pin(paths)

    def _build_pending_scene(self, cancelled=None):
        if self._closed:
            return None
        cancelled = cancelled or (lambda: False)
        ops, self._ops = self._ops, []
        try:
            if cancelled():
                self.close()
                return None
            if self._native is None:
                self._native = self._factory(self._properties_type(), self._image_policy)
            for index, op in enumerate(ops):
                if cancelled():
                    self.close()
                    return None
                name, args, kwargs = op
                getattr(self._native, name)(*args, **kwargs)
                # Release snapshots as soon as native code has consumed them.
                ops[index] = None
            if cancelled():
                self.close()
                return None
            return self._native
        except BaseException:
            self.close()
            raise
        finally:
            ops.clear()
            op = args = kwargs = None

    def GetLightCount(self):
        # Triangle emitters are only known after native Parse. None means
        # pending, never an invented count of just explicitly named lights.
        return self._native.GetLightCount() if self._native is not None else None

    def IsMeshDefined(self, name):
        return (self._native.IsMeshDefined(name) if self._native is not None
                else super().IsMeshDefined(name))

    def IsTextureDefined(self, name):
        return (self._native.IsTextureDefined(name) if self._native is not None
                else super().IsTextureDefined(name))

    def IsMaterialDefined(self, name):
        return (self._native.IsMaterialDefined(name) if self._native is not None
                else super().IsMaterialDefined(name))

    def IsImageMapDefined(self, name):
        return (self._native.IsImageMapDefined(name) if self._native is not None
                else super().IsImageMapDefined(name))

    def GetObjectCount(self):
        return (self._native.GetObjectCount() if self._native is not None
                else super().GetObjectCount())

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        self.synchronous_reason = name
        return getattr(self._build_pending_scene(), name)

    def close(self):
        self._closed = True
        self._ops.clear()
        self._native = None
        lease, self._files = self._files, None
        if lease is not None:
            lease.close()

    def __del__(self):
        self.close()
