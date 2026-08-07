# -*- coding: utf-8 -*-
"""extract 取值路由：比例/材料/图号/重量/图名 的高置信判定（防贪心误派）。"""
from lib.extract import (
    _is_ratio, _looks_material, _is_dwgno, _is_weight, _looks_name,
)


def test_is_ratio():
    assert _is_ratio("1:2")
    assert _is_ratio("1：5")
    assert not _is_ratio("减速器")


def test_looks_material():
    assert _looks_material("Q235")
    assert _looks_material("45#")
    assert not _looks_material("减速器箱体")


def test_is_dwgno():
    assert _is_dwgno("1-1")
    assert not _is_dwgno("HF-001")


def test_is_weight():
    assert _is_weight("0.681")
    assert not _is_weight("0.05")   # <0.1 视为版本号


def test_looks_name():
    assert _looks_name("减速器箱体")
    assert not _looks_name("1:2")
    assert not _looks_name("Q235")
