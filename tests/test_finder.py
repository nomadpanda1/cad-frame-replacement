# -*- coding: utf-8 -*-
"""finder 核心：多图框层级检测（案例七）+ 标题区字段抽取。"""
from helpers import new_doc, add_rect, add_text, add_line
from lib.finder import (
    detect_frames_hierarchical,
    extract_frame_fields,
    dedup_double_border,
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


def test_extract_no_leak_from_neighbor_frame():
    """回归：多图框并排时，帧A标题区不能串入帧B的标题文字。

    修复前 extract_frame_fields 的标题区只约束 cx 左界/cy 上界，区域向右下
    无限延伸，相邻框的标题文字会泄漏进来导致抽错。修复后四向有界。
    """
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 200, 100, closed=True)        # 帧A
    add_rect(msp, 300, 0, 500, 100, closed=True)      # 帧B（并排）
    # 各自标题区放独立标题（无「图名:」前缀，走兜底最长文本）
    add_text(msp, "帧A标题", 120, 20)                 # 帧A 标题区 [90,200]×[0,60]
    add_text(msp, "帧B的标题文字明显更长", 420, 20)    # 帧B 标题区 [390,500]×[0,60]
    fa = extract_frame_fields(doc, (0, 0, 200, 100))
    assert fa.get("TITLE") == "帧A标题"


def test_dedup_double_border_keeps_only_outer():
    """双线图框：外框套内框，应只保留外框（内框线视为同一框的残线）。"""
    outer = (0, 0, 1000, 800)
    inner = (10, 10, 990, 790)      # 面积比 ~0.96，典型双线
    out = dedup_double_border([outer, inner])
    assert len(out) == 1
    assert out[0] == outer


def test_dedup_double_border_keeps_distinct_frames():
    """互不包含的两个图框都保留。"""
    a = (0, 0, 200, 100)
    b = (300, 0, 500, 100)
    out = dedup_double_border([a, b])
    assert len(out) == 2


def test_dedup_double_border_fully_overlapping():
    """完全重合的重复矩形只留一个。"""
    a = (0, 0, 200, 100)
    b = (0, 0, 200, 100)
    out = dedup_double_border([a, b])
    assert len(out) == 1


def test_min_area_share_filters_small_symbols():
    """sheet + 1 大子框 + 3 个小电气符号（面积占比<min_area_share）：只留大子框。

    验证面积占比下限能压掉小矩形，且不误杀真大框（不能用长宽比筛，否则加长
    图幅真框会被误杀 —— 见 detect_frames_hierarchical 注释）。
    """
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 1000, 700, closed=True)        # sheet
    add_rect(msp, 10, 10, 500, 400, closed=True)       # 大子框
    # 小符号：面积 100x100=10000 > min_area(5000) 故会被收集，
    # 但远小于大子框面积(191100)的 0.15 倍 -> 面积占比过滤剔除
    add_rect(msp, 600, 10, 700, 110, closed=True)
    add_rect(msp, 720, 10, 820, 110, closed=True)
    add_rect(msp, 840, 10, 940, 110, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    assert sheet is not None
    assert targets == [(10, 10, 500, 400)]


def test_detect_no_false_positive_like_cng():
    """模拟 CNG 电气系统图：sheet 内含 4 个真大框（加长比 2.0）+ 数十个小闭合矩形。

    修复前仅按"矩形 + 最小边长/面积"检测，会把小闭合矩形全当成图框，
    检出 61 个。修复后两级过滤（面积占比 + 双线去重）应稳定回到 4 个真框。
    所有矩形必须落在同一个 sheet 内，sheet 才会被识别为"纸边"并从目标剔除。
    """
    doc = new_doc()
    msp = doc.modelspace()
    add_rect(msp, 0, 0, 80000, 60000, closed=True)      # sheet（纸边，含所有内容）
    # 4 个大框：20000×10000（长宽比 2.0，电气图加长图幅常见），均在 sheet 内
    big = [
        (1000, 1000, 21000, 11000),
        (30000, 1000, 50000, 11000),
        (1000, 40000, 21000, 50000),
        (30000, 40000, 50000, 50000),
    ]
    for b in big:
        add_rect(msp, b[0], b[1], b[2], b[3], closed=True)
    # 50 个小符号：1000×1000（面积 1e6 > min_area 5000 故会被收集，
    # 但 < 0.15*最大目标框面积(2e8*0.15=3e7) -> 面积占比过滤剔除）
    for i in range(50):
        x = 52000 + (i % 13) * 2100
        y = 1000 + (i // 13) * 2100
        add_rect(msp, x, y, x + 1000, y + 1000, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    assert len(targets) == 4


def test_no_false_positive_borderless_dense():
    """回归：边框less 密集小方框（控制原理图元件符号）不应被判为图框。

    给煤机控制原理图即此情形：全图无 A 幅面边框（长条图，折合1#），图内大量
    继电器/接触器轮廓是闭合小矩形（约 550x390，单个仅占整图 ~1%）。修复前
    detect_frames_hierarchical 会把这些小方框全部当成「图框」返回，导致误插 15 个
    公司框破坏原图。修复后新增全局占比护栏：候选框面积不足整图 2% 时视为元件
    方框剔除，判定为「无有效图框」。
    """
    doc = new_doc()
    msp = doc.modelspace()
    # 长条图轮廓：两条长线把整图范围撑到 ~9200 x 1800（模拟滚动长条图 extents）
    add_line(msp, -6000, 0, 3200, 0)
    add_line(msp, -6000, 1800, 3200, 1800)
    # 15 个元件方框（与给煤机实测一致），散布在图内一小片区域
    boxes = [
        (1455, 825, 2005, 1215), (410, 820, 590, 1107), (875, 415, 1425, 805),
        (2620, 5, 3005, 280), (2630, 65, 2997, 257), (875, 5, 1425, 395),
        (2605, 300, 2995, 850), (2615, 880, 3165, 1270), (2035, 1235, 2585, 1625),
        (2035, 5, 2585, 395), (1455, 5, 2005, 395), (2035, 415, 2585, 805),
        (1455, 415, 2005, 805), (2035, 825, 2585, 1215), (445.8, 4.3, 846.3, 565.3),
    ]
    for x0, y0, x1, y1 in boxes:
        add_rect(msp, x0, y0, x1, y1, closed=True)
    sheet, targets = detect_frames_hierarchical(doc)
    assert sheet is None
    assert targets == []
