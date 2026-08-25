# -*- coding: utf-8 -*-
"""按字段类型校验提取出的属性值，过滤明显错误（位置错位 / 标签当值 / 占位文本）。

设计：先用 weak+strong 融合尽量多提（高召回），再按字段类型校验（高精确）。
把 SCALE='圆柱齿轮'、WEIGHT='图名文本'、DESIGN='标准化'、TITLE='图号: BESS-LST-001'
这类垃圾值拒掉，避免写入新标题栏污染数据；校验不过则留空（记 unmatched）。
"""
import re
from .concepts import CONCEPT_ALIASES, SW_TITLE_VOCAB

_RATIO_RE = re.compile(r"^\d+\s*[:：xX×]\s*\d+$")
_WEIGHT_RE = re.compile(r"^\d+(\.\d+)?\s*(kg|g|t|千克|克|吨)?$", re.I)
_DATE_RE = re.compile(r"^\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}")
_SHEET_RE = re.compile(r"^(第?.?\s*[一二三四五六七八九十\d]+\s*[张页]?\s*[共全]?\s*\d*|^\d+)$")

# 标题栏「字段名标签」归一集合（仅来自 CONCEPT_ALIASES 的别名词）。
# 注意：不能并入 SW_TITLE_VOCAB —— 后者还含「装配图/零件图」等图样类型词，
# 它们在 SW 里常就是真实图名，若用于拒值会把合法 TITLE 误删。
_LABEL_NORMS = set()
for _aliases in CONCEPT_ALIASES.values():
    for _a in _aliases:
        if _a:
            _LABEL_NORMS.add(_a.replace(" ", "").lower())
for _v in SW_TITLE_VOCAB:
    _LABEL_NORMS.add(_v.replace(" ", "").lower())

# 仅字段名别名（不含 SW_TITLE_VOCAB 的图样类型词），用于 TITLE 拒值判定
_TITLE_LABELS = set()
for _a in CONCEPT_ALIASES["TITLE"]:
    if _a:
        _TITLE_LABELS.add(_a.replace(" ", "").lower())

# 标题栏常见标签词（含非字段名的：描图/制图/密级/建设单位/工程名称/设计号/张次…）。
# 值若等于这些词本身（归一后），基本是「标签单元格」而非真实图名——如 SW 打散图框里
# 的“描  图”（描图人栏的标签）就曾被提取成 TITLE 写入新标题栏（92DZ1 帧3/4）。
_TITLE_BAD_NORMS = {
    "描图", "制图", "密级", "建设单位", "工程名称", "项目名称", "设计号",
    "张次", "页码", "总页数", "阶段标记", "图样名称", "标准化", "制表",
    "审核", "校对", "批准", "审定", "会签", "设计", "制图人", "描图人",
    "共张", "第张", "共页", "第页",
}

# 张数/页码类文本（共 张 / 第 张 / 共 X 张 / 第 X 张）绝不当图名——它们应归 SHEET 字段，
# 且源里多为空标签「共  张」，被提取器贪心派给 TITLE 会污染新标题栏（装配体实测：
# 图名字段被误填「共  张」）。归一后形如「共张/第张」，正则兜底拒值。
_TITLE_SHEET_RE = re.compile(r"^(共|第).*张$")

# 环绕引号（中英/弯直）归一时去掉，避免 "图样名称" 因带弯引号而漏判标签
_QUOTE_RE = re.compile(r'^[「『"\'“”‘’]+|[「『"\'“”‘’]+$')

_SCALE_OK = {"nts", "无", "不限", "按实", "比例见", "asshown", "scale1:1", "不注"}

# TITLE 常见「标签前缀」，值若以这些开头基本是标签单元格本身而非图名
_TITLE_PREFIX = ("图号", "图名", "名称", "材料", "比例", "重量", "阶段", "版本",
                "日期", "设计", "校对", "审核", "批准", "会签", "页码", "总页数")

# TITLE 引用/注记判定：标题栏为空时，提取器会把「（摘自华北地区标准图戍2DQZ103页）」
# 这类引用注记、或「详见 / 参见 / 引自…」说明当图名回填 → 用户看到的「属性值混乱」。
# 这些文本绝不该作为图名，直接拒掉（留空，不污染新标题栏）。92DZ1 帧2 实测命中。
_REF_NOTE_RE = re.compile(r"摘自|参见|详见|引自|见.*图")


def _is_reference_note(v):
    """值是否为引用/注记文本（如「（摘自华北地区标准图戍2DQZ103页）」「详见图集」）。"""
    s = (v or "").strip()
    if not s:
        return False
    if _REF_NOTE_RE.search(s):
        return True
    # 全角括号包裹且含 图/页/标准/集 —— 典型「（摘自…标准图…页）」引用注记
    if s.startswith("（") and ("图" in s or "页" in s or "标准" in s or "集" in s):
        return True
    return False


def _norm(s):
    return _QUOTE_RE.sub("", re.sub(r"\s+", "", str(s)).lower())


def _is_label(v):
    """值本身是否就是标题栏字段标签（如 标准化 / 阶段标记 / 图样名称）。"""
    return _norm(v) in _LABEL_NORMS


def validate(concept, value):
    """返回该值是否可作为 concept 字段的有效值。"""
    if not value or not str(value).strip():
        return False
    v = str(value).strip()
    nv = _norm(v)
    if concept == "SCALE":
        return bool(_RATIO_RE.match(v)) or nv in _SCALE_OK
    if concept == "WEIGHT":
        return bool(_WEIGHT_RE.match(v))
    if concept == "DATE":
        return bool(_DATE_RE.search(v)) or bool(re.search(r"\d{4}", v))
    if concept == "SHEET":
        return bool(_SHEET_RE.match(v)) or bool(re.fullmatch(r"\d+", v))
    if concept == "TITLE":
        # 仅用字段名别名拒值（图名/名称/零件名称/图样名称/件名…），
        # 不用 SW_TITLE_VOCAB（含 装配图/零件图 等合法图名）
        if nv in _TITLE_LABELS or nv in _TITLE_BAD_NORMS:
            return False
        # 张数/页码类文本（共 张 / 第 张，归一后 共张/第张）不当图名
        if _TITLE_SHEET_RE.match(nv):
            return False
        # 引用/注记文本（「（摘自华北地区标准图戍2DQZ103页）」「详见图集」）绝不当图名
        if _is_reference_note(v):
            return False
        # 形如「图号：BESS-LST-001」被误当图名
        if re.match(r"^(图号|图名|名称|材料|比例|重量|阶段|版本|日期|设计|校对|"
                    r"审核|批准|会签)\s*[:：]", v):
            return False
        return True
    # 其余字段：拒绝纯标签占位文本（DESIGN='标准化' / STAGE='阶段标记' 等）
    if _is_label(v):
        return False
    return True
