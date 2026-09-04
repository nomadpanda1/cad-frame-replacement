# -*- coding: utf-8 -*-
"""
旧图框属性提取：从检测到的 region 里读出字段值。
  块图框：直接读 INSERT 的 ATTRIB。
  打散图框（SolidWorks）：扫描 region 内 TEXT/MTEXT，做网格化的 标签↔值 贪心匹配。
返回 {concept: value}，concept 由 concepts.infer_concept 推断。
"""
import re
from ezdxf import bbox as bbox_mod
from .concepts import infer_concept, _norm, CONCEPT_ALIASES, SW_TITLE_VOCAB
from .text_decode import decode_mtext


def _clean(t):
    if t is None:
        return ""
    # 去 MTEXT 控制符：\字母...; 及常见无分号码 \P \~ \\ 等（非贪婪，避免吞掉后续正文）
    t = re.sub(r"\\[A-Za-z][^;{}]*;", " ", t)
    t = re.sub(r"\\[A-Za-z~^\\]", " ", t)
    t = re.sub(r"[{}]", "", t)
    return t.strip()


_MAT_RE = re.compile(
    r"(钢|铝|铜|铁|塑|木|合?金|亚克力|尼龙|聚四氟|聚碳|有机玻璃|玻璃|橡胶|硅胶|"
    r"陶瓷|钛|铸铁|黄铜|青铜|紫铜|不锈钢|碳钢|铝合金|皮革|泡沫|电木|酚醛|中密板|"
    r"Q[0-9]|ABS|PLA|PC|PVC|PE|PP|POM|PTFE|PET|TPU|PEEK|304|316|45#|20#|40Cr)"
)
# 比例值（高置信）：1:2 / 1：5 / 1x5 / 2×1
_RATIO_RE = re.compile(r"^\d+\s*[:：xX×]\s*\d+$")


def _looks_material(txt):
    """值是否像材料码：命中材料词表（中/英/牌号）即为材料。"""
    if not txt:
        return False
    return bool(_MAT_RE.search(txt))


def _is_ratio(txt):
    """值是否像比例（如 1:2 / 2:1）。"""
    return bool(_RATIO_RE.match(txt.strip()))


_CJK_RE = re.compile(r"[一-鿿]")

# 图号（装配图编号，如 1-1 / 2-3）
_DWGNO_RE = re.compile(r"^\d+-\d+$")
# 日期（如 2026-09 / 2026.9.3 / 2026-09-04）——与装配图编号 \d+-\d+ 冲突，
# 年份形态的优先按日期处理（2026-09-04，35kV 图日期值被误当日志号修复）
_DATE_RE = re.compile(r"^(?:19|20)\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?$")
# 重量（带小数的千克值，如 0.681；排除版本号 0.001 这类 <0.1 的小数）
_WEIGHT_RE = re.compile(r"^\d+\.\d+$")


def _is_date(txt):
    return bool(_DATE_RE.match(txt.strip()))


def _is_dwgno(txt):
    if _is_date(txt):
        return False  # 2026-09 这类年份形态是日期，不是装配图编号
    return bool(_DWGNO_RE.match(txt.strip()))


def _is_weight(txt):
    m = _WEIGHT_RE.match(txt.strip())
    if not m:
        return False
    try:
        return float(txt.strip()) >= 0.1
    except Exception:
        return False


def _looks_name(txt):
    """值是否像图名/零件名：含汉字，或英文单词（排除数字/代号/区号）。"""
    if not txt:
        return False
    if (_is_zone_mark(txt) or _is_ratio(txt) or _looks_material(txt)
            or _is_dwgno(txt) or _is_weight(txt)):
        return False
    if _CJK_RE.search(txt):
        return True
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9\- ]{1,30}", txt.strip()))


def extract_fields(doc, region):
    if region.get("method") == "block" and region.get("entity") is not None:
        return _extract_from_block(region["entity"])
    return _extract_from_text(doc, region["bbox"])


def _extract_from_block(insert):
    out = {}
    for at in insert.attribs:
        tag = at.dxf.tag
        val = decode_mtext((at.dxf.text or "").strip())
        concept = infer_concept(tag) or tag.upper()
        out[concept] = val
    return out


def _in_bbox(bb, x, y, pad=1.0):
    return (bb[0] - pad <= x <= bb[2] + pad) and (bb[1] - pad <= y <= bb[3] + pad)


def _is_zone_mark(raw):
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,2}", raw.strip()))


def _split_label_value(raw):
    """标签串里内嵌的值拆出来（2026-09-04，35kV 图修复）。

    SolidWorks/CADDesigner 旧标题栏常把标签和值写在同一个 TEXT 里
    （如 '图号 35kV-DB-02'、'比例 1:100'），整串被判成标签后值就丢了，
    贪心配对只好拿邻近内容文本凑数。这里把首个概念别名剥掉，剩余部分
    作为值候选。无剩余返回 None。"""
    from .concepts import CONCEPT_ALIASES
    aliases = sorted({a for al in CONCEPT_ALIASES.values() for a in al},
                     key=len, reverse=True)
    rem = raw.strip()
    low = rem.lower()
    for a in aliases:
        idx = low.find(a)
        if idx >= 0:
            rem = rem[:idx] + rem[idx + len(a):]
            break
    rem = rem.strip(" ：:、.,=-_()")
    return rem or None


def _extract_from_text(doc, bbox):
    msp = doc.modelspace()
    items = []  # (norm_text, concept, raw, bb, is_field_label, is_struct_label)
    for e in msp:
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
        raw = _clean(raw)
        if not raw:
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        cx = (eb[0] + eb[2]) / 2
        cy = (eb[1] + eb[3]) / 2
        if not _in_bbox(bbox, cx, cy, pad=8.0):
            continue
        n = _norm(raw)
        concept = infer_concept(raw)
        is_field_label = concept is not None
        is_struct = (not is_field_label) and any(v in n for v in SW_TITLE_VOCAB)
        items.append((n, concept, raw, eb, is_field_label, is_struct))
        if is_field_label:
            # 标签内嵌值拆分（'图号 35kV-DB-02' → 值 '35kV-DB-02'）：
            # 与标签同 bbox 的伪值条目，供下方值类型预路由/贪心配对使用
            _sv = _split_label_value(raw)
            if _sv and not _is_zone_mark(_sv):
                items.append((n, None, _sv, eb, False, False))

    labels = [it for it in items if it[4]]
    values = [it for it in items if (not it[4]) and (not it[5]) and not _is_zone_mark(it[2])]

    # ---- 值类型预路由：高置信度的值直接归到对应概念，移出贪心池 ----
    # 避免比例/材料码/图号/重量/图名被贪心匹配误派给相邻标签。
    ratio_vals = [v for v in values if _is_ratio(v[2])]
    mat_vals = [v for v in values if _looks_material(v[2])]
    date_vals = [v for v in values if _is_date(v[2])]
    dwgno_vals = [v for v in values if _is_dwgno(v[2])]
    weight_vals = [v for v in values if _is_weight(v[2])]
    name_vals = [v for v in values if _looks_name(v[2])]

    # TITLE 候选：优先带引号者，其次更长者，其次更高（更靠上）者
    title_val = None
    if name_vals:
        def _name_key(v):
            t = v[2]
            quoted = bool(re.search(r'["“"'']', t))
            return (not quoted, -len(t), -v[3][3])
        title_val = sorted(name_vals, key=_name_key)[0]

    routed_ids = (set(id(v) for v in ratio_vals) |
                  set(id(v) for v in mat_vals) |
                  set(id(v) for v in date_vals) |
                  set(id(v) for v in dwgno_vals) |
                  set(id(v) for v in weight_vals) |
                  (set([id(title_val)]) if title_val else set()))
    pool = [v for v in values if id(v) not in routed_ids]

    # 已用高置信值占用的概念，禁止贪心再往里塞
    reserved = set()
    if ratio_vals:
        reserved.add("SCALE")
    if mat_vals:
        reserved.add("MATERIAL")
    if date_vals:
        reserved.add("DATE")
    if dwgno_vals:
        reserved.add("DWG_NO")
    if weight_vals:
        reserved.add("WEIGHT")

    def _score(lab, v):
        lx0, lx1, ly0, ly1 = lab[3]
        lcx, lcy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
        vx0, vx1, vy0, vy1 = v[3]
        vcx, vcy = (vx0 + vx1) / 2, (vy0 + vy1) / 2
        # 同行右侧优先
        if vcx >= lcx - 3 and abs(vcy - lcy) < 15:
            return (vcx - lcx) + abs(vcy - lcy) * 0.2
        # 同列下方次之（同列容差收紧，避免误吞邻列值）
        if vcy < lcy and abs(vcx - lcx) < 18:
            return (lcy - vcy) + abs(vcx - lcx) * 0.2 + 50.0
        return None

    pairs = []
    for vi, v in enumerate(pool):
        for li, lab in enumerate(labels):
            if labels[li][1] in reserved:
                continue
            s = _score(lab, v)
            if s is not None:
                pairs.append((s, vi, li))
    pairs.sort()
    used_v, used_l, out = set(), set(), {}
    for s, vi, li in pairs:
        if vi in used_v or li in used_l:
            continue
        used_v.add(vi)
        used_l.add(li)
        out[labels[li][1]] = pool[vi][2]

    # 预路由回填（高置信，覆盖贪心误派到相邻标签的值）
    if ratio_vals:
        out["SCALE"] = ratio_vals[0][2]
    if mat_vals:
        out["MATERIAL"] = mat_vals[0][2]
    if date_vals:
        out["DATE"] = date_vals[0][2]
    if dwgno_vals:
        out["DWG_NO"] = dwgno_vals[0][2]
    if weight_vals:
        out["WEIGHT"] = weight_vals[0][2]
    if title_val and "TITLE" not in out:
        out["TITLE"] = title_val[2]

    return out
