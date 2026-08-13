# -*- coding: utf-8 -*-
"""模板重定向：把一个公司图框模板改成任意幅面尺寸，标题栏保持原样。

为什么需要
----------
原方案只有 A0~A4 五个 √2 比例的固定模板，插框时按 ``scale = min(W/tw, H/th)``
等比缩放。一旦旧框不是 √2 比例，新框就套不住旧图：

  * 竖版图（210 x 297）套横版 A4 模板 -> scale=0.707 -> 新框只占底部 210x148.5，
    图纸内容整个跑到新框上方（用户实拍「馈电-电气原理图」就是这个现象）。
  * 加长图（长宽比 1.77）-> scale 受高度约束 -> 新框宽 1.414H < 内容宽 1.77H
    -> 内容从右边溢出框外（实拍「裙楼消防平面」「首二层商场平面」）。

补几个固定模板治不了本：非标图幅的比例是连续的。正确做法是**按检出旧框的
真实比例即时重定向模板**，使 W/tw == H/th，等比缩放后严丝合缝。

重定向算法（锚定拉伸）
----------------------
实测公司模板 A0~A4 结构完全一致，可归纳出三类元素，各自的正确变形方式不同：

  1. 整幅矩形（纸边线、内框线）：跨度 > 80% 幅面 -> **保留留边拉伸**。
     做法是「中点分割平移」：坐标落在幅面后半侧的点整体平移 delta，前半侧不动。
     纸边 (0..297) -> (0..210)；内框 (25..292) -> (25..205)，左留边 25、
     右留边 5 全部原样保留。
  2. 标题栏及其内部（网格线 / 15 个静态文字 / 14 个 ATTDEF）：**刚性右下锚定**。
     GB/T 10609.1 规定标题栏恒为 180 x 56 mm，与幅面大小无关，所以绝不能缩放，
     只能整体平移到新幅面的右下角。
  3. 对中符号 / 方向箭头等边缘小元素：按其所在位置**锚定到对应边或中点**。

因为每个元素的变形都退化为纯平移，文字高度、标题栏格线宽度全部不变，
输出模板天然符合制图标准。

自校验：用本模块从 A4 模板重定向出 A1，与仓库里真实的 A1 模板逐点比对完全一致
（见 tests/test_frame_gen.py），说明该算法确实复现了模板设计者的意图。
"""

from __future__ import annotations

import os

import ezdxf

# 分类阈值
FULL_SPAN = 0.80   # 跨度超过幅面这个比例，视为「整幅矩形」，走保留留边拉伸
MID_ABS_TOL = 0.1  # 对中符号判定容差（mm，绝对值）
TITLE_PAD = 1.0    # 判断元素是否属于标题栏时的容差（mm）


# --------------------------------------------------------------------------
# 模板解析
# --------------------------------------------------------------------------

def find_frame_block(doc, prefix="HH_FRAME_"):
    """找出模板里的图框块名。优先带 prefix 的块，否则取实体最多的非匿名块。"""
    names = [b.name for b in doc.blocks if not b.name.startswith("*")]
    hit = [n for n in names if n.startswith(prefix)]
    if hit:
        return sorted(hit)[0]
    best, best_n = None, -1
    for n in names:
        cnt = len(list(doc.blocks[n]))
        if cnt > best_n:
            best_n, best = cnt, n
    if best is None:
        raise ValueError("模板里没有可用的图框块")
    return best


def _closed_rects(blk):
    """收集块内所有闭合矩形（4 点闭合 LWPOLYLINE）的 bbox。"""
    out = []
    for e in blk:
        if e.dxftype() != "LWPOLYLINE" or not e.closed:
            continue
        pts = list(e.get_points("xy"))
        if len(pts) != 4:
            continue
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def paper_rect(blk):
    """幅面纸边矩形 = 面积最大的闭合矩形。找不到则退回块整体范围。"""
    rects = _closed_rects(blk)
    if rects:
        return max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    return entity_group_bbox(list(blk))


def title_rect(blk, paper):
    """标题栏矩形 = 贴住内框右下角、面积小于半幅的最大闭合矩形。

    识别规则（与公司模板实测一致）：右边界和下边界都靠近幅面右/下边（留边范围内），
    且面积不超过幅面一半。取满足条件里面积最大的那个（避免误取内部小格）。
    """
    px0, py0, px1, py1 = paper
    pw, ph = px1 - px0, py1 - py0
    if pw <= 0 or ph <= 0:
        return None
    area_max = 0.5 * pw * ph
    cands = []
    for r in _closed_rects(blk):
        x0, y0, x1, y1 = r
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            continue
        if w * h > area_max:
            continue
        # 右下角贴边：允许最多 8% 幅面的留边
        if (px1 - x1) > 0.08 * pw:
            continue
        if (y0 - py0) > 0.08 * ph:
            continue
        cands.append(r)
    if not cands:
        return None
    return max(cands, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))


def paper_size(dxf_path, prefix="HH_FRAME_"):
    """读出模板的幅面尺寸 (width, height)，给 insert_frame 的 size_table 用。"""
    doc = ezdxf.readfile(dxf_path)
    blk = doc.blocks[find_frame_block(doc, prefix)]
    x0, y0, x1, y1 = paper_rect(blk)
    return (x1 - x0, y1 - y0)


# --------------------------------------------------------------------------
# 实体坐标读写（统一成「取点列表 / 写点列表」，变形逻辑就与实体类型解耦了）
# --------------------------------------------------------------------------

_POINT_ATTRS = {
    "LINE": ("start", "end"),
    "TEXT": ("insert", "align_point"),
    "ATTDEF": ("insert", "align_point"),
    "ATTRIB": ("insert", "align_point"),
    "MTEXT": ("insert",),
    "CIRCLE": ("center",),
    "ARC": ("center",),
    "ELLIPSE": ("center",),
    "POINT": ("location",),
    "INSERT": ("insert",),
    "SOLID": ("vtx0", "vtx1", "vtx2", "vtx3"),
    "TRACE": ("vtx0", "vtx1", "vtx2", "vtx3"),
}


def entity_points(e):
    """读出实体的定位点列表 [(x, y), ...]。不支持的类型返回 []。"""
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
    if t == "POLYLINE":
        return [(float(v.dxf.location.x), float(v.dxf.location.y))
                for v in e.vertices]
    pts = []
    for attr in _POINT_ATTRS.get(t, ()):
        if not e.dxf.hasattr(attr):
            continue
        v = e.dxf.get(attr)
        if v is None:
            continue
        pts.append((float(v[0]), float(v[1])))
    return pts


def transform_entity(e, fx, fy):
    """按坐标映射函数 fx/fy 就地变形实体。返回是否变形成功。"""
    t = e.dxftype()
    if t == "LWPOLYLINE":
        pts = [(fx(float(p[0])), fy(float(p[1]))) for p in e.get_points("xy")]
        e.set_points(pts, format="xy")
        return True
    if t == "POLYLINE":
        for v in e.vertices:
            loc = v.dxf.location
            v.dxf.location = (fx(float(loc.x)), fy(float(loc.y)), float(loc.z))
        return True
    attrs = _POINT_ATTRS.get(t)
    if not attrs:
        return False
    for attr in attrs:
        if not e.dxf.hasattr(attr):
            continue
        v = e.dxf.get(attr)
        if v is None:
            continue
        z = float(v[2]) if len(v) > 2 else 0.0
        e.dxf.set(attr, (fx(float(v[0])), fy(float(v[1])), z))
    return True


def entity_group_bbox(ents):
    """一组实体的定位点包围盒。"""
    xs, ys = [], []
    for e in ents:
        for x, y in entity_points(e):
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------
# 锚定分类 + 坐标映射
# --------------------------------------------------------------------------

def classify_axis(c0, c1, lo, span, in_title, title_mode):
    """判断某个实体在单个坐标轴上的变形模式。

    返回 'stretch' | 'left' | 'right' | 'center'

    判定顺序是有讲究的，四类元素在 A4 上会互相「撞车」，顺序错了就分类错：

      1. **对中符号优先**。GB/T 14689 规定对中符号画在幅面边线的*精确中点*上，
         所以用绝对容差判「中心是否落在幅面中线上」，语义精确而非拍脑袋。
         必须排在标题栏判定之前：A4 标题栏 x 范围是 112~292，恰好把纸面中线
         148.5 包在里面，若先判标题栏，底边对中符号会被当成标题栏内容跟着
         右移（实测差异就出在这里）。
         同时要求跨度小于整幅，否则纸边线（中心当然也在中线上）会被误判。
      2. **标题栏刚性锚定**。排在拉伸判定之前：竖版 A4 的标题栏宽 180 占幅宽
         210 的 86%，若先判拉伸会被误当整幅矩形拉变形。
      3. **整幅矩形保留留边拉伸**。
      4. 其余小元素按所在半侧锚定到近边。
    """
    if span <= 0:
        return "left"
    full = (c1 - c0) > FULL_SPAN * span
    mid = lo + span * 0.5
    if not full and abs((c0 + c1) * 0.5 - mid) <= MID_ABS_TOL:
        return "center"
    if in_title:
        return title_mode
    if full:
        return "stretch"
    return "left" if ((c0 + c1) * 0.5) < mid else "right"


def axis_map(mode, lo, span, delta):
    """按模式返回单轴坐标映射函数。"""
    if mode == "stretch":
        mid = lo + span * 0.5
        return lambda v: v + (delta if v > mid else 0.0)
    if mode == "right":
        return lambda v: v + delta
    if mode == "center":
        return lambda v: v + delta * 0.5
    return lambda v: v


def _in_title(bbox, title):
    """实体中心是否落在标题栏矩形内（带容差）。"""
    if title is None:
        return False
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return (title[0] - TITLE_PAD <= cx <= title[2] + TITLE_PAD
            and title[1] - TITLE_PAD <= cy <= title[3] + TITLE_PAD)


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------

def retarget(src_dxf, out_dxf, new_name, width, height, prefix="HH_FRAME_"):
    """把 src_dxf 模板重定向成 width x height（mm）幅面，写到 out_dxf。

    new_name: 新块名（如 HH_FRAME_A4V / HH_FRAME_C1051X594）。
    返回 (width, height)，即新模板的幅面尺寸。

    实现上是「就地改源模板再另存」，因此文字样式、图层、$INSUNITS 等设置全部
    原样继承，不需要手工重建，避免了跨文档拷贝丢样式的坑。
    """
    width = float(width)
    height = float(height)
    doc = ezdxf.readfile(src_dxf)
    old_name = find_frame_block(doc, prefix)
    blk = doc.blocks[old_name]

    px0, py0, px1, py1 = paper_rect(blk)
    tw, th = px1 - px0, py1 - py0
    if tw <= 0 or th <= 0:
        raise ValueError("模板幅面尺寸异常: %s x %s" % (tw, th))
    tb = title_rect(blk, (px0, py0, px1, py1))
    dW, dH = width - tw, height - th

    for e in list(blk):
        pts = entity_points(e)
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        it = _in_title(bbox, tb)
        # 标题栏：x 向右锚定（贴右留边）、y 向下锚定（贴下留边）—— 尺寸不变
        xm = classify_axis(bbox[0], bbox[2], px0, tw, it, "right")
        ym = classify_axis(bbox[1], bbox[3], py0, th, it, "left")
        transform_entity(e, axis_map(xm, px0, tw, dW),
                         axis_map(ym, py0, th, dH))

    if old_name != new_name:
        doc.blocks.rename_block(old_name, new_name)
        for e in doc.modelspace():
            if e.dxftype() == "INSERT" and e.dxf.name == old_name:
                e.dxf.name = new_name

    out_dir = os.path.dirname(os.path.abspath(out_dxf))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.saveas(out_dxf)
    return (width, height)


def ensure_template(src_dxf, out_dir, spec, prefix="HH_FRAME_"):
    """确保 spec 对应的模板 DXF 存在，返回 (dxf_path, (width, height))。

    spec: lib.sheet.SheetSpec
    已存在则直接复用（模板生成是纯函数，缓存安全）。
    """
    name = prefix + spec.name
    out_dxf = os.path.join(out_dir, name + ".dxf")
    if os.path.exists(out_dxf):
        try:
            return out_dxf, paper_size(out_dxf, prefix)
        except Exception:
            pass  # 文件坏了就重新生成
    size = retarget(src_dxf, out_dxf, name, spec.width, spec.height, prefix)
    return out_dxf, size
