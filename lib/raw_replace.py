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
            # 竖直框线：只要 x 对齐边框竖边即删，不要求端点“由底到顶”存储
            # （SolidWorks 导出的 LINE 常以“高→低”存储，旧写法要求 (s.y,en.y)==(min,max)
            #  会漏删这些竖线，导致旧框竖线残留在新框上）。与水平分支保持一致。
            if abs(s.x - en.x) < 1e-3 and ("v", round(s.x, 1)) in edge_coords:
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


def _spans_beyond(eb, tb, margin):
    """实体是否「大幅越出」标题栏 bbox（在某一侧超出 margin 以上）。

    用于区分两类跨越标题栏边界的长线：
      - 真实尺寸线：横穿整张图纸，会在标题栏角之外大幅延伸（往往延伸到图框边）；
      - 旧图框/标题栏的格线：被限制在标题栏区域，仅轻微探出角外。
    仅当大幅越出时才判定为「应保留的尺寸线」。
    """
    return (eb[0] < tb[0] - margin or eb[2] > tb[2] + margin or
            eb[1] < tb[1] - margin or eb[3] > tb[3] + margin)


# 标题栏字段标签词：旧标题栏的 图名/图号/比例/日期… 文本落在此区，应清掉；
# 这些是明确的标题栏标签词，几乎不会出现在真实绘图内容里，正则命中即可安全删除。
_TITLE_LABEL_RE = re.compile(
    r"(图名|图号|比例|日期|设计|审核|制图|校对|图别|专业|负责人|审定|"
    r"会签|页码|张次|密级|校核|批准|审查|描图|建设单位|制图日期|设计阶段|"
    r"工程名称|项目名称|设计号|图幅|第.{1,3}张|共.{1,3}张)"
)

# 图框/标题栏图层（不含 0：layer 0 上多为真实绘图内容）
_TITLE_LAYERS = {"tukuang", "图框", "pub_title", "图签", "tk", "title",
                 "frame", "border", "borders", "边框", "titleblock", "图框线", "图框层"}


def delete_titleblock(doc, tb, maxdim=None):
    """删标题栏区域内「旧标题栏自身」实体，保留真实绘图内容。

    住宅电气图等内容铺满全图的图纸，标题栏区域（右下约 14%）与绘图内容大面积重合，
    旧逻辑按整块区域无差别删除会把墙/窗/线/标注/块一并删掉。

    旧标题栏外框多在 TK/图框 等图框层，已由 delete_frame_lines 按坐标清除；
    此处仅做安全网：删除区域内残存的图框层实体，以及明确是标题栏字段标签的文本
    （图名/图号/比例/日期…）。墙/窗/线/标注/块/符号/尺寸线等真实绘图内容一律保留。
    """
    msp = doc.modelspace()
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
        layer = (e.dxf.layer or "").lower()
        if layer in _TITLE_LAYERS or layer.startswith("tukuang"):
            msp.delete_entity(e); n += 1; continue
        if dt in ("TEXT", "MTEXT"):
            txt = (e.text if dt == "MTEXT" else e.dxf.text) or ""
            if _TITLE_LABEL_RE.search(txt):
                msp.delete_entity(e); n += 1
    return n


def delete_old_frame_grid(doc):
    """raw-frame 回退专用：清掉旧「打散」图框层残留的标题栏网格与字段标签。

    适用场景：SolidWorks 导出的图框打散成线段落在专门的图框层（图框/tukuang…），
    该层只承载旧图框/标题栏几何，真实绘图内容在 0/粗实线层。
    新公司图框（HH_FRAME_*）插入在 HH_TITLE/0 层，与本层无交集，故可整层清残留。

    删除：图框层上的 LINE/LWPOLYLINE/POLYLINE（框线/标题栏网格）+ TEXT/MTEXT（旧字段标签）。
    保留：INSERT（SW 中心标记等符号块）与 HATCH（剖面线）等真实标注，绝不误删。
    """
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        layer = (e.dxf.layer or "").lower()
        on_title = layer in _TITLE_LAYERS or layer.startswith("tukuang")
        if not on_title:
            continue
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT"):
            msp.delete_entity(e); n += 1
        # INSERT / HATCH / DIMENSION 等真实标注一律保留
    return n


def delete_titleblock_text(doc, tb):
    """raw-frame 回退专用：删标题栏矩形区内所有独立 TEXT/MTEXT。

    SolidWorks 导出的旧标题栏中，字段值（如零件名、材料、比例）有时落在 layer 0
    而非图框层。这些值已被提取并回填到新 HH_FRAME 的 ATTRIB 中，若不清理会与新
    标题栏重叠。新模板以 INSERT 块形式插入，其字段是块内 ATTRIB，不在 msp 顶层，
    因此删除顶层 TEXT/MTEXT 不会误伤新模板。
    """
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("TEXT", "MTEXT"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        if eb[2] < tb[0] or eb[0] > tb[2] or eb[3] < tb[1] or eb[1] > tb[3]:
            continue
        msp.delete_entity(e); n += 1
    return n


def delete_titleblock_grid(doc, tb):
    """raw-frame 回退专用：删标题栏矩形区内的线类实体（LINE/LWPOLYLINE/POLYLINE）。

    与 delete_old_frame_grid 的区别：后者只清「图框层」（_TITLE_LAYERS）上的
    残留，但 SolidWorks 导出的旧标题栏常把网格/字段线放在通用层（如 layer 0、
    layer 10 或数字层），不在 _TITLE_LAYERS 里，整层清就够不到。本函数直接按
    「落在 tb 矩形里」删，不看层名，与 delete_titleblock_text 同口径（都是
    在已检测到的标题栏范围内无差别清理）。风险与 delete_titleblock_text 同：
    若真实绘图内容与标题栏区域大面积重合（住宅/电气图常见），会误删。
    raw-frame 路径已用 detect_titleblock 把 tb 圈定在小区域，对「打散图框」
    类图纸（标题栏相对独立）安全。保留 INSERT/HATCH 真实标注。
    """
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        if eb[2] < tb[0] or eb[0] > tb[2] or eb[3] < tb[1] or eb[1] > tb[3]:
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
