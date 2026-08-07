# -*- coding: utf-8 -*-
"""
模板自动学习：读入公司图框文件，自动判断是“块模板(ATTDEF)”还是“打散模板(<图名>占位符)”，
输出结构化 Template，供替换阶段使用。模板随时会变 —— 重跑即可，代码零改动。
"""
import ezdxf
from ezdxf import bbox as bbox_mod
from .concepts import infer_concept, FRAME_BLOCK_KEYWORDS


def _block_extents(blk):
    try:
        ext = bbox_mod.extents(blk)
        if ext.has_data:
            return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    except Exception:
        pass
    # 兜底：手动算几何实体 bbox
    xs, ys = [], []
    for e in blk:
        try:
            b = e.bbox()
            if b:
                xs += [b.extmin.x, b.extmax.x]
                ys += [b.extmin.y, b.extmax.y]
        except Exception:
            pass
    if xs:
        return (min(xs), min(ys), max(xs), max(ys))
    return (0, 0, 1, 1)


def _score_block_name(name):
    n = (name or "").lower()
    s = 0
    for kw in FRAME_BLOCK_KEYWORDS:
        if kw in n:
            s += 3
    return s


def learn_template(path):
    """返回 Template(dict)。kind='block' 或 'exploded'。"""
    doc = ezdxf.readfile(path)

    # ---- 1) 块模板：找含 ATTDEF 的块定义 ----
    best_blk = None
    best_score = -1
    best_attdefs = []
    for blk in doc.blocks:
        bname = blk.name
        if bname in ("*Model_Space", "*Paper_Space"):
            continue
        attdefs = [e for e in blk if e.dxftype() == "ATTDEF"]
        if attdefs:
            score = len(attdefs) + _score_block_name(bname)
            if score > best_score:
                best_score = score
                best_blk = blk
                best_attdefs = attdefs
    if best_blk is not None:
        fields = []
        for a in best_attdefs:
            tag = a.dxf.tag
            prompt = a.dxf.prompt if a.dxf.prompt else tag
            fields.append({
                "tag": tag,
                "prompt": prompt,
                "concept": infer_concept(prompt) or infer_concept(tag) or tag.upper(),
                "x": a.dxf.insert.x,
                "y": a.dxf.insert.y,
                "height": a.dxf.height if a.dxf.height else 3.0,
                "default": a.dxf.text if a.dxf.text else "",
            })
        bx = _block_extents(best_blk)
        return {
            "kind": "block",
            "src_path": path,
            "block_name": best_blk.name,
            "fields": fields,
            "bbox": bx,
            "geometry": None,
        }

    # ---- 2) 打散模板：找 <...> 占位符 TEXT/MTEXT + 帧几何 ----
    msp = doc.modelspace()
    fields = []
    frame_entities = []
    for e in msp:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            txt = e.text if dt == "MTEXT" else e.dxf.text
            txt = _clean_mtext(txt)
            if txt and ("<" in txt and ">" in txt):
                # 占位符 <图名> -> 取括号内中文
                inner = txt.strip().strip("<>").strip()
                concept = infer_concept(inner) or infer_concept(txt)
                p = e.dxfty if dt == "MTEXT" else e.dxf.insert
                fields.append({
                    "tag": inner,
                    "prompt": inner,
                    "concept": concept or inner.upper(),
                    "x": p.x, "y": p.y,
                    "height": e.dxf.height if e.dxf.height else 3.0,
                    "default": "",
                })
        elif dt in ("LWPOLYLINE", "LINE", "POLYLINE", "ARC", "CIRCLE"):
            # 帧/标题栏几何
            try:
                frame_entities.append(_serialize_entity(e))
            except Exception:
                pass
    if fields:
        bx = _extents_from_geometry(frame_entities, fields)
        return {
            "kind": "exploded",
            "src_path": path,
            "block_name": None,
            "fields": fields,
            "bbox": bx,
            "geometry": frame_entities,
        }

    raise ValueError("模板中既没有 ATTDEF 块，也没有 <...> 占位符文本，无法识别为图框模板。")


def _clean_mtext(t):
    if t is None:
        return ""
    import re
    t = re.sub(r"\\[A-Za-z]+\b[^\x00-\x1f]*", "", t)  # 去 MTEXT 控制符
    return t.replace("{}", "").strip()


def _extents_from_geometry(geometries, fields):
    xs, ys = [], []
    for g in geometries:
        for (x, y) in g.get("points", []):
            xs.append(x); ys.append(y)
    for f in fields:
        xs.append(f["x"]); ys.append(f["y"])
    if xs:
        return (min(xs), min(ys), max(xs), max(ys))
    return (0, 0, 1, 1)


def _msp_extents(msp):
    xs, ys = [], []
    for e in msp:
        try:
            b = e.bbox()
            if b:
                xs += [b.extmin.x, b.extmax.x]
                ys += [b.extmin.y, b.extmax.y]
        except Exception:
            pass
    if xs:
        return (min(xs), min(ys), max(xs), max(ys))
    return (0, 0, 1, 1)


def _serialize_entity(e):
    """把帧几何实体序列化为可重建的简易结构。"""
    dt = e.dxftype()
    attribs = dict(e.dxf.all_existing_dxf_attribs())
    points = []
    if dt == "LWPOLYLINE":
        points = [(p[0], p[1]) for p in e.get_points()]
    elif dt == "LINE":
        points = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    elif dt == "POLYLINE":
        for v in e.vertices():
            points.append((v.dxf.location.x, v.dxf.location.y))
    return {"type": dt, "attribs": attribs, "points": points}
