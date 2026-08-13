# -*- coding: utf-8 -*-
"""校验 test_other 各输出的：插入的 HH_FRAME 块名 / 幅面，标题栏 bbox 内残线数。
残线数应为 0（标题栏修复的「乱」症状验证）。"""
import os, glob, json
import ezdxf

ROOT = os.path.dirname(os.path.abspath(__file__))

def titlebar_bbox_of(doc, insert):
    """返回该 INSERT 的 HH_FRAME 标题栏世界 bbox（右下角小矩形）。"""
    blk = insert.dxf.name
    bdoc = doc.blocks.get(blk)
    if bdoc is None:
        return None
    xs, ys = [], []
    for se in bdoc:
        try:
            pts = se.get_points() if hasattr(se, "get_points") else []
        except Exception:
            pts = []
        for p in pts:
            xs.append(p[0]); ys.append(p[1])
    if not xs:
        return None
    lx0, ly0 = min(xs), min(ys)
    lx1, ly1 = max(xs), max(ys)
    ins = insert.dxf.insert
    sc = insert.dxf.xscale
    wx0, wy0 = lx0 * sc + ins[0], ly0 * sc + ins[1]
    wx1, wy1 = lx1 * sc + ins[0], ly1 * sc + ins[1]
    # 标题栏：右下 0.7~1.0 宽，0.0~0.25 高
    return (wx0 + 0.7 * (wx1 - wx0), wy0, wx1, wy0 + 0.25 * (wy1 - wy0))

def residual_in_tb(doc, tb):
    n = 0
    msp = doc.modelspace()
    for e in msp.query("LINE LWPOLYLINE POLYLINE"):
        try:
            pts = e.get_points() if hasattr(e, "get_points") else []
        except Exception:
            pts = []
        if not pts:
            try:
                pts = [e.dxf.start, e.dxf.end]
            except Exception:
                continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if tb[0] - 1 <= cx <= tb[2] + 1 and tb[1] - 1 <= cy <= tb[3] + 1:
            n += 1
    return n

def main():
    for d in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if not os.path.isdir(d) or os.path.basename(d) == "svg":
            continue
        outs = sorted(glob.glob(os.path.join(d, "*_HH.dxf")))
        if not outs:
            continue
        casename = os.path.basename(d)
        print("==== CASE", casename, "====")
        for out in outs:
            name = os.path.basename(out)
            try:
                doc = ezdxf.readfile(out)
            except Exception as e:
                print("  %-40s READ ERR %s" % (name, e)); continue
            msp = doc.modelspace()
            blocks = []
            residuals = 0
            for e in msp.query("INSERT"):
                if "HH_FRAME" in e.dxf.name:
                    blocks.append(e.dxf.name)
                    tb = titlebar_bbox_of(doc, e)
                    if tb:
                        residuals += residual_in_tb(doc, tb)
            print("  %-40s blocks=%s residual_in_titlebar=%d" % (name, ",".join(blocks) or "-", residuals))

if __name__ == "__main__":
    main()
