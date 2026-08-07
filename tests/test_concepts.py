# -*- coding: utf-8 -*-
"""concepts 概念层：字段名 -> 规范概念推断。"""
from lib import concepts


def test_infer_concept_chinese():
    assert concepts.infer_concept("图名") == "TITLE"
    assert concepts.infer_concept("图号") == "DWG_NO"
    assert concepts.infer_concept("比例") == "SCALE"
    assert concepts.infer_concept("材料") == "MATERIAL"


def test_infer_concept_english():
    assert concepts.infer_concept("TITLE") == "TITLE"
    assert concepts.infer_concept("drawingno") == "DWG_NO"
    assert concepts.infer_concept("MATERIAL") == "MATERIAL"


def test_infer_concept_with_prefix_or_colon():
    # 带冒号/前缀/英文标点也应推断到正确概念
    assert concepts.infer_concept("图名：减速器箱体") == "TITLE"
    assert concepts.infer_concept("drawing no.") == "DWG_NO"


def test_infer_concept_none_for_garbage():
    assert concepts.infer_concept("随机一段无关文字") is None
    assert concepts.infer_concept("") is None
    assert concepts.infer_concept(None) is None
