# -*- coding: utf-8 -*-
"""
旧版图框检测（针对 SolidWorks 导出打散图纸）：
  detect_frames(doc)        —— 用长直线/闭合多段线检测图纸外框矩形（外框+内框）。
  detect_titleblock(doc, frame) —— 用标题栏词表锚定右下角标题栏区域（紧凑，不吞主视图）。
返回供 run_real.py 使用。
"""
import re
from ezdxf import bbox as bbox_mod
from .concepts import SW_TITLE_VOCAB, FRAME_BLOCK_KEYWORDS, CONCEPT_ALIASES


def _norm(s):
    if not s:
        return ""
    s = re.sub(r"\\[A-Za-z]+\b[^\x00-\x1f]*", " ", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", "", s).lower()


def _is_closed(e):
    try:
        return bool(e.dxf.closed) or bool(e.dxf.flags & 1)
    except Exception:
        try:
            return bool(e.dxf.flags & 1)
        except Exception:
            return False


def _seg_edges(e):
    """返回实体轴对齐边 [(orient, coord, c0, c1)]，orient='v'/'h'。非轴对齐返回 []。"""
    dt = e.dxftype()
    out = []
    if dt == "LINE":
        p1, p2 = e.dxf.start, e.dxf.end
        if abs(p1.x - p2.x) < 1e-4 and abs(p1.y - p2.y) > 1e-4:
            out.append(("v", round(p1.x, 3), min(p1.y, p2.y), max(p1.y, p2.y)))
        elif abs(p1.y - p2.y) < 1e-4 and abs(p1.x - p2.x) > 1e-4:
            out.append(("h", round(p1.y, 3), min(p1.x, p2.x), max(p1.x, p2.x)))
    elif dt in ("LWPOLYLINE", "POLYLINE"):
        try:
            if dt == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points()]
            else:
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices()]
        except Exception:
            return out
        closed = _is_closed(e) or (pts and pts[0] == pts[-1])
        if not closed or len(pts) < 3:
            return out
        seq = pts + [pts[0]]
        for i in range(len(seq) - 1):
            x1, y1 = seq[i]
            x2, y2 = seq[i + 1]
            if abs(x1 - x2) < 1e-4 and abs(y1 - y2) > 1e-4:
                out.append(("v", round(x1, 3), min(y1, y2), max(y1, y2)))
            elif abs(y1 - y2) < 1e-4 and abs(x1 - x2) > 1e-4:
                out.append(("h", round(y1, 3), min(x1, x2), max(x1, x2)))
    return out


def detect_frames(doc):
    """检测图纸外框矩形列表 [(x0,y0,x1,y1), ...]（含外框和内框）。"""
    msp = doc.modelspace()
    segs = []
    for e in msp:
        segs.extend(_seg_edges(e))
    if not segs:
        return []
    ext = bbox_mod.extents(msp)
    sw = max(1e-6, ext.extmax.x - ext.extmin.x)
    sh = max(1e-6, ext.extmax.y - ext.extmin.y)
    thr = 0.5 * max(sw, sh)
    vseg = [(c, c0, c1) for (o, c, c0, c1) in segs if o == "v" and (c1 - c0) > thr]
    hseg = [(c, c0, c1) for (o, c, c0, c1) in segs if o == "h" and (c1 - c0) > thr]
    if not vseg or not hseg:
        return []
    xs = sorted(set(round(c, 1) for c, _, _ in vseg))
    ys = sorted(set(round(c, 1) for c, _, _ in hseg))
    vset = set(round(c, 1) for c, _, _ in vseg)
    hset = set(round(c, 1) for c, _, _ in hseg)
    rects = []
    m = min(len(xs) // 2, len(ys) // 2)
    for k in range(m):
        xL, xR = xs[k], xs[-(k + 1)]
        yB, yT = ys[k], ys[-(k + 1)]
        if xR - xL < 1 or yT - yB < 1:
            continue
        if (round(xL, 1) in vset and round(xR, 1) in vset and
                round(yB, 1) in hset and round(yT, 1) in hset):
            rects.append((xL, yB, xR, yT))
    return rects


def detect_titleblock(doc, outer):
    """用标题栏词表锚定右下角标题栏紧凑区域。outer=(x0,y0,x1,y1)。"""
    msp = doc.modelspace()
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    # 只在右下象限内收集锚点，避免把左侧“零件代号/主管设计”或中部注释误当作标题栏
    xmin_q = xL + 0.40 * W
    ymax_q = yB + 0.55 * H
    anchors = []
    for e in msp:
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = e.text if dt == "MTEXT" else e.dxf.text
        if not raw:
            continue
        n = _norm(raw)
        if not n:
            continue
        if any(v in n for v in SW_TITLE_VOCAB):
            try:
                b = bbox_mod.extents([e])
            except Exception:
                continue
            if not (b and b.has_data):
                continue
            cx = (b.extmin.x + b.extmax.x) / 2
            cy = (b.extmin.y + b.extmax.y) / 2
            if cx < xmin_q or cy > ymax_q:
                continue
            anchors.append((b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y))
    if not anchors:
        # 兜底：右下角 0.45W × 0.32H
        return (xR - 0.45 * W, yB, xR, yB + 0.32 * H)
    minx = min(a[0] for a in anchors)
    miny = min(a[1] for a in anchors)
    maxy = max(a[3] for a in anchors)
    # 标题栏贴右边框：右界直接取到外框右边
    left = max(minx, xR - 0.72 * W) - 2.0
    # 上界：扫描右下角区域内的所有文本，取最高一行的顶边（含图名行），避免截断图名
    top_scan = yB + 0.50 * H
    top_y = maxy
    for e in msp:
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = e.text if dt == "MTEXT" else e.dxf.text
        if raw and re.fullmatch(r"[A-Za-z0-9]{1,2}", raw.strip()):
            continue  # 跳过区号字母/数字，避免抬高上界
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not (b and b.has_data):
            continue
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        if left - 4 <= cx <= xR + 4 and yB - 4 <= cy <= top_scan:
            top_y = max(top_y, b.extmax.y)
    top_y = min(top_y, top_scan)
    # 小余量
    return (left, yB - 2.0, xR + 2.0, top_y + 4.0)


# ---------- 多图框逐框检测（案例七） ----------

def _rect_from_entity(e):
    """返回闭合矩形实体的轴对齐 bbox (x0,y0,x1,y1)；非闭合矩形返回 None。"""
    dt = e.dxftype()
    if dt not in ("LWPOLYLINE", "POLYLINE"):
        return None
    try:
        if dt == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
        else:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices()]
    except Exception:
        return None
    if not pts:
        return None
    closed = _is_closed(e) or (pts[0] == pts[-1])
    if not closed or len(pts) < 3:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def detect_frames_hierarchical(doc, min_side=80, min_area=5000):
    """检测所有闭合矩形图框，返回 (sheet_bbox_or_None, list_of_target_frame_bboxes)。

    规则：
    - 收集 modelspace 中所有闭合矩形（轴对齐、side>min_side、area>min_area）。
    - 若存在一个"整图纸框"（bbox 包含其它所有框，且面积明显更大），则它是 sheet（纸边），
      不作为替换目标；其余框为 target（需逐框插入公司图框）。
    - 若无单一整图纸框（如并排多框，互不包含），则所有框均为 target。
    - 若只有 1 个框，它就是 target（退化为单框替换，兼容旧行为）。
    """
    msp = doc.modelspace()
    rects = []
    for e in msp:
        r = _rect_from_entity(e)
        if not r:
            continue
        w = r[2] - r[0]
        h = r[3] - r[1]
        if w > min_side and h > min_side and w * h > min_area:
            rects.append(r)
    if not rects:
        return None, []
    if len(rects) == 1:
        return None, rects

    def contains(big, small, tol=2.0):
        return (big[0] <= small[0] + tol and big[1] <= small[1] + tol and
                big[2] >= small[2] - tol and big[3] >= small[3] - tol)

    sheet = None
    for cand in rects:
        others = [o for o in rects if o != cand]
        if all(contains(cand, o) for o in others):
            # 面积须明显大于其它框，避免平级并排互相误判为 sheet
            if all((cand[2] - cand[0]) * (cand[3] - cand[1]) >
                   (o[2] - o[0]) * (o[3] - o[1]) * 1.05 for o in others):
                sheet = cand
                break
    if sheet is not None:
        targets = [r for r in rects if r != sheet]
        return sheet, targets
    return None, rects


def extract_frame_fields(doc, frame_bbox, concepts=("TITLE", "DWG_NO", "SCALE", "STAGE")):
    """从单个图框 frame_bbox 的右下角标题区提取字段，返回 {concept: value}。

    标题区定义为：右 45% × 底 60%。命中 图名/图号/比例/阶段 等规范概念则按冒号后取值；
    若未抽到图名，用标题区内最长文本兜底为 TITLE。
    """
    fx0, fy0, fx1, fy1 = frame_bbox
    W = fx1 - fx0
    H = fy1 - fy0
    msp = doc.modelspace()
    items = []  # (cx, cy, raw)
    for e in msp:
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = e.text if dt == "MTEXT" else e.dxf.text
        if not raw:
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not (b and b.has_data):
            continue
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        # 限定标题区：右 45% 且 底 60%，且必须落在「当前图框」内。
        # 注意四向都要约束：否则多图框（尤其 2×2 拼贴）时，相邻框的标题文字
        # 会落入本框"标题区"（原实现只约束 cx 左界/cy 上界，区域向右下无限延伸）。
        if not (fx0 + 0.45 * W <= cx <= fx1 and fy0 <= cy <= fy0 + 0.60 * H):
            continue
        items.append((cx, cy, raw.strip()))
    fields = {}
    for concept in concepts:
        aliases = CONCEPT_ALIASES.get(concept, [concept.lower()])
        matched = False
        for al in aliases:
            if not al:
                continue
            # 1) 合并实体：如 "图名：减速器箱体"
            for cx, cy, raw in items:
                n = _norm(raw)
                if al in n and (":" in raw or "：" in raw):
                    val = re.split(r"[:：]", raw, maxsplit=1)[-1].strip()
                    if val:
                        fields[concept] = val
                        matched = True
                        break
            if matched:
                break
            # 2) 标签实体 + 同行右侧的值实体（标签与值分两个 TEXT）
            for cx, cy, raw in items:
                if _norm(raw) == al:
                    best_val = None
                    best_dx = 1e9
                    for cx2, cy2, raw2 in items:
                        if raw2 == raw:
                            continue
                        if abs(cy2 - cy) < 4 and cx2 > cx:
                            dx = cx2 - cx
                            if dx < best_dx:
                                best_dx = dx
                                best_val = raw2
                    if best_val:
                        fields[concept] = best_val
                        matched = True
                        break
            if matched:
                break
    if "TITLE" not in fields:
        cand = [raw for cx, cy, raw in items if len(raw) >= 3]
        if cand:
            cand.sort(key=lambda t: -len(t))
            fields["TITLE"] = cand[0]
    return fields


# ---------- 兼容旧接口（run_skill.py 演示用） ----------

def _bbox_of(e):
    try:
        ext = bbox_mod.extents([e])
        if ext and ext.has_data:
            return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    except Exception:
        pass
    return None


def find_titleblocks(doc, margin_ratio=0.02):
    """旧接口：返回 region 列表（仅用于演示/块模板场景）。"""
    msp = doc.modelspace()
    regions = []
    for e in msp:
        if e.dxftype() != "INSERT":
            continue
        bname = e.dxf.name
        bb = _bbox_of(e)
        if not bb:
            continue
        score = sum(1 for kw in FRAME_BLOCK_KEYWORDS if kw in (bname or "").lower())
        try:
            blk = doc.blocks[bname]
            for ent in blk:
                if ent.dxftype() == "ATTDEF":
                    txt = (ent.dxf.prompt or ent.dxf.tag or "")
                    if any(k in txt for k in SW_TITLE_VOCAB):
                        score += 2
                        break
        except Exception:
            pass
        if score > 0:
            regions.append({"bbox": bb, "confidence": min(0.99, 0.7 + 0.1 * score),
                            "method": "block", "source": bname, "entity": e})
    return regions
