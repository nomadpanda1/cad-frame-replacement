# -*- coding: utf-8 -*-
"""
生成"多图框逐框替换"测试样本（案例七），全部用 ezdxf 直接写 DXF（无 COM、无丢失）。
  07a 平铺多框  —— 一张 A1 整图内含 3 个子图框（含整图纸框），每框带 图名/图号/比例/阶段 标题栏。
                  用于测试 detect_frames_hierarchical 的"含整图纸框"分支（只替换子框，保留纸边）。
  07b 并排多框  —— 4 个并排 A3 图框（无整图纸框），每框带标题栏。
                  用于测试"并排多框/无整图纸框"分支（CNG 真实场景的简化版）。
"""
import os, ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cases", "07_multiframe", "inputs")
os.makedirs(OUT, exist_ok=True)


def add_title_block(doc, x0, y0, w, h, title, dwgno, scale, stage):
    """在 (x0,y0,w,h) 图框右下角画标题栏：4 行（图名/图号/比例/阶段）。"""
    msp = doc.modelspace()
    tw = w * 0.42
    th = h * 0.26
    tx0, ty0 = x0 + w - tw, y0
    # 标题栏外框
    msp.add_lwpolyline([(tx0, ty0), (tx0 + tw, ty0), (tx0 + tw, ty0 + th),
                        (tx0, ty0 + th), (tx0, ty0)], dxfattribs={"closed": True})
    # 行分隔线（3 条）
    rows = [title, dwgno, scale, stage]
    labels = ["图名", "图号", "比例", "阶段"]
    rh = th / 4
    for i in range(1, 4):
        yy = ty0 + i * rh
        msp.add_line((tx0, yy), (tx0 + tw, yy))
    # 标签 + 值
    for i, (lab, val) in enumerate(zip(labels, rows)):
        yy = ty0 + (i + 0.5) * rh
        msp.add_text(lab, dxfattribs={"height": rh * 0.42}).set_placement((tx0 + 3, yy - rh * 0.2))
        msp.add_text(val, dxfattribs={"height": rh * 0.42}).set_placement((tx0 + tw * 0.32, yy - rh * 0.2))


def add_frame(doc, x0, y0, w, h, title, dwgno, scale, stage):
    """画一个外框 + 右下角标题栏 + 框内占位标题文字。"""
    msp = doc.modelspace()
    msp.add_lwpolyline([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h),
                        (x0, y0 + h), (x0, y0)], dxfattribs={"closed": True})
    add_title_block(doc, x0, y0, w, h, title, dwgno, scale, stage)
    # 框内占位（模拟零件名，避免空图）
    msp.add_text(title, dxfattribs={"height": h * 0.06}).set_placement((x0 + w * 0.05, y0 + h * 0.6))


def gen_tiled():
    """07a：A1 整图 (0,0)-(841,594) 内含 3 个子图框。"""
    doc = ezdxf.new("R2010", setup=True)
    # 整图纸框（纸边）
    doc.modelspace().add_lwpolyline([(0, 0), (841, 0), (841, 594), (0, 594), (0, 0)],
                                    dxfattribs={"closed": True})
    add_frame(doc, 20, 300, 420, 270, "A3 零件图-减速器箱体", "JX-001-A3", "1:2", "施工图")
    add_frame(doc, 460, 300, 297, 210, "A4 明细表-螺栓清单", "JX-001-A4", "NTS", "施工图")
    add_frame(doc, 20, 20, 400, 260, "A1 总图-管线布置(缩)", "JX-001-A1", "1:50", "初步设计")
    p = os.path.join(OUT, "07a_tiled.dxf")
    doc.saveas(p)
    return p


def gen_side_by_side():
    """07b：4 个并排 A3 图框（无整图纸框），模拟 CNG 并排多框场景。"""
    doc = ezdxf.new("R2010", setup=True)
    specs = [
        (20, 320, 400, 300, "基础平面图-区一", "CNG-0501/01", "1:100", "初步设计"),
        (440, 320, 400, 300, "基础平面图-区二", "CNG-0501/02", "1:100", "初步设计"),
        (20, 20, 400, 300, "工艺流程图-区一", "CNG-0501/03", "NTS", "施工图"),
        (440, 20, 400, 300, "平面布置图-区二", "CNG-0501/04", "1:100", "建筑室"),
    ]
    for x0, y0, w, h, t, n, s, st in specs:
        add_frame(doc, x0, y0, w, h, t, n, s, st)
    p = os.path.join(OUT, "07b_side_by_side.dxf")
    doc.saveas(p)
    return p


if __name__ == "__main__":
    for fn in [gen_tiled, gen_side_by_side]:
        p = fn()
        print("生成:", os.path.basename(p), os.path.getsize(p), "bytes")
    print("全部完成 ->", OUT)
