# -*- coding: utf-8 -*-
"""block_replace 核心：白名单删除 + 逐框删边框 + 变换计算。

这些是“修 bug 回归保护”的重点：
- delete_title_strip 绝不能误删图内尺寸线/几何/长线（之前专门修过误删）
- delete_frame_border 只删与该帧重合的闭合矩形，不影响其它图框
"""
from helpers import (
    new_doc, add_rect, add_text, add_attdef, add_line, add_dimension,
)
from ezdxf import bbox as bbox_mod
from lib.block_replace import delete_title_strip, delete_frame_border, _compute_transform


def _count(msp, dt):
    return sum(1 for e in msp if e.dxftype() == dt)


def test_delete_title_strip_preserves_dimension_and_skips_long_line():
    doc = new_doc()
    msp = doc.modelspace()
    fb = (0, 0, 200, 100)  # W=200 H=100 -> 标题区 [90,0,200,28]
    # —— 标题区内应删除（旧标题栏内容/格线/标题框）——
    add_text(msp, "图名", 120, 10)                          # TEXT
    add_text(msp, "图号：123", 130, 12, dxftype="MTEXT")    # MTEXT
    add_attdef(msp, "TITLE", "图名", 110, 18)               # ATTDEF
    add_rect(msp, 95, 2, 198, 26, closed=True)             # 闭合标题框
    add_line(msp, 100, 2, 100, 26, dxftype="LWPOLYLINE")   # 短格线
    # —— 标题区内也应保留（误删风险点）——
    add_dimension(msp, (110, 15), (150, 15))               # DIMENSION 绝不删
    # —— 图外应保留 ——
    add_text(msp, "零件视图", 20, 80)                      # 图内文本
    add_line(msp, 0, 15, 200, 15)                          # 贯穿长线（不完全在标题区）

    n = delete_title_strip(doc, fb)

    # 设计意图（2026-08-31 标签证据盒后）：标题区内的文本类（命中
    # _TITLE_LABEL_RE）删除；此外当标题区底部命中 >=2 个标签文本时，
    # 「标签证据盒」内的 layer 0 短格线/闭合标题框也随证据删除（07a/07b
    # 旧标题栏值文本与格线残留的修复）。本测试中 2 个标签文本构成证据，
    # 闭合标题框 (95,2)-(198,26) 与证据盒相交且最长段 103 <= long_th 110
    # → 删除；x=100 的短格线在证据盒左侧之外 → 保留。删除数 = 4。
    assert n == 4, f"应删 4 个（3 个标题文本 + 证据盒内 layer 0 闭合标题框），实际删了 {n}"
    # 关键回归断言：尺寸标注绝不能丢
    assert _count(msp, "DIMENSION") == 1
    # 图内文本保留，仅剩图外那一条
    assert _count(msp, "TEXT") == 1
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert "零件视图" in texts
    assert "图名" not in texts
    # 贯穿长线仍在
    lines = [e for e in msp if e.dxftype() == "LINE"]
    assert len(lines) == 1
    assert lines[0].dxf.start.x == 0 and lines[0].dxf.end.x == 200
    # 证据盒左侧之外的 layer 0 短格线被守卫保留（设计意图）
    assert _count(msp, "LWPOLYLINE") == 1


def test_delete_title_strip_keeps_outside_text():
    doc = new_doc()
    msp = doc.modelspace()
    fb = (0, 0, 200, 100)
    add_text(msp, "图名", 150, 10)     # 在标题区 + 命中 _TITLE_LABEL_RE -> 删
    add_text(msp, "零件视图", 30, 80)  # 图外 -> 留

    n = delete_title_strip(doc, fb)

    assert n == 1
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert "零件视图" in texts
    assert "图名" not in texts


def test_delete_frame_border_only_matching_closed_rect():
    doc = new_doc()
    msp = doc.modelspace()
    fb = (0, 0, 200, 100)
    add_rect(msp, 0, 0, 200, 100, closed=True)          # 与 fb 重合 -> 删
    # 其它图内的「内容层」矩形（如设备/房间轮廓）绝不删——红线是零误删
    add_rect(msp, 10, 10, 60, 60, closed=True, layer="WALL")

    n = delete_frame_border(doc, fb)

    assert n == 1
    rects = [e for e in msp if e.dxftype() in ("LWPOLYLINE", "POLYLINE")]
    assert len(rects) == 1
    b = bbox_mod.extents([rects[0]])
    assert abs(b.extmin.x - 10) < 1 and abs(b.extmax.x - 60) < 1


def test_delete_frame_border_deletes_inner_frame_division():
    """回归：旧图框内部分隔线/标题栏单元格（图框层或 layer 0、含于帧且贴边）
    也应删，避免旧框残留；但内容层矩形（如 WALL）必须保留。"""
    doc = new_doc()
    msp = doc.modelspace()
    fb = (0, 0, 200, 100)
    add_rect(msp, 0, 0, 200, 100, closed=True)                 # 外框 -> 删
    add_rect(msp, 0, 50, 200, 50, closed=True)                 # 旧框中部分隔线(贴上下边) -> 删
    add_rect(msp, 150, 0, 200, 100, closed=True, layer="0")    # 标题栏单元格(贴右+下边) -> 删
    add_rect(msp, 20, 20, 80, 80, closed=True, layer="WALL")   # 内容层矩形 -> 留

    n = delete_frame_border(doc, fb)

    assert n == 3
    rects = [e for e in msp if e.dxftype() in ("LWPOLYLINE", "POLYLINE")]
    assert len(rects) == 1
    assert rects[0].dxf.layer == "WALL"


def test_compute_transform_scaling_and_centering():
    template = {"bbox": (0, 0, 10, 20)}   # tw=10, th=20
    region = {"bbox": (0, 0, 100, 100)}   # rw=rh=100

    s, ix, iy = _compute_transform(template, region, "min")
    assert s == 5 and ix == 25 and iy == 0

    s, ix, iy = _compute_transform(template, region, "max")
    assert s == 10 and ix == 0 and iy == -50

    s, ix, iy = _compute_transform(template, region, "width")
    assert s == 10 and ix == 0 and iy == -50

    s, ix, iy = _compute_transform(template, region, "height")
    assert s == 5 and ix == 25 and iy == 0
