# -*- coding: utf-8 -*-
"""
替换核心：删旧框（尽量不影响电路） -> 插入公司图框（块或打散）-> 回填字段。
纯 ezdxf 离线，不依赖 AutoCAD COM。
"""
import ezdxf
from ezdxf import bbox as bbox_mod
from . import raw_replace as _rr
from .concepts import infer_concept


# 删除时允许的实体类型（打散图框用）
_DELETABLE = {"LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT",
              "ARC", "CIRCLE", "HATCH", "DIMENSION", "INSERT", "ATTDEF"}


def _bbox(e):
    try:
        b = e.bbox()
        if b and b.has_data:
            return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
    except Exception:
        pass
    return None


def table_bottom(doc, default=None):
    """模型空间中所有 ACAD_TABLE（BOM 明细表等）世界 bbox 的最小底边 y。

    装配图/明细表常是 ACAD_TABLE（AutoCAD 2005+ 原生表格对象，几何存放在
    匿名块如 *T1 里）。它既不是 INSERT 也不是 LINE，find_titleblocks /
    detect_frames 都扫不到它；但 ezdxf 的 bbox 模块能算出它的世界范围。
    返回 default（默认 None）表示图纸里没有 ACAD_TABLE。
    """
    tables = [e for e in doc.modelspace() if e.dxftype() == "ACAD_TABLE"]
    if not tables:
        return default
    try:
        ext = bbox_mod.extents(tables)
        return float(ext.extmin.y)
    except Exception:
        return default


def _intersect(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _is_closed(e):
    try:
        return bool(e.dxf.closed) or bool(e.dxf.flags & 1)
    except Exception:
        try:
            return bool(e.dxf.flags & 1)
        except Exception:
            return False


def _delete_line_rect(msp, lines, frame_bbox, tol=2.5):
    """删除由 4 段 LINE 近似拼成、且每条都贯穿整条外框边的旧图框。

    仅当四边各有一条「跨度 >= 50% 边长」的 LINE 时才删——全框矩形几何是明确的旧框，
    不会误删只贴在边上的内容短线段/标注线（零误删）。
    """
    x0, y0, x1, y1 = frame_bbox
    W = x1 - x0; H = y1 - y0
    atol = max(tol, abs(W) * 0.01, abs(H) * 0.01, 50.0)
    half_w, half_h = 0.5 * W, 0.5 * H
    groups = {"L": [], "R": [], "T": [], "B": []}
    for e in lines:
        try:
            s, e2 = e.dxf.start, e.dxf.end
        except Exception:
            continue
        if abs(s.x - x0) < atol and abs(e2.x - x0) < atol and abs(s.y - e2.y) >= half_h:
            groups["L"].append(e); continue
        if abs(s.x - x1) < atol and abs(e2.x - x1) < atol and abs(s.y - e2.y) >= half_h:
            groups["R"].append(e); continue
        if abs(s.y - y0) < atol and abs(e2.y - y0) < atol and abs(s.x - e2.x) >= half_w:
            groups["B"].append(e); continue
        if abs(s.y - y1) < atol and abs(e2.y - y1) < atol and abs(s.x - e2.x) >= half_w:
            groups["T"].append(e); continue
    if groups["L"] and groups["R"] and groups["T"] and groups["B"]:
        n = 0
        for ed in groups.values():
            for e in ed:
                msp.delete_entity(e); n += 1
        return n
    return 0


def _mixed_title_layers(doc, frame_bbox):
    """返回「混合」图框命名层集合（2026-09-01，35kV 全页误删修复）。

    CADDesigner 等生成器把真实内容（设备表/柜阵列/母线/符号框）也画在 FRAME
    图框层上，本模块对图框命名层的「区域内按层名自由删」特权会大面积误删。
    以 raw_replace.title_layer_purity（阈值 0.9）判定：层上实体几乎全是旧框
    几何（SW 打散图框层）才保留特权，混合层一律收回。"""
    try:
        pur = _rr.title_layer_purity(doc, frame_bbox)
    except Exception:
        return set()
    return {lay for lay, p in pur.items() if not p}


def delete_frame_border(doc, frame_bbox, tol=2.5, inner_ratio=0.8,
                        record_cells=True, tb=None):
    """删除与 frame_bbox 重合/包含/对齐的旧图框几何（外框 + 内框 + 纸边外框），
    返回删除数。覆盖四种旧框画法，避免残留（零误删前提下只删明确的框几何）：
      (1) 闭合矩形外框 bbox 与检测框基本一致；
      (2) 检测框完整落在矩形内部（纸边外框比检出子框大一圈，原逻辑漏删）；
      (3) 矩形完整落在检测框内且面积 >= inner_ratio（内框/标题区划分隔线）；
      (4) 矩形与检测框 >=2 条边重合（旧框内部分隔线，如标题栏与图框的中线），
          仅对 图框层/0/默认层 生效，避免误删图内几何。
    仅删明确框几何，绝不碰图内几何。
    """
    x0, y0, x1, y1 = frame_bbox
    W = x1 - x0; H = y1 - y0
    outer_area = max(W * H, 1e-9)
    atol = max(tol, abs(W) * 0.02, abs(H) * 0.02, 50.0)
    msp = doc.modelspace()
    n = 0
    cells = []
    lines = []
    for e in list(msp):
        dt = e.dxftype()
        if dt in ("LWPOLYLINE", "POLYLINE"):
            try:
                if dt == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points()]
                else:
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices()]
            except Exception:
                continue
            if not pts:
                continue
            if not (_is_closed(e) or pts[0] == pts[-1]):
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            r = (min(xs), min(ys), max(xs), max(ys))
            layer = (e.dxf.layer or "").lower()
            frameish = _rr._is_title_frame_layer(layer) or layer in ("0", "")
            hit = False
            rule_no = 0
            # (1) 精确匹配
            if (abs(r[0] - x0) < atol and abs(r[1] - y0) < atol and
                    abs(r[2] - x1) < atol and abs(r[3] - y1) < atol):
                hit = True
                rule_no = 1
            # (2) 检测框完整落在矩形内（纸边外框比检出子框大一圈）
            if not hit and (r[0] <= x0 + atol and r[1] <= y0 + atol and
                            r[2] >= x1 - atol and r[3] >= y1 - atol):
                hit = True
                rule_no = 2
            # (3) 矩形完整落在检测框内且面积够大（内框）
            if not hit and (r[0] >= x0 - atol and r[1] >= y0 - atol and
                            r[2] <= x1 + atol and r[3] <= y1 + atol):
                if (r[2] - r[0]) * (r[3] - r[1]) >= outer_area * inner_ratio:
                    hit = True
                    rule_no = 3
            # (4) 与检测框 >=2 边重合（旧框内部分隔线）；或完全包含于检测框且
            #     贴 >=1 条边（旧框内小分隔格，如标题栏单元格）。仅图框层/0/默认层，
            #     避免误删图内几何。CNG 等内容矩形虽在框内但不贴框边 -> 不受影响。
            #     2026-09-01（35kV 修复）：图框命名层还须满足几何判据——
            #     align>=2（贯穿分隔线）用「与外框环带相交」；contained+align>=1
            #     （标题栏单元格）用「中心在 tb 内」（tb 缺省时退化右下角伪 tb）。
            #     atol 下限 50mm 使「贴边」口径过宽，设备表外框（左缘距框边
            #     34mm）、上子面板（顶缘距框边 14.5mm）等内容矩形被误判为旧框
            #     分隔线，还会被记成墓碑盒引发 delete_title_strip 级联误删。
            #     0/默认层维持原口径不动。
            if not hit and _intersect(r, (x0, y0, x1, y1)):
                contained = (r[0] >= x0 - atol and r[1] >= y0 - atol and
                             r[2] <= x1 + atol and r[3] <= y1 + atol)
                align = (abs(r[0] - x0) < atol) + (abs(r[2] - x1) < atol) + \
                        (abs(r[1] - y0) < atol) + (abs(r[3] - y1) < atol)
                frameish_ok = False
                if layer in ("0", ""):
                    frameish_ok = True
                elif _rr._is_title_frame_layer(layer):
                    if align >= 2:
                        frameish_ok = _rr.frame_geo_hit(
                            (r[0], r[1], r[2], r[3]), frame_bbox,
                            tb=None if tb is not None else (0, 0, -1, -1))
                        # frame_geo_hit 含伪 tb 中心分支，align>=2 只看环带：
                        # 上面传空 tb 使中心分支恒 False，仅环带生效
                    elif contained and align >= 1:
                        frameish_ok = _rr.frame_geo_hit(
                            (r[0], r[1], r[2], r[3]), frame_bbox, tb=tb,
                            band=0.0)  # band=0 禁用环带分支，仅中心在 tb 内
                if frameish_ok and (align >= 2 or (contained and align >= 1)):
                    hit = True
                    rule_no = 4
            if hit:
                msp.delete_entity(e); n += 1
                # 墓碑记录（2026-08-31）：规则(3)(4)删掉的子矩形（面积<=0.2 当前框）
                # 大概率是旧标题栏单元格/内分隔格。其内部的旧标题栏「值文本、格线、
                # 符号块」不匹配 _TITLE_LABEL_RE，此前被守卫漏删，与新标题栏叠加
                # （07a/07b 双份图名、从法兰 INSERT/HATCH 残留）。把墓碑 bbox 交给
                # delete_title_strip 做几何定位清理——范围来自已删除的框几何，不靠
                # 正则猜测，内容文本在墓碑之外不受影响。
                # 注意：record_cells=False（并集外框趟）绝不记录——并集框面积巨大，
                # 真实子框与并集共 2 边会被规则(4)删掉，若按并集面积记墓碑，整个
                # 子框都被当「标题栏单元格」，CNG 实测误删 2109 个实体。
                if record_cells and rule_no in (3, 4):
                    area = (r[2] - r[0]) * (r[3] - r[1])
                    if area <= outer_area * 0.2:
                        pad = max(1.0, 0.01 * max(W, H))
                        cells.append((r[0] - pad, r[1] - pad,
                                      r[2] + pad, r[3] + pad))
        elif dt == "LINE":
            lines.append(e)
    n += _delete_line_rect(msp, lines, frame_bbox, tol)
    if cells:
        try:
            doc._title_cell_boxes.extend(cells)
        except AttributeError:
            doc._title_cell_boxes = cells
    return n


# 标题栏清理白名单：
#  - 文本类：标题栏内容，安全删除
#  - 尺寸标注/引线/几何图元：绝不删（图内标注、不是标题栏）
#  - 线类：仅删"短线段/闭合矩形"（标题栏格线/边框），长线视作几何/尺寸线跳过
_TITLE_TEXT = {"TEXT", "MTEXT", "ATTDEF"}
_TITLE_PRESERVE = {"DIMENSION", "LEADER", "ARC", "CIRCLE", "HATCH", "INSERT",
                   "ELLIPSE", "MLINE", "POINT", "SOLID", "IMAGE", "SPLINE"}


def _fully_in_zone(b, fx0, fy0, fx1, zy1, zx0):
    """实体 bbox 是否完全落在标题区 [zx0,fx1]×[fy0,zy1] 内（留 1 单位容差）。"""
    return (b.extmin.x >= zx0 - 1 and b.extmax.x <= fx1 + 1 and
            b.extmin.y >= fy0 - 1 and b.extmax.y <= zy1 + 1)


def _short_line_len(e, W, H):
    """返回线实体最长分段长度；非线类返回 0。用于判断是否为标题栏短格线。"""
    try:
        dt = e.dxftype()
        if dt == "LINE":
            s, en = e.dxf.start, e.dxf.end
            return ((s.x - en.x) ** 2 + (s.y - en.y) ** 2) ** 0.5
        if dt == "LWPOLYLINE":
            pts = e.get_points()
            if len(pts) < 2:
                return 0
            return max(((pts[i][0] - pts[i - 1][0]) ** 2 +
                        (pts[i][1] - pts[i - 1][1]) ** 2) ** 0.5
                       for i in range(1, len(pts)))
        if dt == "POLYLINE":
            vs = e.vertices()
            if len(vs) < 2:
                return 0
            return max(((vs[i].dxf.location.x - vs[i - 1].dxf.location.x) ** 2 +
                        (vs[i].dxf.location.y - vs[i - 1].dxf.location.y) ** 2) ** 0.5
                       for i in range(1, len(vs)))
    except Exception:
        return 0
    return 0


def delete_title_strip(doc, frame_bbox, strip_ratio=0.28):
    """删除某图框右下角标题栏区域内的实体（旧标题栏线+文本），保留图内几何。返回删除数。

    白名单策略，避免误删图内尺寸线/几何：
      - 文本类（TEXT/MTEXT/ATTDEF）：标题栏文字。删除条件：插入点落在标题区内
        且图层不在 _CONTENT_LAYER_HINTS（墙/窗/线/标注等内容层白名单）。早期用
        ``_fully_in_zone`` 校验整个 bbox 必须在区内，92DZ1 类图纸的 PUB_TEXT 标题栏
        文字字号较大，bbox 顶部刚好超出 strip 顶部（zy1+1）就被漏删，旧标题栏
        「档案号/设计阶段/图号/工程编号 + 长标题 + 公司名」叠加在新 HH_FRAME
        标题栏之上（用户反馈「还是不对」）。改用「插入点 + 内容层白名单」后能
        可靠清理，且不会误删原理图里的设备标签（它们通常在 y>zy1）。
      - 尺寸标注/引线（DIMENSION/LEADER）：绝不删（这是图内标注，不是标题栏）
      - 圆/弧/填充/图块等（ARC/CIRCLE/HATCH/INSERT…）：绝不删，避免误伤图内几何
      - 线类（LINE/LWPOLYLINE/POLYLINE）：
          完全落在标题区内 且 为闭合矩形(标题框) 或 短线段(标题栏格线) 才删；
          长线（疑似贯穿几何/尺寸线）跳过
    """
    fx0, fy0, fx1, fy1 = frame_bbox
    W = fx1 - fx0
    H = fy1 - fy0
    # 2026-09-01（35kV 修复）：混合图框层收回「区域内按层名自由删」特权
    mixed_layers = _mixed_title_layers(doc, frame_bbox)
    zx0 = fx0 + 0.45 * W      # 标题区左界（右 55%）
    zy1 = fy0 + strip_ratio * H  # 标题区上界（底 strip_ratio）
    # 长线阈值：超过此长度视为"几何/尺寸线"而非标题栏格线
    long_th = max(W, H) * 0.55
    msp = doc.modelspace()
    n = 0

    def _ent_bbox(e):
        try:
            b = bbox_mod.extents([e])
            if b and b.has_data:
                return b
        except Exception:
            pass
        return None

    def _in_box(ip, box):
        return (box[0] <= ip[0] <= box[2] and box[1] <= ip[1] <= box[3])

    # ---- 标题区线簇盒（2026-08-31）----
    # 16MW 'TABLE' 层、从法兰 '图框' 层的旧标题栏单元格不在 strip 的线类删除
    # 范围内（层名不在 frameish 允许集 / 单元格越出 strip 边界）时，旧标题栏整簇
    # 残留。这里把标题区内「非内容层、非 0/数字层」的闭合矩形/短格线聚成一个
    # 联合盒 U（>=3 条才算簇），作为清理范围；U 内文本需有 >=2 个标题栏标签
    # （图名/图号/比例…）作证据才放开删除，避免把图例框等当标题栏。
    cluster_ents = []
    # 角落锚定带（2026-08-31）：旧标题栏必然贴着图框右下角。落在标题带内但不贴角
    # 的闭合矩形（如主接线图右下角的 EQUIP 设备框 (570,90)-(780,170)）不是标题栏
    # 成员——收进簇会把簇盒撑大到覆盖内容区，标签证据再放开白名单就会误删内容
    # （实测主接线图 EQUIP 框+3 条说明文本被误删）。
    corner_band_x = fx1 - 0.02 * W   # 距右边界 2% 内
    corner_band_y = fy0 + 0.02 * H   # 距下边界 2% 内
    for e in msp:
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        layer = (e.dxf.layer or "").lower()
        if layer in _rr._CONTENT_LAYER_HINTS or _rr._is_zero_layer(layer):
            continue
        b = _ent_bbox(e)
        if not (b and _fully_in_zone(b, fx0, fy0, fx1, zy1, zx0)):
            continue
        if not (b.extmax.x >= corner_band_x or b.extmin.y <= corner_band_y):
            continue  # 不贴右/下边界的实体不是标题栏成员
        if dt != "LINE" and _is_closed(e):
            cluster_ents.append((e, b))
        elif _short_line_len(e, W, H) <= long_th:
            cluster_ents.append((e, b))
    cluster_box = None
    cluster_labels = 0
    if len(cluster_ents) >= 3:
        ux0 = min(b.extmin.x for _, b in cluster_ents)
        uy0 = min(b.extmin.y for _, b in cluster_ents)
        ux1 = max(b.extmax.x for _, b in cluster_ents)
        uy1 = max(b.extmax.y for _, b in cluster_ents)
        cluster_box = (ux0, uy0, ux1, uy1)
        for e in msp:
            if e.dxftype() not in _TITLE_TEXT:
                continue
            try:
                ip = e.dxf.insert
            except Exception:
                continue
            if not _in_box((ip.x, ip.y), cluster_box):
                continue
            raw = e.text if e.dxftype() == "MTEXT" else (e.dxf.text or "")
            txt = _rr._decode_mtext_mplus(raw or "")
            txt = txt.replace(' ', '').replace('\t', '').replace('\n', '')
            if _rr._TITLE_LABEL_RE.search(txt):
                cluster_labels += 1

    # 标签证据盒（2026-08-31）：旧标题栏网格线可能与表格共用图层（16MW 'TABLE'）、
    # 或落在内容层白名单（'TEXT'）导致线簇聚合不出来。兜底改用「标签文本证据」：
    # strip 区底部 18% 内命中 >=2 个标题栏标签（图名/图号/比例/阶段…，种子不限
    # 图层），以这些标签的联合 bbox 外扩成盒。盒内文本删除（内容层白名单仅在
    # 有标签证据时放开）；盒内非内容层短格线一并清理。
    label_box = None
    if cluster_box is None or cluster_labels < 2:
        lab_bbs = []
        for e in msp:
            if e.dxftype() not in _TITLE_TEXT:
                continue
            try:
                ip = e.dxf.insert
            except Exception:
                continue
            if not (zx0 <= ip.x <= fx1 and fy0 <= ip.y <= fy0 + 0.18 * H):
                continue
            raw = e.text if e.dxftype() == "MTEXT" else (e.dxf.text or "")
            txt = _rr._decode_mtext_mplus(raw or "")
            txt = txt.replace(' ', '').replace('\t', '').replace('\n', '')
            if _rr._TITLE_LABEL_RE.search(txt):
                b = _ent_bbox(e)
                if b is not None:
                    lab_bbs.append(b)
        if len(lab_bbs) >= 2:
            lx0 = min(b.extmin.x for b in lab_bbs) - 0.02 * W
            ly0 = min(b.extmin.y for b in lab_bbs) - 0.01 * H
            lx1 = max(b.extmax.x for b in lab_bbs) + 0.02 * W
            ly1 = max(b.extmax.y for b in lab_bbs) + 0.06 * H
            label_box = (max(lx0, fx0), max(ly0, fy0),
                         min(lx1, fx1), min(ly1, fy1))
    relax_hints = (cluster_box is not None and cluster_labels >= 2) or \
        (label_box is not None)

    def _box_hit(b, box):
        return (b is not None and
                b.extmin.x <= box[2] and b.extmax.x >= box[0] and
                b.extmin.y <= box[3] and b.extmax.y >= box[1])

    # ---- 主循环 ----
    for e in list(msp):
        dt = e.dxftype()
        # 1) 文本类：插入点在标题区内 且 图层非内容层 → 删
        if dt in _TITLE_TEXT:
            try:
                ip = e.dxf.insert
            except Exception:
                continue
            if not (zx0 <= ip.x <= fx1 and fy0 <= ip.y <= zy1):
                continue
            layer = (e.dxf.layer or "").lower()
            if layer in _rr._CONTENT_LAYER_HINTS:
                continue  # 内容层白名单：保护 wall/wire/window/dj/...
            # 图层感知（2026-08-26 治本）：layer 0 / 数字层上的真实绘图内容
            # （如下载图的设备材料表、标注）绝不误删；仅当文本明显是旧标题栏标签
            # （图名/图号/比例…）时才删，避免与新 HH_FRAME 标题栏重叠。旧标题栏
            # 框线/标签多在命名图框层，由 delete_old_frame_grid 等按层名清除。
            if _rr._is_zero_layer(layer):
                # 2026-08-26：旧会签栏中文标签常带空格对齐（"制  图"/"校  对"/
                # "设  计"/"审  核"），去空格后再正则匹配，否则"制图"在
                # "制  图"里搜不到会被守卫误判为"非标题栏文本"而保留。
                # 2026-08-26 v3 补：cluster/strip 区 layer 0 上的「旧标题栏
                # 字段值」（如 10kV主接线图、平面布置图）也属于旧图框内容，
                # 单独检查 _TITLE_VALUE_RE 命中则放行删除。
                # 2026-08-26 v4：源 DXF 中文标签全部以 \M+5XXXX (GBK) 转义码存储
                # （如 \M+5D6C6\M+5CDBC = 制图），不解码正则永远匹配不到 → 守卫
                # 误判保留。`_rr._decode_mtext_mplus()` 把 \M+5XXXX 还原成中文再匹配。
                _txt = (e.text if dt == "MTEXT" else e.dxf.text) or ""
                _txt_dec = _rr._decode_mtext_mplus(_txt)
                _txt_compact = _txt_dec.replace(' ', '').replace('\t', '').replace('\n', '')
                if not (_rr._TITLE_LABEL_RE.search(_txt_compact)
                        or _rr._TITLE_VALUE_RE.search(_txt_compact)):
                    continue
            msp.delete_entity(e)
            n += 1
            continue
        # 2) 尺寸标注/几何图元：绝不删除
        if dt in _TITLE_PRESERVE:
            continue
        # 3) 线类：只删闭合矩形(标题框)或短线段(格线)，长线跳过
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE"):
            layer = (e.dxf.layer or "").lower()
            # 安全网（零误删红线）：标题区线类仅删「明确是旧图框/标题栏层」上的
            # 闭合矩形或短格线；其余层（内容层 wall/axis/wire、0/数字层、以及
            # 首层/D-1/DJ1/信箱 等项目层）一律保留。旧标题栏框线多在 图框/TK/
            # PUB_TITLE/BORDER 等命名层，由本正向允许集覆盖；落在标题区的真实
            # 墙/轴/标注线不再被当旧格线误删（实测 multi 模式曾多删 WALL 302/
            # STAIR 118/WIRE 等共 540 条内容层实体）。
            if not _rr._is_title_frame_layer(layer):
                continue
            if layer in mixed_layers:
                continue  # 混合图框层：内容与旧框混居，宁漏勿误
            try:
                b = bbox_mod.extents([e])
            except Exception:
                continue
            if not (b and b.has_data and _fully_in_zone(b, fx0, fy0, fx1, zy1, zx0)):
                continue
            if dt != "LINE" and _is_closed(e):
                msp.delete_entity(e)  # 闭合矩形 = 标题框
                n += 1
            elif _short_line_len(e, W, H) <= long_th:
                msp.delete_entity(e)  # 短线段 = 标题栏格线
                n += 1
            # else: 长线，跳过（疑似图内几何/尺寸线）
            continue
        # 4) 其它类型不处理

    # ---- 墓碑 / 线簇盒清理（2026-08-31）----
    # 墓碑 = delete_frame_border 规则(3)(4)删掉的标题栏单元格 bbox；其中残存的
    # 旧标题栏值文本/格线/符号块不匹配标签正则，主循环删不到。线簇盒 = 标题区
    # 内命名层格线的联合盒（16MW 'TABLE'、从法兰 '图框'）。两类盒内：
    #   文本     非内容层即删（0/数字层仅墓碑盒内删；线簇盒需 >=2 标签证据），
    #            内容层白名单仅在线簇盒有标签证据时放开（16MW 旧标题在 'TEXT' 层）
    #   线类     图框层全删；0/数字层仅墓碑盒内且短线；内容层不删
    #   INSERT/HATCH  图框层或 0/默认层且 bbox 在盒内；内容层不删
    #   DIMENSION/LEADER 绝不删
    boxes = [("tomb", bx) for bx in (getattr(doc, "_title_cell_boxes", None) or [])]
    if cluster_box is not None and cluster_labels >= 2:
        boxes.append(("cluster", cluster_box))
    if label_box is not None:
        boxes.append(("cluster", label_box))  # 标签证据盒与线簇盒同待遇
    if not boxes:
        return n
    for e in list(msp):
        dt = e.dxftype()
        if dt in ("DIMENSION", "LEADER"):
            continue
        layer = (e.dxf.layer or "").lower()
        if layer in _rr._CONTENT_LAYER_HINTS and not (
                dt in _TITLE_TEXT and relax_hints):
            continue  # 内容层白名单（有标签证据时对文本放开）
        zero = _rr._is_zero_layer(layer)
        frameish = _rr._is_title_frame_layer(layer) and layer not in mixed_layers
        if dt in _TITLE_TEXT:
            try:
                ip = e.dxf.insert
            except Exception:
                continue
            for kind, box in boxes:
                if _in_box((ip.x, ip.y), box):
                    # 墓碑盒：几何上就是已删标题栏单元格内部，0 层值文本直接删；
                    # 线簇/标签盒：需 >=2 标签证据（boxes 列表已把关），同样直接删。
                    msp.delete_entity(e); n += 1
                    break
            continue
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE"):
            b = _ent_bbox(e)
            for kind, box in boxes:
                hit = (_box_hit(b, box) if kind == "cluster"
                       else b is not None and _in_box((b.extmin.x, b.extmin.y), box) and
                       _in_box((b.extmax.x, b.extmax.y), box))
                if not hit:
                    continue
                if frameish:
                    msp.delete_entity(e); n += 1
                elif zero and _short_line_len(e, W, H) <= long_th:
                    msp.delete_entity(e); n += 1
                elif relax_hints and layer not in _rr._CONTENT_LAYER_HINTS and \
                        _short_line_len(e, W, H) <= long_th:
                    # 线簇/标签盒内非内容层短格线（16MW 旧标题网格在 'TABLE' 层）
                    msp.delete_entity(e); n += 1
                break
            continue
        if dt in ("INSERT", "HATCH"):
            b = _ent_bbox(e)
            for kind, box in boxes:
                hit = (_box_hit(b, box) if kind == "cluster"
                       else b is not None and _in_box((b.extmin.x, b.extmin.y), box) and
                       _in_box((b.extmax.x, b.extmax.y), box))
                if not hit:
                    continue
                if frameish or (zero and kind == "tomb") or layer in ("", ):
                    msp.delete_entity(e); n += 1
                break
            continue
    return n


def delete_frameish_leftovers(doc, frame_bbox, tol=1.0):
    """删除标题区（右下 strip 带）内图框命名层（图框/TK/BORDER/图签…）的残体。

    2026-08-31：multi 逐框路径的 delete_frame_border + delete_title_strip 只删
    「几何上像框/格线」的实体，从法兰类 SW 图纸残留在标题区外（左侧装订边刻度、
    竖排字段列 x<strip 左界、INSERT/HATCH 符号）的图框层实体删不到。最初的实现在
    整 frame_bbox 内清，结果把装配体爆炸图 17 个 SW_NOTE 零件球标（散落在图面
    y=80-265 的内容区，「图框」层上 SW 把它们放这）一并清了。现收敛到 strip
    区（标题栏所在角落），从法兰标题栏角落的 INSERT×4 + HATCH×2 在带内被清，
    散落在图面的球标全保留。
    在 insert_template 之前调用（新框尚未插入，无误伤对象）。
    """
    fx0, fy0, fx1, fy1 = frame_bbox
    W = fx1 - fx0
    H = fy1 - fy0
    # 2026-09-01（35kV 修复）：混合图框层收回特权
    mixed_layers = _mixed_title_layers(doc, frame_bbox)
    zx0 = fx0 + 0.45 * W      # 与 delete_title_strip 标题区一致
    zy1 = fy0 + 0.28 * H
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        layer = (e.dxf.layer or "").lower()
        if not _rr._is_title_frame_layer(layer):
            continue
        if layer in mixed_layers:
            continue  # 混合图框层：内容与旧框混居，宁漏勿误
        dt = e.dxftype()
        if dt in ("DIMENSION", "LEADER"):
            continue
        try:
            b = bbox_mod.extents([e])
            if not (b and b.has_data):
                continue
        except Exception:
            continue
        # 仅清理完全落在标题 strip 带内的图框层残体
        if not (b.extmin.x >= zx0 - tol and b.extmax.x <= fx1 + tol and
                b.extmin.y >= fy0 - tol and b.extmax.y <= zy1 + tol):
            continue
        msp.delete_entity(e)
        n += 1
    return n


def delete_old(doc, region, margin=5.0):
    """删除旧图框区域实体。块图框只删该 INSERT + 其 ATTRIB；打散则删区域内几何。
    返回删除实体数。"""
    msp = doc.modelspace()
    bbox = region["bbox"]
    rb = (bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin)
    deleted = 0

    if region.get("method") == "block" and region.get("entity") is not None:
        ins = region["entity"]
        # 先删附带的 ATTRIB（orphan）
        for e in list(msp):
            if e.dxftype() == "ATTRIB":
                eb = _bbox(e)
                if eb and _intersect(eb, rb):
                    msp.delete_entity(e)
                    deleted += 1
        try:
            msp.delete_entity(ins)
            deleted += 1
        except Exception:
            pass
        return deleted

    # 打散：删区域内实体
    for e in list(msp):
        if e.dxftype() not in _DELETABLE:
            continue
        eb = _bbox(e)
        if eb and _intersect(eb, rb):
            msp.delete_entity(e)
            deleted += 1
    return deleted


def _compute_transform(template, region, fit):
    tx0, ty0, tx1, ty1 = template["bbox"]
    tw = max(1e-6, tx1 - tx0)
    th = max(1e-6, ty1 - ty0)
    rx0, ry0, rx1, ry1 = region["bbox"]
    rw = rx1 - rx0
    rh = ry1 - ry0
    if fit == "min":
        s = min(rw / tw, rh / th)
    elif fit == "max":
        s = max(rw / tw, rh / th)
    elif fit == "width":
        s = rw / tw
    elif fit == "height":
        s = rh / th
    else:
        s = min(rw / tw, rh / th)
    # 块局部 (tx0,ty0) 映射到目标起点（居中）
    target_x = rx0 + (rw - tw * s) / 2
    target_y = ry0 + (rh - th * s) / 2
    insert_x = target_x - tx0 * s
    insert_y = target_y - ty0 * s
    return s, insert_x, insert_y


def _ensure_block_deps(doc, src, block_name):
    """把模板块引用到的 图层 / 文字样式 / 线型 从模板文档拷进目标 doc。

    关键修复：模板块里的 TEXT 标注了 style=HH_CHN、layer=HH_TITLE，但源图纸
    的 STYLE/LAYER 表里根本没有这两条。AutoCAD 导入 DXF 时，TEXT 引用的文字
    样式若不在 STYLE 表中会直接报「无效的 DXF 数据」而放弃图形（错误码 53）。
    之前所有「跨文档复制块打不开」的根因就在这里——实体 tag 完全一致，坏的是
    表记录缺失。所以复制块实体之前，必须先把依赖的表记录补齐。"""
    need_layers = set()
    need_styles = set()
    need_lts = set()
    if block_name in src.blocks:
        for e in src.blocks[block_name]:
            try:
                if e.dxf.hasattr("layer"):
                    need_layers.add(e.dxf.layer)
            except Exception:
                pass
            try:
                if e.dxf.hasattr("style"):
                    need_styles.add(e.dxf.style)
            except Exception:
                pass
            try:
                if e.dxf.hasattr("linetype"):
                    lt = e.dxf.linetype
                    if lt not in ("BYLAYER", "BYBLOCK"):
                        need_lts.add(lt)
            except Exception:
                pass
    # 图层：缺则按模板属性补建（不复制 plotstyle/material 句柄，避免悬空引用）
    for nm in need_layers:
        if nm in doc.layers:
            continue
        if nm in src.layers:
            sl = src.layers.get(nm)
            nl = doc.layers.add(nm)
            for a in ("color", "linetype", "lineweight", "flags", "description"):
                try:
                    setattr(nl.dxf, a, getattr(sl.dxf, a))
                except Exception:
                    pass
        else:
            doc.layers.add(nm)
    # 文字样式：缺则按模板字体补建（HH_CHN -> simhei.ttf 等 TrueType）
    for nm in need_styles:
        if nm in doc.styles:
            continue
        if nm in src.styles:
            ss = src.styles.get(nm)
            ns = doc.styles.add(nm, font=(getattr(ss.dxf, "font", None) or "txt"))
            for a in ("bigfont", "width", "oblique", "flags", "generation_flags", "height"):
                try:
                    setattr(ns.dxf, a, getattr(ss.dxf, a))
                except Exception:
                    pass
        else:
            doc.styles.add(nm, font="txt")
    # 线型：缺则用 Importer 整条带图案复制
    if need_lts:
        try:
            from ezdxf.addons.importer import Importer
            imp = Importer(src, doc)
            for nm in need_lts:
                if nm not in doc.linetypes and nm in src.linetypes:
                    imp.import_table("linetypes", [nm])
            imp.finalize()
        except Exception:
            pass


def import_template_block(doc, template):
    """确保模板块已存在于目标 doc（仅 block 类型需要）。返回块名。
    用跨文档 e.copy() 复制块定义（比 Importer 更稳，兼容 ezdxf 1.4）。"""
    if template["kind"] != "block":
        return None
    block_name = template["block_name"]
    if block_name in [b.name for b in doc.blocks]:
        return block_name
    src = ezdxf.readfile(template["src_path"])
    _ensure_block_deps(doc, src, block_name)
    src_blk = src.blocks[block_name]
    nb = doc.blocks.new(block_name)
    for e in src_blk:
        # 跳过 ATTDEF：ezdxf 1.4.4 在 add_blockref 引用含 ATTDEF 的块时，
        # 会在模型空间写出双重 AcDbText / 错误实体类型的 ATTRIB，AutoCAD 无法打开。
        # 字段值改由 insert_template 用 add_text 干净写回。
        if e.dxftype() == "ATTDEF":
            continue
        try:
            nb.add_entity(e.copy())
        except Exception:
            pass
    return block_name


def insert_template(doc, template, region, values, fit="min"):
    """在 region 处插入公司图框并回填字段。返回 (insert_ref, written_fields)。"""
    msp = doc.modelspace()

    # 补齐模板依赖的 图层/文字样式（缺则 AutoCAD 导入 DXF 报「无效的 DXF 数据」）
    if template.get("src_path"):
        try:
            _src = ezdxf.readfile(template["src_path"])
            _ensure_block_deps(doc, _src, template.get("block_name"))
        except Exception:
            pass

    if template["kind"] == "block":
        block_name = import_template_block(doc, template)
        # 确定字段值要用的样式：取模板块里第一个有 style 的 TEXT 的样式
        # （标准模板 HH_FRAME_* 用 HH_CHN=simhei.ttf），写出的独立 TEXT 才能
        # 正常显示中文；否则走默认 STANDARD（ASCII SHX），中文显示成 ????。
        # 自定义模板若用了别的中文样式名，也能自动适配。
        label_style = None
        try:
            for _e in doc.blocks.get(block_name, []):
                if _e.dxftype() == "TEXT":
                    _s = getattr(_e.dxf, "style", None)
                    if _s:
                        label_style = _s
                        break
        except Exception:
            pass
        if not label_style:
            label_style = "HH_CHN"
        s, ix, iy = _compute_transform(template, region, fit)
        ins = msp.add_blockref(block_name, (ix, iy),
                               dxfattribs={"xscale": s, "yscale": s})
        # 回填字段：用 add_text 写文本（避免 ezdxf 1.4.4 add_auto_attribs
        # 产生的双重 AcDbText / 错误实体类型，导致 AutoCAD 无法打开）。
        # 块自带 ATTDEF，AutoCAD 打开 INSERT 时会显示标题栏占位；
        # 这里再把已提取到的值以干净 TEXT 写回，避免与块内 ATTDEF 重叠。
        written = []
        for fld, val in zip(template["fields"], values):
            if not val:
                continue
            x = ix + fld["x"] * s
            y = iy + fld["y"] * s
            msp.add_text(val, dxfattribs={"height": fld["height"] * s,
                                          "style": label_style}).set_placement((x, y))
            written.append(fld["tag"])
        return ins, written

    # exploded：重建几何 + 文本
    s, ix, iy = _compute_transform(template, region, fit)
    written = []
    for geo in (template.get("geometry") or []):
        _recreate_entity(msp, geo, ix, iy, s)
    # 模板是 exploded 时，从 geometry 文本里取样式（自定义/标准模板都通用）
    label_style = None
    for geo in (template.get("geometry") or []):
        if geo.get("type") == "TEXT":
            _s = (geo.get("attribs") or {}).get("style")
            if _s:
                label_style = _s
                break
    if not label_style:
        label_style = "HH_CHN"
    for fld, val in zip(template["fields"], values):
        if not val:
            continue
        x = ix + fld["x"] * s
        y = iy + fld["y"] * s
        msp.add_text(val, dxfattribs={"height": fld["height"] * s,
                                      "style": label_style}).set_placement((x, y))
        written.append(fld["tag"])
    return None, written


def _recreate_entity(msp, geo, ix, iy, s):
    dt = geo["type"]
    a = dict(geo.get("attribs", {}))
    pts = geo.get("points", [])
    try:
        if dt == "LWPOLYLINE":
            msp.add_lwpolyline([(ix + x * s, iy + y * s) for x, y in pts], dxfattribs=a)
        elif dt == "LINE":
            msp.add_line((ix + pts[0][0] * s, iy + pts[0][1] * s),
                         (ix + pts[1][0] * s, iy + pts[1][1] * s), dxfattribs=a)
        elif dt == "POLYLINE":
            # 简化：用 lwpolyline 替代
            msp.add_lwpolyline([(ix + x * s, iy + y * s) for x, y in pts], dxfattribs=a)
    except Exception:
        pass
