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
            # Cycles counts volume scattering apart from diffuse bounces
            ("volume_bounces", "depth_volume", None),
        ]
        for cyc_name, slc_name, op in depth_map:
            try:
                v = int(getattr(cyc, cyc_name))
            except Exception:
                continue
            if slc_name == "depth_volume":
                # 0 volume bounces is single scattering, not "unset"
                slc.config.path.depth_volume = max(0, v)
                changed.append(f"depth_volume={slc.config.path.depth_volume}")
                continue
            if v <= 0:
                continue
            cur = getattr(slc.config.path, slc_name, None)
            if op == "min" and cur is not None:
                v = min(v, cur)
            setattr(slc.config.path, slc_name, max(1, v))
            changed.append(f"{slc_name}={getattr(slc.config.path, slc_name)}")

        # --- transport colour model ------------------------------------
        # Cycles transports RGB. SuperLuxCore's spectral mode projects the
        # hero wavelengths through a low-noise control variate that leaves
        # a few-% hue bias on near-monochromatic emitters (a (1, .24, 0)
        # sodium lamp gains a pink cast under AgX), and the Cycles reader
        # exports no spectral-only feature (dispersion), so a converted
        # Cycles scene renders closest to Cycles in RGB.
        if getattr(slc.config, "spectral_enable", False):
            slc.config.spectral_enable = False
            changed.append("spectral=off")

        # --- bump terminator --------------------------------------------
        # Cycles softens bumped diffuse with Conty et al.'s shadowing term
        # (the Chiang term darkened 065's sand ripples ~2x under a low sun)
        if getattr(slc.config, "shadow_terminator", "CONTY") != "CONTY":
            slc.config.shadow_terminator = "CONTY"
            changed.append("shadow_terminator=conty")

        # --- clamping ---------------------------------------------------
        # Cycles clamps each sample contribution (RGB sum) against
        # sample_clamp_direct / _indirect; SuperLuxCore's own variance
        # clamp has no Cycles counterpart, so it goes off and the Cycles
        # limits map 1:1 (0 = off on both sides).
        try:
            cd = max(0.0, float(cyc.sample_clamp_direct))
            ci = max(0.0, float(cyc.sample_clamp_indirect))
        except Exception:
            cd = ci = None
        if cd is not None:
            slc.config.path.cycles_clamp_direct = cd
            slc.config.path.cycles_clamp_indirect = ci
            slc.config.path.use_clamping = False
            slc.config.path.auto_clamping = False
            changed.append(f"clamp direct={cd:g} indirect={ci:g}")

        # --- Filter Glossy ------------------------------------------------
        # The engine runs Cycles' own filter (path.filterglossy); the
        # auto-seeded path-space regularization is a different blur
        # (biased, decaying with spp) and goes off either way.
        try:
            blur_glossy = max(0.0, float(cyc.blur_glossy))
        except Exception:
            blur_glossy = None
        if blur_glossy is not None:
            slc.config.path.cycles_filter_glossy = blur_glossy
            slc.config.psr_auto = False
            slc.config.psr_sigma = 0.0
            changed.append(f"filter_glossy={blur_glossy:g}")

        # --- 픽셀 필터 ------------------------------------------------
        # Cycles의 종류별 샘플링 지지 구간을 엔진의 반지름으로 변환한다.
        # Gaussian은 폭을 3배 확장하므로 감쇠 계수는 8 / 폭²이다.
        try:
            ftype = str(cyc.pixel_filter_type)
            fwidth = float(cyc.filter_width)
        except Exception:
            ftype = None
        filter_map = {"BOX": "BOX", "GAUSSIAN": "GAUSSIAN",
                      "BLACKMAN_HARRIS": "BLACKMANHARRIS"}
        if ftype in filter_map:
            slc.config.filter_enabled = True
            slc.config.filter = filter_map[ftype]
            radius_scale = {"BOX": 0.5, "GAUSSIAN": 1.5, "BLACKMAN_HARRIS": 1.0}
            slc.config.filter_width = max(0.005, fwidth * radius_scale[ftype])
            if ftype == "GAUSSIAN":
                slc.config.gaussian_alpha = max(0.1, 8.0 / max(fwidth, 0.01) ** 2)
            changed.append(f"filter={filter_map[ftype]} {slc.config.filter_width:g}px")

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
