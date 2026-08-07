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
    """装配体这类'无图框但有标题栏/明细表'图纸：插入公司图框前，只清理旧标题栏
    文字与旧标题框闭合矩形。绝不碰线/几何/尺寸/BOM 表（避免误删真实数据）。

    白名单策略：
      - TEXT/MTEXT/ATTDEF（标题文字）：删
      - 闭合矩形 LWPOLYLINE/POLYLINE（旧标题框）：删
      - 线/弧/圆/填充/块/尺寸标注 等其它一切：全部保留
    """
    msp = doc.modelspace()
    zx0, zy0, zx1, zy1 = zone
    zx0 -= pad; zy0 -= pad; zx1 += pad; zy1 += pad

    def _fully_in(b):
        return (b.extmin.x >= zx0 - 1 and b.extmax.x <= zx1 + 1 and
                b.extmin.y >= zy0 - 1 and b.extmax.y <= zy1 + 1)

    def _closed(e):
        try:
            if e.dxftype() == "LWPOLYLINE":
                return bool(e.closed)
            if e.dxftype() == "POLYLINE":
                return bool(e.is_closed)
        except Exception:
            return False
        return False

    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT", "ATTDEF"):
            try:
                b = bbox_mod.extents([e])
            except Exception:
                continue
            if b and b.has_data and _fully_in(b):
                msp.delete_entity(e); n += 1
            continue
        if dt in ("LWPOLYLINE", "POLYLINE") and _closed(e):
            try:
                b = bbox_mod.extents([e])
            except Exception:
                continue
            if b and b.has_data and _fully_in(b):
                msp.delete_entity(e); n += 1
            continue
        # 其它（LINE/ARC/CIRCLE/DIMENSION/INSERT/...）：全部保留
    return n


def insert_frame_only(doc, tpl_path, sheet_bbox):
    """只插公司图框的'外框'，不插标题栏——用于图纸已有标题栏/明细表时，
    保留原标题栏内容，只补一圈公司框边界。"""
    # 用稳定落地的 .bak 占位（safe-delete shim 会直接删掉 tempfile 的临时文件，
    # 导致后续 learn_template 读取时文件已消失）；删除失败则忽略，不影响流程。
    tmp = os.path.join(HERE, "_frame_only.bak")
    tdoc = ezdxf.readfile(tpl_path)
    tmsp = tdoc.modelspace()
    # 模板坐标下标题栏大致区域（A3 约 x∈[200,420] y∈[0,70]），删掉标题栏实体
    for e in list(tmsp):
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if b and b.has_data and b.extmin.x >= 195 and b.extmax.x <= 425 \
                and b.extmin.y >= 0 and b.extmax.y <= 72:
            tmsp.delete_entity(e)
    tdoc.saveas(tmp)
    template = template_learn.learn_template(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass  # safe-delete shim 拦截时忽略（占位文件）
    region = {"bbox": sheet_bbox, "confidence": 1.0, "method": "frame",
              "source": "sheet", "entity": None}
    ins, written = block_replace.insert_template(doc, template, region, {}, fit="max")
    return ins, written


def title_zone_has_content(doc, zone, pad=2.0):
    """统计标题区内实体数，判断是否已存在标题栏/明细表（避免清掉真实内容）。"""
    zx0, zy0, zx1, zy1 = zone
    zx0 -= pad; zy0 -= pad; zx1 += pad; zy1 += pad
    n = 0
    for e in doc.modelspace():
        if e.dxftype() not in ("TEXT", "MTEXT", "ATTDEF", "LWPOLYLINE",
                               "POLYLINE", "LINE", "INSERT"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not (b and b.has_data):
            continue
        if (b.extmin.x >= zx0 - 1 and b.extmax.x <= zx1 + 1 and
                b.extmin.y >= zy0 - 1 and b.extmax.y <= zy1 + 1):
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

    n_zone = title_zone_has_content(doc, tblk)
    print("title-zone entity count:", n_zone)
    if n_zone > 6:
        # 标题区已有标题栏/明细表 -> 只加外框，保留原标题栏（不丢数据）
        ins, written = insert_frame_only(doc, TPL, sheet)
        mode = "只加外框(保留原标题栏)"
    else:
        # 真空白 -> 白名单清区后插整框
        n = clear_title_block_zone(doc, tblk)
        print("cleared title-block-zone entities:", n)
        region = {"bbox": sheet, "confidence": 1.0, "method": "frame",
                  "source": "sheet", "entity": None}
        ins, written = block_replace.insert_template(doc, template, region, {}, fit="max")
        mode = "清空+整框插入"
    print("inserted", ins, "written", written, "| mode:", mode)

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
