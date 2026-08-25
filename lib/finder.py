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
from .text_decode import decode_mtext


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
                        split_cover=0.5, min_drawing_share=0.02):
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
    """用标题栏词表锚定右下角标题栏紧凑区域。outer=(x0,y0,x1,y1)。

    2026-08-24 fix (#3 过度删 治本)：
      - 兜底（无 anchor）时 tb 默认 0.45W×0.32H 在「无标题栏标签词」建筑/电气图里会
        圈进 1-1 剖面图、右侧墙/窗/线（实测 强电平面.dxf tb/outer=14.4% → delete_titleblock_grid
        误删 238 实体）。收紧到 0.30W×0.18H（约 5.4%）。
      - 终态 tb 宽度再加硬上限 0.32W：任何情况下 tb 都不会吞进图幅右 1/3 以外的内容。
    """
    msp = doc.modelspace()
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    # 只在右下象限内收集锚点，避免把左侧“零件代号/主管设计”或中部注释误当作标题栏
    xmin_q = xL + 0.40 * W
    ymax_q = yB + 0.55 * H
    anchors = []
    # Track anchor provenance: "vocab" 路径用 SW_TITLE_VOCAB 命中，强信号；
    # "layer" 路径只按层名兜底（强电平面 TK 层「注:B1栋…」典型例），弱信号。
    anchor_source = "vocab"
    for e in msp:
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
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
        # Anchor 2（#5 增强）：标题层（TK/图框/frame/border/…）上的文本，
        # 即使不含 图名/图号/比例 等标签词，也作为标题栏锚点。
        # 强电平面.dxf 等住宅电气图的旧标题栏只有「注:B1栋标准层...」这种
        # TITLE 值文本，落在 TK 层，不在 SW_TITLE_VOCAB 里。命中后用文本
        # 真实 bbox 做 tb 边界，比 fallback 百分比准确得多。
        #
        # ⚠️ layer 路径信号弱，必须限制高度 cap（不超 0.30H ≈ 旧白框高度），
        # 防止把 tb 上方「主卧室 / 卧室 / 1:100 / 强电设计说明」等真实内容圈进
        # tb 后被 delete_titleblock_text 误删（无白名单保护）。同时跳过下方
        # anchor 路径的 top_scan 向上扩展——layer 锚点只有「标题栏文本位置」
        # 的弱信号，不足以推断上边界。
        anchor_source = "layer"
        _TITLE_LAYER_ANCHOR = {
            "tukuang", "图框", "pub_title", "图签", "tk", "title",
            "frame", "border", "borders", "边框", "titleblock",
            "图框线", "图框层", "0",  # 0 层也兜底：部分图把标题文本画在 0
        }
        for e in msp:
            dt = e.dxftype()
            if dt not in ("TEXT", "MTEXT"):
                continue
            layer_norm = (e.dxf.layer or "").strip().lower()
            if layer_norm not in _TITLE_LAYER_ANCHOR:
                continue
            raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
            if not raw:
                continue
            n = _norm(raw)
            if not n:
                continue
            # 跳过 0 层上明显是「普通文字」的内容（短句、含中文长尾）
            if layer_norm == "0" and len(n) < 6:
                continue
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
        # 兜底：右下角 0.30W × 0.18H（≈5.4% of outer），再按网格线扩展。
        # 旧值 0.45×0.32 = 14.4% 在 强电平面/裙楼消防/消防弱电2 等无 anchor 图上
        # 把 1-1 剖面/设备材料表/右侧墙/窗/线全部圈进 tb，被 delete_titleblock_grid
        # 误删（用户反馈「修改后多删了一些元素」）。
        tb = (xR - 0.30 * W, yB, xR, yB + 0.18 * H)
        tb = _expand_tb_by_grid(doc, tb, outer)
        # 兜底硬上限：宽度不超过 0.32W（标准标题栏宽不超过图幅 1/3）。
        # 注意：只对无 anchor 的兜底路径生效；anchor 路径下 minx 已限定 tb 左界，
        # 再加 cap 会误伤小图（如 200×100 测例，标题栏文字在 x=100 会跑出 tb）。
        if (tb[2] - tb[0]) > 0.32 * W:
            tb = (tb[2] - 0.32 * W, tb[1], tb[2], tb[3])
        return tb
    minx = min(a[0] for a in anchors)
    miny = min(a[1] for a in anchors)
    maxy = max(a[3] for a in anchors)
    # 标题栏贴右边框：右界直接取到外框右边
    left = max(minx, xR - 0.72 * W) - 2.0
    if anchor_source == "vocab":
        # vocab 路径信号强：扫描右下角区域内的所有文本，取最高一行的顶边（含图名行），
        # 避免截断图名（图名行可能在锚点上方）。
        top_scan = yB + 0.50 * H
        top_y = maxy
        for e in msp:
            dt = e.dxftype()
            if dt not in ("TEXT", "MTEXT"):
                continue
            raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
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
    else:
        # layer 路径信号弱：禁用 top_scan（避免把上方「主卧室 / 1:100 / 强电设计说明」
        # 等真实内容圈进 tb 被 delete_titleblock_text 误删）。只取 anchor 自身 bbox 顶边
        # + 网格扩展，并加 0.30H 高度硬封顶（标准旧白框不会超过 0.30H）。
        tb = (left, yB - 2.0, xR + 2.0, maxy + 4.0)
    # 再按实际网格线扩展，防止文字偏右导致左侧格子线漏删
    tb = _expand_tb_by_grid(doc, tb, outer)
    # layer 路径加 0.30H 高度 cap（vocab 路径不加，避免误伤含图名行的小图）
    if anchor_source == "layer":
        max_top = yB + 0.30 * H
        if tb[3] > max_top:
            tb = (tb[0], tb[1], tb[2], max_top)
    # 注意：anchor 路径不加 0.32W 宽度 cap（见上方兜底分支注释）。
    return tb


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
        raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
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
        # 标签单元格（描图/设计/校对…）绝不当图名候选（92DZ1 帧3/4 曾把「描 图」当 TITLE）
        if _is_pure_label(raw):
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
        raw = decode_mtext(e.text if dt == "MTEXT" else e.dxf.text)
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
            if len(t) >= 2 and not _is_note(t) and not _is_pure_label(t):
                cand.append(t)
    if cand:
        cand.sort(key=lambda t: -len(t))
        return cand[0]
    return None


# 标题栏「字段名标签」归一集合：概念别名 + SW 标题栏词表。
# 用于抽取时禁止把列标题本身（标准化 / 阶段标记 / 比例…）当作字段值。
_LABEL_NORM_SET = set()
for _al in CONCEPT_ALIASES.values():
    for _a in _al:
        if _a:
            _LABEL_NORM_SET.add(_norm(_a))
for _v in SW_TITLE_VOCAB:
    _LABEL_NORM_SET.add(_norm(_v))


def _is_pure_label(raw):
    """文本本身是否就是标题栏字段标签（列头），不应作为字段值。"""
    return _norm(raw) in _LABEL_NORM_SET


_QUOTE_CHARS = ['"', "'", "“", "”", "‘", "’", "「", "」", "『", "』"]


def _strip_surrounding_quotes(s):
    """去掉文本首尾成对的中文/英文引号（SW 常把零件名用弯引号括住）。"""
    s = (s or "").strip()
    if len(s) >= 2 and s[0] in _QUOTE_CHARS and s[-1] in _QUOTE_CHARS:
        return s[1:-1].strip()
    return s


def _nearest_ratio_to_label(items, label_norm):
    """在标题栏文本里找最靠近指定标签的比例文本（如 1:100 / 2:1）。

    SolidWorks 图框的「比例」标签与其值常不在同一单元格、且可能隔行，
    用「标签附近的比例文本」定位比「同行右侧最近文本」可靠得多——
    否则会误把紧邻的图名/其它文本抓成比例（案例：比例标签抓到“从动轮法兰”）。
    """
    lab = None
    for cx, cy, raw, h in items:
        n = _norm(raw)
        if n == label_norm or (label_norm in n and len(n) <= len(label_norm) + 3):
            lab = (cx, cy)
            break
    if lab is None:
        return None
    best = None
    best_d = 1e18
    for cx, cy, raw, h in items:
        if _RATIO_RE.match(raw.strip()):
            d = (cx - lab[0]) ** 2 + (cy - lab[1]) ** 2
            if d < best_d:
                best_d = d
                best = raw.strip()
    return best


def _quoted_title(items):
    """标题栏里被引号包裹的单段文本（如 "从动轮法兰" / “法兰盘”）通常是图名。

    SW 图框常把零件名用弯引号括起来放在标题单元格，且没有独立的「图名」标签，
    这种带引号文本是可靠的图名信号；其内侧若仍是标签则放弃。
    """
    for cx, cy, raw, h in items:
        s = (raw or "").strip()
        if not s:
            continue
        if s[0] in _QUOTE_CHARS and s[-1] in _QUOTE_CHARS:
            inner = s[1:-1].strip()
            if inner and not _is_pure_label(inner):
                return s
    return None


# ---------- ATTDEF/ATTRIB 标题栏提取（92DZ1 类图：旧标题栏由属性定义构成） ----------
def _attdef_value(e):
    """从 ATTDEF/ATTRIB 取字段值。值通常写在 tag(group2) 或 text(group1)。

    92DZ1 类图把真实值写在 tag（如 项目名称 的 tag=单台消火栓泵闭式自耦降压起动），
    text(group1) 反而是占位符（如「公寓」）；常规图则 text 为值、tag 为短代码。
    规则：优先含中文且更长者；若都无中文取 text(group1)。
    """
    tag = (getattr(e.dxf, "tag", None) or "").strip()
    txt = (getattr(e.dxf, "text", None) or "").strip()

    def has_cjk(s):
        return any("\u4e00" <= c <= "\u9fff" for c in s)
    if txt and has_cjk(txt) and (not has_cjk(tag) or len(txt) >= len(tag)):
        return txt
    if tag and has_cjk(tag):
        return tag
    return txt or tag


_ATTDEF_PROMPT_MAP = {
    "项目名称": "TITLE", "图名": "TITLE", "图样名称": "TITLE", "名称": "TITLE",
    "比例": "SCALE",
    "日期": "DATE", "制图日期": "DATE",
    "图号": "DWG_NO", "图纸编号": "DWG_NO", "档案号": "DWG_NO", "档 案 号": "DWG_NO",
    "阶段": "STAGE",
    "单位名称": "UNIT", "设计单位": "UNIT", "设计单位名称": "UNIT",
    "设计": "DESIGN", "制图": "DESIGN", "绘制": "DESIGN",
    "审核": "CHECKED", "校对": "CHECKED",
    "审定": "REVIEWED", "审查": "REVIEWED",
    "批准": "APPROVED", "审批": "APPROVED",
    "会签": "COUNTERSIGN",
}


def _collect_attdef_fields(doc, tb):
    """从标题栏区域 tb 内的 ATTDEF/ATTRIB 提取字段。

    部分图纸（如 92DZ1 消火栓泵控制图）旧标题栏完全由 ATTDEF 构成，值写在
    tag/text，而非独立 TEXT/MTEXT，常规 extract_frame_fields 读不到 → 标题留空、
    旧标题栏 ATTDEF 残留。这里按 prompt(组3) 映射到概念，取描述性字符串为值。
    仅取落在 tb 内的 ATTDEF/ATTRIB，避免误抓图幅其它位置的属性定义。
    """
    fx0, fy0, fx1, fy1 = tb
    out = {}
    msp = doc.modelspace()
    for e in msp:
        dt = e.dxftype()
        if dt not in ("ATTDEF", "ATTRIB"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        if eb[2] < fx0 or eb[0] > fx1 or eb[3] < fy0 or eb[1] > fy1:
            continue
        prompt = (getattr(e.dxf, "prompt", None) or "").strip()
        concept = _ATTDEF_PROMPT_MAP.get(prompt)
        if not concept:
            continue
        val = _attdef_value(e)
        if val:
            out[concept] = val
    return out


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
    # 值单元格与标签的水平间距上限（相对标题栏宽）：SW 网格里标签与值常分属不同单元格，
    # 必须限制“同行右邻”只在相邻格子内生效，否则会跨列抓到远处文本（如 设计→图名/比例）。
    tbw = max(1e-6, tb[2] - tb[0])
    max_gap = max(20.0, 0.4 * tbw)
    fields = {}
    # 0) SCALE 优先按「比例」标签附近的比例文本（1:100 / 2:1），最可靠，
    #    避免把紧邻的图名/其它文本误当比例（案例：比例标签抓到“从动轮法兰”）。
    ratio = _nearest_ratio_to_label(items_tb, "比例")
    if ratio:
        fields["SCALE"] = ratio
    # 1) 标签+值概念（DWG_NO/STAGE/DATE/DESIGN/SCALE 兜底）
    for concept in concepts:
        if concept == "TITLE":
            continue
        if concept == "SCALE" and "SCALE" in fields:
            continue
        aliases = CONCEPT_ALIASES.get(concept, [concept.lower()])
        found = None
        for al in aliases:
            if not al:
                continue
            for cx, cy, raw, h in items_tb:
                if al in _norm(raw) and (":" in raw or "：" in raw):
                    val = re.split(r"[:：]", raw, maxsplit=1)[-1].strip()
                    if val and not _is_pure_label(val):
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
                        if _is_pure_label(raw2):   # 跳过列标题/标签本身，绝不把“标准化”之类当值
                            continue
                        # 比例文本（如 2:1）只属于 SCALE，其它字段（设计/图号/日期…）
                        # 绝不该把它当值——SW 网格里比例值常与标签同行右邻而被误抓
                        if concept != "SCALE" and _RATIO_RE.match(raw2.strip()):
                            continue
                        if abs(cy2 - cy) < 6 and cx2 > cx:
                            dx = cx2 - cx
                            if dx > max_gap:   # 跨列太远（如 设计→149单位外的图名），不当值
                                continue
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
    # 2) SCALE 裸比例文本兜底（标签/比例附近都未命中时）
    if "SCALE" not in fields:
        sc = _pick_scale(items_tb)
        if sc:
            fields["SCALE"] = sc
    # 3) TITLE：带引号图名 → 标签:值 → 含图类名 → 整图右35%含图类名 → 最长非标签文本
    title = _quoted_title(items_tb)
    if not title:
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
        fields["TITLE"] = _strip_surrounding_quotes(title)
    # ATTDEF/ATTRIB 标题栏（92DZ1 类）：用属性定义里的值覆盖/补全字段。
    # ATTDEF 是结构化标题栏数据，比启发式 TEXT 扫描更可靠，故以 ATTDEF 为准；
    # 无 ATTDEF 的常规图 att_fields 为空，不产生任何影响。
    att_fields = _collect_attdef_fields(doc, tb)
    for k, v in att_fields.items():
        if v:
            fields[k] = v
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

# ===================== v2: 几何约束 + 标签/值分离打分 =====================
# 改进点（相对 extract_frame_fields）：
#  1) 扩展「标签/列头」排除集：标题栏字段名 + SW 词表 + 设备表列头（名称/型号规格/单位/
#     数量/备注/编号/进线编号/档案号/项目号/室别…），这些文本绝不当作字段值。
#  2) 标签:值 取值时做「类型打分」——优先选符合该字段类型正则的候选（SCALE=比例、
#     DATE=日期、DWG_NO=图号码、STAGE=阶段值…），而不是盲取「同行右邻最近文本」。
#  3) TITLE 增加「标题栏上栏居中」位置权重，并排除列头/字段名（避免把 型号规格 当图名）。
# 不改动 v1，供对比与后续接管使用。

_TB_COLHEAD = {
    "名称", "型号规格", "型号", "规格", "单位", "数量", "备注", "编号", "进线编号",
    "进线回路编号", "出线回路编号", "回路编号", "配电箱编号", "低压配电柜编号",
    "低压配电柜型号", "配电箱型号及规格", "设备容量", "电缆型号及规格", "用途", "栋数",
    "档案号", "项目号", "室别", "比例", "阶段", "日期", "材料", "重量", "版本",
    "设计", "制图", "校对", "审核", "批准", "会签", "标准化", "图名", "图号",
}
_TB_LABEL_SET_V2 = set(_LABEL_NORM_SET) | {_norm(x) for x in _TB_COLHEAD}


def _is_pure_label_v2(raw):
    """v2：文本本身是否就是标题栏字段名/列头（绝不当字段值）。"""
    return _norm(raw) in _TB_LABEL_SET_V2


_V2_DATE = re.compile(r"^\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}")
_V2_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.]{2,}$")
_STAGE_VALS = {"初步设计", "施工图", "方案设计", "竣工图", "设计", "施工", "招标",
               "报批", "规划", "可研", "代初设", "施工图设计"}


def _vtype_score(concept, raw):
    """提取端类型打分：候选文本越像该字段的合法值，分越高。"""
    v = (raw or "").strip()
    if concept == "SCALE":
        return 1.0 if _RATIO_RE.match(v) else 0.0
    if concept == "DATE":
        return 1.0 if (_V2_DATE.search(v) or re.search(r"\d{4}", v)) else 0.1
    if concept == "DWG_NO":
        if re.search(r"[，。、（）()：:\s]", v):
            return 0.05
        return 1.0 if _V2_CODE.match(v) else 0.1
    if concept == "STAGE":
        return 1.0 if _norm(v) in _STAGE_VALS else 0.4
    if concept == "WEIGHT":
        return 1.0 if re.match(r"^\d", v) else 0.2
    if concept in ("DESIGN", "CHECK", "REVIEW", "APPROVE", "DRAWN", "COUNTERSIGN"):
        return 0.1 if _is_pure_label_v2(v) else 0.7
    return 0.5


# 各概念「接受最小值」：候选打分低于此阈值即视为误判（标签/列头/注记/非类型文本），
# 直接留空，不写入新标题栏。门槛目标：
#   STAGE >=0.8  —— 必须是真实阶段值（初步设计/施工图…），拒绝「档案号:」之类错拍；
#   DWG_NO >=0.5 —— 必须是图号码（alnum/-_/.，如 BESS-LST-001、001），拒绝注记长句
#                   （如「1, 1Q1(B2)箱同1Q(B1)箱,其进线编号如下:」）；
#   其余 >=0.5   —— 类型不可信（DATE/WEIGHT 非类型文本）也留空，避免污染数据。
_MIN_SCORE = {"STAGE": 0.8, "DWG_NO": 0.5}


def extract_frame_fields_v2(doc, frame_bbox, concepts=("TITLE", "DWG_NO", "SCALE", "STAGE", "DATE", "DESIGN")):
    """v2 提取：几何约束 + 标签/值分离打分。"""
    fx0, fy0, fx1, fy1 = frame_bbox
    tb = detect_titleblock(doc, frame_bbox)
    items = _collect_items(doc, tb)
    tbw = max(1e-6, tb[2] - tb[0])
    max_gap = max(20.0, 0.4 * tbw)
    fields = {}
    # SCALE 优先「比例」标签附近比例文本
    ratio = _nearest_ratio_to_label(items, "比例")
    if ratio:
        fields["SCALE"] = ratio
    # 标签:值 概念（类型打分 + 标签排除）
    for concept in concepts:
        if concept == "TITLE":
            continue
        if concept == "SCALE" and "SCALE" in fields:
            continue
        aliases = CONCEPT_ALIASES.get(concept, [concept.lower()])
        best = None
        best_score = -1.0
        for al in aliases:
            if not al:
                continue
            for cx, cy, raw, h in items:
                n = _norm(raw)
                labeled = (n == al) or (al in n and (":" in raw or "：" in raw))
                if not labeled:
                    continue
                cands = []
                if ":" in raw or "：" in raw:
                    val = re.split(r"[:：]", raw, 1)[-1].strip()
                    if val and not _is_pure_label_v2(val):
                        sc = _vtype_score(concept, val)
                        if sc > 0:
                            cands.append((val, cx, cy, sc))
                for cx2, cy2, raw2, h2 in items:
                    if raw2 == raw:
                        continue
                    if _is_pure_label_v2(raw2):
                        continue
                    if concept != "SCALE" and _RATIO_RE.match(raw2.strip()):
                        continue
                    if abs(cy2 - cy) < 6 and cx2 > cx:
                        dx = cx2 - cx
                        if dx > max_gap:
                            continue
                        sc = _vtype_score(concept, raw2)
                        sc -= min(0.3, dx / max_gap * 0.3)
                        if sc > 0:
                            cands.append((raw2, cx2, cy2, sc))
                if cands:
                    cands.sort(key=lambda c: -c[3])
                    if cands[0][3] > best_score:
                        best_score = cands[0][3]
                        best = cands[0][0]
        if best is not None:
            _thr = _MIN_SCORE.get(concept, 0.5)
            if best_score >= _thr:
                fields[concept] = best.strip()
    # SCALE 裸兜底
    if "SCALE" not in fields:
        sc = _pick_scale(items)
        if sc:
            fields["SCALE"] = sc
    # TITLE：字高 + 上栏居中 + 排注记/列头
    title = _pick_title_v2(items, tb)
    if title:
        fields["TITLE"] = _strip_surrounding_quotes(title)
    return fields


def _pick_title_v2(items, tb):
    """v2 图名：字高最大 + 完整图类名加权 + 标题栏越靠上越好；排除注记/列头/字段名。"""
    tbx0, tby0, tbx1, tby1 = tb
    th = max(1e-6, tby1 - tby0)
    cands = []
    for cx, cy, raw, h in items:
        if _is_note(raw):
            continue
        if _is_pure_label_v2(raw):
            continue
        if not any(k in raw for k in _TITLE_KW):
            continue
        if raw.startswith(("接", "由", "详见", "做法")):
            continue
        full = any(k in raw for k in _TITLE_FULL)
        ypos = (cy - tby0) / th
        cands.append((h + (100.0 if full else 0.0) + 30.0 * max(0.0, ypos), cy, raw))
    if not cands:
        return None
    cands.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return cands[0][2]
