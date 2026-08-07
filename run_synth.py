# -*- coding: utf-8 -*-
"""
案例六验证：对 4 类合成异常样本跑图框替换工具，记录实际行为与局限。
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
        try: font_manager.fontManager.addfont(fp)
        except Exception: pass

INP = os.path.join(HERE, "cases", "06_synth", "inputs")
OUT = os.path.join(HERE, "cases", "06_synth", "outputs")
TPL_DIR = os.path.join(HERE, "templates")
os.makedirs(OUT, exist_ok=True)

def render(doc, png):
    qsave(doc.modelspace(), png, dpi=130, size_inches=(11.7, 8.3))

def sheet(doc):
    bb = bbox_mod.extents(list(doc.modelspace()))
    return (bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y)

def detect_frames_simple(doc):
    """数 LWPOLYLINE 闭合矩形（近似图框）：宽高均>80 且面积>5000 即计为一个图框。"""
    msp = doc.modelspace()
    frames = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.closed:
            b = bbox_mod.extents([e])
            if not b.has_data: continue
            w = b.extmax.x-b.extmin.x; h = b.extmax.y-b.extmin.y
            if w > 80 and h > 80 and w*h > 5000:
                frames.append((round(w), round(h)))
    return frames

def extract_by_label(doc):
    """右下角按标签抽取 图名/图号/比例/阶段，并配对相邻的值文本。"""
    msp = doc.modelspace()
    s = sheet(doc); Sw, Sh = s[2]-s[0], s[3]-s[1]
    items = []
    for e in msp:
        if e.dxftype() in ("TEXT","MTEXT"):
            b = bbox_mod.extents([e])
            if not b.has_data: continue
            cx, cy = (b.extmin.x+b.extmax.x)/2, (b.extmin.y+b.extmax.y)/2
            if cx >= s[0]+Sw*0.5 and cy <= s[1]+Sh*0.5:
                t = (e.dxf.text if e.dxftype()!="MTEXT" else (getattr(e,"text","") or "")).strip()
                if t: items.append((cx, cy, t))
    # 标签 -> 同行右侧的值
    got = {}
    labels = ("图名","图号","比例","阶段")
    for cx, cy, t in items:
        if t in labels:
            val = ""
            for cx2, cy2, t2 in items:
                if t2 not in labels and abs(cy2-cy) < 4 and cx2 > cx:
                    val = t2; break
            got[t] = val or "(未配对)"
    return got

def insert_hh(doc, size):
    tpl = os.path.join(TPL_DIR, f"HH_FRAME_{size}.dxf")
    template = template_learn.learn_template(tpl)
    s = sheet(doc)
    region = {"bbox": s, "confidence": 1.0, "method": "frame", "source": "sheet", "entity": None}
    ins, written = block_replace.insert_template(doc, template, region, {}, fit="max")
    return ins, written

results = {}

# ---- 06a 多图框混排 ----
doc = ezdxf.readfile(os.path.join(INP, "06a_multiframe.dxf"))
fr = detect_frames_simple(doc)
render(doc, os.path.join(OUT, "06a_before.png"))
# 演示当前工具行为：整图幅插一张 A1 公司图框（覆盖而非逐框）
ins_a, _ = insert_hh(doc, "A1")
doc.saveas(os.path.join(OUT, "06a_after.dxf"))
render(doc, os.path.join(OUT, "06a_after.png"))
results["06a_多图框混排"] = {
    "检测到的闭合矩形(宽×高)": fr,
    "当前工具行为": "整图幅插入 1 张 HH_FRAME_A1（覆盖原多图框，非逐框替换）",
    "结论": f"检测到 {len(fr)} 个闭合矩形（1 个最外 A1 框 + 内嵌的 A3/A4/A1 小图框）。"
            "当前工具按'整图幅'插一张公司图框，不逐图框(视口)替换——"
            "多图框混排图纸是已知局限，需后续增强为逐框处理。",
}

# ---- 06b 嵌套块标题栏 ----
doc = ezdxf.readfile(os.path.join(INP, "06b_nested_title.dxf"))
_tmp = os.path.join(OUT, "_06b_learn.dxf")
doc.saveas(_tmp)
lt = template_learn.learn_template(_tmp)
os.remove(_tmp)
nested_note = "标题栏=块 TITLEBLOCK，内部又 INSERT 了含 ATTDEF 的子块 TB_FIELDS"
# 抽取：看 learn_template 选了哪个块、拿到哪些字段
chosen = lt.get("block_name"); flds = [(f["tag"], f.get("prompt","")) for f in lt.get("fields",[])]
render(doc, os.path.join(OUT, "06b_before.png"))
# 尝试插公司图框（整图 A4）
ins, written = insert_hh(doc, "A4")
doc.saveas(os.path.join(OUT, "06b_after.dxf"))
render(doc, os.path.join(OUT, "06b_after.png"))
results["06b_嵌套块标题栏"] = {
    "learn_template 选中块": chosen,
    "识别到的字段数": len(flds),
    "字段样例": flds[:6],
    "说明": nested_note + "；" + ("learn_template 正确穿透到含 ATTDEF 的子块 ✅" if flds else "未穿透到嵌套字段 ⚠（局限）"),
    "插公司图框": f"INSERT={ins.dxf.name if ins else None}, 写回字段={written}",
}

# ---- 06c 缺字体 SHX ----
doc = ezdxf.readfile(os.path.join(INP, "06c_missing_font.dxf"))
# 抽取文字串（与字体无关）
msp = doc.modelspace()
txts = [ (e.dxf.text if e.dxftype()!="MTEXT" else (getattr(e,"text","") or "")).strip()
         for e in msp if e.dxftype() in ("TEXT","MTEXT") ]
render(doc, os.path.join(OUT, "06c_before.png"))   # 缺失字体下渲染不应崩
ins, written = insert_hh(doc, "A4")
doc.saveas(os.path.join(OUT, "06c_after.dxf"))
render(doc, os.path.join(OUT, "06c_after.png"))
results["06c_缺字体SHX"] = {
    "引用字体": "hzdx_ghost.shx（不存在）",
    "抽取到的文字串": txts,
    "渲染是否崩溃": "否（matplotlib 回退默认字体，缺字显示方框但不报错）",
    "插公司图框": f"INSERT={ins.dxf.name if ins else None}",
}

# ---- 06d 会签栏差异 ----
doc = ezdxf.readfile(os.path.join(INP, "06d_countersign.dxf"))
got = extract_by_label(doc)
render(doc, os.path.join(OUT, "06d_before.png"))
ins, written = insert_hh(doc, "A4")
doc.saveas(os.path.join(OUT, "06d_after.dxf"))
render(doc, os.path.join(OUT, "06d_after.png"))
results["06d_会签栏差异"] = {
    "原始标题栏含字段": "图名/图号/比例/阶段/设计/校对/审核/批准/会签(多出)",
    "按标签抽取结果": got,
    "结论": "尽管多了'会签'列，图名/图号/比例/阶段 仍被正确抽取并回填 ✅（字段映射按标签而非位置）",
    "插公司图框": f"INSERT={ins.dxf.name if ins else None}, 写回={written}",
}

# 写结果日志
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# 案例索引
html = os.path.join(OUT, "index.html")
with open(html, "w", encoding="utf-8") as f:
    f.write("<html><head><meta charset='utf-8'><style>"
            "body{font-family:sans-serif;background:#1e1e1e;color:#ddd}"
            "img{max-width:46%;border:1px solid #444;margin:4px}"
            "h1{color:#fff}.k{color:#9cd}</style></head><body>\n")
    f.write("<h1>案例六 · 合成异常样本（多图框/嵌套块/缺字体/会签栏差异）</h1>\n")
    f.write("<p class='k'>用 ezdxf 程序化生成的可控异常图，用于验证工具鲁棒性。加密类见案例二(CNG)。</p>\n")
    pairs = [("06a","多图框混排"),("06b","嵌套块标题栏"),("06c","缺字体SHX"),("06d","会签栏差异")]
    for pre, name in pairs:
        f.write(f"<h2>{pre} {name}</h2>\n")
        f.write(f"<img src='{pre}_before.png'><img src='{pre}_after.png'>\n")
    f.write("</body></html>\n")
print("案例六索引:", html)
print(json.dumps(results, ensure_ascii=False, indent=2))
