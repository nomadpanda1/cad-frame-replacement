# -*- coding: utf-8 -*-
"""
AutoCAD COM 直接操作原 DWG —— 用于 ezdxf 无法写回的图纸。

为什么需要它：设计院原图常含**加密/代理实体**，经 ezdxf 读→saveas 重写后，
AutoCAD 打开会报“解密数据时出错”，回退成空白 Drawing1。ezdxf 渲染的 PNG 不受影响，
但交给 AutoCAD 的 DXF/DWG 会炸。这条路线**完全不动 ezdxf 的写回**，只让 AutoCAD
COM 在原 DWG 副本上做：删旧图框/会签栏 → 插公司图框块 → 回填属性 → Save。

本模块是纯函数库（不含任何图纸特定的字段提取逻辑），被 run_cng_acad.py 等脚本调用。
依赖：pywin32 (win32com)；本机需手动打开 AutoCAD（不自动启动实例）。

关键约定（本机实测，缺一不可）：
- 插入点必须是 VARIANT(VT_ARRAY|VT_R8, [x,y,0])
- 实体 bbox 用 e.GetBoundingBox()（不是 GeometricExtents）
- Documents.Open 后必须 time.sleep(2) 等加载
- 保存用 doc.Save()（本机 SaveAs 的 format 参数失效，会写出 DXF）
- 模板块必须先用 WBLOCK 写成真正的二进制 DWG（magic=AC1032），InsertBlock 不支持 DXF 源
"""
import os
import shutil
import time
import win32com.client


# 公司标准图框尺寸（毫米），用于按外框比例选模板、算等比缩放。
A_SIZES = {
    "A0": (1189, 841),
    "A1": (841, 594),
    "A2": (594, 420),
    "A3": (420, 297),
    "A3_WIDE": (604, 299),
    "A4": (297, 210),
}


def variant_point(x, y, z=0.0):
    """InsertBlock 需要的插入点 VARIANT。"""
    return win32com.client.VARIANT(
        win32com.client.pythoncom.VT_ARRAY | win32com.client.pythoncom.VT_R8,
        [float(x), float(y), float(z)],
    )


def get_acad_dispatch():
    """只取已打开的 AutoCAD 实例（不自动启动，Dispatch 启动的实例 COM 不稳）。"""
    return win32com.client.Dispatch("AutoCAD.Application")


def open_doc_copy(app, src_dwg, dst_dwg, wait_open=2.0):
    """复制原 DWG 到 dst_dwg，在副本上打开；返回 (doc, msp)。

    wait_open：Open 后必须等加载，否则 ModelSpace 报“被呼叫方拒绝接收呼叫”。
    """
    shutil.copy(src_dwg, dst_dwg)
    doc = app.Documents.Open(os.path.abspath(dst_dwg))
    time.sleep(wait_open)
    return doc, doc.ModelSpace


def save_close(doc):
    """保存在已打开的副本上并关闭（不另存，避免 SaveAs format 失效）。"""
    doc.Save()
    doc.Close(False)


def entity_bbox(e):
    """获取 AutoCAD COM 实体的 bbox，返回 (xmin,ymin,xmax,ymax) 或 None。"""
    try:
        mn, mx = e.GetBoundingBox()
        return (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))
    except Exception:
        return None


def del_in_region(msp, x0, y0, x1, y1, allowed_types=None, exclude_types=None):
    """删除 modelspace 中中心完全落在矩形区域内的实体。"""
    to_del = []
    for i in range(msp.Count):
        e = msp.Item(i)
        et = e.EntityName if hasattr(e, "EntityName") else e.EntityType
        if allowed_types and et not in allowed_types:
            continue
        if exclude_types and et in exclude_types:
            continue
        bb = entity_bbox(e)
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        cx, cy = (ex0 + ex1) / 2, (ey0 + ey1) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            to_del.append(e)
    for e in to_del:
        try:
            e.Delete()
        except Exception:
            pass
    return len(to_del)


def del_frame_edges(msp, frame, margin=500):
    """删除图框层上、与外框面积重合>80% 或贴四边的 LINE/LWPOLYLINE/CIRCLE。"""
    x0, y0, x1, y1 = frame
    frame_layers = {"tukuang", "图框", "0"}
    to_del = []
    for i in range(msp.Count):
        e = msp.Item(i)
        et = e.EntityName if hasattr(e, "EntityName") else e.EntityType
        if et not in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline", "AcDbCircle"):
            continue
        layer = e.Layer.lower() if hasattr(e, "Layer") else ""
        if layer not in frame_layers and not layer.startswith("tukuang"):
            continue
        bb = entity_bbox(e)
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        inter_x0, inter_y0 = max(x0, ex0), max(y0, ey0)
        inter_x1, inter_y1 = min(x1, ex1), min(y1, ey1)
        if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
            continue
        inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
        frame_area = (x1 - x0) * (y1 - y0)
        if inter_area / frame_area > 0.80:
            to_del.append(e)
            continue
        near_edge = (
            (abs(ex0 - x0) < margin and abs(ex1 - x0) < margin) or
            (abs(ex0 - x1) < margin and abs(ex1 - x1) < margin) or
            (abs(ey0 - y0) < margin and abs(ey1 - y0) < margin) or
            (abs(ey0 - y1) < margin and abs(ey1 - y1) < margin)
        )
        if near_edge and ex0 >= x0 - margin and ex1 <= x1 + margin and ey0 >= y0 - margin and ey1 <= y1 + margin:
            to_del.append(e)
    for e in to_del:
        try:
            e.Delete()
        except Exception:
            pass
    return len(to_del)


def insert_frame(msp, frame, tpl_dwg, fields, size_table=None):
    """在 frame 左下角插入公司图框块（tpl_dwg 为 WBLOCK 生成的 *.dwg），等比缩放并回填属性。

    返回 (insert, scale)。缩放 = min(W/tw, H/th)（等比，保持模板自身比例）。
    """
    if size_table is None:
        size_table = A_SIZES
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    size_name = os.path.splitext(os.path.basename(tpl_dwg))[0].replace("HH_FRAME_", "")
    tw, th = size_table.get(size_name, (W, H))
    scale = min(W / tw, H / th) if tw and th else 1.0

    insert = msp.InsertBlock(
        variant_point(x0, y0, 0.0),
        tpl_dwg,
        scale, scale, scale, 0.0,
    )

    # 属性回填：只对 tag 命中 fields 的 ATTDEF 写值。
    try:
        for a in insert.GetAttributes():
            tag = a.TagString
            if tag in fields:
                a.TextString = fields[tag]
    except Exception as e:
        print("    set attribs warn:", e)

    return insert, scale


def prepare_templates(app, tpl_dir, out_dir):
    """把 templates/ 下的 HH_FRAME_*.dxf 用 AutoCAD -WBLOCK 写成 *.dwg。

    InsertBlock 不接受 DXF 源，必须用二进制 DWG。本函数幂等：已存在的 DWG 跳过。
    返回 {size_name: dwg_path} 字典。
    """
    import glob
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for src in sorted(glob.glob(os.path.join(tpl_dir, "HH_FRAME_*.dxf"))):
        name = os.path.splitext(os.path.basename(src))[0]
        size_name = name.replace("HH_FRAME_", "")
        dst = os.path.join(out_dir, name + ".dwg")
        result[size_name] = dst
        if os.path.exists(dst):
            continue
        doc = app.Documents.Open(os.path.abspath(src))
        time.sleep(0.5)
        # -WBLOCK 命令：文件路径、块名、插入点（回车用空格）
        cmd = '_.-WBLOCK\n"%s"\n%s\n ' % (dst, name)
        doc.SendCommand(cmd)
        time.sleep(1.0)
        doc.Close(False)
    return result


def _entity_name(e):
    """兼容 EntityName / EntityType 的实体类型读取。"""
    try:
        return e.EntityName
    except Exception:
        try:
            return e.EntityType
        except Exception:
            return None


def del_frame_lines_acad(msp, frames, margin=1.0):
    """按坐标删除图框外框/内框矩形的边线（适用于 SolidWorks 打散图框）。

    frames: [(x0,y0,x1,y1), ...]
    返回删除数量。
    """
    edge_coords = {"v": set(), "h": set()}
    for (x0, y0, x1, y1) in frames:
        for c in (x0, x1):
            edge_coords["v"].add(round(c, 1))
        for c in (y0, y1):
            edge_coords["h"].add(round(c, 1))

    to_del = []
    for i in range(msp.Count):
        e = msp.Item(i)
        et = _entity_name(e)
        if et == "AcDbLine":
            try:
                s = e.StartPoint
                en = e.EndPoint
            except Exception:
                continue
            if abs(s[0] - en[0]) < 1e-3 and round(s[0], 1) in edge_coords["v"]:
                to_del.append(e)
            elif abs(s[1] - en[1]) < 1e-3 and round(s[1], 1) in edge_coords["h"]:
                to_del.append(e)
        elif et == "AcDbPolyline":
            try:
                coords = list(e.Coordinates)
                pts = [(coords[j], coords[j + 1]) for j in range(0, len(coords), 2)]
                closed = bool(e.Closed)
            except Exception:
                continue
            if not (closed or (pts and pts[0] == pts[-1])):
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            for (x0, y0, x1, y1) in frames:
                if (abs(xmin - x0) < margin and abs(xmax - x1) < margin and
                        abs(ymin - y0) < margin and abs(ymax - y1) < margin):
                    to_del.append(e)
                    break
        elif et == "AcDb2dPolyline":
            # 老版本 2d 多段线：遍历顶点
            try:
                pts = []
                for v in e:
                    pts.append((v.Coordinate[0], v.Coordinate[1]))
                closed = bool(e.Closed)
            except Exception:
                continue
            if not (closed or (pts and pts[0] == pts[-1])):
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            for (x0, y0, x1, y1) in frames:
                if (abs(xmin - x0) < margin and abs(xmax - x1) < margin and
                        abs(ymin - y0) < margin and abs(ymax - y1) < margin):
                    to_del.append(e)
                    break

    n = 0
    for e in to_del:
        try:
            e.Delete()
            n += 1
        except Exception:
            pass
    return n


def del_titleblock_acad(msp, tb, maxdim):
    """删除标题栏区域内实体：文本全删；线只删短线（网格线），保留长线（可能是尺寸线）。

    tb: (x0,y0,x1,y1)
    返回删除数量。
    """
    x0, y0, x1, y1 = tb
    thr = 0.30 * maxdim
    to_del = []
    for i in range(msp.Count):
        e = msp.Item(i)
        et = _entity_name(e)
        if et == "AcDbBlockReference":
            continue
        bb = entity_bbox(e)
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        if ex1 < x0 or ex0 > x1 or ey1 < y0 or ey0 > y1:
            continue
        if et in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline"):
            L = max(ex1 - ex0, ey1 - ey0)
            if L > thr:
                continue
        to_del.append(e)

    n = 0
    for e in to_del:
        try:
            e.Delete()
            n += 1
        except Exception:
            pass
    return n


def del_edge_markers_acad(msp, outer, strip=10.0):
    """删除沿外框边缘的区号字母/数字（如 A/B/C 与 4/5/6）。"""
    import re
    x0, y0, x1, y1 = outer
    to_del = []
    for i in range(msp.Count):
        e = msp.Item(i)
        et = _entity_name(e)
        if et not in ("AcDbText", "AcDbMText"):
            continue
        try:
            raw = e.TextString
        except Exception:
            continue
        if not raw or not re.fullmatch(r"[A-Za-z0-9]{1,2}", raw.strip()):
            continue
        bb = entity_bbox(e)
        if bb is None:
            continue
        cx = (bb[0] + bb[2]) / 2.0
        cy = (bb[1] + bb[3]) / 2.0
        if abs(cx - x0) < strip or abs(cx - x1) < strip or \
           abs(cy - y0) < strip or abs(cy - y1) < strip:
            to_del.append(e)

    n = 0
    for e in to_del:
        try:
            e.Delete()
            n += 1
        except Exception:
            pass
    return n
