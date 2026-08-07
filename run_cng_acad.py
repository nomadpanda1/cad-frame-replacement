# -*- coding: utf-8 -*-
"""
CNG 电气系统图 — AutoCAD COM 直接处理原 DWG。

原因：设计院 DWG 经 ezdxf 读写后会被 AutoCAD 报“解密数据时出错”，
因此字段提取由 ezdxf 完成（plan()），实际删框/插框/回填全部交给
AutoCAD COM（lib/acad_com.py）在原 DWG 副本上完成，最后 Save 成真正的 DWG。

复用：lib/acad_com.py 是通用 COM 操作库，本脚本只保留 CNG 特定的
“图框检测 + 字段提取（plan）”逻辑。换别的加密图纸时，改 plan() 即可。
"""
import os
import sys
import re
import json
import time
import shutil
import win32com.client
import ezdxf
from ezdxf import bbox as bbox_mod

from lib.acad_com import (
    open_doc_copy,
    save_close,
    del_in_region,
    del_frame_edges,
    insert_frame,
)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DXF_IN = os.path.join(HERE, "dxf_cng", "CNG_电气系统图.dxf")
DWG_IN = os.path.join(HERE, "input_cng", "CNG_电气系统图.dwg")
OUT_DIR = os.path.join(HERE, "output_cng_acad")
TPL_DIR = os.path.join(HERE, "tpl_dwgs")
os.makedirs(OUT_DIR, exist_ok=True)

# 仅用于图框比例判定（与 lib/acad_com.A_SIZES 同源）。
A_SIZES = {
    "A0": (1189, 841),
    "A1": (841, 594),
    "A2": (594, 420),
    "A3": (420, 297),
    "A3_WIDE": (604, 299),
    "A4": (297, 210),
}


def _rect_score(w, h):
    rw, rh = max(w, h), min(w, h)
    ratio = rw / rh if rh else 1e9
    if 1.95 <= ratio <= 2.05:
        return "A3_WIDE"
    if 1.38 <= ratio <= 1.44:
        if rw >= 75000:
            return "A1"
        if rw >= 52000:
            return "A2"
        if rw >= 35000:
            return "A3"
        return "A4"
    best_name, best_err = "A1", 1e9
    for name, (tw, th) in A_SIZES.items():
        tr = tw / th
        r_err = abs(ratio - tr) / tr
        if r_err < best_err:
            best_err, best_name = r_err, name
    return best_name


def detect_big_frames(doc):
    frames = []
    for e in doc.modelspace().query("LWPOLYLINE"):
        pts = [(p[0], p[1]) for p in e.get_points()]
        if len(pts) < 4:
            continue
        closed = bool(e.dxf.flags & 1) or (pts and pts[0] == pts[-1])
        if not closed:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if min(w, h) < 20000:
            continue
        if len(pts) <= 6:
            frames.append((float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))))
    frames.sort(key=lambda f: (f[2] - f[0]) * (f[3] - f[1]), reverse=True)
    MARGIN = 2000
    out = []
    for f in frames:
        if any((o[0] - MARGIN <= f[0] and o[1] - MARGIN <= f[1] and
                o[2] + MARGIN >= f[2] and o[3] + MARGIN >= f[3]) for o in out):
            continue
        out.append(f)
    out.sort(key=lambda f: (f[0], f[1]))
    return out


def titleblock_box(frame):
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    return (x0 + 0.55 * W, y0, x1, y0 + 0.24 * H)


def extract_design_fields(doc, frame):
    tb = titleblock_box(frame)
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    msp = doc.modelspace()
    items = []
    for e in msp.query("TEXT MTEXT"):
        raw = e.text if e.dxftype() == "MTEXT" else e.dxf.text
        if not raw:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        if not (tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]):
            continue
        h = e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height
        items.append((float(cy), float(cx), float(h), raw))
    items.sort(reverse=True)

    fields = {}
    name_cands = [it for it in items if it[2] >= 500 and y0 <= it[0] <= y0 + 0.20 * H]
    if name_cands:
        fields["TITLE"] = name_cands[-1][3].replace(" ", "")

    for cy, cx, h, t in items:
        if re.search(r"[A-Za-z]+[-]?\d{2,4}.\d{2,4}", t):
            fields["DWG_NO"] = t
            break

    stage_map = {"初步设计": "初步设计", "施工图": "施工图", "方案": "方案", "初步": "初步设计", "施工": "施工图"}
    for cy, cx, h, t in items:
        for k, v in stage_map.items():
            if k in t:
                fields["STAGE"] = v
                break
        if "STAGE" in fields:
            break

    for cy, cx, h, t in items:
        if t.endswith("室") or t in ("电气", "建筑", "结构", "暖通", "给排水"):
            fields["MATERIAL"] = t
            break

    for cy, cx, h, t in items:
        m = re.search(r"1\s*:\s*\d+", t)
        if m:
            fields["SCALE"] = m.group(0).replace(" ", "")
            break

    for cy, cx, h, t in items:
        m = re.match(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}", t)
        if m:
            fields["DATE"] = t
            break

    return fields


def plan():
    """返回处理计划（图框+字段），供 AutoCAD COM 步骤使用。"""
    doc = ezdxf.readfile(DXF_IN)
    frames = detect_big_frames(doc)
    plan = []
    for idx, frame in enumerate(frames):
        x0, y0, x1, y1 = frame
        w, h = x1 - x0, y1 - y0
        size_name = _rect_score(w, h)
        fields = extract_design_fields(doc, frame)
        plan.append({
            "idx": idx + 1,
            "frame": frame,
            "size": size_name,
            "fields": fields,
            "tpl_dwg": os.path.join(TPL_DIR, f"HH_FRAME_{size_name}.dwg"),
        })
    return plan


def main():
    plan_data = plan()
    print("处理计划:", len(plan_data), "个图框")
    for p in plan_data:
        print(f"  [{p['idx']}] {p['size']} {p['frame']} fields={p['fields']}")

    with open(os.path.join(OUT_DIR, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)

    app = win32com.client.Dispatch("AutoCAD.Application")
    time.sleep(3)  # 等待 AutoCAD 启动完成
    print("\nAutoCAD:", app.Caption)

    # 复制原 DWG 到输出目录，在副本上修改，避免破坏原图。
    out_dwg = os.path.join(OUT_DIR, "CNG_电气系统图_HH.dwg")
    doc, msp = open_doc_copy(app, DWG_IN, out_dwg, wait_open=2.0)
    print("打开副本 DWG:", out_dwg)

    results = []
    for p in plan_data:
        idx = p["idx"]
        frame = p["frame"]
        size_name = p["size"]
        fields = p["fields"]
        tpl_dwg = p["tpl_dwg"]
        print(f"\n== 图框 {idx}: {size_name} ==")

        x0, y0, x1, y1 = frame
        tb = titleblock_box(frame)

        n_edge = del_frame_edges(msp, frame)
        n_tb = del_in_region(msp, tb[0], tb[1], tb[2], tb[3])
        print(f"   删除: 外框线={n_edge} 会签栏={n_tb}")

        insert, scale = insert_frame(msp, frame, tpl_dwg, fields)
        print(f"   插入: {os.path.basename(tpl_dwg)} scale={scale:.4f}")

        results.append({
            "idx": idx,
            "size": size_name,
            "frame": frame,
            "scale": scale,
            "fields": fields,
            "deleted_edges": n_edge,
            "deleted_tb": n_tb,
        })

    print("\n保存 DWG:", out_dwg)
    save_close(doc)
    print("Done")

    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
