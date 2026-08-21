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


# win32com 仅在 Windows + 本机有 AutoCAD 的 COM 直处理路径才会用到；
# 移到函数内惰性导入，避免 Linux/无 pywin32 环境下 import acad_com 直接崩溃
# （run_skill.py 在模块顶部就 from lib import acad_com，必须可无 win32com 导入）。

# 公司标准图框尺寸（毫米），用于按外框比例选模板、算等比缩放。
A_SIZES = {
    "A0": (1189, 841),
    "A1": (841, 594),
    "A2": (594, 420),
    "A3": (420, 297),
    "A3_WIDE": (604, 299),
    "A4": (297, 210),
    # 竖版（Portrait）占位：后续添加 HH_FRAME_*V.dxf 模板后自动生效
    "A0V": (841, 1189),
    "A1V": (594, 841),
    "A2V": (420, 594),
    "A3V": (297, 420),
    "A4V": (210, 297),
}


def variant_point(x, y, z=0.0):
    """InsertBlock 需要的插入点 VARIANT。"""
    import win32com.client
    return win32com.client.VARIANT(
        win32com.client.pythoncom.VT_ARRAY | win32com.client.pythoncom.VT_R8,
        [float(x), float(y), float(z)],
    )


def get_acad_dispatch():
    """只取已打开的 AutoCAD 实例（不自动启动，Dispatch 启动的实例 COM 不稳）。"""
    import win32com.client
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


def _dyn(obj):
    """把一个 COM 对象重新包装成 late-bound（动态分派）代理。

    为什么必须这么做（本机实测根因）：
    win32com 默认 early-binding 会把 msp.Item(i) 等返回成**基类型 IAcadEntity**
    （无论实体实际是 Line/Polyline/Text/BlockReference），于是 StartPoint /
    Coordinates / InsertionPoint / Center / Radius / TextString / TagString /
    GetAttributes / GetBoundingBox 等“子类型属性”全部报 AttributeError。

    原来这些读取都被 _retry 包着，于是每遇到一个实体就：抛 AttributeError →
    睡 1.5s → 重试 6 次 ≈ 9s，单图几百实体累计上千秒，表现成“COM 永久卡死”
    （其实是被海量异常-重试拖死，shell 超时被杀）。

    改用 win32com.client.dynamic.Dispatch 让属性在运行时按**实际**类型解析，
    与本地缓存的 typelib 版本（本机甚至是“AutoCAD 2025 Type Library”）无关，
    彻底消除该问题。返回对象底层仍是同一个 COM 指针，Delete/InsertBlock 等照常可用。
    """
    import win32com.client
    return win32com.client.dynamic.Dispatch(obj)


def _prune_deleted(ents, to_del):
    """删除后把已删实体从共享 ents 列表中剔除。

    根因（本机实测）：del_* 函数通过 COM 删除实体后，该实体的 Python 代理对象并未
    从 ents 列表移除。后续 del_* 函数再对这些“已删除”对象读属性（TextString /
    StartPoint 等）时，AutoCAD COM 调用会**永久阻塞**（既不抛异常也不返回），
    表现成“卡死”，而 _retry 只能抓异常、抓不住阻塞。每次删除批次后把已删项剔除，
    后续函数便不会再触碰死对象。
    """
    if not to_del:
        return
    dead = {id(e) for e in to_del}
    ents[:] = [d for d in ents if id(d["e"]) not in dead]


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
            e = _dyn(_retry(lambda: msp.Item(i)))
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


# 图框类图层（设计院图纸图框常落在这些层之一；"frame" 覆盖大小写）
FRAME_LAYERS = {"tukuang", "图框", "0", "pub_title", "图签", "tk", "title", "frame",
                "border", "borders", "边框", "titleblock", "图框线", "图框层"}
# 仅这些实体类型按"框内残留"策略删除（避免误删图内文本/块/标注）
_FRAME_LINE_TYPES = ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline",
                     "AcDbLWPolyline", "AcDbArc")
# 框内整框清除时排除默认层 0：大量建筑/电气图把局部详图、符号、标注放在 layer 0，
# 若按图框层整框删除会把这些主内容误删。外框边线仍可由 del_frame_edges（带几何约束）处理。
_FRAME_INTERIOR_LAYERS = FRAME_LAYERS - {"0"}

# 标题栏字段标签词：旧标题栏的 图名/图号/比例/日期… 文本落在此区，应清掉；
# 这些是明确的标题栏标签词，几乎不会出现在真实绘图内容里，正则命中即可安全删除，
# 不会误删房间名/回路号/引线标注等内容文本。
import re
_TITLE_LABEL_RE = re.compile(
    r"(图名|图号|比例|日期|设计|审核|制图|校对|图别|专业|负责人|审定|"
    r"会签|页码|张次|密级|校核|批准|审查|描图|建设单位|制图日期|设计阶段|"
    r"工程名称|项目名称|设计号|图幅|第.{1,3}张|共.{1,3}张)"
)


def del_frame_layer_inside(ents, frame, margin=20.0):
    """删除图框类图层上、完全落在旧框 bbox 内的全部线类实体。

    解决"双线/多线图框 + 标题栏内部分隔线"残留在新框上的问题：这些旧框内部线条
    （内框、标题栏网格、竖向分隔线）并不与新框外边对齐，del_frame_lines_acad（按外边
    坐标精确匹配）与 del_frame_edges（面积>80% 或贴边）都删不到。本函数按"图层 + 完全
    落在旧框内"直接整框清除——住宅案例十首层配电(18条 FRAME 层线)、首二层商场(1条)
    的残线正是这一类。

    margin 仅用于吸收检出框与实绘外框之间几单位的拟合偏差（默认 20，相对万级图幅可忽略，
    不会外溢到框外内容）。删层限制为线类，绝不碰图内 TEXT/INSERT/DIMENSION。
    """
    x0, y0, x1, y1 = frame
    to_del = []
    for d in ents:
        e, et, layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et not in _FRAME_LINE_TYPES:
            continue
        ll = (layer or "").lower()
        if ll not in _FRAME_INTERIOR_LAYERS and not ll.startswith("tukuang"):
            continue
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        if (ex0 >= x0 - margin and ex1 <= x1 + margin and
                ey0 >= y0 - margin and ey1 <= y1 + margin):
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
    to_del = []
    for d in ents:
        e, et, layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et not in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline", "AcDbCircle"):
            continue
        ll = (layer or "").lower()
        if ll not in FRAME_LAYERS and not ll.startswith("tukuang"):
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


def insert_frame(msp, frame, tpl_dwg, fields, size_table=None, fit="max"):
    """在 frame 处插入公司图框块（tpl_dwg 为 prepare_templates 生成的 *.dwg），缩放并回填属性。

    双插法（外壳块导入 HH_FRAME_Ax 定义 → 按名插干净块 → 删外壳）同前。

    缩放与 ezdxf 路径的 lib/block_replace._compute_transform(fit) 完全对齐：
    等比缩放 s + 居中插入。此前用「非等比拉伸 xscale=W/tw, yscale=H/th」会把标题栏
    比例压扁/拉长（尤其检出框比例与模板 √2 略有出入的非标幅面），这正是本地 --dwg
    输出比网站（ezdxf）观感差的根因。统一为等比+居中后两者几何一致。
    fit 默认 "max"（满填），与网站默认一致；也可由调用方按 --fit 覆盖。
    """
    if size_table is None:
        size_table = A_SIZES
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    size_name = _size_name_from_tpl(tpl_dwg)
    # 模板实际幅面：优先用上游即时生成的精确尺寸（size_table，由 for_frame 给出），
    # 缺则退回 A_SIZES。tw/th 与 frame 同单位，等比缩放 s 即「图形单位/模板单位」。
    tw, th = size_table.get(size_name, (W, H))
    if fit == "min":
        s = min(W / tw, H / th)
    elif fit == "width":
        s = W / tw
    elif fit == "height":
        s = H / th
    else:  # max / 默认
        s = max(W / tw, H / th)
    s = s if (tw and th and s > 0) else 1.0
    # 模板块以 (0,0) 为左下角，居中映射到 frame（与 _compute_transform 一致）
    target_x = x0 + (W - tw * s) / 2
    target_y = y0 + (H - th * s) / 2
    ins_pt = variant_point(target_x, target_y, 0.0)

    # 1) 插入外壳块（导入 HH_FRAME_Ax 块定义）
    wrapper = _retry(lambda: msp.InsertBlock(
        ins_pt,
        tpl_dwg,
        s, s, 1.0, 0.0,
    ), label="InsertBlock wrapper")
    # 2) 按名插入干净的带属性块
    insert = _retry(lambda: msp.InsertBlock(
        ins_pt,
        "HH_FRAME_" + size_name,
        s, s, 1.0, 0.0,
    ), label="InsertBlock frame")
    # 3) 删除外壳块，只保留按名插入的块
    try:
        wrapper.Delete()
    except Exception as e:
        print("    delete wrapper warn:", e)

    # 属性回填：只对 tag 命中 fields 的 ATTDEF 写值。
    # 注意：insert / attrs / a 必须 early-binding——InsertBlock 返回的是真正的
    # IAcadBlockReference 子类型，GetAttributes 在其上正常返回属性集合；若误用
    # _dyn 包成动态代理，含 out 参数的 GetAttributes 会被动态分派成 tuple，
    # 导致“'tuple' object has no attribute 'GetTypeInfo'”而无法回填属性。
    try:
        attrs = _retry(lambda: insert.GetAttributes())
        for a in attrs:
            try:
                tag = a.TagString
                if tag not in fields:
                    continue
                v = fields[tag]
                if v is None:
                    v = ""
                v = str(v).replace("\r", " ").replace("\n", " ").strip()
                # 占位标签当值（提取到的是 tag 名本身，如 TITLE="TITLE"）→ 清空，
                # 不把占位符写进标题栏；validators 已挡大部分，这里兜底。
                if v and v.upper() == str(tag).upper():
                    v = ""
                # 保证新框字段值用中文样式（HH_CHN），避免源图缺该样式时回填值变 ????。
                # InsertBlock 已把模板样式导入目标图，这里显式绑定更稳。
                try:
                    if a.StyleName != "HH_CHN":
                        a.StyleName = "HH_CHN"
                except Exception:
                    pass
                a.TextString = v
            except Exception:
                continue
    except Exception as e:
        print("    set attribs warn:", e)

    return insert, (s, s)


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
        size_name = os.path.splitext(os.path.basename(src))[0].replace("HH_FRAME_", "")
        result[size_name] = prepare_one(app, src, out_dir)
    return result


def prepare_one(app, src_dxf, out_dir):
    """把单个模板 DXF 转成二进制 DWG，返回 dwg 路径。

    从 prepare_templates 抽出，供「按检出框比例即时生成的模板」按需转换
    （非标幅面的模板在跑之前不可能预先枚举出来，只能边检测边生成）。
    """
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src_dxf))[0]
    dst = os.path.join(out_dir, "_" + name + ".dwg")  # 前导下划线规避自参照
    if _is_dwg(dst):
        print("   模板 %s 已就绪，跳过" % name)
        return dst
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
    doc = _retry(lambda: app.Documents.Open(os.path.abspath(src_dxf)), label="Open tpl")
    time.sleep(0.5)
    try:
        _retry(lambda: doc.SaveAs(os.path.abspath(dst), 12), label="SaveAs dwg")
    except Exception as e:
        print("   模板 %s SaveAs 失败: %r" % (name, e))
    _retry(lambda: doc.Close(False), label="Close tpl")
    print("   模板 %s -> %s valid=%s" % (name, dst, _is_dwg(dst)))
    return dst


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
    _prune_deleted(ents, to_del)
    return n


def del_titleblock_acad(ents, tb, maxdim=None):
    """删除标题栏区域内「属于旧标题栏自身」的实体，保留真实绘图内容。

    住宅电气图等内容铺满全图的图纸，标题栏区域（右下约 14%）与绘图内容大面积重合，
    旧逻辑按整块区域无差别删除，会把墙/窗/线/标注/块一并删掉（用户反馈“依旧缺失”）。

    旧标题栏外框多在 TK/图框 等图框层，已由 del_frame_layer_inside 整框清除；
    此处仅做安全网：删除区域内残存的图框层实体，以及明确是标题栏字段标签的文本
    （图名/图号/比例/日期…）。墙/窗/线/标注/块/符号/尺寸线等真实绘图内容一律保留，
    交由新插入的图框块（HH_FRAME_Ax）在原位覆盖/叠加。
    """
    x0, y0, x1, y1 = tb
    TITLE_LAYERS = FRAME_LAYERS - {"0"}
    to_del = []
    for d in ents:
        e, et, layer, bb = d["e"], d["et"], d["layer"], d["bb"]
        if et == "AcDbBlockReference":
            continue
        if bb is None:
            continue
        ex0, ey0, ex1, ey1 = bb
        if ex1 < x0 or ex0 > x1 or ey1 < y0 or ey0 > y1:
            continue
        ll = (layer or "").lower()
        if ll in TITLE_LAYERS or ll.startswith("tukuang"):
            to_del.append(e)
            continue
        if et in ("AcDbText", "AcDbMText"):
            try:
                raw = _retry(lambda: e.TextString)
            except Exception:
                raw = ""
            if raw and _TITLE_LABEL_RE.search(raw):
                to_del.append(e)
    n = 0
    for e in to_del:
        try:
            e.Delete()
            n += 1
        except Exception:
            pass
    _prune_deleted(ents, to_del)
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
    _prune_deleted(ents, to_del)
    return n
