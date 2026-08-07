# -*- coding: utf-8 -*-
"""
生成"异常场景"合成测试样本（案例六），全部用 ezdxf 直接写 DXF（无 COM、无丢失）。
覆盖四类可程序化合成的异常，用于验证图框替换工具对多样输入的鲁棒性：
  06a 多图框混排   —— 一张图内含 A3/A4/A1 三张不同尺寸图框
  06b 嵌套块标题栏 —— 标题栏是 BLOCK，内部又 INSERT 了含 ATTDEF 的子块
  06c 缺字体(SHX)  —— TEXT 引用不存在的字体（hzdx_ghost.shx），验证不崩溃
  06d 会签栏差异   —— 标题栏含"会签"列（不同设计院常见），验证字段映射不受影响
注：加密/代理实体 DWG（案例二 CNG 已覆盖）无法用 ezdxf 合成真实代理实体，故不在本包。
"""
import os, ezdxf
from ezdxf import bbox as bbox_mod

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cases", "06_synth", "inputs")
os.makedirs(OUT, exist_ok=True)

# HH_FRAME 14 个标准字段（与 templates 对齐），用于合成含字段的标题栏
FIELDS = ["TITLE","DWG_NO","SCALE","STAGE","MATERIAL","WEIGHT","VERSION",
          "DATE","SIZE","DESIGN","CHECK","REVIEW","APPROVE","COUNTERSIGN"]

def add_frame(doc, x0, y0, w, h, title):
    """在 (x0,y0) 起、宽 w 高 h 处画一个外框 + 右下角标题条 + 标题文字。"""
    msp = doc.modelspace()
    msp.add_lwpolyline([(x0,y0),(x0+w,y0),(x0+w,y0+h),(x0,y0+h),(x0,y0)],
                       dxfattribs={"closed": True})
    # 标题条（右下角）
    tx0, ty0 = x0 + w*0.55, y0 + h*0.02
    msp.add_lwpolyline([(tx0,ty0),(x0+w,ty0),(x0+w,y0+h*0.18),(tx0,y0+h*0.18),(tx0,ty0)],
                       dxfattribs={"closed": True})
    msp.add_text(title, dxfattribs={"height": h*0.05}).set_placement((tx0+5, ty0+h*0.06))

# ---------- 06a 多图框混排 ----------
def gen_multiframe():
    doc = ezdxf.new("R2010", setup=True)
    # A1 整图 841x594
    doc.modelspace().add_lwpolyline([(0,0),(841,0),(841,594),(0,594),(0,0)],
                                    dxfattribs={"closed": True})
    add_frame(doc, 20, 300, 420, 270, "图框A: A3 零件图")   # A3 420x297 近似
    add_frame(doc, 460, 300, 297, 210, "图框B: A4 明细表")   # A4
    add_frame(doc, 20, 20, 400, 260, "图框C: A1 总图(缩)")  # 大框
    p = os.path.join(OUT, "06a_multiframe.dxf")
    doc.saveas(p); return p

# ---------- 06b 嵌套块标题栏 ----------
def gen_nested():
    doc = ezdxf.new("R2010", setup=True)
    doc.modelspace().add_lwpolyline([(0,0),(420,0),(420,297),(0,297),(0,0)],
                                    dxfattribs={"closed": True})
    # 子块：含 ATTDEF 字段
    sub = doc.blocks.new("TB_FIELDS")
    sub.add_lwpolyline([(300,5),(415,5),(415,60),(300,60),(300,5)],
                       dxfattribs={"closed": True})
    labels = ["图名","图号","比例","阶段","材料","设计","校对","审核","批准"]
    for i, lab in enumerate(labels):
        y = 52 - i*6
        sub.add_text(lab, dxfattribs={"height": 3}).set_placement((303, y))
        sub.add_attdef(f"F{i:02d}", dxfattribs={"height": 3, "prompt": lab}).set_placement((340, y))
    # 父块：画边框 + INSERT 子块
    parent = doc.blocks.new("TITLEBLOCK")
    parent.add_lwpolyline([(298,3),(417,3),(417,62),(298,62),(298,3)],
                          dxfattribs={"closed": True})
    parent.add_blockref("TB_FIELDS", (0, 0))
    # 插入父块
    doc.modelspace().add_blockref("TITLEBLOCK", (0, 0))
    p = os.path.join(OUT, "06b_nested_title.dxf")
    doc.saveas(p); return p

# ---------- 06c 缺字体 SHX ----------
def gen_missing_font():
    doc = ezdxf.new("R2010", setup=True)
    doc.styles.new("GHOST", dxfattribs={"font": "hzdx_ghost.shx"})  # 不存在的 SHX
    doc.modelspace().add_lwpolyline([(0,0),(420,0),(420,297),(0,297),(0,0)],
                                    dxfattribs={"closed": True})
    msp = doc.modelspace()
    msp.add_text("正常字体标题：法兰", dxfattribs={"height": 8}).set_placement((20, 250))
    msp.add_text("缺失字体文字：图号 FLANGE-001",
                 dxfattribs={"height": 8, "style": "GHOST"}).set_placement((20, 220))
    msp.add_text("比例 1:2 / 阶段 施工图",
                 dxfattribs={"height": 8, "style": "GHOST"}).set_placement((20, 190))
    p = os.path.join(OUT, "06c_missing_font.dxf")
    doc.saveas(p); return p

# ---------- 06d 会签栏差异 ----------
def gen_countersign():
    doc = ezdxf.new("R2010", setup=True)
    doc.modelspace().add_lwpolyline([(0,0),(420,0),(420,297),(0,297),(0,0)],
                                    dxfattribs={"closed": True})
    msp = doc.modelspace()
    # 标准标题栏 + 额外"会签"列（设计院 B 风格）
    msp.add_lwpolyline([(235,5),(415,5),(415,62),(235,62),(235,5)],
                       dxfattribs={"closed": True})
    rows = [("图名","16MW储能 舱体布置图"),("图号","BESS-LST-010"),
            ("比例","NTS"),("阶段","施工图"),
            ("设计","张三"),("校对","李四"),("审核","王五"),("批准","赵六"),
            ("会签","钱七")]   # <- 多出的会签栏
    for i,(k,v) in enumerate(rows):
        y = 56 - i*5.5
        msp.add_text(k, dxfattribs={"height": 3}).set_placement((238, y))
        msp.add_text(v, dxfattribs={"height": 3}).set_placement((275, y))
    p = os.path.join(OUT, "06d_countersign.dxf")
    doc.saveas(p); return p

if __name__ == "__main__":
    for fn in [gen_multiframe, gen_nested, gen_missing_font, gen_countersign]:
        p = fn()
        print("生成:", os.path.basename(p), os.path.getsize(p), "bytes")
    print("全部完成 ->", OUT)
