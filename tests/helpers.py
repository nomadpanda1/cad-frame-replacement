# -*- coding: utf-8 -*-
"""构造最小 DXF 的测试辅助。所有测试不依赖外部图纸/模板文件，纯内存生成。"""
import ezdxf


def new_doc():
    """返回一个全新的 R2010 图纸文档。"""
    return ezdxf.new("R2010")


def add_rect(msp, x0, y0, x1, y1, closed=True, dxftype="LWPOLYLINE"):
    """在 modelspace 加一个轴对齐闭合矩形（旧图框/标题框）。"""
    if dxftype == "LWPOLYLINE":
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        return msp.add_lwpolyline(pts, close=closed)
    e = msp.add_polyline3d(
        [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, y0, 0)]
    )
    e.close(True)
    return e


def add_text(msp, text, x, y, dxftype="TEXT", height=2.5):
    """在 (x,y) 加一个文本实体。"""
    if dxftype == "TEXT":
        return msp.add_text(text, dxfattribs={"insert": (x, y), "height": height})
    return msp.add_mtext(text, dxfattribs={"insert": (x, y)})


def add_attdef(msp, tag, prompt, x, y, height=2.5):
    """在 (x,y) 加一个 ATTDEF（属性定义，标题栏字段）。"""
    return msp.add_attdef(
        tag, insert=(x, y), text=prompt,
        dxfattribs={"height": height, "prompt": prompt},
    )


def add_line(msp, x1, y1, x2, y2, dxftype="LINE"):
    """加一条线。dxftype='LWPOLYLINE' 时返回非闭合两段多段线（用于短格线）。"""
    if dxftype == "LINE":
        return msp.add_line((x1, y1), (x2, y2))
    return msp.add_lwpolyline([(x1, y1), (x2, y2)], close=False)


def add_dimension(msp, p1, p2, dimstyle="Standard"):
    """加一个线性尺寸标注（DIMENSION 实体），返回该实体。"""
    dim = msp.add_linear_dim(
        base=(p1[0], p1[1] - 10), p1=p1, p2=p2, dimstyle=dimstyle
    )
    dim.render()
    for e in msp:
        if e.dxftype() == "DIMENSION":
            return e
    return None
