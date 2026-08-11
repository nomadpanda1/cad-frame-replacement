# -*- coding: utf-8 -*-
"""
针对真实 DWG（SolidWorks 导出、打散图框、A3/A4）的整框替换脚本。
流程：DWG→DXF（已转好放 input_real/）→ 检测外框矩形 + 标题栏 → 先提取旧字段
      → 删旧外框线 + 删旧标题栏(紧凑) + 删边缘区号 → 按图幅匹配 HH_FRAME_A* 模板
      → 插入公司图框并回填字段 → 出 DXF + PNG 对比图（生成前/模板/生成后）。
"""
import os
import sys
import glob
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 中文字体（标题栏汉字）
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
INPUT_DIR = os.path.join(HERE, "input_real")
OUT_DIR = os.path.join(HERE, "output_real")

A_SIZES = [("A0", 1189, 841), ("A1", 841, 594), ("A2", 594, 420),
           ("A3", 420, 297), ("A4", 297, 210)]


def sheet_extents(doc):
    ext = bbox_mod.extents(doc.modelspace())
    if not ext or not ext.has_data:
        return None
    return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)


def guess_size(sheet):
    w = sheet[2] - sheet[0]
    h = sheet[3] - sheet[1]
    best, best_err = None, 1e9
    for name, sw, sh in A_SIZES:
        for cand in [(sw, sh), (sh, sw)]:
            err = abs(w - cand[0]) / cand[0] + abs(h - cand[1]) / cand[1]
            if err < best_err:
                best_err, best = err, name
    return best if best_err < 0.15 else "A3"


def pick_template(size_name):
    p = os.path.join(TPL_DIR, f"HH_FRAME_{size_name}.dxf")
    if os.path.exists(p):
        return p
    cands = sorted(glob.glob(os.path.join(TPL_DIR, "HH_FRAME_*.dxf")))
    return cands[-1] if cands else None


def delete_frame_lines(doc, frames):
    """只删外框/内框矩形的四条边线（不碰内容）。"""
    msp = doc.modelspace()
    # 收集所有边线坐标
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
            # 竖直框线：只要求 x 对齐边框竖边，不要求端点“由底到顶”存储
            # （SolidWorks 导出的 LINE 常以“高→低”存储，旧写法会漏删竖线）。
            if abs(s.x - en.x) < 1e-3 and ("v", round(s.x, 1)) in edge_coords:
                msp.delete_entity(e); n += 1
            elif abs(s.y - en.y) < 1e-3 and ("h", round(s.y, 1)) in edge_coords:
                msp.delete_entity(e); n += 1
        elif dt in ("LWPOLYLINE", "POLYLINE"):
            # 闭合矩形边框（坐标命中）也删
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


def delete_titleblock(doc, tb, maxdim):
    """删标题栏区域内实体：文本全删；线只删短线（网格线），保留长线（可能是真实尺寸线）。"""
    msp = doc.modelspace()
    thr = 0.30 * maxdim
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
        if dt in ("LINE", "LWPOLYLINE", "POLYLINE"):
            L = max(eb[2] - eb[0], eb[3] - eb[1])
            if L > thr:
                continue
        msp.delete_entity(e); n += 1
    return n


def delete_edge_markers(doc, outer, strip=10.0):
    """删沿外框边缘的区号字母/数字（如 A/B/C 与 4/5/6），这些是 SW 图框系统的一部分。"""
    import re
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


def render_one(doc_or_path, png_path, size_inches, dpi=130):
    doc = ezdxf.readfile(doc_or_path) if isinstance(doc_or_path, str) else doc_or_path
    qsave(doc.modelspace(), png_path, dpi=dpi, size_inches=size_inches)


def size_inches_for(sheet):
    w = sheet[2] - sheet[0]
    h = sheet[3] - sheet[1]
    return (8.3, 11.7) if h > w else (11.7, 8.3)


def process_one(dxf_path, out_dir):
    base = os.path.splitext(os.path.basename(dxf_path))[0]
    print("\n== 处理:", base)
    doc = ezdxf.readfile(dxf_path)
    sheet = sheet_extents(doc)
    if not sheet:
        return None, "无法计算图幅"
    print("   图幅 bbox:", [round(x, 1) for x in sheet])

    frames = finder.detect_frames(doc)
    if not frames:
        return None, "未检测到外框"
    # #5：取面积最大的框作为最外框，双线图框（外框+内框）时不会被内框误导
    outer = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    print("   检测到外框:", [tuple(round(v, 1) for v in f) for f in frames])
    tb = finder.detect_titleblock(doc, outer)
    print("   标题栏区域:", [round(v, 1) for v in tb])

    # #4：按检测到的 outer 框选模板幅面，避免 stray 远点误判
    size_name = guess_size(outer)
    print("   匹配幅面:", size_name)
    tpl_path = pick_template(size_name)
    if not tpl_path:
        return None, "找不到模板"
    print("   模板:", os.path.basename(tpl_path))
    template = template_learn.learn_template(tpl_path)

    # 渲染 生成前
    before_png = os.path.join(out_dir, base + "_before.png")
    render_one(dxf_path, before_png, size_inches_for(outer))
    # 渲染 模板
    tpl_png = os.path.join(out_dir, base + "_template.png")
    render_one(tpl_path, tpl_png, size_inches_for(outer))

    # ★ 先提取旧字段（删除前）
    old_fields = extract.extract_fields(doc, {"bbox": tb, "method": "keyword", "entity": None})
    print("   提取字段:", old_fields)
    values, unmatched, unused = mapper.map_fields(template["fields"], old_fields)
    print("   回填字段:", list(dict.fromkeys([f["tag"] for f, v in zip(template["fields"], values) if v])))

    maxdim = max(outer[2] - outer[0], outer[3] - outer[1])
    n_edge = delete_frame_lines(doc, frames)
    n_tb = delete_titleblock(doc, tb, maxdim)
    n_mark = delete_edge_markers(doc, outer, strip=10.0)
    print(f"   删除: 外框线={n_edge} 标题栏实体={n_tb} 边缘区号={n_mark}")

    # 插入新公司图框（按检测到的 outer 框缩放，#4：避免 stray 远点把新框撑大）
    region = {"bbox": outer, "confidence": 1.0, "method": "frame", "source": "sheet", "entity": None}
    ins, written = block_replace.insert_template(doc, template, region, values, fit="max")
    print("   实际回填:", list(dict.fromkeys(written)))

    out_dxf = os.path.join(out_dir, base + "_HH.dxf")
    doc.saveas(out_dxf)

    after_png = os.path.join(out_dir, base + "_after.png")
    render_one(out_dxf, after_png, size_inches_for(outer))

    return {"dxf": out_dxf, "before": before_png, "template": tpl_png,
            "after": after_png, "size": size_name, "tpl": os.path.basename(tpl_path),
            "fields": old_fields, "written": list(dict.fromkeys(written))}, None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.dxf")))
    results = []
    for fp in files:
        rec, err = process_one(fp, OUT_DIR)
        if err:
            print("   [ERR]", err)
        else:
            results.append(rec)
    print("\n== 完成，共处理", len(results), "张")
    html = os.path.join(OUT_DIR, "index.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><style>body{font-family:sans-serif;background:#1e1e1e;color:#ddd}img{max-width:100%;border:1px solid #444;margin:6px}h2{color:#fff}table{margin:0 auto}.k{color:#9cd}</style></head><body>\n")
        f.write("<h1>CAD 图框批量置换效果对比（生成前 / 公司模板 / 生成后）</h1>\n")
        for r in results:
            f.write(f"<h2>{os.path.basename(r['dxf'])} &nbsp;<span class='k'>({r['size']}, 模板 {r['tpl']})</span></h2>\n")
            f.write("<p class='k'>提取字段：" + str(r['fields']) + "<br>回填字段：" + str(r['written']) + "</p>\n")
            f.write("<table><tr>\n")
            f.write(f"<td><b>生成前</b><br><img src='{os.path.basename(r['before'])}'></td>\n")
            f.write(f"<td><b>公司模板</b><br><img src='{os.path.basename(r['template'])}'></td>\n")
            f.write(f"<td><b>生成后</b><br><img src='{os.path.basename(r['after'])}'></td>\n")
            f.write("</tr></table>\n")
        f.write("</body></html>\n")
    print("对比索引:", html)


if __name__ == "__main__":
    main()
