# -*- coding: utf-8 -*-
"""线框检测（整框替换）复用函数：用于 SolidWorks 导出「打散」图框（0 INSERT 块）的图纸。

从 run_real.py 抽出，供 run_skill.py 在块式 find_titleblocks 0 命中时回退使用，
使 exe 也能处理这类图纸。此处不依赖 matplotlib，避免污染冻结 exe。
"""
import re
from ezdxf import bbox as bbox_mod
from .text_decode import decode_mtext as _decode_mtext


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


def delete_frame_edge_ticks(doc, outer, margin=30.0, max_len=30.0):
    """删旧「打散」图框的边标刻度线（坐标/比例刻度短线）。

    SolidWorks 导出的图框常在边框外侧留一圈短刻度线（左/右边缘水平短线、
    上/下边缘竖直短线），用于标注坐标/比例。这些线落在图纸边距带（旧框
    矩形 outer 外侧）而非边框线上，delete_frame_lines 只删边框矩形四边、
    够不到，导致替换后（尤其新框放大铺满整页时）这些白线残留于新框内、
    与用户所见「上个图框的白线存在」一致。

    判定（2026-08-25 fix 缺陷 H）：短线段（最长分段 ≤ max_len）且其 bbox
    中点位于旧框矩形 outer 的 OUTSIDE、且距外框边 ≤ margin（即落在边距带
    内）→ 视为旧框刻度线删掉。真实绘图内容通常位于外框内侧，边距带内仅有
    旧框系统几何，故安全（实测装配体 24 条刻度线全中、0 条长线误删、
    2308 条框内真实内容不受影响）。
    """
    x0, y0, x1, y1 = outer
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
        # 短段判定：最长分段 ≤ max_len 才视为刻度短线
        try:
            if dt == "LINE":
                s, en = e.dxf.start, e.dxf.end
                seg = ((s.x - en.x) ** 2 + (s.y - en.y) ** 2) ** 0.5
            elif dt == "LWPOLYLINE":
                pts = e.get_points()
                if not pts:
                    continue
                seg = max(((pts[i][0] - pts[i-1][0]) ** 2 +
                           (pts[i][1] - pts[i-1][1]) ** 2) ** 0.5
                          for i in range(1, len(pts)))
            else:
                vs = list(e.vertices())
                if not vs:
                    continue
                seg = max(((vs[i].dxf.location.x - vs[i-1].dxf.location.x) ** 2 +
                           (vs[i].dxf.location.y - vs[i-1].dxf.location.y) ** 2) ** 0.5
                          for i in range(1, len(vs)))
        except Exception:
            continue
        if seg > max_len:
            continue
        # 中点在旧框外、且距外框边 ≤ margin（落在边距带内）
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        inside = (x0 <= cx <= x1) and (y0 <= cy <= y1)
        if inside:
            continue
        dx = max(x0 - cx, 0.0, cx - x1)
        dy = max(y0 - cy, 0.0, cy - y1)
        if (dx * dx + dy * dy) ** 0.5 <= margin:
            msp.delete_entity(e)
            n += 1
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
# 2026-08-26 补：旧会签栏标签（房间号/档案号/项目号）原本不在词表。
_TITLE_LABEL_RE = re.compile(
    r"(图名|图号|比例|日期|设计|审核|制图|校对|图别|专业|负责人|审定|"
    r"会签|页码|张次|密级|校核|批准|审查|描图|建设单位|制图日期|设计阶段|"
    r"工程名称|项目名称|设计号|图幅|第.{1,3}张|共.{1,3}张|"
    r"室别|建筑室|项目号|档案号|阶段)"
)
# 2026-08-26 补：cluster 区内「旧标题栏字段值」（非 ATTRIB、非块内文字，而是
# 散落在 layer 0 / 数字层的旧标题内容）模式。CNG 例子里 A3X3 #3 的源标题值
# "10kV主接线图" 落在 layer 0，layer-0 守卫会按"非标题栏标签"误判保留，与
# 新 HH_FRAME 重叠（用户反馈"没有删除旧图框"）。layer-3 同文本为原图自带的
# 真正图名，应保留。
_TITLE_VALUE_RE = re.compile(
    r"(10kV主接线图|主接线图|平面布置图|电气原理图|装配图|剖面图|展开图|系统图)"
)

# 图框/标题栏图层（不含 0：layer 0 上多为真实绘图内容）
_TITLE_LAYERS = {"tukuang", "图框", "pub_title", "图签", "tk", "title",
                 "frame", "border", "borders", "边框", "titleblock", "图框线", "图框层"}


# 内容层白名单：detect_titleblock tb 圈已收紧，但若仍误入内容区，delete_titleblock_grid
# 应跳过这些「明显是真实绘图内容」的层。覆盖建筑/电气/暖通常见层名（大小写不敏感）。
# 旧标题栏网格线一般落在通用层（0、10、数字层）而非这些「领域层」，故白名单不会
# 误伤旧标题栏清场。
_CONTENT_LAYER_HINTS = frozenset({
    # 建筑
    "wall", "walls", "墙", "墙体", "wall-1", "wall-2",
    "window", "windows", "窗", "窗户",
    "door", "doors", "门", "门洞", "门联窗",
    "column", "columns", "柱", "柱子", "轴线",
    "furn", "furniture", "家具", "洁具", "橱柜", "柜台",
    "stair", "楼梯", "台阶", "坡道",
    "room", "房间", "功能", "隔墙",
    # 电气
    "wire", "wires", "电线", "导线", "线槽", "桥架", "母线", "母线槽", "配电",
    "dj", "灯具", "灯", "lamp", "light", "lighting", "开关", "插座", "配电箱",
    "fire", "消防", "报警", "烟感", "手报", "广播", "应急照明",
    # 暖通/给排水
    "hvac", "暖通", "空调", "空调位", "风口", "diff", "风管", "水管", "给水",
    # 标注/文字
    "文字", "text", "annotation", "注记", "标注", "tag", "label",
    "dim", "dimension", "defpoints",  # defpoints=AutoCAD 尺寸默认层
})


def _is_zero_layer(layer):
    """图层感知守卫：layer 0 与纯数字层（下载/第三方 DWG 常把真实绘图内容堆在这些层）
    视为受保护内容层。清理函数默认不删其上的 TEXT/MTEXT/线类，避免误删设备材料表等
    真实内容；只有明确属于旧标题栏结构（ATTDEF/ATTRIB、或命中 _TITLE_LABEL_RE 的
    标题标签）才例外删除。旧标题栏框线/网格通常落在命名图框层（TK/图框/PUB_TEXT…），
    由 delete_old_frame_grid / delete_frame_lines 按层名/几何清除，不依赖 0 层。"""
    l = (layer or "").strip()
    return l == "0" or (l.isdigit() and l != "")


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


def delete_titleblock_cluster_text(doc, tb, outer):
    """raw-frame 回退增强：清掉「标题栏簇」（标题栏 + 紧邻的继电器表/明细栏）区内全部
    独立 TEXT/MTEXT，解决 92DZ1 类图「旧继电器表残留 + 新框属性值混乱」。

    根因：detect_titleblock 只圈出右下角标题栏小方块；继电器表/端子表常位于其左/上方，
    不在 tb 内，delete_titleblock_text 按 tb 删会漏 → 旧表文字残留在新框里。
    修复：把删除区向右下角框架内扩展（框架右 0.45W × 下 0.55H，与 tb 合并，且限制在
    框架内），在该区内无差别删 TEXT/MTEXT；但跳过 _CONTENT_LAYER_HINTS 内容层
    （墙/窗/线/标注等真实绘图内容），避免误删原理图。INSERT/HATCH 不删。
    """
    if not outer:
        return 0
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    cx0 = xR - 0.45 * W
    cy0 = yB
    cx1 = xR
    cy1 = yB + 0.55 * H
    zx0 = max(min(tb[0], cx0), xL)
    zy0 = max(min(tb[1], cy0), yB)
    zx1 = min(max(tb[2], cx1), xR)
    zy1 = min(max(tb[3], cy1), yT)
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        is_att = dt in ("ATTDEF", "ATTRIB")
        if dt not in ("TEXT", "MTEXT", "ATTDEF", "ATTRIB"):
            continue
        # ATTDEF/ATTRIB 是标题栏数据实体（属性定义/属性引用），结构上属于旧图框
        # 标题栏，不属于自由文字绘图内容；不受 _CONTENT_LAYER_HINTS 内容层白名单保护，
        # 否则落在「文字」层的旧标题栏 ATTDEF（如 92DZ1 的「项目名称/比例/日期」）
        # 会被白名单跳过而残留，与新 HH_FRAME 标题栏重叠（用户反馈「名字位置还是有偏差」）。
        if not is_att:
            layer = (e.dxf.layer or "").lower()
            if layer in _CONTENT_LAYER_HINTS:
                continue
            # 图层感知：layer 0 / 数字层上的真实绘图内容（如设备材料表）绝不误删；
            # 仅命中标题栏标签（图名/图号…）的旧文本才删，避免与新 HH_FRAME 重叠。
            # 2026-08-26 补：旧会签栏中文标签常带空格对齐（"制  图"/"校  对"/
            # "设  计"/"审  核"），正则匹配前先去除空白，让"制图"/"校对"等能
            # 命中 _TITLE_LABEL_RE，否则会被误判为"非标题栏文本"而保留。
            # 2026-08-26 v3 补：cluster 区 layer 0 上的「旧标题栏字段值」
            # （如 10kV主接线图、平面布置图）不在标签词表里，按标签正则匹配
            # 不到会被守卫保留；单独检查 _TITLE_VALUE_RE 命中则放行删除。
            if _is_zero_layer(layer):
                _txt = (e.text if dt == "MTEXT" else e.dxf.text) or ""
                _txt_compact = re.sub(r'\s+', '', _txt)
                if not (_TITLE_LABEL_RE.search(_txt_compact)
                        or _TITLE_VALUE_RE.search(_txt_compact)):
                    continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        if eb[2] < zx0 or eb[0] > zx1 or eb[3] < zy0 or eb[1] > zy1:
            continue
        msp.delete_entity(e); n += 1
    return n


def delete_titleblock_cluster_grid(doc, outer, tb=None):
    """删「标题栏簇」区（含紧邻的明细栏/BOM 表格）内的 LINE/LWPOLYLINE/POLYLINE 网格。

    与 delete_titleblock_cluster_text 配对：后者清文字，本函数清表格网格。
    92DZ1 / 装配体 类图纸的源「设备材料表/明细栏」是 LWPOLYLINE 矩形网格 + 文字，
    仅删文字会留下整片空白表格压在新 HH_FRAME 标题栏上方/相切。

    删线规则（必须同时满足，避免误伤原理图长线/尺寸线）：
      - 落在簇区 [right 45% × bottom 55% of outer] ∪ tb（与文字同区）
      - 图层非 _CONTENT_LAYER_HINTS
      - 短段：最长分段 ≤ max(W,H) * 0.45（标题栏格线通常 < 200mm；原理图长线/Wire 远超此值）
    INSERT / HATCH / DIMENSION 等真实标注一律保留。
    """
    if not outer:
        return 0
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    cx0 = xR - 0.45 * W
    cy0 = yB
    cx1 = xR
    cy1 = yB + 0.55 * H
    if tb:
        zx0 = max(min(tb[0], cx0), xL)
        zy0 = max(min(tb[1], cy0), yB)
        zx1 = min(max(tb[2], cx1), xR)
        zy1 = min(max(tb[3], cy1), yT)
    else:
        zx0, zy0, zx1, zy1 = cx0, cy0, cx1, cy1
    long_th = max(W, H) * 0.45
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        layer = (e.dxf.layer or "").lower()
        if layer in _CONTENT_LAYER_HINTS:
            continue
        # 图层感知：layer 0 / 数字层上的真实内容（设备材料表网格等）跳过，不误删
        if _is_zero_layer(layer):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        if b.extmax.x < zx0 or b.extmin.x > zx1 or b.extmax.y < zy0 or b.extmin.y > zy1:
            continue
        # 短段判定：最长分段 ≤ long_th 才视为表格格线
        try:
            if dt == "LINE":
                s, en = e.dxf.start, e.dxf.end
                seg = ((s.x - en.x) ** 2 + (s.y - en.y) ** 2) ** 0.5
                if seg > long_th:
                    continue
            elif dt == "LWPOLYLINE":
                pts = e.get_points()
                if len(pts) >= 2:
                    seg = max(((pts[i][0] - pts[i-1][0]) ** 2 +
                               (pts[i][1] - pts[i-1][1]) ** 2) ** 0.5
                              for i in range(1, len(pts)))
                    if seg > long_th:
                        continue
            elif dt == "POLYLINE":
                vs = list(e.vertices())
                if len(vs) >= 2:
                    seg = max(((vs[i].dxf.location.x - vs[i-1].dxf.location.x) ** 2 +
                               (vs[i].dxf.location.y - vs[i-1].dxf.location.y) ** 2) ** 0.5
                              for i in range(1, len(vs)))
                    if seg > long_th:
                        continue
        except Exception:
            continue
        msp.delete_entity(e)
        n += 1
    return n


def delete_titleblock_cluster_table(doc, outer, tb=None):
    """删「标题栏簇」区内的 ACAD_TABLE（AutoCAD 原生明细栏/BOM 表格）。

    与 cluster_text/cluster_grid 配对：92DZ1/装配体 类的源「设备材料表/明细栏」
    常是 ACAD_TABLE 原生表对象（不是 LWPOLYLINE+TEXT），前述函数只删
    LINE/LWPOLYLINE/POLYLINE 与 TEXT/MTEXT，完全够不到 ACAD_TABLE → 旧表
    整张压在新 HH_FRAME 标题栏上方相切（用户反馈「还是有重合」）。

    ACAD_TABLE 是单实体、无分段，故不判「短段」，只判：
      - 落在簇区 [right 45% × bottom 55% of outer] ∪ tb（与文字/网格同区）
      - 与簇区有交叠（非完全包含，避免贴边 1mm 漏删）即删
    真实绘图内容（非 ACAD_TABLE 类型）不受影响。
    """
    if not outer:
        return 0
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    cx0 = xR - 0.45 * W
    cy0 = yB
    cx1 = xR
    cy1 = yB + 0.55 * H
    if tb:
        zx0 = max(min(tb[0], cx0), xL)
        zy0 = max(min(tb[1], cy0), yB)
        zx1 = min(max(tb[2], cx1), xR)
        zy1 = min(max(tb[3], cy1), yT)
    else:
        zx0, zy0, zx1, zy1 = cx0, cy0, cx1, cy1
    # ACAD_TABLE（明细栏/BOM 原生表）属图纸真实内容，保留不删。
    # 装配图/零件图的明细栏是必要内容（列出组成件），误删=丢失信息；
    # 仅当该表「完全位于标题栏微区 tb 内」（即它本就是旧标题栏的一部分、
    # 而非独立明细栏）时才删除。常规独立明细栏在 tb 上方/左侧，保持保留。
    # 注：92DZ1 等住宅电气图的旧「设备材料表」为 LWPOLYLINE+TEXT（非 ACAD_TABLE），
    # 仍由 cluster_grid/cluster_text 清理，不受此处影响。
    if tb is None:
        return 0
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        if e.dxftype() != "ACAD_TABLE":
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        # 仅当表格整体落在 tb 微区内才视为旧标题栏内嵌表而删除
        if b.extmin.x >= tb[0] and b.extmax.x <= tb[2] and b.extmin.y >= tb[1] and b.extmax.y <= tb[3]:
            msp.delete_entity(e)
            n += 1
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

    2026-08-24 fix (#3 过度删 治标)：加 _CONTENT_LAYER_HINTS 白名单。
    即使 tb 圈仍偏大（建筑/电气图内容铺到 tb 区），白名单内的领域层
    （wall/wire/window/dj/文字/空调位…）也会被跳过，旧标题栏通用层（0/10/数字）
    仍正常清理。
    """
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        layer = (e.dxf.layer or "").lower()
        if layer in _CONTENT_LAYER_HINTS:
            continue  # 内容层白名单：保护 wall/wire/window/dj/文字/空调位 等
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


def delete_old_frame_grid_extended(doc, outer, tb=None):
    """扩展版旧图框栅格清理：0 通用层 + 长度 > 4000mm 的长直线 + 落在「旧标题栏区」。

    2026-08-24 fix (#10 旧白框栅格残留治本)：
      - 原 `delete_old_frame_grid` 只清 _TITLE_LAYERS（TK/图框/...）上的线类，对 0 通用层
        上的「旧白框栅格 + 旧标题栏栅格」无效（SolidWorks 把这些打散到 0 层）。
      - 住宅电气图（强电平面.dxf）实测：0 层有 10 条长直线构成两个矩形（"标准层照明"
        行 + "八-十三层"行 + "注:B1栋"分隔线），是旧白框栅格核心，但 4.8% tb bbox 圈
        不到（这些线在 tb 顶上方 5~15m）。
      - 规则：x > xR-0.30W AND y < yB+0.30H（旧标题栏区）AND layer ∈ {"0"} AND 长直线
        (min(w,h)<1 且 max(w,h)>4000) → 视为旧白框栅格，删。
      - 真实内容（1-1 剖面/卧室/A/C/K/强欣设计图库）均在 y > yB+0.30H = -57347 或
        x < xR-0.30W = 104605，本规则不会误伤。
      - 旧白框栅格通常成对出现（水平 + 垂直 + 水平 + 垂直 → 矩形），单条删除会破坏
        视觉但不留残线；与 `delete_old_frame_grid`（清 TK 层）互补。
    """
    msp = doc.modelspace()
    xL, yB, xR, yT = outer
    W = max(1e-6, xR - xL)
    H = max(1e-6, yT - yB)
    x_min = xR - 0.30 * W  # = 104605 for 强电平面
    y_max = yB + 0.30 * H  # = -57347 for 强电平面
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        layer = (e.dxf.layer or "").upper()
        if layer not in ("0",):
            continue  # 只清 0 通用层（保护 wall/wire/window/dj/文字 等内容层）
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        w = b.extmax.x - b.extmin.x
        h = b.extmax.y - b.extmin.y
        # 长直线：min(w,h) < 1.0（实际直线/极扁矩形）且 max(w,h) > 4000
        if min(w, h) >= 1.0:
            continue
        if max(w, h) <= 4000:
            continue
        # 落在旧标题栏区
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        if cx < x_min or cy > y_max:
            continue
        msp.delete_entity(e)
        n += 1
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
