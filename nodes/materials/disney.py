import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty
from ..base import SuperLuxCoreNodeMaterial
from .glass import THIN_FILM_DESCRIPTION
from ...utils import node as utils_node
from ...utils.node import ThinFilmCoating, SellmeierDispersion


class SuperLuxCoreNodeMatDisney(SuperLuxCoreNodeMaterial, bpy.types.Node):
    bl_label = "Disney Material"
    bl_width_default = 190

    def update_use_thinfilmcoating(self, context):
        id = self.inputs.find("Film Amount")
        self.inputs[id].enabled = self.use_thinfilmcoating
        ThinFilmCoating.toggle(self, context)

    def update_sheen_model(self, context):
        id = self.inputs.find("Sheen Roughness")
        if id != -1:
            self.inputs[id].enabled = self.sheen_model == "charlie"
        utils_node.force_viewport_update(self, context)

    use_thinfilmcoating: BoolProperty(name="Thin Film Coating", default=False,
                                      description=THIN_FILM_DESCRIPTION,
                                      update=update_use_thinfilmcoating)
    multibounce: BoolProperty(name="Multibounce", default=False,
                              description="Compensate the energy lost by "
                                          "multiple scattering inside the "
                                          "specular micro-facet lobe "
                                          "(Turquin / Kulla-Conty)",
                              update=utils_node.force_viewport_update)
    sheen_model: EnumProperty(name="Sheen Model",
                              items=[("schlick", "Schlick (Legacy)",
                                      "Disney's Schlick sheen approximation", 0),
                                     ("charlie", "Charlie",
                                      "Estevez-Kulla '17 physical microfacet "
                                      "sheen (height-correlated)", 1)],
                              default="schlick",
                              update=update_sheen_model)
    dispersion_model: EnumProperty(name="Dispersion Model",
                                   items=SellmeierDispersion.MODEL_ITEMS,
                                   default="cauchy",
                                   update=utils_node.force_viewport_update)
    sellmeier_preset: EnumProperty(name="Glass Preset",
                                   items=SellmeierDispersion.PRESET_ITEMS,
                                   default="N-BK7",
                                   update=utils_node.force_viewport_update)
    sellmeier_b: FloatVectorProperty(name="Sellmeier B", size=3,
                                     default=(1.0, 0.5, 1.0),
                                     description="Sellmeier B1 B2 B3 coefficients",
                                     update=utils_node.force_viewport_update)
    sellmeier_c: FloatVectorProperty(name="Sellmeier C", size=3,
                                     default=(0.006, 0.02, 100.0),
                                     description="Sellmeier C1 C2 C3 coefficients (um^2)",
                                     update=utils_node.force_viewport_update)

    def init(self, context):
        self.add_input("SuperLuxCoreSocketColor", "Base Color", [0.7] * 3)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Subsurface", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Metallic", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Specular", 0.5)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Specular Tint", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Roughness", 0.2)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Anisotropic", 0)
        self.add_input("SuperLuxCoreSocketFloatDisneySheen", "Sheen", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Sheen Tint", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Sheen Roughness", 0.5, enabled=False)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Clearcoat", 0)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Clearcoat Gloss", 1)
        self.add_input("SuperLuxCoreSocketFloat0to1", "Film Amount", 1, enabled=False)
        self.add_input("SuperLuxCoreSocketCauchyC", "Dispersion", 0)
        ThinFilmCoating.init(self)
        self.add_common_inputs()

        self.outputs.new("SuperLuxCoreSocketMaterial", "Material")

    def draw_buttons(self, context, layout):
        layout.prop(self, "sheen_model")
        layout.prop(self, "multibounce")
        layout.prop(self, "use_thinfilmcoating")
        SellmeierDispersion.draw(self, layout)

    def sub_export(self, exporter, depsgraph, props, superluxcore_name=None, output_socket=None):
        definitions = {
            "type": "disney",
            "basecolor": self.inputs["Base Color"].export(exporter, depsgraph, props),
            "subsurface": self.inputs["Subsurface"].export(exporter, depsgraph, props),
            "metallic": self.inputs["Metallic"].export(exporter, depsgraph, props),
            "specular": self.inputs["Specular"].export(exporter, depsgraph, props),
            "speculartint": self.inputs["Specular Tint"].export(exporter, depsgraph, props),
            "roughness": self.inputs["Roughness"].export(exporter, depsgraph, props),
            "anisotropic": self.inputs["Anisotropic"].export(exporter, depsgraph, props),
            "sheen": self.inputs["Sheen"].export(exporter, depsgraph, props),
            "sheentint": self.inputs["Sheen Tint"].export(exporter, depsgraph, props),
            "clearcoat": self.inputs["Clearcoat"].export(exporter, depsgraph, props),
            "clearcoatgloss": self.inputs["Clearcoat Gloss"].export(exporter, depsgraph, props),
            "multibounce": self.multibounce,
        }

        # Charlie sheen is opt-in: exporting sheenroughness switches the
        # sheen lobe from Schlick to the physical microfacet model
        if self.sheen_model == "charlie":
            definitions["sheenroughness"] = \
                self.inputs["Sheen Roughness"].export(exporter, depsgraph, props)

        if not SellmeierDispersion.export(self, definitions):
            cauchyb = self.inputs["Dispersion"].export(exporter, depsgraph, props)
            if self.inputs["Dispersion"].is_linked or cauchyb > 0:
                definitions["cauchyb"] = cauchyb
        
        if self.use_thinfilmcoating:
            amount_socket = self.inputs["Film Amount"]
            amount = amount_socket.export(exporter, depsgraph, props)
            
            if amount_socket.is_linked or amount > 0:
                definitions["filmamount"] = amount
                ThinFilmCoating.export(self, exporter, depsgraph, props, definitions)

        self.export_common_inputs(exporter, depsgraph, props, definitions)
        return self.create_props(props, definitions, superluxcore_name)
