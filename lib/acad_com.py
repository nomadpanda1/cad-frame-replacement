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

性能/健壮性（本机实测修订）：
- AutoCAD COM 调用偶发“被呼叫方拒绝接收呼叫”(RPC_E_CALL_REJECTED)，所有属性读取必须用
  _retry 包裹，否则单帧一个瞬断就整轮崩溃。
- 实体清单在 process_file 里**只采集一次**（collect_entities），逐帧只在 Python 里按区域
  过滤，避免 9000 实体 × 帧数 的 COM 往返（原来跑一张图要 9 分钟且易崩）。
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


def _retry(fn, tries=6, wait=1.5, label="op"):
    """对 AutoCAD COM 调用做重试，容忍瞬时的“被呼叫方拒绝接收呼叫”(RPC_E_CALL_REJECTED)。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(wait)
    raise last


def entity_bbox(e):
    """计算实体包围盒（优先用轻量几何属性，避免 GetBoundingBox 的高 COM 开销与挂起风险）。

    返回 (xmin,ymin,xmax,ymax) 或 None。批量采集时个别实体读不到几何则跳过（不参与删除即可）。

    关键坑：GetBoundingBox 对部分实体（如 AcDbPoint）可能持续报错；若用 _retry 会 6×1.5s 挂起，
    上千实体即数小时。这里改用各类型自身的轻量属性（StartPoint/Coordinates/InsertionPoint/
    Center…），单次 COM 调用即可，几乎不会触发长挂起。
    """
    try:
        et = e.EntityName if hasattr(e, "EntityName") else e.EntityType
    except Exception:
        et = None
    try:
        if et == "AcDbLine":
            s = e.StartPoint
            en = e.EndPoint
            xs, ys = (s[0], en[0]), (s[1], en[1])
        elif et in ("AcDbPolyline", "AcDbLWPolyline", "AcDb2dPolyline", "AcDb3dPolyline"):
            c = e.Coordinates
            if not c:
                raise ValueError("no coords")
            xs = [c[i] for i in range(0, len(c), 2)]
            ys = [c[i + 1] for i in range(0, len(c), 2)]
        elif et in ("AcDbText", "AcDbMText"):
            p = e.InsertionPoint
            xs, ys = (p[0],), (p[1],)
        elif et == "AcDbPoint":
            p = e.Coordinates
            xs, ys = (p[0],), (p[1],)
        elif et in ("AcDbCircle", "AcDbArc"):
            c = e.Center
            r = e.Radius
            xs, ys = (c[0] - r, c[0] + r), (c[1] - r, c[1] + r)
        elif et == "AcDbBlockReference":
            p = e.InsertionPoint
            xs, ys = (p[0],), (p[1],)
        else:
            # HATCH / DIMENSION / 未知类型：兜底用一次 GetBoundingBox
            mn, mx = e.GetBoundingBox()
            return (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        try:
            mn, mx = e.GetBoundingBox()
            return (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))
        except Exception:
            return None


def _entity_name(e):
    """兼容 EntityName / EntityType 的实体类型读取（单次尝试，失败返回 None）。"""
    try:
        return e.EntityName if hasattr(e, "EntityName") else e.EntityType
    except Exception:
        return None


def _entity_layer(e):
    try:
        return (e.Layer or "").lower()
    except Exception:
        return ""


def collect_entities(msp):
    """一次性采集 modelspace 全部实体的 (引用, 类型, 图层, bbox)。

    只跨 COM 边界取一次，后续逐帧过滤全在 Python 内进行，避免“实体数 × 帧数”的往返。
    任一实体读取失败则跳过（不阻断整轮）。
    """
    ents = []
    try:
        n = _retry(lambda: msp.Count)
    except Exception:
        return ents
    for i in range(n):
        try:
            e = _retry(lambda: msp.Item(i))
        except Exception:
            continue
        et = _entity_name(e)
        if et is None:
            continue
        layer = _entity_layer(e)
        bb = entity_bbox(e)
        ents.append({"e": e, "et": et, "layer": layer, "bb": bb})
    return ents


def del_in_region(ents, x0, y0, x1, y1, allowed_types=None, exclude_types=None):
    """删除实体清单中中心完全落在矩形区域内的实体。"""
    to_del = []
    for d in ents:
        e, et, _layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et is None or bb is None:
            continue
        if allowed_types and et not in allowed_types:
            continue
        if exclude_types and et in exclude_types:
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


def del_frame_edges(ents, frame, margin=500):
    """删除图框层上、与外框面积重合>80% 或贴四边的 LINE/LWPOLYLINE/CIRCLE。

    兼容设计院图纸：图框常落在 PUB_TITLE/图签/TK 等非标准图层；若按图层没删到边框，
    再做几何兜底——删 bbox 与本框完全重合的外框多段线（只此一条，不会误删内容）。
    """
    x0, y0, x1, y1 = frame
    frame_layers = {"tukuang", "图框", "0", "pub_title", "图签", "tk", "title", "frame"}
    to_del = []
    for d in ents:
        e, et, layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et not in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline", "AcDbCircle"):
            continue
        ll = (layer or "").lower()
        if ll not in frame_layers and not ll.startswith("tukuang"):
            continue
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
    # 几何兜底：图层匹配没删到边框时，删 bbox 与本框重合的外框多段线（设计院图框在非标准图层）
    if not to_del:
        for d in ents:
            e, et, _layer, bb = d["e"], d["et"], d["layer"], d["bb"]
            if et not in ("AcDbPolyline", "AcDb2dPolyline", "AcDbLWPolyline"):
                continue
            if bb is None:
                continue
            if (abs(bb[0] - x0) < margin and abs(bb[1] - y0) < margin and
                    abs(bb[2] - x1) < margin and abs(bb[3] - y1) < margin):
                to_del.append(e)
    for e in to_del:
        try:
            e.Delete()
        except Exception:
            pass
    return len(to_del)


def _size_name_from_tpl(tpl_dwg):
    """从模板 dwg 文件名反推幅面名（A0~A4）。

    prepare_templates 用冲突规避名（如 _HH_FRAME_A3.dwg）写出，
    这里稳定地剥出 "A3"，避免与原块名 HH_FRAME_A3 自参照。
    """
    base = os.path.splitext(os.path.basename(tpl_dwg))[0]
    if "HH_FRAME_" in base:
        return base.split("HH_FRAME_", 1)[1]
    return base


def insert_frame(msp, frame, tpl_dwg, fields, size_table=None):
    """在 frame 左下角插入公司图框块（tpl_dwg 为 prepare_templates 生成的 *.dwg），等比缩放并回填属性。

    由于模板 dwg 内部是“块 HH_FRAME_Ax 内嵌于模型空间”，直接 InsertBlock 该 dwg 会得到一个
    “外壳块 + 嵌套 HH_FRAME_Ax”的结构，外层 GetAttributes 为空。为拿到可直接回填的 14 个属性，
    采用双插法：先 InsertBlock(dwg) 把 HH_FRAME_Ax 块定义导入目标图，再按名 InsertBlock("HH_FRAME_Ax")
    得到干净、带属性的块引用，最后删掉外壳块。

    返回 (insert, scale)。缩放 = min(W/tw, H/th)（等比，保持模板自身比例）。
    """
    if size_table is None:
        size_table = A_SIZES
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    size_name = _size_name_from_tpl(tpl_dwg)
    tw, th = size_table.get(size_name, (W, H))
    scale = min(W / tw, H / th) if tw and th else 1.0

    # 1) 插入外壳块（导入 HH_FRAME_Ax 块定义）
    wrapper = _retry(lambda: msp.InsertBlock(
        variant_point(x0, y0, 0.0),
        tpl_dwg,
        scale, scale, scale, 0.0,
    ), label="InsertBlock wrapper")
    # 2) 按名插入干净的带属性块
    insert = _retry(lambda: msp.InsertBlock(
        variant_point(x0, y0, 0.0),
        "HH_FRAME_" + size_name,
        scale, scale, scale, 0.0,
    ), label="InsertBlock frame")
    # 3) 删除外壳块，只保留按名插入的块
    try:
        wrapper.Delete()
    except Exception as e:
        print("    delete wrapper warn:", e)

    # 属性回填：只对 tag 命中 fields 的 ATTDEF 写值。
    try:
        attrs = _retry(lambda: insert.GetAttributes())
        for a in attrs:
            tag = a.TagString
            if tag in fields:
                a.TextString = fields[tag]
    except Exception as e:
        print("    set attribs warn:", e)

    return insert, scale


def _is_dwg(path):
    """判断文件是否为真正的二进制 DWG（魔数 AC10xx）。"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as f:
            return f.read(6).startswith(b"AC10")
    except Exception:
        return False


def prepare_templates(app, tpl_dir, out_dir):
    """把 templates/ 下的 HH_FRAME_*.dxf 写成二进制 *.dwg（InsertBlock 必须 DWG 源）。

    关键坑（本机 AutoCAD 2026）：
      - SendCommand('_.-WBLOCK ...') 会让 AutoCAD 挂起，COM 后续全拒（被呼叫方拒绝接收呼叫）。
      - doc.SaveAs(.dwg) 不传 format 时本机可能写出 DXF（magic 非 AC10）。
    因此这里用 doc.SaveAs(dwg, 12)（acNative=12 → 真正的二进制 DWG），文件名加前导下划线
    （_HH_FRAME_Ax.dwg）以避免与模板内部块名 HH_FRAME_Ax 在 InsertBlock 时“自参照”。

    返回 {size_name: dwg_path}。已存在且为有效 DWG 则跳过（模板很少变，省一次 AutoCAD 往返）。
    """
    import glob
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for src in sorted(glob.glob(os.path.join(tpl_dir, "HH_FRAME_*.dxf"))):
        name = os.path.splitext(os.path.basename(src))[0]
        size_name = name.replace("HH_FRAME_", "")
        dst = os.path.join(out_dir, "_" + name + ".dwg")  # 前导下划线规避自参照
        result[size_name] = dst
        # 已有效则跳过
        if _is_dwg(dst):
            print("   模板 %s 已就绪，跳过" % name)
            continue
        # 清掉残留（可能上次写成 .dwg.dxf 或无效文件）
        for cand in (dst, dst + ".dxf"):
            if os.path.exists(cand):
                try:
                    os.remove(cand)
                except Exception:
                    pass
        try:
            app.Visible = True
        except Exception:
            pass
        doc = _retry(lambda: app.Documents.Open(os.path.abspath(src)), label="Open tpl")
        time.sleep(0.5)
        try:
            _retry(lambda: doc.SaveAs(os.path.abspath(dst), 12), label="SaveAs dwg")
        except Exception as e:
            print("   模板 %s SaveAs 失败: %r" % (name, e))
        _retry(lambda: doc.Close(False), label="Close tpl")
        print("   模板 %s -> %s valid=%s" % (name, dst, _is_dwg(dst)))
    return result


def del_frame_lines_acad(ents, frames, margin=1.0):
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
    for d in ents:
        e, et, _layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et == "AcDbLine":
            try:
                s = _retry(lambda: e.StartPoint)
                en = _retry(lambda: e.EndPoint)
            except Exception:
                continue
            if abs(s[0] - en[0]) < 1e-3 and round(s[0], 1) in edge_coords["v"]:
                to_del.append(e)
            elif abs(s[1] - en[1]) < 1e-3 and round(s[1], 1) in edge_coords["h"]:
                to_del.append(e)
        elif et == "AcDbPolyline":
            try:
                coords = list(_retry(lambda: e.Coordinates))
                pts = [(coords[j], coords[j + 1]) for j in range(0, len(coords), 2)]
                closed = bool(_retry(lambda: e.Closed))
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
                    pts.append((_retry(lambda: v.Coordinate)[0], _retry(lambda: v.Coordinate)[1]))
                closed = bool(_retry(lambda: e.Closed))
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


def del_titleblock_acad(ents, tb, maxdim):
    """删除标题栏区域内实体：文本全删；线/多段线完全落在标题栏内的全删，
    仅对跨越标题栏边界的线保留"短线删、长线（可能是尺寸线）保留"策略。

    tb: (x0,y0,x1,y1)
    返回删除数量。
    """
    x0, y0, x1, y1 = tb
    thr = 0.30 * maxdim
    to_del = []
    for d in ents:
        e, et, _layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et == "AcDbBlockReference":
            continue
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        if ex1 < x0 or ex0 > x1 or ey1 < y0 or ey0 > y1:
            continue
        if et in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline"):
            fully_inside = (ex0 >= x0 and ex1 <= x1 and ey0 >= y0 and ey1 <= y1)
            if not fully_inside:
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


def del_edge_markers_acad(ents, outer, strip=10.0):
    """删除沿外框边缘的区号字母/数字（如 A/B/C 与 4/5/6）。"""
    import re
    x0, y0, x1, y1 = outer
    to_del = []
    for d in ents:
        e, et, _layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et not in ("AcDbText", "AcDbMText"):
            continue
        try:
            raw = _retry(lambda: e.TextString)
        except Exception:
            continue
        if not raw or not re.fullmatch(r"[A-Za-z0-9]{1,2}", raw.strip()):
            continue
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
