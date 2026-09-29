import bpy
from bpy.props import IntProperty, BoolProperty, FloatProperty

USE_SAMPLES_DESC = (
    "The rendering will stop when the number of samples reaches "
    "the specified value"
)

SAMPLES_DESC = (
    "At least this many samples will be rendered before stopping"
)

USE_LIGHT_PATH_SAMPLES_DESC = (
    "The rendering will stop when the number of light path samples reaches "
    "the specified value"
)

LIGHT_PATH_SAMPLES_DESC = (
    "At least this many light path samples will be rendered before stopping"
)

USE_NOISE_THRESH_DESC = (
    "The rendering will stop when the noise in the image falls "
    "below the specified threshold"
)

NOISE_THRESH_DESC = (
    "Value between 0 and 255. If the noise falls below this value, the rendering is stopped. "
    "Smaller values mean less noise. "
    "It may be hard to reach a smaller noise value than 3"
)
NOISE_THRESH_WARMUP_DESC = (
    "How many samples to render before doing the first convergence test. "
    "Note that the first actual noise check only happens at the second test, after (warmup + step) samples"
)
NOISE_THRESH_STEP_DESC = (
    "How many samples to render between convergence tests. Use smaller values if "
    "your scene renders very slowly, and higher values if it renders very fast"
)

USE_NOISE_LEVEL_DESC = (
    "Stop when the statistical noise level of the image falls below the "
    "target (relative pixel error, Corona-style). Uses film variance data, "
    "works identically on CPU and GPU"
)

NOISE_LEVEL_DESC = (
    "Noise level in percent of the average pixel value. Lower values mean "
    "less noise. Typical production target: 2-5%"
)


# Attached to view layer and scene
class SuperLuxCoreHaltConditions(bpy.types.PropertyGroup):
    # On by default: a final render should finish by itself
    # (Corona-style fire-and-forget) instead of running until Esc.
    enable: BoolProperty(name="Enable", default=True)

    use_time: BoolProperty(name="Use Time", default=False)
    time: IntProperty(name="Time (s)", default=600, min=1)

    use_samples: BoolProperty(name="Use Samples", default=True,
                               description=USE_SAMPLES_DESC)
    # Backstop only - the noise-level stop (3%) normally fires far
    # earlier; this just guarantees termination on scenes that can not
    # reach the target.
    samples: IntProperty(name="Samples", default=2048, min=2, soft_max=16384,
                          description=SAMPLES_DESC)

    use_light_samples: BoolProperty(name="Use Light Path Samples", default=False,
                                     description=USE_LIGHT_PATH_SAMPLES_DESC)
    light_samples: IntProperty(name="Light Path Samples", default=100, min=1,
                                description=LIGHT_PATH_SAMPLES_DESC)

    # Noise threshold
    use_noise_thresh: BoolProperty(name="Use Noise Threshold", default=False,
                                    description=USE_NOISE_THRESH_DESC)
    noise_thresh: IntProperty(name="Noise Threshold", default=5, min=0, soft_min=3, max=255,
                               description=NOISE_THRESH_DESC)
    noise_thresh_warmup: IntProperty(name="Warmup Samples", default=64, min=1,
                                      description=NOISE_THRESH_WARMUP_DESC)
    noise_thresh_step: IntProperty(name="Test Step Samples", default=64, min=1, soft_min=16,
                                    description=NOISE_THRESH_STEP_DESC)

    # Statistical noise level target (adaptive error, E5)
    use_noise_level: BoolProperty(name="Use Noise Level", default=True,
                                   description=USE_NOISE_LEVEL_DESC)
    noise_level: FloatProperty(name="Noise Level (%)", default=3.0,
                                min=0.05, soft_min=1.0, soft_max=25.0, max=100.0,
                                description=NOISE_LEVEL_DESC)
    noise_level_warmup: IntProperty(name="Warmup Samples", default=8, min=1,
                                     description=NOISE_THRESH_WARMUP_DESC)
    noise_level_step: IntProperty(name="Test Step Samples", default=16, min=1, soft_min=4,
                                   description=NOISE_THRESH_STEP_DESC)

    def is_enabled(self):
        return self.enable and (self.use_time or self.use_samples
                or self.use_noise_thresh or self.use_noise_level)


class SuperLuxCoreViewLayerHaltConditions(SuperLuxCoreHaltConditions):
    # Per-view-layer override: opt-in only. When this shared the scene
    # class's enable=True default, every view layer silently overrode
    # the global stop conditions with stock values (e.g. a global
    # 25 s time limit never reached the engine because the layer's
    # use_time=False won). Off by default = layers inherit the scene.
    enable: BoolProperty(name="Enable", default=False)
