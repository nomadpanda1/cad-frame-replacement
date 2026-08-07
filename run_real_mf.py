# -*- coding: utf-8 -*-
"""
案例八 · 真实多图框端到端 runner。

对 gen_real_mf.py 生成的「4 张真实 ESS 图拼成的多图框 DXF」跑逐框替换管线：
检测多图框 → 逐框选模板 / learn / 抽字段 / mapper 对齐 / 删旧框线+标题栏 / insert_template(fit=max) 回填。
验证目标：4 个真实图框都能被正确检测、抽取真实字段、逐框插入 HH 公司图框，且表格几何零丢失。
"""
import os, sys, json
import ezdxf
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

INP = os.path.join(HERE, "cases", "08_real_mf", "inputs")
OUT = os.path.join(HERE, "cases", "08_real_mf", "outputs")
TPL_DIR = os.path.join(HERE, "templates")
os.makedirs(OUT, exist_ok=True)

A_SIZES = {"A0": (1190, 843), "A1": (842, 596), "A2": (595, 422),
           "A3": (421, 299), "A4": (298, 212)}


def pick_template(fb):
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


fname = "08_real_multiframe.dxf"
print("==========", "案例八 · 真实多图框端到端", "==========")
doc = ezdxf.readfile(os.path.join(INP, fname))
base = fname.replace(".dxf", "")
before_png = os.path.join(OUT, base + "_before.png")
render(doc, before_png)

sheet_bbox, targets = finder.detect_frames_hierarchical(doc)
print(f"  整图纸框(sheet): {[round(v, 1) for v in sheet_bbox] if sheet_bbox else None}")
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
tpl_png = os.path.join(OUT, base + "_template.png")
if tpl_for_index:
    render(ezdxf.readfile(tpl_for_index), tpl_png)

# 几何零丢失校验：before/after 实体数对比（_HH 多出的只是新插入的 HH_FRAME）
n_before = len(list(ezdxf.readfile(os.path.join(INP, fname)).modelspace()))
n_after = len(list(doc.modelspace()))
print(f"\n  几何校验: before 实体={n_before} after 实体={n_after} "
      f"(差值={n_after - n_before} = 新插入的 HH 图框, 旧几何应保留)")

results = {
    "说明": "4 张真实 ESS 图纸(一次设备表/二次信号表/二次柜体表/主接线图)平移拼成 2×2 多图框，内容 100% 真实，仅排布合成。",
    "整图纸框(纸边)": [round(v, 1) for v in sheet_bbox] if sheet_bbox else None,
    "检测到需替换的图框数": len(targets),
    "before实体数": n_before, "after实体数": n_after,
    "逐框结果": per,
}
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n案例八结果:", os.path.join(OUT, "results.json"))
print(json.dumps(results, ensure_ascii=False, indent=2))
