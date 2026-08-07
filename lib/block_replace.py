# -*- coding: utf-8 -*-
"""
替换核心：删旧框（尽量不影响电路） -> 插入公司图框（块或打散）-> 回填字段。
纯 ezdxf 离线，不依赖 AutoCAD COM。
"""
import ezdxf
from ezdxf import bbox as bbox_mod
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


def delete_frame_border(doc, frame_bbox, tol=2.5):
    """删除与 frame_bbox 重合的闭合矩形边框（旧图框线），返回删除数。

    仅匹配 bbox 与该帧基本重合的 LWPOLYLINE/POLYLINE，不影响图内几何——这是逐框替换的
    关键：只去掉该子图的旧边框，保留其内部的零件几何。
    """
    x0, y0, x1, y1 = frame_bbox
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LWPOLYLINE", "POLYLINE"):
            continue
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
        if (abs(r[0] - x0) < tol and abs(r[1] - y0) < tol and
                abs(r[2] - x1) < tol and abs(r[3] - y1) < tol):
            msp.delete_entity(e)
            n += 1
    return n


def delete_title_strip(doc, frame_bbox, strip_ratio=0.28):
    """删除某图框右下角标题栏区域内的实体（旧标题栏线+文本），保留图内几何。返回删除数。

    只删"完全落在标题区内"的实体（右 55% × 底 strip_ratio），避免误删图内尺寸线/几何。
    已知局限：若图内尺寸线恰好落在右下角标题区，也会被删（生产环境建议加白名单）。
    """
    fx0, fy0, fx1, fy1 = frame_bbox
    W = fx1 - fx0
    H = fy1 - fy0
    zx0 = fx0 + 0.45 * W      # 标题区左界（右 55%）
    zy1 = fy0 + strip_ratio * H  # 标题区上界（底 strip_ratio）
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT",
                      "ARC", "CIRCLE", "HATCH", "INSERT", "ATTDEF"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not (b and b.has_data):
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        # 实体必须完全落在标题区内才删
        if (eb[0] >= zx0 - 1 and eb[2] <= fx1 + 1 and
                eb[1] >= fy0 - 1 and eb[3] <= zy1 + 1):
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


def import_template_block(doc, template):
    """确保模板块已存在于目标 doc（仅 block 类型需要）。返回块名。
    用跨文档 e.copy() 复制块定义（比 Importer 更稳，兼容 ezdxf 1.4）。"""
    if template["kind"] != "block":
        return None
    block_name = template["block_name"]
    if block_name in [b.name for b in doc.blocks]:
        return block_name
    src = ezdxf.readfile(template["src_path"])
    src_blk = src.blocks[block_name]
    nb = doc.blocks.new(block_name)
    for e in src_blk:
        try:
            nb.add_entity(e.copy())
        except Exception:
            pass
    return block_name


def insert_template(doc, template, region, values, fit="min"):
    """在 region 处插入公司图框并回填字段。返回 (insert_ref, written_fields)。"""
    msp = doc.modelspace()

    if template["kind"] == "block":
        block_name = import_template_block(doc, template)
        s, ix, iy = _compute_transform(template, region, fit)
        ins = msp.add_blockref(block_name, (ix, iy),
                               dxfattribs={"xscale": s, "yscale": s})
        # 回填 ATTDEF 字段：值缺失时写空串，保留可编辑占位（14 个字段齐全）。
        kv = {}
        for fld, val in zip(template["fields"], values):
            kv[fld["tag"]] = val if val else ""
        ins.add_auto_attribs(kv)
        written = [t for t, v in kv.items() if v]
        return ins, written

    # exploded：重建几何 + 文本
    s, ix, iy = _compute_transform(template, region, fit)
    written = []
    for geo in (template.get("geometry") or []):
        _recreate_entity(msp, geo, ix, iy, s)
    for fld, val in zip(template["fields"], values):
        if not val:
            continue
        x = ix + fld["x"] * s
        y = iy + fld["y"] * s
        msp.add_text(val, dxfattribs={"height": fld["height"] * s}).set_placement((x, y))
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
