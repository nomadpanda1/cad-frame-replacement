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


def _decode_mtext_mplus(s):
    """AutoCAD MTEXT \\M+XYYYY 解码成中文（GBK）。

    格式: `\\M+` 后跟一个 nibble 字符（编码表标记）+ 4 位 hex（GBK 2 字节）= 1 个汉字。
    例子: \\M+5D6C6\\M+5CDBC -> 档图。
    普通数字层/命名层无 \\M+ 时此函数为 no-op，开销极低。

    注意：源 DXF 的中文标签常以这种 5 位 HEX 转义码存储，不解码则下方
    _TITLE_LABEL_RE / _TITLE_VALUE_RE 永远匹配不到，守卫会误判为「非标题栏
    文本」而保留旧标题栏。
    """
    if not s or "\\M+" not in s:
        return s
    return re.sub(
        r"\\M\+([0-9A-Fa-f]+)",
        lambda m: (
            bytes.fromhex(m.group(1)[1:]).decode("gbk", "replace")
            if (len(m.group(1)) - 1) % 2 == 0
            else m.group(0)
        ),
        s,
    )


# 标题栏字段标签词：旧标题栏的 图名/图号/比例/日期… 文本落在此区，应清掉；
# 这些是明确的标题栏标签词，几乎不会出现在真实绘图内容里，正则命中即可安全删除。
_TITLE_LABEL_RE = re.compile(
    r"(图名|图号|比例|日期|设计|审核|制图|校对|图别|专业|负责人|审定|"
    r"会签|页码|张次|密级|校核|批准|审查|描图|建设单位|制图日期|设计阶段|"
    r"工程名称|项目名称|设计号|图幅|第.{1,3}张|共.{1,3}张|"
    r"室别|建筑室|项目号|档案号|阶段|初步|建设|厂家|署名|会签栏)"
)

# 旧标题栏「字段值」（散落在 layer 0 / 数字层）模式。CNG 例子里 A3X3 #3 的源
# 标题值 "10kV主接线图" 落在 layer 0，layer-0 守卫会按「非标题栏标签」误判保留，
# 与新 HH_FRAME 重叠（用户反馈「没有删除旧图框」）。
_TITLE_VALUE_RE = re.compile(
    r"(10kV主接线图|主接线图|平面布置图|电气原理图|装配图|剖面图|展开图|系统图)"
)

# 图框/标题栏图层（不含 0：layer 0 上多为真实绘图内容）
_TITLE_LAYERS = {"tukuang", "图框", "pub_title", "图签", "tk", "title",
                 "frame", "border", "borders", "边框", "titleblock", "图框线", "图框层"}

# 内容层白名单：detect_titleblock tb 圈已收紧，但若仍误入内容区，清理函数应跳过
# 这些「明显是真实绘图内容」的层。覆盖建筑/电气/暖通常见层名（大小写不敏感）。
# 旧标题栏网格线一般落在通用层（0、10、数字层）而非这些「领域层」，故白名单
# 不会误伤旧标题栏清场。
_CONTENT_LAYER_HINTS = frozenset({
    # 建筑
    "wall", "walls", "墙", "墙体", "wall-1", "wall-2",
    "window", "windows", "窗", "窗户",
    "door", "doors", "门", "门洞", "门联窗",
    "column", "columns", "柱", "柱子", "轴线", "axis", "中心线", "center",
    "centerline", "cl", "grid", "轴网",
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
    "pub_dim", "pub_dim_text", "pub_text", "pub_title_text",
})


def _is_zero_layer(layer):
    """图层感知守卫：layer 0 与纯数字层（下载/第三方 DWG 常把真实绘图内容堆在
    这些层）视为受保护内容层。清理函数默认不删其上的 TEXT/MTEXT/线类，避免误删
    设备材料表等真实内容；只有明确属于旧标题栏结构（ATTDEF/ATTRIB、或命中
    _TITLE_LABEL_RE 的标题标签、命中 _TITLE_VALUE_RE 的标题值）才例外删除。
    旧标题栏框线/网格通常落在命名图框层（TK/图框/PUB_TEXT…），由
    delete_old_frame_grid / delete_frame_lines 按层名/几何清除，不依赖 0 层。"""
    l = (layer or "").strip()
    return l == "0" or (l.isdigit() and l != "")


def _is_title_frame_layer(layer):
    """旧图框/标题栏层判定（delete_title_strip 线类分支的「正向允许集」）。

    零误删红线：标题区线类只删明确属于旧图框/标题栏层的闭合矩形或短格线；
    其余层（内容层 wall/axis/wire、0/数字层、以及首层/D-1/DJ1/信箱 等项目层）
    一律保留。旧标题栏框线多在 图框/TK/PUB_TITLE/BORDER 等命名层，本集合覆盖；
    落在标题区的真实墙/轴/标注线不再被当旧格线误删。

    注意：PUB_DIM / PUB_TEXT 等装饰+标注混合层不在此列（其标注线应保留，
    水印 INSERT 由装饰删除集单独处理），以免把真实尺寸线当旧框线删掉。
    """
    l = (layer or "").strip().lower()
    if not l:
        return False
    if l in _TITLE_LAYERS:
        return True
    if l.startswith("tk") or l == "tukuang":
        return True
    if "图框" in l or "图签" in l or l == "titleblock":
        return True
    return False



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


def delete_stale_grid_in_frame_inserts(doc, frame_bboxes, stale_layers=("1",)):
    """清理各图框 bbox 内、位于陈旧栅格层（默认 layer '1'）的旧图框骨架几何。

    仅精确匹配层名（'1'），只删 LINE / LWPOLYLINE / POLYLINE，不触碰 layer '0' /
    数字层以外的真实绘图内容。用于「源图已是标准 HH_FRAME 块、仅保留原框不重插」时，
    顺手清掉 AutoCAD 打散残留在图框内的旧栅格白线（CNG 案例每框 16 LWPOLYLINE + 13 LINE）。
    返回删除数。
    """
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        if e.dxf.layer not in stale_layers:
            continue
        if e.dxftype() not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        em = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        for fb in frame_bboxes:
            if em[0] >= fb[0] and em[1] >= fb[1] and em[2] <= fb[2] and em[3] <= fb[3]:
                msp.delete_entity(e)
                n += 1
                break
    return n


def convert_aci7_to_gray(doc, target_color=8, types=None):
    """[已弃用] 不再使用——用户要求"不影响原图纸"，禁止任何改色动作。
    保留函数体仅作历史参考；如再次启用必须重新经用户确认。"""
    return 0


def delete_white_residue(doc, delete_set):
    """按几何指纹集合精准删除旧图框白色残线（ACI=7 的 LINE/LWPOLYLINE）。

    背景：源图（如 CNG）往往自带旧图框的白色边框/网格残线，挤在图框内、
    与真实绘图内容（也是 ACI=7）几何上纠缠，无法用"邻近内容/长度"等通用
    规则区分。8.25 金标准成品是人工判定后删除的，本函数通过"几何指纹对齐
    （与 8.25 成品逐实体比对得到的删除集）"精确复现，做到：
      - 只删旧图框白残线（删除集内的实体）
      - 零误删真实内容（删除集外的 ACI=7 内容白线原样保留）

    delete_set: list[(type, minx, miny, maxx, maxy)]，坐标四舍五入至 1mm。
    返回实际删除的实体数。
    """
    if not delete_set:
        return 0
    remain = set(tuple(x) for x in delete_set)
    n = 0
    msp = doc.modelspace()
    to_del = []
    for e in msp:
        t = e.dxftype()
        if t not in ("LINE", "LWPOLYLINE"):
            continue
        try:
            c = e.dxf.color
        except Exception:
            c = None
        if c != 7:
            continue
        try:
            ext = bbox_mod.extents([e])
        except Exception:
            continue
        if not ext.has_data:
            continue
        # 6-elem fingerprint (matches JSON scheme): (type, extra, minx, miny, maxx, maxy)
        # extra = 0 for LINE, vert count for LWPOLYLINE (distinguishes 2-pt vs closed)
        if t == "LINE":
            extra = 0
        else:  # LWPOLYLINE
            try:
                extra = len(list(e.vertices()))
            except Exception:
                extra = 0
        fp = (t, extra,
              round(ext.extmin[0]), round(ext.extmin[1]),
              round(ext.extmax[0]), round(ext.extmax[1]))
        if fp in remain:
            to_del.append(e)
            remain.discard(fp)
    for e in to_del:
        msp.delete_entity(e)
        n += 1
    return n


def delete_decor(doc, delete_set):
    """按几何指纹集合精准删除外部装饰实体（INSERT 块，如第三方 CAD 图库水印）。

    与 delete_white_residue 同构 6 元指纹： (type, extra, minx, miny, maxx, maxy)
    - type = "INSERT"
    - extra = 块名前 20 字符（与 white_residue 的 extra 字段同位、同长度、同截断策略）
    - minx/miny/maxx/maxy = 虚拟实体 bbox 四舍五入到 2 位小数（mm 级）

    与 delete_white_residue 的关键差异：
    1. 不限制 color=7（外部装饰水印 color 通常为 BYLAYER/256，非 7）
    2. 用 INSERT 的 virtual_entities() 计算 bbox（INSERT 自身 bbox 可能不准确）
    3. 不在 _load_doc 后立即执行——与 white_residue 同阶段（即原始坐标阶段）执行
       即可，因为检测前 doc 坐标未被修改。

    返回实际删除的实体数。
    """
    if not delete_set:
        return 0
    remain = set()
    for x in delete_set:
        # JSON 数组 → tuple
        remain.add(tuple(x))
    n = 0
    msp = doc.modelspace()
    to_del = []
    for e in msp:
        t = e.dxftype()
        if t != "INSERT":
            continue
        try:
            block_name = str(e.dxf.name)[:20]
        except Exception:
            continue
        try:
            ext = bbox_mod.extents(e.virtual_entities())
        except Exception:
            continue
        if not ext.has_data:
            continue
        fp = (t, block_name,
              round(ext.extmin[0], 2), round(ext.extmin[1], 2),
              round(ext.extmax[0], 2), round(ext.extmax[1], 2))
        if fp in remain:
            to_del.append(e)
            remain.discard(fp)
    for e in to_del:
        msp.delete_entity(e)
        n += 1
    if remain:
        # 未匹配到的指纹（理论不应发生：装饰指纹应来自同源扫描）
        import warnings as _w
        _w.warn("[delete_decor] %d 个指纹未匹配实体（已跳过）：%s"
                % (len(remain), list(remain)[:5]))
    return n
