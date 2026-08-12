# -*- coding: utf-8 -*-
"""案例十渲染：把 11 张住宅楼电气图纸的 原图/结果 渲染成 PNG（DWG 经 COM 转 DXF 后 ezdxf 出图）。

用法:
  python render_case10.py            # 渲染全部 before/after
  python render_case10.py before     # 仅原图
  python render_case10.py after      # 仅结果
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
IN_DIR = os.path.join(HERE, "cases", "10_residential_electrical", "inputs")
OUTDIR = os.path.join(HERE, "cases", "10_residential_electrical", "outputs")
RES_DIR = os.path.join(HERE, "output_test")
os.makedirs(OUTDIR, exist_ok=True)


def dwg_to_dxf(src, dst):
    import win32com.client as wc
    for _ in range(4):
        try:
            a = wc.GetActiveObject("AutoCAD.Application")
            a.Visible = True
            break
        except Exception:
            time.sleep(2)
    else:
        a = wc.Dispatch("AutoCAD.Application")
        a.Visible = True
    if os.path.exists(dst):
        try: os.remove(dst)
        except Exception: pass
    doc = a.Documents.Open(os.path.abspath(src))
    time.sleep(2)
    for _ in range(3):
        try:
            doc.SaveAs(os.path.abspath(dst))
            break
        except Exception as e:
            print("   SaveAs dxf err:", e); time.sleep(2)
    time.sleep(1)
    try:
        doc.Close(False)
    except Exception:
        pass
    time.sleep(1)
    return os.path.exists(dst)


def render_dxf(dxf, png, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    fig = plt.figure(figsize=(11.7, 8.27))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp, finalize=True)
    ax.set_aspect("equal")
    if title:
        ax.set_title(title, fontsize=10)
    fig.savefig(png, dpi=130)
    plt.close(fig)
    print("  rendered", os.path.basename(png))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(f for f in os.listdir(IN_DIR) if f.lower().endswith(".dwg"))
    for fn in files:
        base = os.path.splitext(fn)[0]
        if only in (None, "before"):
            src = os.path.join(IN_DIR, fn)
            dxf = os.path.join(OUTDIR, "_%s_src.dxf" % base)
            print("转原图 %s ..." % fn)
            if dwg_to_dxf(src, dxf):
                render_dxf(dxf, os.path.join(OUTDIR, base + "_before.png"), base + " (原图)")
        if only in (None, "after"):
            res = os.path.join(RES_DIR, base + "_HH.dwg")
            if not os.path.exists(res):
                print("  ! 缺少结果:", res); continue
            dxf = os.path.join(OUTDIR, "_%s_HH.dxf" % base)
            print("转结果 %s ..." % base)
            if dwg_to_dxf(res, dxf):
                render_dxf(dxf, os.path.join(OUTDIR, base + "_HH.png"), base + " (HH)")
    # 清理临时 DXF
    for f in os.listdir(OUTDIR):
        if f.startswith("_") and f.endswith(".dxf"):
            try: os.remove(os.path.join(OUTDIR, f))
            except Exception: pass
    print("done")


if __name__ == "__main__":
    main()
