# -*- coding: utf-8 -*-
"""稳健生成 README 前后对比缩略图（DXF -> SVG -> PNG）。
关键修复：svglib 必须经「文件路径」读取 SVG（直接喂 StringIO+<?xml?> 声明会触发
'NoneType' object has no attribute 'renderScale' 并产出 202 字节空图）。
每个 PNG 产出后做体积校验（>2KB），失败自动回退 matplotlib 后端直渲。
用法：
  python gen_thumbnails.py
PAIRS 在文件底部定义（name, src_dxf, dst_dxf）；before=src, after=dst。
"""
import os
import re
import io
import sys
import tempfile

import ezdxf
from ezdxf.addons.drawing import Frontend
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.addons.drawing.properties import RenderContext
from ezdxf.addons.drawing import layout as layout_mod

from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "assets", "thumbnails")
SRC_SVG_DIR = os.path.join(HERE, "z_temp", "svg")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(SRC_SVG_DIR, exist_ok=True)

DARK = "#212830"
BGINT = 0x212830
MIN_BYTES = 2 * 1024


def render_svg(dxf_path):
    """渲染 DXF 为带深色背景的 SVG 字符串。"""
    doc = ezdxf.readfile(dxf_path)
    layout = doc.modelspace()
    if len(layout) == 0:
        for lay in doc.layouts:
            if lay.dxf.name != "Model" and len(lay) > 0:
                layout = lay
                break
    backend = SVGBackend()
    ctx = RenderContext(doc)
    Frontend(ctx, backend).draw_layout(layout)
    try:
        page = layout_mod.Page.from_dxf_layout(layout)
    except Exception:
        page = layout_mod.Page(0, 0, layout_mod.Units.mm)
    svg = backend.get_string(page)
    if 'fill="#212830"' not in svg[:5000]:
        m = re.search(r"<svg[^>]*>", svg)
        if m:
            pos = m.end()
            svg = svg[:pos] + '\n<rect x="0" y="0" width="100%" height="100%" fill="#212830"/>' + svg[pos:]
        else:
            svg = svg.replace(">", '>\n<rect x="0" y="0" width="100%" height="100%" fill="#212830"/>', 1)
    return svg


def svg_to_png_svglib(svg, dst):
    """svglib 经文件路径转换，返回是否成功。"""
    tmp = os.path.join(SRC_SVG_DIR, "_tmp.svg")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(svg)
    try:
        d = svg2rlg(tmp)  # 必须经路径，勿喂 StringIO
        if d is None:
            return False
        renderPM.drawToFile(d, dst, fmt="PNG", bg=BGINT)
        return os.path.getsize(dst) > MIN_BYTES
    except Exception:
        return False


def svg_to_png_mpl(svg, dst):
    """matplotlib 直渲回退（svg 参数此处未用，直接重渲 DXF）。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        # 这里无法从 svg 反推，仅作为占位；实际回退在 render_pair 内完成
        return False
    except Exception:
        return False


def render_pair_direct(dxf_path, dst):
    """matplotlib 后端直渲 DXF -> PNG（绕过 SVG 中间层）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    doc = ezdxf.readfile(dxf_path)
    layout = doc.modelspace()
    if len(layout) == 0:
        for lay in doc.layouts:
            if lay.dxf.name != "Model" and len(lay) > 0:
                layout = lay
                break
    fig = plt.figure(figsize=(8, 6))
    fig.patch.set_facecolor(DARK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(DARK)
    backend = MatplotlibBackend(ax)
    try:
        Frontend(RenderContext(doc), backend).draw_layout(layout, finalize=True)
    except Exception:
        Frontend(RenderContext(doc), backend).draw_layout(layout)
    ax.set_axis_off()
    fig.savefig(dst, dpi=110, facecolor=DARK, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return os.path.getsize(dst) > MIN_BYTES


def make_thumb(dxf_path, dst):
    if not os.path.exists(dxf_path):
        print(f"  [SKIP] 源不存在: {dxf_path}")
        return False
    svg = render_svg(dxf_path)
    ok = svg_to_png_svglib(svg, dst)
    if not ok:
        print(f"  [FALLBACK mpl] {os.path.basename(dxf_path)}")
        ok = render_pair_direct(dxf_path, dst)
    if not ok:
        print(f"  [ERR] 两路均失败: {dst}")
        return False
    print(f"  [ok] {os.path.basename(dst)} {os.path.getsize(dst)}B")
    return True


# ----------------- PAIRS -----------------
# exe 真实测试（case 01 的 9 张）—— 修复坏图 + 全量重染
EXE_PAIRS = [
    ("exe_从法兰(2)", "cases/01_SW_parts/inputs/从法兰(2).dxf", "exe_test_out/从法兰(2)_HH.dxf"),
    ("exe_前叉(1)", "cases/01_SW_parts/inputs/前叉(1).dxf", "exe_test_out/前叉(1)_HH.dxf"),
    ("exe_圆柱齿轮13×1(2)", "cases/01_SW_parts/inputs/圆柱齿轮13×1(2).dxf", "exe_test_out/圆柱齿轮13×1(2)_HH.dxf"),
    ("exe_圆柱齿轮65×1(1)", "cases/01_SW_parts/inputs/圆柱齿轮65×1(1).dxf", "exe_test_out/圆柱齿轮65×1(1)_HH.dxf"),
    ("exe_法兰(2)", "cases/01_SW_parts/inputs/法兰(2).dxf", "exe_test_out/法兰(2)_HH.dxf"),
    ("exe_等轴测图(1)", "cases/01_SW_parts/inputs/等轴测图(1).dxf", "exe_test_out/等轴测图(1)_HH.dxf"),
    ("exe_装配体图纸(1)", "cases/01_SW_parts/inputs/装配体图纸(1).dxf", "exe_test_out/装配体图纸(1)_HH.dxf"),
    ("exe_装配体爆炸图1(1)", "cases/01_SW_parts/inputs/装配体爆炸图1(1).dxf", "exe_test_out/装配体爆炸图1(1)_HH.dxf"),
    ("exe_龙门架", "cases/01_SW_parts/inputs/龙门架.dxf", "exe_test_out/龙门架_HH.dxf"),
]

# 其他场景测试（用 exe 核心 run_skill 重跑 case 03/06/07/08 后的 *_HH 输出）
OTHER_PAIRS = [
    ("exe_03__16MW_32MWh_一次设备表", "cases/03_ESS_cad/inputs/16MW_32MWh_一次设备表.dxf", "exe_test_other/16MW_32MWh_一次设备表_HH.dxf"),
    ("exe_03__16MW_32MWh_二次系统信号表", "cases/03_ESS_cad/inputs/16MW_32MWh_二次系统信号表.dxf", "exe_test_other/16MW_32MWh_二次系统信号表_HH.dxf"),
    ("exe_03__16MW_32MWh_二次系统柜体表", "cases/03_ESS_cad/inputs/16MW_32MWh_二次系统柜体表.dxf", "exe_test_other/16MW_32MWh_二次系统柜体表_HH.dxf"),
    ("exe_03__16MW_32MWh_储能系统简化主接线图", "cases/03_ESS_cad/inputs/16MW_32MWh_储能系统简化主接线图.dxf", "exe_test_other/16MW_32MWh_储能系统简化主接线图_HH.dxf"),
    ("exe_06__06a_multiframe", "cases/06_synth/inputs/06a_multiframe.dxf", "exe_test_other/06a_multiframe_HH.dxf"),
    ("exe_06__06b_nested_title", "cases/06_synth/inputs/06b_nested_title.dxf", "exe_test_other/06b_nested_title_HH.dxf"),
    ("exe_06__06c_missing_font", "cases/06_synth/inputs/06c_missing_font.dxf", "exe_test_other/06c_missing_font_HH.dxf"),
    ("exe_06__06d_countersign", "cases/06_synth/inputs/06d_countersign.dxf", "exe_test_other/06d_countersign_HH.dxf"),
    ("exe_07__07a_tiled", "cases/07_multiframe/inputs/07a_tiled.dxf", "exe_test_other/07a_tiled_HH.dxf"),
    ("exe_07__07b_side_by_side", "cases/07_multiframe/inputs/07b_side_by_side.dxf", "exe_test_other/07b_side_by_side_HH.dxf"),
    ("exe_08__08_real_multiframe", "cases/08_real_mf/inputs/08_real_multiframe.dxf", "exe_test_other/08_real_multiframe_HH.dxf"),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "exe"
    pairs = EXE_PAIRS if mode == "exe" else OTHER_PAIRS
    for name, src, dst in pairs:
        print(f"== {name}")
        make_thumb(src, os.path.join(OUT_DIR, name + "_before.png"))
        make_thumb(dst, os.path.join(OUT_DIR, name + "_after.png"))


if __name__ == "__main__":
    main()
