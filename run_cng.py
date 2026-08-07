# -*- coding: utf-8 -*-
"""
CNG_电气系统图.dxf 专用处理：4 张大坐标设计院图框批量替换为公司图框。

布局：左侧 3 个 A3_WIDE 横向图框（84100×42000，ratio≈2.0）
      右侧 1 个 A1 图框（84100×59400，ratio≈1.41）
流程：检测闭合矩形外框 → 每个图框分别提取标题栏字段 → 删旧框 → 按幅面匹配模板
      → 插入公司图框并回填字段 → 出 DXF + PNG 对比。
"""
import os
import sys
import glob
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

CJK_FONT = r"C:\Windows\Fonts\simhei.ttf"
if os.path.exists(CJK_FONT):
    font_manager.fontManager.addfont(CJK_FONT)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=CJK_FONT).get_name()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ezdxf
from ezdxf import bbox as bbox_mod
from ezdxf.addons.drawing.matplotlib import qsave

from lib import template_learn, finder, extract, mapper, block_replace

TPL_DIR = r"C:\Users\86308\WorkBuddy\2026-08-04-09-31-00\outputs\cad-frame-replacement\templates"
DXF_IN = os.path.join(HERE, "dxf_cng", "CNG_电气系统图.dxf")
OUT_DIR = os.path.join(HERE, "output_cng")

A_SIZES = {
    "A0": (1189, 841, 1.414),
    "A1": (841, 594, 1.416),
    "A2": (594, 420, 1.414),
    "A3": (420, 297, 1.414),
    "A3_WIDE": (604, 299, 2.02),
    "A4": (297, 210, 1.414),
}


def _rect_score(w, h):
    """评估矩形匹配哪个标准幅面（CNG 图纸：标准幅面按 100 倍打印）。"""
    rw, rh = max(w, h), min(w, h)
    ratio = rw / rh if rh else 1e9
    # 加长幅面（2:1 左右）
    if 1.95 <= ratio <= 2.05:
        return "A3_WIDE", 0.0
    # 标准幅面（约 1.414）按长边尺寸判断
    if 1.38 <= ratio <= 1.44:
        if rw >= 75000:
            return "A1", 0.0
        if rw >= 52000:
            return "A2", 0.0
        if rw >= 35000:
            return "A3", 0.0
        return "A4", 0.0
    # fallback：纯比例匹配
    best_name, best_err = "A1", 1e9
    for name, (tw, th, tr) in A_SIZES.items():
        r_err = abs(ratio - tr) / tr
        if r_err < best_err:
            best_err, best_name = r_err, name
    return best_name, best_err


def detect_big_frames(doc):
    """检测大坐标下的闭合矩形图框列表。"""
    msp = doc.modelspace()
    frames = []
    for e in msp.query("LWPOLYLINE"):
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
        # 近似矩形（4 点）
        if len(pts) <= 6:
            frames.append((min(xs), min(ys), max(xs), max(ys)))
    # 去重：保留外层（如果 A 完全包含 B，则丢弃 B）
    frames.sort(key=lambda f: (f[2]-f[0])*(f[3]-f[1]), reverse=True)
    MARGIN = 2000
    out = []
    for f in frames:
        if any((o[0]-MARGIN <= f[0] and o[1]-MARGIN <= f[1] and
                o[2]+MARGIN >= f[2] and o[3]+MARGIN >= f[3] and
                (o[2]-o[0])*(o[3]-o[1]) > (f[2]-f[0])*(f[3]-f[1])) for o in out):
            continue
        out.append(f)
    out.sort(key=lambda f: (f[0], f[1]))
    return out


def delete_frame_lines(doc, frame, margin=300):
    """删除命中该图框边线的 LINE / LWPOLYLINE。"""
    x0, y0, x1, y1 = frame
    msp = doc.modelspace()
    edge_x = {round(x0,1), round(x1,1)}
    edge_y = {round(y0,1), round(y1,1)}
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt == "LINE":
            s, t = e.dxf.start, e.dxf.end
            if abs(s.x-t.x) < 1 and (round(s.x,1) in edge_x):
                if min(s.y,t.y) >= y0-margin and max(s.y,t.y) <= y1+margin:
                    msp.delete_entity(e); n += 1
            elif abs(s.y-t.y) < 1 and (round(s.y,1) in edge_y):
                if min(s.x,t.x) >= x0-margin and max(s.x,t.x) <= x1+margin:
                    msp.delete_entity(e); n += 1
        elif dt == "LWPOLYLINE":
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                closed = bool(e.dxf.flags & 1) or (pts and pts[0] == pts[-1])
                if not closed or len(pts) < 4:
                    continue
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                if abs(min(xs)-x0)<margin and abs(max(xs)-x1)<margin and \
                   abs(min(ys)-y0)<margin and abs(max(ys)-y1)<margin:
                    msp.delete_entity(e); n += 1
            except Exception:
                pass
    return n


def titleblock_box(frame):
    """设计院图纸：标题栏固定为图框右下角区域（x 右 45%，y 底部 24%）。"""
    x0, y0, x1, y1 = frame
    W, H = x1 - x0, y1 - y0
    return (x0 + 0.55 * W, y0, x1, y0 + 0.24 * H)


def delete_titleblock(doc, frame):
    """删除右下角会签栏区域内所有实体（线、文字、表格），避免与公司图框重叠。"""
    tb = titleblock_box(frame)
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt == "INSERT":
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        cx = (eb[0] + eb[2]) / 2
        cy = (eb[1] + eb[3]) / 2
        if tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]:
            msp.delete_entity(e); n += 1
    return n


def delete_old_frame_inserts(doc, frame, margin=500):
    """删除图框区域内的旧图框 INSERT 块引用（如设计院 M_A2ZXL 图框块）。"""
    x0, y0, x1, y1 = frame
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        if e.dxftype() != "INSERT":
            continue
        ix, iy = e.dxf.insert.x, e.dxf.insert.y
        if x0 - margin <= ix <= x1 + margin and y0 - margin <= iy <= y1 + margin:
            msp.delete_entity(e); n += 1
    return n


def extract_design_fields(doc, frame):
    """设计院右下角会签栏字段提取。"""
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
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        cx = (eb[0] + eb[2]) / 2
        cy = (eb[1] + eb[3]) / 2
        if not (tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]):
            continue
        h = e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height
        items.append((cy, cx, h, raw))
    items.sort(reverse=True)

    fields = {}
    name_cands = [it for it in items if it[2] >= 500 and y0 <= it[0] <= y0 + 0.20 * H]
    if name_cands:
        fields["TITLE"] = name_cands[-1][3].replace(" ", "")

    for cy, cx, h, t in items:
        if re.search(r"[A-Za-z]+[-]?\d{2,4}.\d{2,4}", t):
            fields["DWG_NO"] = t
            break

    stage_map = {"初步设计": "初步设计", "施工图": "施工图", "方案": "方案",
                 "初步": "初步设计", "施工": "施工图"}
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
        if re.match(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}", t):
            fields["DATE"] = t
            break

    return fields


def delete_edge_markers(doc, frame, strip=400):
    """删除沿图框边缘的区号字母/数字。"""
    x0, y0, x1, y1 = frame
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
        if abs(cx-x0) < strip or abs(cx-x1) < strip or \
           abs(cy-y0) < strip or abs(cy-y1) < strip:
            msp.delete_entity(e); n += 1
    return n


def render_doc(doc, png_path, size_inches=(16,11.5), dpi=130):
    qsave(doc.modelspace(), png_path, dpi=dpi, size_inches=size_inches)


def pick_template(size_name):
    p = os.path.join(TPL_DIR, f"HH_FRAME_{size_name}.dxf")
    if os.path.exists(p):
        return p
    cands = sorted(glob.glob(os.path.join(TPL_DIR, "HH_FRAME_*.dxf")))
    return cands[-1] if cands else None


def process():
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = ezdxf.readfile(DXF_IN)
    frames = detect_big_frames(doc)
    print("检测到图框:", len(frames))
    for i, f in enumerate(frames):
        print(f"  [{i+1}] {f}  w={f[2]-f[0]:.0f} h={f[3]-f[1]:.0f} r={(f[2]-f[0])/(f[3]-f[1]):.3f}")

    # 渲染原图
    before_png = os.path.join(OUT_DIR, "CNG_电气系统图_before.png")
    render_doc(doc, before_png)

    results = []
    tpl_png_cache = {}
    for idx, frame in enumerate(frames):
        x0, y0, x1, y1 = frame
        w, h = x1 - x0, y1 - y0
        size_name, err = _rect_score(w, h)
        print(f"\n== 图框 {idx+1}: {frame} -> 匹配 {size_name} (err={err:.3f})")
        tpl_path = pick_template(size_name)
        if not tpl_path:
            print("   无模板，跳过")
            continue
        # 每个 size 渲染一次模板 PNG
        if size_name not in tpl_png_cache:
            tpl_png = os.path.join(OUT_DIR, f"template_{size_name}.png")
            render_doc(ezdxf.readfile(tpl_path), tpl_png)
            tpl_png_cache[size_name] = f"template_{size_name}.png"
        template = template_learn.learn_template(tpl_path)

        # 设计院图纸：专用右下角会签栏字段提取
        old_fields = extract_design_fields(doc, frame)
        print("   提取字段:", old_fields)
        values, unmatched, unused = mapper.map_fields(template["fields"], old_fields)

        n_edge = delete_frame_lines(doc, frame)
        n_tb = delete_titleblock(doc, frame)
        n_mark = delete_edge_markers(doc, frame)
        n_ins = delete_old_frame_inserts(doc, frame)
        print(f"   删除: 外框线={n_edge} 标题栏={n_tb} 边缘区号={n_mark} 旧图框块={n_ins}")

        # 插入新公司图框
        region = {"bbox": frame, "confidence": 1.0, "method": "frame", "source": "sheet", "entity": None}
        ins, written = block_replace.insert_template(doc, template, region, values, fit="max")
        print("   回填字段:", list(dict.fromkeys(written)))

        results.append({"idx": idx+1, "frame": frame, "size": size_name,
                        "fields": old_fields, "written": list(dict.fromkeys(written)),
                        "tpl_png": tpl_png_cache[size_name]})

    out_dxf = os.path.join(OUT_DIR, "CNG_电气系统图_HH.dxf")
    doc.saveas(out_dxf)
    print("\n已保存:", out_dxf, "版本=", doc.dxfversion)

    # 渲染生成后
    after_png = os.path.join(OUT_DIR, "CNG_电气系统图_after.png")
    render_doc(doc, after_png)

    # 生成对比 HTML（生成前 / 模板 / 生成后）
    html = os.path.join(OUT_DIR, "index.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><style>body{font-family:sans-serif;background:#1e1e1e;color:#ddd}img{max-width:100%;border:1px solid #444;margin:6px}h1,h2{color:#fff}table{width:100%}.k{color:#9cd}</style></head><body>\n")
        f.write("<h1>CNG 电气系统图 — 图框批量置换（生成前 / 公司模板 / 生成后）</h1>\n")
        for r in results:
            f.write(f"<h2>图框 {r['idx']} — {r['size']}</h2>\n")
            f.write(f"<p class='k'>提取字段：{r['fields']} &nbsp;|&nbsp; 回填字段：{r['written']}</p>\n")
            f.write("<table><tr>\n")
            f.write(f"<td width='45%'><b>生成前</b><br><img src='CNG_电气系统图_before.png'></td>\n")
            f.write(f"<td width='10%'><b>公司模板</b><br><img src='{r['tpl_png']}'></td>\n")
            f.write(f"<td width='45%'><b>生成后</b><br><img src='CNG_电气系统图_after.png'></td>\n")
            f.write("</tr></table>\n")
        f.write("</body></html>\n")
    print("对比索引:", html)
    return results


if __name__ == "__main__":
    process()
