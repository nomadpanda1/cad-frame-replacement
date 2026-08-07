# -*- coding: utf-8 -*-
"""finder 核心：多图框层级检测（案例七）+ 标题区字段抽取。"""
from helpers import new_doc, add_rect, add_text
from lib.finder import (
    detect_frames_hierarchical,
    extract_frame_fields,
)


def test_hierarchical_single_frame():
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 200, 100, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    assert sheet is None
    assert len(targets) == 1


def test_hierarchical_sheet_with_subframes():
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 800, 600, closed=True)        # sheet（整图纸边）
    add_rect(msp, 10, 10, 200, 200, closed=True)
    add_rect(msp, 250, 10, 400, 200, closed=True)
    add_rect(msp, 450, 10, 650, 500, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    assert sheet is not None
    assert len(targets) == 3


def test_hierarchical_side_by_side():
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 200, 100, closed=True)
    add_rect(msp, 250, 0, 450, 100, closed=True)
    add_rect(msp, 0, 150, 200, 250, closed=True)
    add_rect(msp, 250, 150, 450, 250, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    # 互不包含 -> 全都是替换目标，无 sheet
    assert sheet is None
    assert len(targets) == 4


def test_extract_frame_fields():
    doc = new_doc()
    msp = doc.modelspace()
    fb = (0, 0, 200, 100)
    add_text(msp, "图名：减速器箱体", 100, 10)
    add_text(msp, "图号：HF-001", 100, 30)
    add_text(msp, "比例：1:2", 100, 50)
    f = extract_frame_fields(doc, fb)
    assert f.get("TITLE") == "减速器箱体"
    assert f.get("DWG_NO") == "HF-001"
    assert f.get("SCALE") == "1:2"
