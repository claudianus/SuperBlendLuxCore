import bpy


class SUPERLUXCORE_OT_import_cycles_settings(bpy.types.Operator):
    """Copy a scene's Cycles render settings into SuperLuxCore.

    Reads scene.cycles.* (sample count, bounce depths, denoise flag) and
    writes the matching SuperLuxCore halt/path properties. Run after
    switching render engines; idempotent. View-layer overrides win.
    """
    bl_idname = "superluxcore.import_cycles_settings"
    bl_label = "Import Cycles Settings"
    bl_description = ("Copy Cycles render settings (samples, bounce "
                      "depths, denoise flag) into SuperLuxCore")
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, "cycles")

    def execute(self, context):
        scene = context.scene
        cyc = scene.cycles
        slc = scene.superluxcore

        changed = []

        # --- samples -> halt budget ------------------------------------
        # Cycles' "samples" is a hard cap; SuperLuxCore's halt.samples
        # is the same guarantee. The 3% noise-level stop stays on so an
        # easy scene still terminates earlier than the Cycles budget.
        try:
            samples = int(cyc.samples)
        except Exception:
            samples = 0
        if samples > 0:
            slc.halt.enable = True
            slc.halt.use_samples = True
            slc.halt.samples = samples
            changed.append(f"samples={samples}")

        # --- bounce depths -> path.pathdepth.* -------------------------
        # Cycles separates the count by lobe type; SuperLuxCore does the
        # same (total / diffuse / glossy / specular).
        depth_map = [
            ("max_bounces",     "depth_total",    None),
            ("diffuse_bounces", "depth_diffuse",  None),
            ("glossy_bounces",  "depth_glossy",   None),
            ("transparent_bounces", "depth_specular", None),
            ("transmission_bounces", "depth_specular", "min"),
        ]
        for cyc_name, slc_name, op in depth_map:
            try:
                v = int(getattr(cyc, cyc_name))
            except Exception:
                continue
            if v <= 0:
                continue
            cur = getattr(slc.config.path, slc_name, None)
            if op == "min" and cur is not None:
                v = min(v, cur)
            setattr(slc.config.path, slc_name, max(1, v))
            changed.append(f"{slc_name}={getattr(slc.config.path, slc_name)}")

        # --- transparent film ------------------------------------------
        try:
            if bool(cyc.film_transparent):
                # Find the first imagepipeline with the flag; enable it.
                for pipeline in getattr(scene.superluxcore,
                                        "imagepipelines", []) or []:
                    if hasattr(pipeline, "transparent_film"):
                        pipeline.transparent_film = True
                        changed.append("transparent_film")
                        break
        except Exception:
            pass

        # --- denoise flag ----------------------------------------------
        try:
            use_dn = bool(cyc.use_denoising)
        except Exception:
            use_dn = None
        if use_dn is not None:
            slc.denoiser.enabled = use_dn
            changed.append(f"denoiser={use_dn}")

        # --- view layer overrides (Cycles keeps them per-layer) --------
        for vl in scene.view_layers:
            vl_cyc = getattr(vl, "cycles", None)
            vl_slc = getattr(vl, "superluxcore", None)
            if vl_cyc is None or vl_slc is None:
                continue
            try:
                s = int(vl_cyc.samples)
            except Exception:
                continue
            if s > 0:
                vl_slc.halt.enable = True
                vl_slc.halt.use_samples = True
                vl_slc.halt.samples = s

        msg = "SuperLuxCore: imported " + (", ".join(changed) if changed else "nothing")
        self.report({"INFO"}, msg)
        return {"FINISHED"}
