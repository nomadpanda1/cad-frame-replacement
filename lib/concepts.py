# -*- coding: utf-8 -*-
"""
概念中间层：把五花八门的字段名（中/英文、简写、带空格）统一成一套规范概念。
旧图和新模板的字段都先映射到概念，再做迁移，这样“公司图框随时换字段”也能对上。
"""
import re

# 规范概念 -> 别名（小写、去空格后匹配）
CONCEPT_ALIASES = {
    "TITLE":      ["图名", "名称", "零件名称", "图样名称", "件名", "name", "title", "drawingname", "dwgname"],
    "DWG_NO":     ["图号", "编号", "代号", "零件代号", "图号no", "dwgno", "drawingno", "docno", "number", "no"],
    "SCALE":      ["比例", "scale"],
    "STAGE":      ["阶段", "stage", "phase"],
    "DATE":       ["日期", "设计日期", "date"],
    "DESIGN":     ["设计", "设计人", "制图", "设计员", "design", "designedby", "drawnby", "drawer"],
    "CHECK":      ["校对", "校核", "check", "checkedby"],
    "REVIEW":     ["审核", "review", "reviewedby"],
    "APPROVE":    ["批准", "approve", "approvedby"],
    "COUNTERSIGN":["会签", "countersign", "cosign"],
    "DRAWN":      ["描图", "描图员", "drawn"],
    "SHEET":      ["页码", "第张", "sheet", "page", "pageno"],
    "TOTAL":      ["总页数", "总张数", "total", "totalsheets", "of"],
    "MATERIAL":   ["材料", "材质", "material"],
    "WEIGHT":     ["重量", "质量", "单件重量", "weight", "mass"],
    "VERSION":    ["版本", "version", "rev"],
    "SIZE":       ["图幅", "sheetsize", "size"],
    "PROJECT":    ["项目", "project", "proj"],
    "CUSTOMER":   ["客户", "customer", "client"],
}

# 反向：别名 -> 概念
_ALIAS_TO_CONCEPT = {}
for _concept, _aliases in CONCEPT_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_CONCEPT[_a.lower().replace(" ", "")] = _concept

# 标题栏识别关键词（用于 finder 关键词吸附）
TITLEBLOCK_KEYWORDS = ["图名", "图号", "比例", "阶段", "设计", "校对", "审核",
                       "批准", "会签", "材料", "重量", "版本", "图幅", "日期"]
# 疑似图框块名关键词
FRAME_BLOCK_KEYWORDS = ["frame", "title", "图框", "标题", "border", "sheet", "tb_", "a_", "hw_"]

# SolidWorks 导出图框的标题栏词表（含空格/变体，用于定位标题栏区域 + 标注识别）
SW_TITLE_VOCAB = [
    "图名", "名称", "零件名称", "图样名称", "件名",
    "图号", "编号", "代号", "零件代号", "图号no", "旧底图总号",
    "材料", "材质",
    "比例",
    "重量", "质量", "单件重量",
    "版本", "阶段", "阶段标记", "标记",
    "签名", "年月日", "日期", "设计日期",
    "设计", "制图", "描图", "校对", "校核", "审核", "批准", "标准化", "工艺", "会签", "主管设计",
    "共", "第", "张", "页码", "总张数", "总页数",
    "分区", "处数", "更改文件号", "替代", "装配图", "装配", "投影", "投影角",
]


def _norm(s):
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s)).lower()


def infer_concept(text):
    """把字段名/标签文本推断为规范概念，命中返回概念，否则返回 None。"""
    n = _norm(text)
    if not n:
        return None
    if n in _ALIAS_TO_CONCEPT:
        return _ALIAS_TO_CONCEPT[n]
    # 子串匹配（如 "图名：" / "drawing no."）
    for alias, concept in _ALIAS_TO_CONCEPT.items():
        if alias and alias in n:
            return concept
    return None
