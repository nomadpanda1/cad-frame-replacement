# -*- coding: utf-8 -*-
"""案例十深度验证：COM 把 cases/10_residential_electrical/outputs/dwg/<名>_HH.dwg
转 DXF，再用 ezdxf 做深度几何+属性核查。

覆盖浅核验(verify/verify_shallow.json)漏掉的项：
 1) 图框覆盖度：新 HH_FRAME 框是否真正罩住全部图面内容(有无内容溢出框外)
 2) 比例匹配：插入框宽高比 vs 图面内容宽高比(抓非√2/竖版误配，已知缺陷#2)
 3) 标题栏属性填值：图名/图号/比例/日期等关键 ATTDEF 是否非空
 4) 旧框残留(放宽)：不只在 FRAME 类图层，任何层上的"大边框线"若落在 HH_FRAME 框内且贴边，都记为潜在残留
"""
import os, sys, time, json, collections, math
import ezdxf
from ezdxf import bbox as _bbox

_BC = _bbox.Cache()

# HH_FRAME_A0 模板归一化原生包围盒(来自已验证的归一化块: [0,0,1190,843], √2 横版)
NATIVE_A0 = [0.0, 0.0, 1190.0, 843.0]

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CASE = os.path.join(HERE, "cases", "10_residential_electrical")
RES = os.path.join(CASE, "outputs", "dwg")
VERIFY_DIR = os.path.join(CASE, "verify")
CONV = os.path.join(VERIFY_DIR, "_conv_deep")   # 中间 DXF，跑完可删
os.makedirs(CONV, exist_ok=True)

# 从案例十 outputs/dwg 的 *_HH.dwg 推导图名，只保留住宅楼的 11 张
RES_NAMES = ["天面", "弱电1", "强电平面", "消防，弱电2", "消防系统图", "系统",
             "裙楼消防平面", "首二层商场平面", "首二层系统图",
             "首层配电干线平面图", "高低压系统"]
_present = {os.path.splitext(f)[0][:-len("_HH")]
            for f in os.listdir(RES)
            if f.endswith("_HH.dwg") and os.path.isfile(os.path.join(RES, f))}
NAMES = [n for n in RES_NAMES if n in _present]
print("待核验住宅楼图(%d 张): %s" % (len(NAMES), NAMES), flush=True)

import win32com.client as wc


def get_acad():
    try:
        return wc.GetActiveObject("AutoCAD.Application")
    except Exception:
        print("[info] 启动 AutoCAD...", flush=True)
        a = wc.Dispatch("AutoCAD.Application")
        a.Visible = True
        time.sleep(5)
        return a


def to_dxf(src, dst):
    a = get_acad()
    a.Visible = True
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass
    doc = None
    for _ in range(6):
        try:
            doc = a.Documents.Open(os.path.abspath(src))
            break
        except Exception as e:
            print("  Open retry (%s)" % e, flush=True)
            time.sleep(3)
    if doc is None:
        raise RuntimeError("AutoCAD Open failed " + src)
    time.sleep(1.5)
    doc.SaveAs(os.path.abspath(dst))
    time.sleep(0.6)
    try:
        doc.Close(False)
    except Exception:
        pass
    time.sleep(0.4)
    return os.path.exists(dst)


def ent_bbox(e):
    """用 ezdxf.bbox.extents 计算实体(含 INSERT 变换)的世界坐标包围盒。
    排除含无穷/NaN 的退化实体(射线/构造线/异常块)，避免污染内容包围盒。"""
    try:
        bb = _bbox.extents([e], cache=_BC)
    except Exception:
        return None
    if bb is None:
        return None
    try:
        if not (math.isfinite(bb.extmin.x) and math.isfinite(bb.extmin.y)
                and math.isfinite(bb.extmax.x) and math.isfinite(bb.extmax.y)):
            return None
    except Exception:
        return None
    return (bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y)


def extend(acc, bb):
    if bb is None:
        return acc
    if acc is None:
        return [bb[0], bb[1], bb[2], bb[3]]
    return [min(acc[0], bb[0]), min(acc[1], bb[1]),
            max(acc[2], bb[2]), max(acc[3], bb[3])]


FRAME_LAYERS = {"图框", "tukuang", "pub_title", "图签", "tk", "title", "frame",
                "border", "borders", "边框", "titleblock", "图框线", "图框层"}

# 关键标题栏属性(任一命中即视为"该字段")
CRIT_TAGS = ["TITLE", "图名", "NAME",
             "DRAWING_NO", "图号", "NO", "NUM",
             "SCALE", "比例",
             "DATE", "日期",
             "PHASE", "阶段",
             "PROJ", "工程名称", "PROJECT",
             "CLIENT", "建设单位", "OWNER",
             "DESIGN", "设计", "DESIGNER"]


def block_native_bbox(doc, name):
    try:
        blk = doc.blocks.get(name)
    except Exception:
        return None
    if blk is None:
        return None
    acc = None
    for e in blk:
        acc = extend(acc, ent_bbox(e))
    return acc


def placed_bbox(native, ins, xs, ys, rot):
    """由块原生包围盒 + 插入矩阵(插入点/比例/旋转)反算放置后包围盒。"""
    if native is None or ins is None:
        return None
    x0, y0, x1, y1 = native
    ix, iy = ins[0], ins[1]
    r = math.radians(rot)
    ca, sa = math.cos(r), math.sin(r)
    xs_ = []
    ys_ = []
    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        sx, sy = px * xs, py * ys
        rx = sx * ca - sy * sa
        ry = sx * sa + sy * ca
        xs_.append(rx + ix)
        ys_.append(ry + iy)
    return [min(xs_), min(ys_), max(xs_), max(ys_)]


def analyze(dxf):
    import ezdxf
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    global _BC
    _BC = _bbox.Cache()  # 每文件刷新，避免跨文件缓存污染导致边框退化

    hh = []          # list of dicts
    hh_bboxes = []
    native_cache = {}
    content_acc = None
    total_lines = 0
    # 第一遍：实体遍历
    for e in msp:
        try:
            dt = e.dxftype()
        except Exception:
            continue
        try:
            nm = e.get_dxf_attrib("name", "") if dt == "INSERT" else ""
        except Exception:
            nm = ""
        if dt == "INSERT" and "HH_FRAME" in str(nm):
            try:
                ins = e.get_dxf_attrib("insert", (0, 0, 0))
            except Exception:
                ins = (0, 0, 0)
            xs = e.get_dxf_attrib("xscale", 1.0)
            ys = e.get_dxf_attrib("yscale", 1.0)
            rot = e.get_dxf_attrib("rotation", 0.0)
            nat = native_cache.get(nm)
            if nat is None:
                nat = block_native_bbox(doc, nm)
                native_cache[nm] = nat
            bb = ent_bbox(e)  # 世界坐标放置包围盒(含插入变换)
            if bb is None:    # 退化时回退：归一化模板原生尺寸 + 插入矩阵反算
                bb = placed_bbox(NATIVE_A0, (ins[0], ins[1]), xs, ys, rot)
            attribs = {}
            try:
                for att in e.attribs:
                    try:
                        t = att.get_dxf_attrib("tag", "")
                        v = att.get_dxf_attrib("text", "")
                    except Exception:
                        continue
                    attribs[t] = v
            except Exception:
                pass
            hh.append({"name": nm, "bbox": bb,
                       "xscale": xs, "yscale": ys, "rotation": rot,
                       "attribs": attribs})
            if bb:
                hh_bboxes.append(bb)
            continue
        # 内容范围(排除 HH_FRAME 块)
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "INSERT",
                  "TEXT", "MTEXT", "ELLIPSE", "SPLINE", "POINT", "HATCH",
                  "DIMENSION", "SOLID", "3DFACE", "MESH"):
            content_acc = extend(content_acc, ent_bbox(e))
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE"):
            total_lines += 1

    # 块原生尺寸(首个 HH_FRAME)
    native = None
    if hh:
        native = block_native_bbox(doc, hh[0]["name"])

    # 残留(放宽)：任何层上的"大边框线"落在 HH_FRAME 框内且贴边
    resid = 0
    resid_detail = collections.Counter()
    resid_frameset = 0
    resid_frameset_detail = collections.Counter()
    for hb in hh_bboxes:
        fw = hb[2] - hb[0]
        fh = hb[3] - hb[1]
        fa = fw * fh
        band = max(fw, fh) * 0.03  # 贴边带
        # 边框四边 y/x 容差带
        for e in msp:
            try:
                dt = e.dxftype()
            except Exception:
                continue
            if dt not in ("LINE", "LWPOLYLINE", "POLYLINE"):
                continue
            try:
                layer = (e.get_dxf_attrib("layer", "") or "")
            except Exception:
                layer = ""
            bb = ent_bbox(e)
            if bb is None:
                continue
            ew = bb[2] - bb[0]
            eh = bb[3] - bb[1]
            # 大边框线判定：自身是"大矩形/长线"，且中心落在 HH_FRAME 框内
            big = (min(ew, eh) > 0.4 * min(fw, fh)) and (max(ew, eh) > 0.4 * max(fw, fh))
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            inside = (hb[0] <= cx <= hb[2]) and (hb[1] <= cy <= hb[3])
            if big and inside:
                resid += 1
                resid_detail[layer or "<0>"] += 1
            # 原 FRAME 类图层判定(浅核验口径)
            if (layer or "").lower() in FRAME_LAYERS and inside:
                resid_frameset += 1
                resid_frameset_detail[layer or "<0>"] += 1

    return {
        "hh": hh,
        "content_bbox": content_acc,
        "native_bbox": native,
        "total_lines": total_lines,
        "residual_broad": resid,
        "residual_broad_layers": dict(resid_detail),
        "residual_frameset": resid_frameset,
        "residual_frameset_layers": dict(resid_frameset_detail),
    }


def check_frame(hh_item, content_bbox):
    """对单个 HH_FRAME 做覆盖度/比例/属性判定，返回 flags。"""
    flags = []
    bb = hh_item["bbox"]
    if bb is None:
        flags.append("FRAME_NO_BBOX")
        return flags, None, None
    fw = bb[2] - bb[0]
    fh = bb[3] - bb[1]
    frame_aspect = fw / fh if fh else 0

    # 覆盖度：内容是否被框罩住
    if content_bbox:
        # 允许 1% 容差
        tol_x = fw * 0.01
        tol_y = fh * 0.01
        if content_bbox[0] < bb[0] - tol_x or content_bbox[1] < bb[1] - tol_y \
           or content_bbox[2] > bb[2] + tol_x or content_bbox[3] > bb[3] + tol_y:
            flags.append("CONTENT_OVERFLOW")
        cw = content_bbox[2] - content_bbox[0]
        ch = content_bbox[3] - content_bbox[1]
        content_aspect = cw / ch if ch else 0
    else:
        content_aspect = 0

    # 比例匹配：插入框宽高比 vs 内容宽高比
    if content_aspect and frame_aspect:
        rel = abs(frame_aspect - content_aspect) / content_aspect
        if rel > 0.08:
            flags.append("ASPECT_MISMATCH(%.0f%%)" % (rel * 100))

    # 属性填值
    attrs = hh_item.get("attribs", {})
    filled_crit = 0
    empty_crit = []
    for t in CRIT_TAGS:
        if t in attrs:
            v = (attrs[t] or "").strip()
            if v:
                filled_crit += 1
            else:
                empty_crit.append(t)
    if empty_crit:
        flags.append("EMPTY_ATTR:%s" % ",".join(empty_crit))
    return flags, frame_aspect, content_aspect


ALL = []
for fn in NAMES:
    base = os.path.splitext(fn)[0]
    hh_path = os.path.join(RES, base + "_HH.dwg")
    rec = {"name": base, "hh_exists": os.path.exists(hh_path),
           "hh_size": os.path.getsize(hh_path) if os.path.exists(hh_path) else None,
           "frames": [], "flags": [], "content_aspect": None,
           "frame_aspects": [], "residual_broad": 0,
           "residual_broad_layers": {}, "residual_frameset": 0,
           "residual_frameset_layers": {}}
    if not rec["hh_exists"]:
        print("== %s: 缺少输出 ==" % base, flush=True)
        ALL.append(rec)
        continue
    dxf = os.path.join(CONV, base + "_HH.dxf")
    print("转换 %s ..." % base, flush=True)
    t0 = time.time()
    ok = to_dxf(hh_path, dxf)
    print("  转换耗时 %.1fs ok=%s" % (time.time() - t0, ok), flush=True)
    if not ok:
        print("  ! 转换失败", flush=True)
        ALL.append(rec)
        continue
    try:
        r = analyze(dxf)
    except Exception as e:
        print("  ! 分析异常:", repr(e)[:200], flush=True)
        ALL.append(rec)
        continue
    rec["residual_broad"] = r["residual_broad"]
    rec["residual_broad_layers"] = r["residual_broad_layers"]
    rec["residual_frameset"] = r["residual_frameset"]
    rec["residual_frameset_layers"] = r["residual_frameset_layers"]
    cb = r["content_bbox"]
    rec["content_bbox"] = [round(x, 1) for x in cb] if cb else None
    rec["native_bbox"] = [round(x, 1) for x in r["native_bbox"]] if r["native_bbox"] else None
    rec["total_lines"] = r["total_lines"]
    for h in r["hh"]:
        fl, fa, ca = check_frame(h, cb)
        rec["frames"].append({
            "name": h["name"],
            "xscale": round(h["xscale"], 2),
            "yscale": round(h["yscale"], 2),
            "rotation": round(h["rotation"], 1),
            "bbox": [round(x, 1) for x in h["bbox"]] if h["bbox"] else None,
            "attribs": {k: (v if v is not None else "") for k, v in h["attribs"].items()},
            "flags": fl,
            "frame_aspect": round(fa, 4) if fa else None,
            "content_aspect": round(ca, 4) if ca else None,
        })
        rec["flags"].extend(fl)
        if fa:
            rec["frame_aspects"].append(round(fa, 4))
        if ca:
            rec["content_aspect"] = round(ca, 4)
    # 去重 flags
    rec["flags"] = list(dict.fromkeys(rec["flags"]))
    print("== %-16s 帧:%d 属性帧:%d 内容比:%.3f 框比:%s 残留(宽):%d 残留(框层):%d 标记:%s"
          % (base, len(r["hh"]), sum(1 for f in rec["frames"] if f["attribs"]),
             rec["content_aspect"] or 0, rec["frame_aspects"],
             r["residual_broad"], r["residual_frameset"], rec["flags"]),
          flush=True)
    ALL.append(rec)

with open(os.path.join(VERIFY_DIR, "verify_deep.json"), "w", encoding="utf-8") as f:
    json.dump(ALL, f, ensure_ascii=False, indent=2)

# 汇总
n = len(ALL)
ok_frames = sum(1 for r in ALL if r["hh_exists"] and r["frames"])
print("\n==== 深度核验汇总 ====")
print("总图数:%d  有输出:%d  有HH_FRAME:%d" % (n, sum(1 for r in ALL if r["hh_exists"]), ok_frames))
print("覆盖溢出(CONTENT_OVERFLOW):", [r["name"] for r in ALL if "CONTENT_OVERFLOW" in r["flags"]])
print("比例失配(ASPECT_MISMATCH):", [r["name"] for r in ALL if any(x.startswith("ASPECT") for x in r["flags"])])
print("空属性(EMPTY_ATTR):", [r["name"] for r in ALL if any(x.startswith("EMPTY_ATTR") for x in r["flags"])])
print("放宽残留>0:", [(r["name"], r["residual_broad"]) for r in ALL if r["residual_broad"] > 0])
print("框层残留>0:", [(r["name"], r["residual_frameset"]) for r in ALL if r["residual_frameset"] > 0])
print("结束", flush=True)
