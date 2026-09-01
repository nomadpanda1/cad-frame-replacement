# -*- coding: utf-8 -*-
"""构造最小 DXF 的测试辅助。所有测试不依赖外部图纸/模板文件，纯内存生成。"""
import ezdxf


def new_doc():
    """返回一个全新的 R2010 图纸文档。"""
    return ezdxf.new("R2010")


def add_rect(msp, x0, y0, x1, y1, closed=True, dxftype="LWPOLYLINE", layer="0"):
    """在 modelspace 加一个轴对齐闭合矩形（旧图框/标题框）。"""
    if dxftype == "LWPOLYLINE":
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        return msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
    e = msp.add_polyline3d(
        [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, y0, 0)],
        dxfattribs={"layer": layer},
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


def add_rect_segments(msp, x0, y0, x1, y1, segs_per_side=3):
    """用分段短直线（LINE）画一个轴对齐矩形，模拟「边框被拆成多段短直线」的画法。

    每条边（上/下/左/右）拆成 segs_per_side 段，单段长度 < 边长，故单段不足以
    跨越图幅 —— 旧 detect_frames 的「单段 > 0.5×图幅」阈值会漏检，新覆盖度实现可重建。
    """
    def seg(a, b, n):
        out = []
        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n
            out.append((a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0,
                        a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1))
        return out
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    lines = []
    for k in range(4):
        lines += seg(pts[k], pts[k + 1], segs_per_side)
    for (sx, sy, ex, ey) in lines:
        msp.add_line((sx, sy), (ex, ey))
