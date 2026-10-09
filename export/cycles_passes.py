"""Blender 데이터 패스를 원래 이름과 단위로 RenderResult에 전달한다."""
from typing import NamedTuple


class Pass(NamedTuple):
    flag: str
    name: str
    output: str
    channels: str
    socket: str


PASSES = (
    Pass("use_pass_z", "Depth", "DEPTH", "Z", "VALUE"),
    Pass("use_pass_normal", "Normal", "SHADING_NORMAL", "XYZ", "VECTOR"),
    Pass("use_pass_position", "Position", "POSITION", "XYZ", "VECTOR"),
    Pass("use_pass_uv", "UV", "UV", "UVA", "VECTOR"),
    Pass("use_pass_object_index", "IndexOB", "OBJECT_ID", "X", "VALUE"),
    Pass("use_pass_material_index", "IndexMA", "MATERIAL_ID", "X", "VALUE"),
    Pass("use_pass_emit", "Emit", "EMISSION", "RGB", "COLOR"),
    Pass("use_pass_mist", "Mist", "DEPTH", "Z", "VALUE"),
)


def enabled(layer):
    return tuple(p for p in PASSES if getattr(layer, p.flag, False))


def outputs(layer):
    names = {p.output for p in enabled(layer)}
    # UV의 마스크는 UV=0 여부와 무관하며 실제 교차 여부를 사용한다.
    if getattr(layer, "use_pass_uv", False):
        names.add("DEPTH")
    if layer.use_pass_z or layer.use_pass_mist:
        names.update({"DEPTH", "POSITION"})
    if layer.use_pass_mist:
        names.add("ALPHA")
    return names
