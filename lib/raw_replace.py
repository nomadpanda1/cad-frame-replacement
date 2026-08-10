# -*- coding: utf-8 -*-
"""线框检测（整框替换）复用函数：用于 SolidWorks 导出「打散」图框（0 INSERT 块）的图纸。

从 run_real.py 抽出，供 run_skill.py 在块式 find_titleblocks 0 命中时回退使用，
使 exe 也能处理这类图纸。此处不依赖 matplotlib，避免污染冻结 exe。
"""
import re
from ezdxf import bbox as bbox_mod


def sheet_extents(doc):
    ext = bbox_mod.extents(doc.modelspace())
    if not ext or not ext.has_data:
        return None
    return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)


def delete_frame_lines(doc, frames):
    """只删外框/内框矩形的四条边线（不碰内容）。frames=[(x0,y0,x1,y1), ...]。"""
    msp = doc.modelspace()
    edge_coords = set()
    for (x0, y0, x1, y1) in frames:
        for c in (round(x0, 1), round(x1, 1)):
            edge_coords.add(("v", c))
        for c in (round(y0, 1), round(y1, 1)):
            edge_coords.add(("h", c))
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt == "LINE":
            s, en = e.dxf.start, e.dxf.end
            if abs(s.x - en.x) < 1e-3 and ("v", round(s.x, 1)) in edge_coords and \
               (s.y, en.y) == (min(s.y, en.y), max(s.y, en.y)):
                msp.delete_entity(e); n += 1
            elif abs(s.y - en.y) < 1e-3 and ("h", round(s.y, 1)) in edge_coords:
                msp.delete_entity(e); n += 1
        elif dt in ("LWPOLYLINE", "POLYLINE"):
            try:
                if dt == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points()]
                else:
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices()]
            except Exception:
                continue
            try:
                closed = bool(e.dxf.flags & 1)
            except Exception:
                closed = False
            if not (closed or (pts and pts[0] == pts[-1])):
                continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            for (x0, y0, x1, y1) in frames:
                if abs(xmin - x0) < 1 and abs(xmax - x1) < 1 and \
                   abs(ymin - y0) < 1 and abs(ymax - y1) < 1:
                    msp.delete_entity(e); n += 1
                    break
    return n


def delete_titleblock(doc, tb, maxdim):
    """删标题栏区域内实体：文本全删；线只删短线（网格线），保留长线（可能是真实尺寸线）。"""
    msp = doc.modelspace()
    thr = 0.30 * maxdim
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt == "INSERT":
            continue  # 跳过 SW 符号块（中心线等）
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        if eb[2] < tb[0] or eb[0] > tb[2] or eb[3] < tb[1] or eb[1] > tb[3]:
            continue
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE"):
            L = max(eb[2] - eb[0], eb[3] - eb[1])
            if L > thr:
                continue
        msp.delete_entity(e); n += 1
    return n


def delete_edge_markers(doc, outer, strip=10.0):
    """删沿外框边缘的区号字母/数字（如 A/B/C 与 4/5/6），这些是 SW 图框系统的一部分。"""
    x0, y0, x1, y1 = outer
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        raw = e.text if dt == "MTEXT" else e.dxf.text
        if not raw or not re.fullmatch(r"[A-Za-z0-9]{1,2}", raw.strip()):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        if abs(cx - x0) < strip or abs(cx - x1) < strip or \
           abs(cy - y0) < strip or abs(cy - y1) < strip:
            msp.delete_entity(e); n += 1
    return n
