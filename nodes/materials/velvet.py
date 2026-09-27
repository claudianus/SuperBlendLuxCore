import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from ..base import SuperLuxCoreNodeMaterial
from ...utils import node as utils_node


class SuperLuxCoreNodeMatVelvet(SuperLuxCoreNodeMaterial, bpy.types.Node):
    bl_label = "Velvet Material"
    bl_width_default = 160

    def update_advanced(self, context):
        sockets = ["p1", "p2", "p3"]

        for socket in sockets:
            id = self.inputs.find(socket)
            self.inputs[id].enabled = self.advanced and self.model == "legacy"

        utils_node.force_viewport_update(self, context)

    def update_model(self, context):
        legacy = self.model == "legacy"
        for socket in ("p1", "p2", "p3"):
            id = self.inputs.find(socket)
            self.inputs[id].enabled = self.advanced and legacy
        id = self.inputs.find("Sheen Roughness")
        self.inputs[id].enabled = not legacy

        utils_node.force_viewport_update(self, context)

    advanced: BoolProperty(name="Advanced Options", description="Advanced Velvet Parameters", default=False, update=update_advanced)

    model: EnumProperty(name="Model",
                        items=[("legacy", "Velvet (Legacy)",
                                "Retro-reflective polynomial velvet model", 0),
                               ("charlie", "Charlie Sheen",
                                "Estevez-Kulla '17 physical microfacet sheen "
                                "(height-correlated)", 1)],
                        default="legacy", update=update_model)

    def init(self, context):
        self.add_input("SuperLuxCoreSocketColor", "Diffuse Color", (1, 1, 1))
        self.add_input("SuperLuxCoreSocketFloat0to1", "Thickness", 0.1)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Sheen Roughness", 0.5, enabled=False)
        self.add_input("SuperLuxCoreSocketFloatUnbounded", "p1", 2)
        self.add_input("SuperLuxCoreSocketFloatUnbounded", "p2", 10)
        self.add_input("SuperLuxCoreSocketFloatUnbounded", "p3", 2)
        self.inputs["p1"].enabled = False
        self.inputs["p2"].enabled = False
        self.inputs["p3"].enabled = False

        self.add_common_inputs()

        self.outputs.new("SuperLuxCoreSocketMaterial", "Material")

    def draw_buttons(self, context, layout):
        layout.prop(self, "model")
        if self.model == "legacy":
            layout.prop(self, "advanced", toggle=True)

    def sub_export(self, exporter, depsgraph, props, superluxcore_name=None, output_socket=None):
        definitions = {
            "type": "velvet",
            "kd": self.inputs["Diffuse Color"].export(exporter, depsgraph, props),
            "thickness": self.inputs["Thickness"].export(exporter, depsgraph, props),
        }

        if self.model == "charlie":
            definitions["model"] = "charlie"
            definitions["sheenroughness"] = \
                self.inputs["Sheen Roughness"].export(exporter, depsgraph, props)
        elif self.advanced:
            definitions.update({
                "p1": self.inputs["p1"].export(exporter, depsgraph, props),
                "p2": self.inputs["p2"].export(exporter, depsgraph, props),
                "p3": self.inputs["p3"].export(exporter, depsgraph, props),
            })

        self.export_common_inputs(exporter, depsgraph, props, definitions)
        return self.create_props(props, definitions, superluxcore_name)
