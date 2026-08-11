# -*- coding: utf-8 -*-
"""raw-frame 打散回退回归：#4 插入区域用 outer 框而非全局 sheet；#5 outer 取面积最大框。

背景：SolidWorks「打散」图纸无 INSERT 块，run_skill 在块式检测 0 命中时回退到线框检测。
此前两个缺陷：
  #4 插入 region 用全局 sheet_extents（整图外包）——若图内有 stray 远点实体会把新框撑大/错位；
  #5 outer 取 frames[0]——双线图框（外框+内框）时可能取到内框而非最外框。
"""
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import new_doc, add_rect, add_text
import ezdxf
from lib import finder


def _make_double_line_with_stray(tmp_dxf):
    """双线图框（外框 1000x700 + 内框 980x680）+ 右下角标题栏 + 远点 stray 实体。

    stray 放在 (1100,700)：仍在 2×图框范围内，detect_frames 仍能检出外框；
    但会把它当作图幅一部分，使全局 sheet_extents 从 1000x700 撑大到 1100x700。
    这正是 #4 的风险源——若插入区域用全局 sheet，新框会被 stray 撑大。
    """
    doc = new_doc()
    msp = doc.modelspace()
    W, H = 1000.0, 700.0
    add_rect(msp, 0, 0, W, H, closed=True)            # 外框（面积最大）
    add_rect(msp, 10, 10, W - 10, H - 10, closed=True)  # 内框（双线）
    # 右下角标题栏锚点（让 detect_titleblock 命中、extract 有字段）
    add_text(msp, "图名：回归测试", W - 40, 20)
    add_text(msp, "图号：HF-R1", W - 40, 40)
    # stray 远点实体：把全局 sheet_extents 撑大到 1100x700（#4 风险源）
    add_text(msp, "stray", 1100, 700)
    doc.saveas(tmp_dxf)
    return (0.0, 0.0, W, H)


def test_raw_frame_picks_largest_outer():
    """#5：双线图框时 outer 必须是面积最大的外框，而非内框。"""
    fd, p = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        outer = _make_double_line_with_stray(p)
        doc = ezdxf.readfile(p)
        frames = finder.detect_frames(doc)
        assert frames, "应检测到外框"
        chosen = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        assert chosen == outer, "outer 应取面积最大的框，而非内框"
    finally:
        os.remove(p)


def test_raw_frame_region_uses_outer_not_sheet():
    """#4：打散回退的插入区域应是检测到的 outer 框，而非被 stray 撑大的全局 sheet。

    直接驱动 run_skill 主流程（打散图纸→块式 0 命中→线框回退），断言生成的
    run_report.json 中 region == outer（双线外框），而非 ≈5000 的全局 sheet。
    """
    import run_skill
    fd, p = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    outer = _make_double_line_with_stray(p)
    out = tempfile.mkdtemp()
    old_argv = sys.argv
    try:
        tpl = os.path.join(os.path.dirname(run_skill.__file__), "templates", "HH_FRAME_A3.dxf")
        sys.argv = ["run_skill.py", "--template", tpl,
                    "--out", out, "--mode", "single", "--fit", "min", p]
        run_skill.main()
        rp = os.path.join(out, "run_report.json")
        assert os.path.exists(rp), "应生成 run_report.json"
        rep = json.load(open(rp, encoding="utf-8"))
        rec = rep["files"][0]
        region = rec["mappings"][0]["region"]
        # 修复后 region 应等于 outer（双线外框 1000x700），而非被 stray 撑大到 1100x700 的全局 sheet
        assert region == [0.0, 0.0, 1000.0, 700.0], \
            "插入区域应为检测到的 outer 框，而非全局 sheet，得到 %s" % region
        assert rec["method"] == "raw-frame"
        assert rep["fit"] == "min"  # #3：尊重 GUI 缩放选择（args.fit 透传，未写死 max）
    finally:
        sys.argv = old_argv
        try:
            os.remove(p)
        except Exception:
            pass
        shutil.rmtree(out, ignore_errors=True)
