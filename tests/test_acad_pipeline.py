# -*- coding: utf-8 -*-
"""acad_pipeline / acad_com 非 COM 逻辑的单元测试。

真正调用 AutoCAD COM 的部分需要本机已打开 AutoCAD，沙箱里无法自动测试，
因此这里只覆盖 plan 构建、幅面推断、字段打包等纯 Python 逻辑。
"""
import os
import pytest

from lib import template_learn, acad_pipeline, sheet
import run_skill


HERE = os.path.dirname(os.path.abspath(__file__))
TPL_A3 = os.path.join(HERE, "..", "templates", "HH_FRAME_A3.dxf")


def test_guess_size_a3_landscape():
    assert sheet.guess_sheet_bbox([0, 0, 420, 297]).name == "A3"


def test_guess_size_a4_portrait():
    """竖版 A4 必须判成 A4V，而不是横版 A4。

    旧实现返回 "A4"（横版模板），插框时 scale=min(210/297, 297/210)=0.707，
    新框只占旧框底部 210x148.5，图纸内容整个跑到新框上方——这正是用户实拍
    「馈电-电气原理图」的现象。
    """
    spec = sheet.guess_sheet_bbox([0, 0, 210, 297])
    assert spec.name == "A4V"
    assert (spec.width, spec.height) == (210.0, 297.0)


def test_guess_size_a1():
    assert sheet.guess_sheet_bbox([0, 0, 841, 594]).name == "A1"


def test_values_to_fields_skips_empty():
    fields = [{"tag": "TITLE"}, {"tag": "DWG_NO"}, {"tag": "SCALE"}]
    values = ["主视图", "", "1:2"]
    out = run_skill._values_to_fields(fields, values)
    assert out == {"TITLE": "主视图", "SCALE": "1:2"}


def test_build_plan_from_mapping_block():
    assert os.path.exists(TPL_A3)
    template = template_learn.learn_template(TPL_A3)
    mappings = [{
        "region": [10.0, 10.0, 410.0, 287.0],
        "extracted": {"TITLE": "测试件", "DWG_NO": "CNG-0501/01"},
    }]
    tpl_dwgs = {"A3": "/tmp/HH_FRAME_A3.dwg", "A4": "/tmp/HH_FRAME_A4.dwg"}
    plan = acad_pipeline.build_plan_from_mapping(
        None, mappings, template, tpl_dwgs, fit="min")
    assert len(plan["frames"]) == 1
    fr = plan["frames"][0]
    assert fr["frame"] == [10.0, 10.0, 410.0, 287.0]
    assert fr["mode"] in ("block", "frame")
    assert fr["tpl_dwg"] == "/tmp/HH_FRAME_A3.dwg"
    assert fr["fields"]["TITLE"] == "测试件"
    assert fr["fields"]["DWG_NO"] == "CNG-0501/01"


def test_build_plan_for_raw_frame():
    assert os.path.exists(TPL_A3)
    template = template_learn.learn_template(TPL_A3)
    outer = [10.0, 10.0, 410.0, 287.0]
    tb = [230.0, 10.0, 410.0, 80.0]
    fields = {"TITLE": "前叉", "SCALE": "1:1"}
    tpl_dwgs = {"A3": "/tmp/HH_FRAME_A3.dwg"}
    plan = acad_pipeline.build_plan_for_raw_frame(
        None, outer, tb, template, tpl_dwgs, fields)
    fr = plan["frames"][0]
    assert fr["mode"] == "raw-frame"
    assert fr["titleblock"] == [230.0, 10.0, 410.0, 80.0]
    assert fr["fields"] == fields
