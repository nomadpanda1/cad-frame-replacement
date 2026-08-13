# -*- coding: utf-8 -*-
"""
旧版图框检测（针对 SolidWorks 导出打散图纸）：
  detect_frames(doc)        —— 用长直线/闭合多段线检测图纸外框矩形（外框+内框）。
  detect_titleblock(doc, frame) —— 用标题栏词表锚定右下角标题栏区域（紧凑，不吞主视图）。
返回供 run_real.py 使用。
"""
import bisect
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


def _merge_ivs(intervals, bridge=0.0):
    """合并重叠/相邻（间隙 <= bridge）的区间，返回 [(a, b), ...]。"""
    out = []
    cur = None
    for a, b in sorted(intervals):
        if cur is None:
            cur = [a, b]
        elif a <= cur[1] + bridge:
            if b > cur[1]:
                cur[1] = b
        else:
            out.append((cur[0], cur[1]))
            cur = [a, b]
    if cur:
        out.append((cur[0], cur[1]))
    return out


def _union_span(intervals):
    """合并重叠区间，返回总覆盖长度（用于按坐标聚合线段覆盖度）。"""
    return sum(b - a for a, b in _merge_ivs(intervals))


def _axis_edges(segs, orient, coord_tol, bridge, min_len, limit=900):
    """把同方向线段重建成「整条边」：同坐标聚簇 + 区间合并。

    返回 [(coord, lo, hi), ...]（按 coord 升序），只保留长度 >= min_len 的边。
    国标图框常把边框拆成多段短直线，合并后才能还原成一条完整边。
    """
    buckets = {}
    for (o, c, c0, c1) in segs:
        if o != orient:
            continue
        buckets.setdefault(c, []).append((c0, c1))
    edges = []

    def flush(cl):
        if not cl:
            return
        ivs = []
        for c in cl:
            ivs.extend(buckets[c])
        cc = sum(cl) / len(cl)
        for a, b in _merge_ivs(ivs, bridge):
            if b - a >= min_len:
                edges.append((cc, a, b))

    cluster = []
    for c in sorted(buckets):
        # 只在「簇总宽度 <= coord_tol」时并入，避免密集平行线连成一大簇
        if cluster and c - cluster[0] <= coord_tol:
            cluster.append(c)
        else:
            flush(cluster)
            cluster = [c]
    flush(cluster)
    if len(edges) > limit:      # 极端复杂图纸下限制装配规模，保留最长的边
        edges.sort(key=lambda e: -(e[2] - e[1]))
        edges = edges[:limit]
    edges.sort()
    return edges


def _covers(edges, coords, coord, lo, hi, coord_tol, slack):
    """edges 中是否存在坐标≈coord、且区间覆盖 [lo, hi] 的边。"""
    i = bisect.bisect_left(coords, coord - coord_tol)
    while i < len(edges) and edges[i][0] <= coord + coord_tol:
        _, a, b = edges[i]
        if a <= lo + slack and b >= hi - slack:
            return True
        i += 1
    return False


def _assemble_rects(vedges, hedges, coord_tol, min_side, rel_tol=0.01):
    """由边线装配矩形：两条**共端点**竖边 + 两端各有一条跨越它们的横边。

    关键在「共端点」约束（两竖边的上下端点必须近似相同）——图框是闭合矩形，
    四条边首尾相接；而图内的长表格线、墙线虽然也很长，却极少与另一条竖线
    端点严格对齐、且两端都有横边贯通，因此天然被排除。
    """
    hcoords = [e[0] for e in hedges]
    out = []
    n = len(vedges)
    for i in range(n):
        xi, yi0, yi1 = vedges[i]
        for j in range(i + 1, n):
            xj, yj0, yj1 = vedges[j]
            w = xj - xi
            if w < min_side:
                continue
            h = min(yi1, yj1) - max(yi0, yj0)
            if h < min_side:
                continue
            vtol = max(coord_tol, rel_tol * h)
            if abs(yi0 - yj0) > vtol or abs(yi1 - yj1) > vtol:
                continue
            yB = (yi0 + yj0) / 2.0
            yT = (yi1 + yj1) / 2.0
            slack = max(coord_tol, rel_tol * w)
            htol = max(coord_tol, rel_tol * (yT - yB))
            if not _covers(hedges, hcoords, yB, xi, xj, htol, slack):
                continue
            if not _covers(hedges, hcoords, yT, xi, xj, htol, slack):
                continue
            out.append((xi, yB, xj, yT))
    return out


def _bbox_overlap(a, b, tol=0.0):
    """两 bbox 是否有实质重叠（仅贴边不算）。"""
    return (a[0] < b[2] - tol and b[0] < a[2] - tol and
            a[1] < b[3] - tol and b[1] < a[3] - tol)


def detect_frame_groups(doc, min_area_share=0.35, dedup_ratio=0.8,
                        split_cover=0.6, min_drawing_share=0.02):
    """线框图纸（打散图框，无 INSERT 块）的图框检测。

    返回 (sheet_bbox_or_None, groups)，groups = [{"outer": rect, "inner": [rect...]}]，
    按面积降序。inner 是同一个图框的内层框线（双线边框），不是独立替换目标。

    为什么不再用「按坐标取极值」
    ----------------------------
    原实现把「覆盖度 >= 0.6×图幅」的 x/y 坐标全收上来，然后取 xs[0]/xs[-1]、
    ys[0]/ys[-1] 当外框四边。实测案例十的「首二层商场平面」里，图内的配电箱
    系统表有多条横线宽达 84000（> 0.6×118800），于是最底下那条表格线被当成
    图框底边，检出框变成 118800×99782（真框是 118800×84000），下游按这个错
    比例插框 → 内容溢出/图框悬空。「首层配电干线平面图」同理（错成 118800×124702）。

    现改为矩形装配：先把线段还原成整条边，再要求「两竖边共端点 + 两端横边贯通」
    才算一个矩形，长表格线因端点不对齐而被排除；随后按包含关系分层（双线内框
    归到 inner、拼版纸边识别为 sheet），并做面积占比 + 互不重叠筛选。
    """
    msp = doc.modelspace()
    segs = []
    for e in msp:
        segs.extend(_seg_edges(e))
    if not segs:
        return None, []
    try:
        ext = bbox_mod.extents(msp)
    except Exception:
        return None, []
    sw = max(1e-6, ext.extmax.x - ext.extmin.x)
    sh = max(1e-6, ext.extmax.y - ext.extmin.y)
    maxdim = max(sw, sh)
    coord_tol = max(0.5, 5e-4 * maxdim)
    bridge = max(1.0, 2e-3 * maxdim)
    min_side = max(20.0, 0.02 * maxdim)

    vedges = _axis_edges(segs, "v", coord_tol, bridge, min_side)
    hedges = _axis_edges(segs, "h", coord_tol, bridge, min_side)
    rects = _assemble_rects(vedges, hedges, coord_tol, min_side)
    if not rects:
        return None, []

    # 同一矩形可能被多组边线重复装配，按坐标量化去重
    uniq = {}
    for r in rects:
        key = tuple(round(v / coord_tol) for v in r)
        if key not in uniq or _bbox_area(r) > _bbox_area(uniq[key]):
            uniq[key] = r
    rects = sorted(uniq.values(), key=lambda r: -_bbox_area(r))

    def children_of(r):
        return [c for c in rects
                if c is not r and _bbox_contains(r, c, coord_tol) and
                _bbox_area(c) < dedup_ratio * _bbox_area(r)]

    def tops_of(pool):
        out = []
        for r in pool:
            if any(o is not r and _bbox_area(o) > _bbox_area(r) * 1.0001 and
                   _bbox_contains(o, r, coord_tol) for o in pool):
                continue
            out.append(r)
        return out

    tops = tops_of(rects)

    # 拼版纸边：最外框内含 >=2 个互不重叠的子框且合计占其大半，则它是纸边，
    # 真正的替换目标是子框（对应 detect_frames_hierarchical 的 sheet 概念）。
    sheet = None
    if len(tops) == 1:
        kids = children_of(tops[0])
        sel = []
        for c in sorted(kids, key=lambda x: -_bbox_area(x)):
            if all(not _bbox_overlap(c, s, coord_tol) for s in sel):
                sel.append(c)
        if len(sel) >= 2 and \
                sum(_bbox_area(c) for c in sel) >= split_cover * _bbox_area(tops[0]):
            sheet = tops[0]
            rects = [r for r in rects if r is not sheet]
            tops = tops_of(rects)

    if len(tops) > 1:
        max_area = max(_bbox_area(r) for r in tops)
        # 并排多框的图幅普遍同规格，占比过小的是图内表格/图例，不是图框
        tops = [r for r in tops if _bbox_area(r) >= min_area_share * max_area]
        kept = []
        for r in sorted(tops, key=lambda x: -_bbox_area(x)):
            if any(_bbox_overlap(r, k, coord_tol) for k in kept):
                continue
            kept.append(r)
        tops = kept

    # 全局占比护栏：真实图框应占整图 min_drawing_share 以上；占比过小（如控制原理图里
    # 满屏继电器/接触器小方框，单个仅占整图 ~1%）的闭合矩形极可能是元件轮廓，应剔除，
    # 避免误插公司框破坏原图。仅在出现多个候选框时启用——单框图纸保持旧行为（1 框即 1 目标），
    # 不误杀小图幅里那唯一一个大框。参见 detect_frames_hierarchical 的同名护栏。
    if min_drawing_share and min_drawing_share > 0 and len(tops) > 1:
        try:
            dext = bbox_mod.extents(msp)
            drawing_area = float((dext.extmax.x - dext.extmin.x) *
                                 (dext.extmax.y - dext.extmin.y))
        except Exception:
            drawing_area = 1e-9
        if drawing_area > 0 and drawing_area != float("inf"):
            kept_g = [r for r in tops if _bbox_area(r) >= min_drawing_share * drawing_area]
            if kept_g:
                tops = kept_g
            else:
                # 没有任何框占整图 min_drawing_share 以上 → 视为无有效图框
                # （给煤机控制原理图即此情形：全图无 A 幅面边框）
                return None, []

    tops.sort(key=lambda r: -_bbox_area(r))
    groups = []
    for t in tops:
        inner = [r for r in rects
                 if r is not t and _bbox_contains(t, r, coord_tol) and
                 _bbox_area(r) >= dedup_ratio * _bbox_area(t)]
        groups.append({"outer": t, "inner": inner})
    return sheet, groups


def detect_frames(doc):
    """检测图纸外框矩形列表 [(x0,y0,x1,y1), ...]（含外框和内框）。

    兼容旧接口：把 detect_frame_groups 的结果摊平，每个图框先外框后内框；
    下游取面积最大者即最外框。多图框图纸请直接用 detect_frame_groups。
    """
    out = []
    for g in detect_frame_groups(doc)[1]:
        out.append(g["outer"])
        out.extend(g["inner"])
    return out


def _expand_tb_by_grid(doc, tb, outer, max_left_span=200.0, max_top_span=70.0):
    """根据右下角实际网格线扩展标题栏 bbox。

    文本锚点检测有时会低估标题栏宽度（例如 SW 机械小图的标题栏文字集中在右侧，
    左侧格子线没有文字），导致旧标题栏残线留在新框里。此函数扫描右下固定区域
    （右缘向内 200mm、下缘向上 70mm）内的长竖线/长横线，把 tb 扩展到真实网格边界。
    """
    xL, yB, xR, yT = outer
    x0, y0, x1, y1 = tb
    tb_h = max(1.0, y1 - y0)
    min_v_span = 0.55 * tb_h
    leftmost_x = xR - max_left_span
    topmost_y = yB + max_top_span

    v_lines = []
    h_lines = []
    for e in doc.modelspace().query("LINE LWPOLYLINE POLYLINE"):
        pts = []
        dt = e.dxftype()
        if dt == "LINE":
            pts = [(e.dxf.start[0], e.dxf.start[1]),
                   (e.dxf.end[0], e.dxf.end[1])]
        elif dt == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        else:
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        # 长竖线：标题栏左边界
        if (bx1 - bx0) <= 0.5 and (by1 - by0) >= min_v_span:
            if leftmost_x - 1 <= bx0 <= xR + 2 and by0 <= y1 + 2 and by1 >= y0 - 2:
                v_lines.append(bx0)
        # 长横线：标题栏上边界（或内部主横线）
        if (by1 - by0) <= 0.5 and (bx1 - bx0) >= 30.0:
            if yB - 2 <= by0 <= topmost_y and bx0 <= xR + 2 and bx1 >= x0 - 2:
                h_lines.append(by0)
    if v_lines:
        x0 = min(x0, min(v_lines) - 1.0)
    if h_lines:
        y1 = max(y1, max(h_lines) + 1.0)
    return (x0, y0, x1, y1)


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
        # 兜底：右下角 0.45W × 0.32H，再按网格线扩展
        tb = (xR - 0.45 * W, yB, xR, yB + 0.32 * H)
        return _expand_tb_by_grid(doc, tb, outer)
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
    tb = (left, yB - 2.0, xR + 2.0, top_y + 4.0)
    # 再按实际网格线扩展，防止文字偏右导致左侧格子线漏删
    return _expand_tb_by_grid(doc, tb, outer)


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


def _bbox_area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def _bbox_contains(big, small, tol=2.0):
    return (big[0] <= small[0] + tol and big[1] <= small[1] + tol and
            big[2] >= small[2] - tol and big[3] >= small[3] - tol)


def dedup_double_border(frames, dedup_ratio=0.8):
    """合并"外框 + 内框"双线图框，只保留外框。

    工程图框普遍画成两条矩形：外面一圈纸边、里面一圈图框线（如 CNG 图 84100×59400
    外框套 80600×57400 内框，面积比 0.93）。二者是同一个图框，不该当成两个替换目标。
    按面积从大到小遍历，若已保留的外框 A 包含当前框 B 且 area(B)/area(A) >= dedup_ratio，
    则判定 B 是 A 的内框线，丢弃。完全重合的重复矩形也会被这条规则吃掉。
    返回结果保持 frames 中的原始出现顺序。
    """
    order = {id(r): i for i, r in enumerate(frames)}
    kept = []
    for r in sorted(frames, key=lambda x: -_bbox_area(x)):
        area = _bbox_area(r)
        if any(_bbox_contains(k, r) and area >= _bbox_area(k) * dedup_ratio
               for k in kept):
            continue
        kept.append(r)
    kept.sort(key=lambda r: order[id(r)])
    return kept


def detect_frames_hierarchical(doc, min_side=80, min_area=5000,
                               min_area_share=0.15, dedup_ratio=0.8,
                               min_drawing_share=0.02):
    """检测所有闭合矩形图框，返回 (sheet_bbox_or_None, list_of_target_frame_bboxes)。

    规则：
    - 收集 modelspace 中所有闭合矩形（轴对齐、side>min_side、area>min_area）。
    - 若存在一个"整图纸框"（bbox 包含其它所有框，且面积明显更大），则它是 sheet（纸边），
      不作为替换目标；其余框为 target（需逐框插入公司图框）。
    - 若无单一整图纸框（如并排多框，互不包含），则所有框均为 target。
    - 目标框再过两道合理性筛（多框时才启用，单框保持旧行为）：
      1) 面积占比：面积不足最大目标框 min_area_share 的剔除。电气图里大量端子/符号/
         表格单元都是闭合矩形，CNG 图曾因此检出 61 个"图框"，其中 53 个占比仅 0.003。
      2) 双线去重：见 dedup_double_border。
      注意不能用"长宽比接近 √2"来筛——加长图幅在电气图里很常见（CNG 左侧三个图框
      长宽比就是 2.00），按标准图幅比例过滤会把真图框误杀。
    - 过滤后若为空，回退到未过滤结果，保证不会"什么都检测不到"。
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

    sheet = None
    for cand in rects:
        others = [o for o in rects if o != cand]
        if all(_bbox_contains(cand, o) for o in others):
            # 面积须明显大于其它框，避免平级并排互相误判为 sheet
            if all(_bbox_area(cand) > _bbox_area(o) * 1.05 for o in others):
                sheet = cand
                break

    targets = [r for r in rects if r is not sheet] if sheet is not None else list(rects)
    raw = list(targets)

    if len(targets) > 1:
        max_area = max(_bbox_area(r) for r in targets)
        if max_area > 0:
            targets = [r for r in targets
                       if _bbox_area(r) >= max_area * min_area_share]
        targets = dedup_double_border(targets, dedup_ratio=dedup_ratio)

    # 全局占比护栏：真实图框应占整图 min_drawing_share 以上；占比过小的闭合矩形
    # 极可能是元件/符号方框（如控制原理图里大量继电器、接触器轮廓），应剔除。
    # 给煤机控制原理图即此情形：全图无 A 幅面边框、检出 15 个方框（单个仅占整图
    # ~1%），经此过滤全部剔除后判定为「无有效图框」，交回上层走线框检测或
    # 「未检测到图框」，避免误插公司框破坏原图。该护栏仅对「多个候选框」生效，
    # 单框（len==1）保持旧行为。
    global_filtered = False
    if len(targets) > 1:
        try:
            ext = bbox_mod.extents(msp)
            drawing_area = max(1e-9, (ext.extmax.x - ext.extmin.x) *
                               (ext.extmax.y - ext.extmin.y))
        except Exception:
            drawing_area = 1e-9
        kept = [r for r in targets if _bbox_area(r) >= min_drawing_share * drawing_area]
        if kept:
            targets = kept
        else:
            targets = []
            global_filtered = True

    if not targets and not global_filtered:
        targets = raw
    return sheet, targets


# ---------- 字段提取（打散图框）：标题名 + 裸比例 ----------
_TITLE_KW = ("系统图", "平面图", "布置图", "接线图", "配置图", "原理图", "干线图",
             "大样图", "详图", "示意图", "平面", "系统", "干线", "配电", "图")
_TITLE_FULL = ("系统图", "平面图", "布置图", "接线图", "配置图", "原理图", "干线图",
               "大样图", "详图", "示意图")
_RATIO_RE = re.compile(r"^\d+\s*[:：xX×]\s*\d+$")


def _collect_items(doc, box):
    """收集 box 内 TEXT/MTEXT 实体：(cx, cy, raw, height)。"""
    x0, y0, x1, y1 = box
    out = []
    for e in doc.modelspace():
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
        if x0 - 5 <= cx <= x1 + 5 and y0 - 5 <= cy <= y1 + 5:
            h = float(getattr(e.dxf, "height", 0) or 0)
            out.append((cx, cy, raw.strip(), h))
    return out


def _is_note(raw):
    """判断是否为注记/说明文本（不应作为图名）。"""
    s = (raw or "").strip()
    if not s:
        return True
    if s.startswith(("注", "说明")):
        return True
    if re.match(r"^\d+[、.．]", s):
        return True
    if "同B1" in s or "同B2" in s or ("同" in s and "栋" in s):
        return True
    return False


def _pick_title(items):
    """从文本项里挑出最可能的图名：含图名关键词、非注记。
    排序：① 完整图类名（系统图/平面图/…）加权 +100；② 字高最大（标题名单元格通常
    字高最大）；③ 同分取标题栏最上方（cy 最大）。
    """
    cands = []
    for cx, cy, raw, h in items:
        if _is_note(raw):
            continue
        if not any(k in raw for k in _TITLE_KW):
            continue
        if raw.startswith(("接", "由", "详见", "做法")):
            continue
        full = any(k in raw for k in _TITLE_FULL)
        cands.append((h + (100.0 if full else 0.0), cy, raw))
    if not cands:
        return None
    cands.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return cands[0][2]


def _pick_scale(items):
    """从文本项里挑比例：优先最常见值，同频按标准比例优先级。"""
    std = ["1:100", "1:50", "1:150", "1:200", "1:250", "1:20",
           "1:500", "1:1000", "1:2", "1:5", "1:10"]
    ratios = [raw.strip() for cx, cy, raw, h in items if _RATIO_RE.match(raw.strip())]
    if not ratios:
        return None
    cnt = {}
    for r in ratios:
        cnt[r] = cnt.get(r, 0) + 1
    def _idx(r):
        return std.index(r) if r in std else len(std)
    order = sorted(cnt.items(), key=lambda kv: (-kv[1], _idx(kv[0])))
    return order[0][0]


def _title_from_label(items):
    """标题栏内有「图名：xxx」合并标签，或「图名」标签+同行右侧值，则返回其值。"""
    for cx, cy, raw, h in items:
        n = _norm(raw)
        for al in CONCEPT_ALIASES.get("TITLE", []):
            if not al:
                continue
            if al in n and (":" in raw or "：" in raw):
                val = re.split(r"[:：]", raw, maxsplit=1)[-1].strip()
                if val:
                    return val
    for cx, cy, raw, h in items:
        if _norm(raw) in [a for a in CONCEPT_ALIASES.get("TITLE", []) if a]:
            best = None
            best_dx = 1e9
            for cx2, cy2, raw2, h2 in items:
                if raw2 == raw:
                    continue
                if abs(cy2 - cy) < 6 and cx2 > cx:
                    dx = cx2 - cx
                    if dx < best_dx:
                        best_dx = dx
                        best = raw2
            if best:
                return best
    return None


def _longest_in_region(doc, fx0, fy0, fx1, fy1):
    """兼容旧行为：右45%×底60% 区域内最长（≥2字、非注记）文本兜底为 TITLE。"""
    W = max(1e-6, fx1 - fx0)
    H = max(1e-6, fy1 - fy0)
    cand = []
    for e in doc.modelspace():
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
        if fx0 + 0.45 * W <= cx <= fx1 and fy0 <= cy <= fy0 + 0.60 * H:
            t = raw.strip()
            if len(t) >= 2 and not _is_note(t):
                cand.append(t)
    if cand:
        cand.sort(key=lambda t: -len(t))
        return cand[0]
    return None


def extract_frame_fields(doc, frame_bbox, concepts=("TITLE", "DWG_NO", "SCALE", "STAGE", "DATE", "DESIGN")):
    """从单个图框 frame_bbox 的右下角标题栏提取字段，返回 {concept: value}。

    打散图框（无块式标题栏）的字段提取质量关键点：
      - TITLE 解析顺序：①「图名：xxx」标签值；② 标题栏框内含图名关键词(平面/系统图/…)
        且非注记(注：/同B1栋/2、…)的文本，按 字高(+完整图类名) 取最大者（标题名单元格
        通常字高最大）；③ 标题栏框未命中时回退整图右35%；④ 最后兜底旧行为（右45%×底60%
        最长非注记文本）。②③④对案例十这类「标题是自由文本、注记更长」的图至关重要，避免
        把注记/电缆型号/房间号误当图名。
      - SCALE：优先「比例：」标签值；否则取标题栏框内裸比例文本（1:100），最常见/标准值优先；
        框外疑似视图比例不纳入，避免错填。
      - DWG_NO/STAGE/DATE/DESIGN：标题栏框内标签+值匹配；无对应文本则留空。
    """
    fx0, fy0, fx1, fy1 = frame_bbox
    W = max(1e-6, fx1 - fx0)
    H = max(1e-6, fy1 - fy0)
    tb = detect_titleblock(doc, frame_bbox)
    items_tb = _collect_items(doc, tb)
    fields = {}
    # 1) 标签+值概念（DWG_NO/STAGE/DATE/DESIGN/SCALE）
    for concept in concepts:
        if concept == "TITLE":
            continue
        aliases = CONCEPT_ALIASES.get(concept, [concept.lower()])
        found = None
        for al in aliases:
            if not al:
                continue
            for cx, cy, raw, h in items_tb:
                if al in _norm(raw) and (":" in raw or "：" in raw):
                    val = re.split(r"[:：]", raw, maxsplit=1)[-1].strip()
                    if val:
                        found = val
                        break
            if found:
                break
            for cx, cy, raw, h in items_tb:
                if _norm(raw) == al:
                    best_val = None
                    best_dx = 1e9
                    for cx2, cy2, raw2, h2 in items_tb:
                        if raw2 == raw:
                            continue
                        if abs(cy2 - cy) < 6 and cx2 > cx:
                            dx = cx2 - cx
                            if dx < best_dx:
                                best_dx = dx
                                best_val = raw2
                    if best_val:
                        found = best_val
                        break
            if found:
                break
        if found:
            fields[concept] = found
    # 2) SCALE 裸比例文本兜底（标签未命中时）
    if "SCALE" not in fields:
        sc = _pick_scale(items_tb)
        if sc:
            fields["SCALE"] = sc
    # 3) TITLE
    title = _title_from_label(items_tb)
    if not title:
        title = _pick_title(items_tb)
    if not title:
        try:
            dext = bbox_mod.extents(doc.modelspace())
            ex = (dext.extmin.x, dext.extmin.y, dext.extmax.x, dext.extmax.y)
        except Exception:
            ex = (fx0, fy0, fx1, fy1)
        fw = max(1e-6, ex[2] - ex[0])
        fb2 = (ex[2] - 0.35 * fw, ex[1], ex[2], ex[3])
        title = _pick_title(_collect_items(doc, fb2))
    if not title:
        title = _longest_in_region(doc, fx0, fy0, fx1, fy1)
    if title:
        fields["TITLE"] = title
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
