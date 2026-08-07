# -*- coding: utf-8 -*-
"""
装配体图纸(1).DWG 的图框替换脚本（AutoCAD COM 转 DXF + ezdxf 处理）。

图纸特征（已探测）：
- 二进制 DWG，0 个代理实体 -> 可安全用 AutoCAD COM 转成 DXF。
- 幅面 A3 横放（420×297），4109 实体，无 TEXT 标题栏 -> 仅做框替换，字段留空。
- 旧图框 = 沿纸边的线段 + 分区号数字/A-F 字母；删除纸边 3mm margin 内实体即可清掉。

流程：DWG→DXF(SaveAs fmt=1) -> 删旧框边/分区号 -> 插 HH_FRAME_A3 -> 出 DXF + 三栏 PNG。
"""
import os
import sys
import time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ezdxf
import win32com.client
from ezdxf import bbox as bbox_mod
from ezdxf.addons.drawing.matplotlib import qsave

from lib import template_learn, block_replace

for fp in [r"C:\Windows\Fonts\simhei.ttf"]:
    if os.path.exists(fp):
        try:
            font_manager.fontManager.addfont(fp)
        except Exception:
            pass

DWG_IN = r"C:\Users\86308\Documents\xwechat_files\luorong5973_2748\msg\file\2026-08\装配体图纸(1).DWG"
TPL = os.path.join(HERE, "templates", "HH_FRAME_A3.dxf")
OUT_DIR = os.path.join(HERE, "cases", "04_assembly", "outputs")
DXF_TMP = os.path.join(HERE, "_asm_tmp.dxf")


def dwg_to_dxf(src_dwg, dst_dxf):
    app = win32com.client.Dispatch("AutoCAD.Application")
    doc = app.Documents.Open(src_dwg)
    time.sleep(2)
    doc.SaveAs(dst_dxf, 1)  # DXF ASCII
    doc.Close(False)
    print("DWG->DXF:", dst_dxf, "size", os.path.getsize(dst_dxf))


def clear_title_block_zone(doc, zone, pad=2.0):
    """装配体这类'无图框/无标题栏'图纸：原图在标题栏区域仅有零散标注/尺寸文本，
    插入公司标题栏前，先把该矩形内的原始实体清掉，避免与公司标题栏重叠。"""
    msp = doc.modelspace()
    zx0, zy0, zx1, zy1 = zone
    zx0 -= pad; zy0 -= pad; zx1 += pad; zy1 += pad
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE",
                     "TEXT", "MTEXT", "INSERT", "ATTDEF", "DIMENSION"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        eb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        # 实体与标题栏矩形相交即删除
        if eb[2] >= zx0 and eb[0] <= zx1 and eb[3] >= zy0 and eb[1] <= zy1:
            msp.delete_entity(e)
            n += 1
    return n


def render_one(path_or_doc, png, landscape=True):
    doc = ezdxf.readfile(path_or_doc) if isinstance(path_or_doc, str) else path_or_doc
    size = (11.7, 8.3) if landscape else (8.3, 11.7)
    qsave(doc.modelspace(), png, dpi=130, size_inches=size)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(DWG_IN))[0]

    # 1) 转 DXF
    if not os.path.exists(DXF_TMP):
        dwg_to_dxf(DWG_IN, DXF_TMP)

    # 2) ezdxf 处理
    doc = ezdxf.readfile(DXF_TMP)
    msp = doc.modelspace()
    ext = bbox_mod.extents(msp)
    sheet = (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    print("sheet:", [round(v, 1) for v in sheet])

    # 生成前渲染（基于临时 DXF）
    before_png = os.path.join(OUT_DIR, base + "_before.png")
    render_one(DXF_TMP, before_png)

    # 模板渲染
    tpl_png = os.path.join(OUT_DIR, base + "_template.png")
    render_one(TPL, tpl_png)

    # 装配体无旧图框/标题栏 -> 直接计算公司模板的标题栏矩形（A3->A3 近 1:1，
    # 模板坐标≈图纸坐标），清掉该区域内零散标注后再插公司标题栏。
    template = template_learn.learn_template(TPL)
    tblk = None
    best_area = 1e18
    blk = doc.blocks.get(template.get("block_name")) if template.get("block_name") else None
    if blk is None:
        for b in doc.blocks:
            if "FRAME" in b.name.upper():
                blk = b
                break
    if blk is not None:
        for e in blk:
            if e.dxftype() == "LWPOLYLINE" and e.closed:
                try:
                    b = bbox_mod.extents([e])
                except Exception:
                    continue
                if not b or not b.has_data:
                    continue
                area = (b.extmax.x - b.extmin.x) * (b.extmax.y - b.extmin.y)
                # 标题栏是三道闭合框里面积最小的那道，且位于右下角
                if area < best_area and b.extmin.x > (sheet[2] - sheet[0]) / 2:
                    best_area = area
                    tblk = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
    if tblk is None:
        tblk = (235, 6, 415, 62)  # 兜底：HH A3 标题栏默认范围
    print("title-block zone (template coords):", [round(v, 1) for v in tblk])

    n = clear_title_block_zone(doc, tblk)
    print("cleared title-block-zone entities:", n)

    # 插公司图框
    region = {"bbox": sheet, "confidence": 1.0, "method": "frame", "source": "sheet", "entity": None}
    ins, written = block_replace.insert_template(doc, template, region, {}, fit="max")
    print("inserted", ins, "written", written)

    out_dxf = os.path.join(OUT_DIR, base + "_HH.dxf")
    doc.saveas(out_dxf)

    after_png = os.path.join(OUT_DIR, base + "_after.png")
    render_one(out_dxf, after_png)

    # 复制输入 DWG
    inp_dir = os.path.join(HERE, "cases", "04_assembly", "inputs")
    os.makedirs(inp_dir, exist_ok=True)
    import shutil
    dst = os.path.join(inp_dir, os.path.basename(DWG_IN))
    if not os.path.exists(dst):
        shutil.copy(DWG_IN, dst)

    # 索引
    html = os.path.join(OUT_DIR, "index.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><style>"
                "body{font-family:sans-serif;background:#1e1e1e;color:#ddd}"
                "img{max-width:100%;border:1px solid #444;margin:6px}h2{color:#fff}"
                "table{margin:0 auto}.k{color:#9cd}</style></head><body>\n")
        f.write("<h1>装配体图纸 DWG 图框替换（COM 转 DXF + ezdxf）</h1>\n")
        f.write("<p class='k'>幅面 A3 横放 420×297；无 TEXT 标题栏 -> 字段留空；"
                "旧图框通过删除纸边 3mm 边带清除。</p>\n")
        f.write("<table><tr>\n")
        f.write(f"<td><b>生成前</b><br><img src='{os.path.basename(before_png)}'></td>\n")
        f.write(f"<td><b>公司模板</b><br><img src='{os.path.basename(tpl_png)}'></td>\n")
        f.write(f"<td><b>生成后</b><br><img src='{os.path.basename(after_png)}'></td>\n")
        f.write("</tr></table>\n")
        f.write("</body></html>\n")
    print("对比索引:", html)


if __name__ == "__main__":
    main()
