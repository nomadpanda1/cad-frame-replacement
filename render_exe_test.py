# -*- coding: utf-8 -*-
"""把 exe 测试的输入/输出 DXF 渲染成 SVG，用于 HTML 前后对比。
输入/输出 DXF 均为真实产物（exe 真跑得到）。"""
import os
import ezdxf
from ezdxf.addons.drawing import Frontend
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.addons.drawing.properties import RenderContext
from ezdxf.addons.drawing import layout as layout_mod

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "exe_test_out", "svg")
os.makedirs(OUT, exist_ok=True)

PAIRS = [
    ("从法兰(2)", "cases/01_SW_parts/inputs/从法兰(2).dxf", "exe_test_out/从法兰(2)_HH.dxf"),
    ("前叉(1)", "cases/01_SW_parts/inputs/前叉(1).dxf", "exe_test_out/前叉(1)_HH.dxf"),
    ("圆柱齿轮13×1(2)", "cases/01_SW_parts/inputs/圆柱齿轮13×1(2).dxf", "exe_test_out/圆柱齿轮13×1(2)_HH.dxf"),
    ("圆柱齿轮65×1(1)", "cases/01_SW_parts/inputs/圆柱齿轮65×1(1).dxf", "exe_test_out/圆柱齿轮65×1(1)_HH.dxf"),
    ("法兰(2)", "cases/01_SW_parts/inputs/法兰(2).dxf", "exe_test_out/法兰(2)_HH.dxf"),
    ("等轴测图(1)", "cases/01_SW_parts/inputs/等轴测图(1).dxf", "exe_test_out/等轴测图(1)_HH.dxf"),
    ("装配体图纸(1)", "cases/01_SW_parts/inputs/装配体图纸(1).dxf", "exe_test_out/装配体图纸(1)_HH.dxf"),
    ("装配体爆炸图1(1)", "cases/01_SW_parts/inputs/装配体爆炸图1(1).dxf", "exe_test_out/装配体爆炸图1(1)_HH.dxf"),
    ("龙门架", "cases/01_SW_parts/inputs/龙门架.dxf", "exe_test_out/龙门架_HH.dxf"),
]


def pick_layout(doc):
    msp = doc.modelspace()
    if len(msp) > 0:
        return msp
    for lay in doc.layouts:
        if lay is not doc.layouts.modelspace():
            if len(lay) > 0:
                return lay
    return msp


def render(dxf_path, out_svg):
    doc = ezdxf.readfile(dxf_path)
    layout = pick_layout(doc)
    backend = SVGBackend()
    # 关键：Frontend 第一个参数必须是 RenderContext(doc)，不是 doc 也不是 doc.styles
    ctx = RenderContext(doc)
    Frontend(ctx, backend).draw_layout(layout)
    # 页面尺寸：用模型空间自身页面设置，缺失（0）时自动适配内容包围盒
    try:
        page = layout_mod.Page.from_dxf_layout(layout)
    except Exception:
        page = layout_mod.Page(0, 0, layout_mod.Units.mm)
    svg = backend.get_string(page)
    # 注入白底，保证在网页里线条可见
    if "<rect" not in svg[:500]:
        svg = svg.replace(">", '>\n<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>', 1)
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write(svg)
    return len(svg)


if __name__ == "__main__":
    for name, inp, outp in PAIRS:
        try:
            si = render(inp, os.path.join(OUT, name + "_in.svg"))
            so = render(outp, os.path.join(OUT, name + "_out.svg"))
            print(f"[ok] {name}: in {si}B / out {so}B")
        except Exception as e:
            print(f"[ERR] {name}: {e}")
