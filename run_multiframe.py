# -*- coding: utf-8 -*-
"""
案例七 · 多图框逐框替换：检测多图框 -> 逐框插入公司图框(HH_FRAME) -> 逐框回填字段。
覆盖两种分支：
  - 含整图纸框（07a 平铺）：只替换子框，保留纸边。
  - 并排多框无整图纸框（07b）：所有框均为替换目标（CNG 真实场景的简化版）。
"""
import os, sys, json
import ezdxf
from ezdxf import bbox as bbox_mod
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from ezdxf.addons.drawing.matplotlib import qsave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import template_learn, block_replace, finder, mapper

for fp in [r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]:
    if os.path.exists(fp):
        try:
            font_manager.fontManager.addfont(fp)
        except Exception:
            pass
plt.rcParams["font.family"] = "DejaVu Sans"

INP = os.path.join(HERE, "cases", "07_multiframe", "inputs")
OUT = os.path.join(HERE, "cases", "07_multiframe", "outputs")
TPL_DIR = os.path.join(HERE, "templates")
os.makedirs(OUT, exist_ok=True)

A_SIZES = {"A0": (1190, 843), "A1": (842, 596), "A2": (595, 422),
           "A3": (421, 299), "A4": (298, 212)}


def pick_template(fb):
    """按图框宽高比选最接近的 A 幅面模板。"""
    w = fb[2] - fb[0]
    h = fb[3] - fb[1]
    ar = w / h
    best, bd = "A4", 1e9
    for sz, (tw, th) in A_SIZES.items():
        d = abs(ar - tw / th)
        if d < bd:
            bd = d
            best = sz
    return os.path.join(TPL_DIR, f"HH_FRAME_{best}.dxf"), best


def render(doc, png, landscape=True):
    size = (11.7, 8.3) if landscape else (8.3, 11.7)
    qsave(doc.modelspace(), png, dpi=130, size_inches=size)


SAMPLES = [
    ("07a_tiled.dxf", "A1 整图含 3 个子图框（含整图纸框）"),
    ("07b_side_by_side.dxf", "4 个并排 A3 图框（无整图纸框，CNG 简化版）"),
]

results = {}

for fname, desc in SAMPLES:
    print("\n==========", fname, "==========")
    doc = ezdxf.readfile(os.path.join(INP, fname))
    base = fname.replace(".dxf", "")
    before_png = os.path.join(OUT, base + "_before.png")
    render(doc, before_png)

    sheet_bbox, targets = finder.detect_frames_hierarchical(doc)
    print(f"  整图纸框(sheet): {[round(v,1) for v in sheet_bbox] if sheet_bbox else None}")
    print(f"  需逐框替换的图框数: {len(targets)}")

    per = []
    tpl_for_index = None
    for i, fb in enumerate(targets):
        tpl_path, size = pick_template(fb)
        if tpl_for_index is None:
            tpl_for_index = tpl_path
        template = template_learn.learn_template(tpl_path)
        fields = finder.extract_frame_fields(doc, fb)
        values, unmatched, unused = mapper.map_fields(template["fields"], fields)
        written = [f["tag"] for f, v in zip(template["fields"], values) if v]
        # 外科手术式删除：只删该帧旧边框 + 右下角旧标题栏，保留图内几何
        nd = block_replace.delete_frame_border(doc, fb)
        nts = block_replace.delete_title_strip(doc, fb)
        region = {"bbox": fb, "confidence": 1.0, "method": "frame",
                  "source": "multiframe", "entity": None}
        ins, written2 = block_replace.insert_template(doc, template, region, values, fit="max")
        per.append({
            "frame": [round(v, 1) for v in fb],
            "size": size,
            "fields": fields,
            "written": written2,
            "del_border": nd,
            "del_strip": nts,
        })
        print(f"  帧{i+1} {size} 字段={fields} 写回={written2} 删边框={nd} 删标题栏={nts}")

    out_dxf = os.path.join(OUT, base + "_HH.dxf")
    doc.saveas(out_dxf)
    after_png = os.path.join(OUT, base + "_HH.png")
    render(doc, after_png)
    # 模板缩略图（首帧所选模板）
    tpl_png = os.path.join(OUT, base + "_template.png")
    if tpl_for_index:
        render(ezdxf.readfile(tpl_for_index), tpl_png)

    results[fname] = {
        "说明": desc,
        "整图纸框(纸边)": [round(v, 1) for v in sheet_bbox] if sheet_bbox else None,
        "检测到需替换的图框数": len(targets),
        "逐框结果": per,
    }

# 写结果日志
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# 案例索引
html = os.path.join(OUT, "index.html")
with open(html, "w", encoding="utf-8") as f:
    f.write("<html><head><meta charset='utf-8'><style>"
            "body{font-family:sans-serif;background:#1e1e1e;color:#ddd}"
            "img{max-width:31%;border:1px solid #444;margin:3px;vertical-align:top}"
            "h1{color:#fff}.k{color:#9cd}table{border-collapse:collapse;margin:6px 0}"
            "td{border:1px solid #444;padding:4px 8px;font-size:13px}"
            "th{background:#333;color:#fff}</style></head><body>\n")
    f.write("<h1>案例七 · 多图框逐框替换（生成前 / 公司模板 / 生成后）</h1>\n")
    f.write("<p class='k'>检测多图框 → 逐框插入公司图框(HH_FRAME) → 逐框回填字段。"
            "07a 含整图纸框(只换子框)；07b 并排多框无整图纸框(全换)。</p>\n")
    for fname, desc in SAMPLES:
        base = fname.replace(".dxf", "")
        r = results[fname]
        f.write(f"<h2>{fname} —— {desc}</h2>\n")
        f.write(f"<p class='k'>整图纸框(纸边): {r['整图纸框(纸边)']} | "
                f"替换图框数: {r['检测到需替换的图框数']}</p>\n")
        f.write(f"<img src='{base}_before.png'><img src='{base}_template.png'>"
                f"<img src='{base}_HH.png'>\n")
        f.write("<table><tr><th>帧</th><th>尺寸</th><th>抽取字段</th>"
                f"<th>写回</th><th>删边框</th><th>删标题栏</th></tr>\n")
        for i, fr in enumerate(r["逐框结果"]):
            f.write(f"<tr><td>{i+1}</td><td>{fr['size']}</td>"
                    f"<td>{fr['fields']}</td><td>{fr['written']}</td>"
                    f"<td>{fr['del_border']}</td><td>{fr['del_strip']}</td></tr>\n")
        f.write("</table>\n")
    f.write("</body></html>\n")
print("\n案例七索引:", html)
print(json.dumps(results, ensure_ascii=False, indent=2))
