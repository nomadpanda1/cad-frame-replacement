# -*- coding: utf-8 -*-
"""
针对储能(ESS) CAD 成果包（16MW/32MWh 一次设备表 / 二次系统信号表 / 二次系统柜体表 /
储能系统简化主接线图）的整框替换脚本。

图纸特征（已探测）：
- 干净 AC1032 DXF，0 个代理实体 -> 走 ezdxf 纯离线路径（策略一）。
- 外框 = 单个闭合 LWPOLYLINE，821×574（≈A1 幅面，x[10,831] y[10,584]）。
- 标题栏 = 右下角小条（x[565,831] y[10,55]），4 个字段：
    图名: 16MW/32MWh 储能电站 一次设备表
    图号: BESS-LST-001
    阶段: 学习/概念设计
    比例: NTS
  无 日期/设计/审核/批准 -> 这些 HH_FRAME 字段留空。

流程：检测外框 -> 提取标题栏字段 -> 删旧外框+删底部标题条 -> 插公司图框(HH_FRAME_A3 缩放 2x≈A1)
      -> 回填字段 -> 出 DXF + PNG 三栏对比。
"""
import os
import sys
import glob
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ezdxf
from ezdxf import bbox as bbox_mod
from ezdxf.addons.drawing.matplotlib import qsave

from lib import template_learn, block_replace, mapper

# 中文字体
for fp in [r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]:
    if os.path.exists(fp):
        try:
            font_manager.fontManager.addfont(fp)
        except Exception:
            pass
plt.rcParams["font.family"] = "DejaVu Sans"

TPL_DIR = os.path.join(HERE, "templates")
# ESS 探测得 821×574≈A1；所有图纸均为同一幅面
TPL = os.path.join(TPL_DIR, "HH_FRAME_A1.dxf")
ESS_DIR = r"C:\Users\86308\Documents\xwechat_files\luorong5973_2748\msg\file\2026-08\储能CAD成果包\储能CAD成果包"
OUT_DIR = os.path.join(HERE, "cases", "03_ESS_cad", "outputs")

FILES = [
    "16MW_32MWh_一次设备表.dxf",
    "16MW_32MWh_二次系统信号表.dxf",
    "16MW_32MWh_二次系统柜体表.dxf",
    "16MW_32MWh_储能系统简化主接线图.dxf",
]


def sheet_extents(doc):
    ext = bbox_mod.extents(doc.modelspace())
    if not ext or not ext.has_data:
        return None
    return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)


def detect_outer_frame(doc):
    """返回最外层闭合矩形 (x0,y0,x1,y1) 或 None。"""
    msp = doc.modelspace()
    segs = []
    for e in msp:
        dt = e.dxftype()
        if dt == "LWPOLYLINE":
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
            except Exception:
                continue
            closed = bool(e.dxf.flags & 1) if hasattr(e.dxf, "flags") else False
            if not (closed or (pts and pts[0] == pts[-1])):
                continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            if (x1 - x0) > 100 and (y1 - y0) > 100:
                segs.append((x0, y0, x1, y1))
    if not segs:
        return None
    # 取面积最大者
    segs.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
    return segs[0]


def extract_ess_fields(doc, outer):
    """从右下角标题条提取 图名/图号/阶段/比例 -> {concept: value}。"""
    msp = doc.modelspace()
    x0, y0, x1, y1 = outer
    W = x1 - x0; H = y1 - y0
    texts = []
    for e in msp.query("TEXT"):
        try:
            x, y, t = e.dxf.insert.x, e.dxf.insert.y, e.dxf.text
        except Exception:
            continue
        texts.append((x, y, t))
    fields = {}
    for x, y, t in texts:
        if "图号" in t:
            fields["DWG_NO"] = t.split("图号", 1)[1].lstrip(":： ").strip()
        elif "阶段" in t:
            fields["STAGE"] = t.split("阶段", 1)[1].lstrip(":： ").strip()
        elif "比例" in t:
            fields["SCALE"] = t.split("比例", 1)[1].lstrip(":： ").strip()
    # 图名：标题区内无冒号、较长的中文文本
    cand = [(x, y, t) for x, y, t in texts
            if y <= y0 + 0.14 * H and x >= x0 + 0.4 * W
            and ":" not in t and len(t) >= 4]
    if cand:
        cand.sort(key=lambda r: -len(r[2]))
        fields["TITLE"] = cand[0][2]
    return fields


def delete_outer_frame(doc, outer):
    x0, y0, x1, y1 = outer
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        if e.dxftype() == "LWPOLYLINE":
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
            except Exception:
                continue
            if not pts:
                continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            if (abs(min(xs) - x0) < 2 and abs(max(xs) - x1) < 2 and
                    abs(min(ys) - y0) < 2 and abs(max(ys) - y1) < 2):
                msp.delete_entity(e); n += 1
    return n


def delete_bottom_strip(doc, outer, strip=62.0):
    """删除底部标题条区域所有实体（线+文本），安全：内容最低 y≈90 远高于条区。"""
    x0, y0, x1, y1 = outer
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        dt = e.dxftype()
        if dt not in ("LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "CIRCLE", "ARC"):
            continue
        try:
            b = bbox_mod.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        if b.extmax.y <= y0 + strip:
            msp.delete_entity(e); n += 1
    return n


def render_one(path_or_doc, png, landscape):
    dpi = 150
    size = (11.7, 8.3) if landscape else (8.3, 11.7)
    doc = ezdxf.readfile(path_or_doc) if isinstance(path_or_doc, str) else path_or_doc
    qsave(doc.modelspace(), png, dpi=dpi, size_inches=size)


def process_one(dxf_path, out_dir):
    base = os.path.splitext(os.path.basename(dxf_path))[0]
    print("\n== 处理:", base)
    doc = ezdxf.readfile(dxf_path)
    sheet = sheet_extents(doc)
    if not sheet:
        return None, "无法计算图幅"
    outer = detect_outer_frame(doc)
    if not outer:
        return None, "未检测到外框"
    print("   外框:", [round(v, 1) for v in outer])

    # 渲染 生成前
    before_png = os.path.join(out_dir, base + "_before.png")
    render_one(dxf_path, before_png, landscape=True)

    # 模板（A3 缩放后≈A1）
    tpl_png = os.path.join(out_dir, base + "_template.png")
    render_one(TPL, tpl_png, landscape=True)

    # 提取字段（删除前）
    old_fields = extract_ess_fields(doc, outer)
    print("   提取字段:", old_fields)

    # 模板学习 + 字段映射
    template = template_learn.learn_template(TPL)
    values, unmatched, unused = mapper.map_fields(template["fields"], old_fields)
    written = [f["tag"] for f, v in zip(template["fields"], values) if v]
    print("   回填字段:", written, " 未匹配:", unmatched)

    # 删除旧框 + 标题条
    n_f = delete_outer_frame(doc, outer)
    n_b = delete_bottom_strip(doc, outer)
    print(f"   删除: 外框线={n_f} 标题条实体={n_b}")

    # 插公司图框：扩到 A1 整幅（841×594），A3 模板缩放≈2x
    x0, y0, x1, y1 = outer
    W = x1 - x0; H = y1 - y0
    # 以原外框为中心，扩到 A1 比例（841:594）整幅
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sw, sh = 841.0, 594.0
    # 采用 max fit 填满，等比缩放
    region = {"bbox": (cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2),
              "confidence": 1.0, "method": "frame", "source": "sheet", "entity": None}
    ins, written2 = block_replace.insert_template(doc, template, region, values, fit="max")
    print("   实际回填:", written2)

    out_dxf = os.path.join(out_dir, base + "_HH.dxf")
    doc.saveas(out_dxf)

    after_png = os.path.join(out_dir, base + "_after.png")
    render_one(out_dxf, after_png, landscape=True)

    return {"dxf": out_dxf, "before": before_png, "template": tpl_png,
            "after": after_png, "fields": old_fields,
            "written": written2, "unmatched": unmatched}, None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # 复制输入
    inp_dir = os.path.join(HERE, "cases", "03_ESS_cad", "inputs")
    os.makedirs(inp_dir, exist_ok=True)
    results = []
    for fn in FILES:
        src = os.path.join(ESS_DIR, fn)
        if not os.path.exists(src):
            # 微信源目录不可用时，回退到已拷贝的 inputs/
            src = os.path.join(inp_dir, fn)
        if not os.path.exists(src):
            print("MISSING", src)
            continue
        dst = os.path.join(inp_dir, fn)
        if not os.path.exists(dst):
            import shutil
            shutil.copy(src, dst)
        rec, err = process_one(src, OUT_DIR)
        if err:
            print("   [ERR]", err)
        else:
            results.append(rec)
    print("\n== 完成，共处理", len(results), "张")
    html = os.path.join(OUT_DIR, "index.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><style>"
                "body{font-family:sans-serif;background:#1e1e1e;color:#ddd}"
                "img{max-width:100%;border:1px solid #444;margin:6px}h2{color:#fff}"
                "table{margin:0 auto}.k{color:#9cd}</style></head><body>\n")
        f.write("<h1>ESS 储能 CAD 图框替换效果对比（生成前 / 公司模板 / 生成后）</h1>\n")
        for r in results:
            f.write(f"<h2>{os.path.basename(r['dxf'])}</h2>\n")
            f.write("<p class='k'>提取字段：" + str(r['fields']) +
                    "<br>回填字段：" + str(r['written']) +
                    "<br>未匹配(留空)：" + str(r['unmatched']) + "</p>\n")
            f.write("<table><tr>\n")
            f.write(f"<td><b>生成前</b><br><img src='{os.path.basename(r['before'])}'></td>\n")
            f.write(f"<td><b>公司模板</b><br><img src='{os.path.basename(r['template'])}'></td>\n")
            f.write(f"<td><b>生成后</b><br><img src='{os.path.basename(r['after'])}'></td>\n")
            f.write("</tr></table>\n")
        f.write("</body></html>\n")
    print("对比索引:", html)


if __name__ == "__main__":
    main()
