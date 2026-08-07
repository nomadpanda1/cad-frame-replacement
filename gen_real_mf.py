# -*- coding: utf-8 -*-
"""
案例八 · 用真实图纸拼真实多图框（解决「真实多图框端到端验证缺数据」）。

把 4 张**真实 ESS 图纸**（一次设备表 / 二次系统信号表 / 二次系统柜体表 / 储能系统
简化主接线图）的 modelspace 实体平移拷贝到一张新 DXF 的 2×2 网格，形成 4 个
**真实图框**（真实标题栏 + 真实字段 + 真实几何）。仅排布是合成的，内容 100% 真实。

这样即可在「真实标题块结构」上跑多图框逐框替换管线，完成端到端验证，不依赖任何新图纸。
"""
import os, sys
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ESS = os.path.join(HERE, "cases", "03_ESS_cad", "inputs")
OUT_DIR = os.path.join(HERE, "cases", "08_real_mf", "inputs")
os.makedirs(OUT_DIR, exist_ok=True)

# 4 张真实 ESS 图纸（均为单张 A1，标题栏在 modelspace TEXT）
SOURCES = [
    ("16MW_32MWh_一次设备表.dxf",          (0,   660)),
    ("16MW_32MWh_二次系统信号表.dxf",       (900, 660)),
    ("16MW_32MWh_二次系统柜体表.dxf",       (0,   0)),
    ("16MW_32MWh_储能系统简化主接线图.dxf",  (900, 0)),
]
CELL_W, CELL_H = 900, 660

target = ezdxf.new("R2010")
tm = target.modelspace()
total = 0
for fname, (ox, oy) in SOURCES:
    src = ezdxf.readfile(os.path.join(ESS, fname))
    cnt = 0
    for e in src.modelspace():
        try:
            c = e.copy()
            try:
                c.translate(ox, oy, 0.0)
            except Exception as ex:
                print(f"  [warn] {fname} translate failed: {ex}")
            tm.add_entity(c)
            cnt += 1
        except Exception as ex:
            print(f"  [warn] {fname} {e.dxftype()} copy failed: {ex}")
    print(f"  {fname}: 拷贝 {cnt} 实体 -> 网格({ox},{oy})")
    total += cnt

out = os.path.join(OUT_DIR, "08_real_multiframe.dxf")
target.saveas(out)
print(f"\n合成多图框图纸已生成: {out}")
print(f"共 {total} 实体（4 张真实 ESS 图纸平移拼接，无整图纸边 → 4 框均为替换目标）")
