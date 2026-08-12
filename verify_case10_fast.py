# -*- coding: utf-8 -*-
"""案例十快速验证：COM 把 *_HH.dwg 转 DXF(一次 SaveAs)，再用 ezdxf 快速统计。
避免逐个实体 COM 遍历(120k 调用/张 太慢)。统计 HH_FRAME 块引用(名称+属性)
与旧框残留(专用图框层、排除 0、中心落在任一 HH_FRAME 框内)。
"""
import os, sys, time, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RES = os.path.join(HERE, "output_test")
OUT = os.path.join(HERE, "cases", "10_residential_electrical", "outputs")
CONV = os.path.join(OUT, "_conv")
os.makedirs(CONV, exist_ok=True)
NAMES = sorted(f for f in os.listdir(os.path.join(HERE, "cases", "10_residential_electrical", "inputs")) if f.lower().endswith(".dwg"))

FRAME_LAYERS = {"图框", "tukuang", "pub_title", "图签", "tk", "title", "frame",
                "border", "borders", "边框", "titleblock", "图框线", "图框层"}

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
        try: os.remove(dst)
        except Exception: pass
    for _ in range(5):
        try:
            doc = a.Documents.Open(os.path.abspath(src))
            break
        except Exception as e:
            print("  Open retry (%s)" % e, flush=True)
            time.sleep(3)
    else:
        raise RuntimeError("AutoCAD Open failed " + src)
    time.sleep(1.5)
    doc.SaveAs(os.path.abspath(dst))
    time.sleep(0.6)
    doc.Close(False)
    time.sleep(0.4)
    return os.path.exists(dst)


def analyze(dxf):
    import ezdxf
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    hh_bboxes = []
    hh_blocks = collections.Counter()
    attrs = 0
    layers_seen = set()
    # 第一遍：块引用
    for e in msp:
        try:
            dt = e.dxftype()
        except Exception:
            continue
        try:
            layer = e.get_dxf_attrib("layer", "")
        except Exception:
            layer = ""
        layers_seen.add(layer)
        if dt == "INSERT":
            try:
                nm = e.get_dxf_attrib("name", "")
            except Exception:
                nm = ""
            if "HH_FRAME" in str(nm):
                hh_blocks[nm] += 1
                try:
                    attrs += len(list(e.attribs))
                except Exception:
                    pass
                try:
                    bb = e.bbox()
                    if bb:
                        hh_bboxes.append((bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y))
                except Exception:
                    pass
    # 第二遍：残留在专用图框层、落在 HH_FRAME 框内
    resid = 0
    resid_layers = collections.Counter()
    for e in msp:
        try:
            dt = e.dxftype()
        except Exception:
            continue
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE", "2DLINE"):
            # ezdxf 把 LINE 叫 LINE；多段线 LWPOLYLINE/POLYLINE
            continue
        try:
            layer = (e.get_dxf_attrib("layer", "") or "")
        except Exception:
            layer = ""
        if (layer or "").lower() not in FRAME_LAYERS:
            continue
        try:
            bb = e.bbox()
        except Exception:
            continue
        if not bb:
            continue
        cx, cy = (bb.extmin.x + bb.extmax.x) / 2, (bb.extmin.y + bb.extmax.y) / 2
        for hb in hh_bboxes:
            if hb[0] - 500 <= cx <= hb[2] + 500 and hb[1] - 500 <= cy <= hb[3] + 500:
                resid += 1
                resid_layers[layer] += 1
                break
    return hh_blocks, attrs, resid, resid_layers, layers_seen


ALL = []
for fn in NAMES:
    base = os.path.splitext(fn)[0]
    hh = os.path.join(RES, base + "_HH.dwg")
    rec = {"name": base, "hh_exists": os.path.exists(hh), "hh_size": None,
           "hh_blocks": {}, "attrs": 0, "residual": 0, "residual_layers": {},
           "frame_layers_present": []}
    if not rec["hh_exists"]:
        print("== %s: 缺少输出 ==" % base, flush=True)
        ALL.append(rec); continue
    rec["hh_size"] = os.path.getsize(hh)
    dxf = os.path.join(CONV, base + "_HH.dxf")
    print("转换 %s ..." % base, flush=True)
    t0 = time.time()
    ok = to_dxf(hh, dxf)
    print("  转换耗时 %.1fs ok=%s" % (time.time() - t0, ok), flush=True)
    if not ok:
        print("  ! 转换失败，跳过统计", flush=True)
        ALL.append(rec); continue
    hh_blocks, attrs, resid, resid_layers, layers_seen = analyze(dxf)
    rec["hh_blocks"] = dict(hh_blocks)
    rec["attrs"] = attrs
    rec["residual"] = resid
    rec["residual_layers"] = dict(resid_layers)
    rec["frame_layers_present"] = sorted([l for l in layers_seen if l and l.lower() != "0"
                                          and any(k in l.lower() for k in
                                                  ("框", "图", "title", "tk", "border", "frame"))])
    print("== %-18s 块:%s 属性:%d 残留:%d %s" % (
        base, rec["hh_blocks"], attrs, resid,
        ("层=%s" % resid_layers) if resid else ""), flush=True)
    ALL.append(rec)

with open(os.path.join(RES, "case10_verify.json"), "w", encoding="utf-8") as f:
    json.dump(ALL, f, ensure_ascii=False, indent=2)

ok = sum(1 for r in ALL if r["hh_exists"] and r["hh_blocks"] and r["residual"] == 0)
print("\n验证汇总: %d/%d 张成功(有HH_FRAME块且残留=0)" % (ok, len(ALL)), flush=True)
print("残留>0 的图:", [r["name"] for r in ALL if r["residual"] > 0], flush=True)
print("缺输出的图:", [r["name"] for r in ALL if not r["hh_exists"]], flush=True)
print("结束", flush=True)
