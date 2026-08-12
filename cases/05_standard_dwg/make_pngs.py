# -*- coding: utf-8 -*-
"""案例五（标准设计院图纸 92DZ1 消火栓泵）配图生成：
  1) 用本机 AutoCAD COM 把源 DWG / 成品 _HH.dwg 各 SaveAs 成 DXF（格式整数穷举 + ezdxf 回读校验）；
  2) 用 ezdxf qsave 渲染 生成前 / 公司模板 / 生成后 三张 PNG 到 outputs/。
  依赖本机 AutoCAD（与 run_cng_acad.py 同策略二）。仅用于生成展示配图，不参与核心管线。
"""
import os, sys, tempfile, glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

CJK = r"C:\Windows\Fonts\simhei.ttf"
if os.path.exists(CJK):
    font_manager.fontManager.addfont(CJK)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=CJK).get_name()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import ezdxf
from ezdxf.addons.drawing.matplotlib import qsave

import win32com.client as wc

SRC_DWG = os.path.join(HERE, "inputs", "92DZ1_xiaohuobeng.dwg")
OUT_DWG = os.path.join(HERE, "outputs", "dwg", "92DZ1_xiaohuobeng_HH.dwg")
TPL_DXF = os.path.join(ROOT, "templates", "HH_FRAME_A3.dxf")
OUT_DIR = os.path.join(HERE, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)


def find_dxf_format(doc, src_path):
    """穷举 SaveAs 格式整数，用 ezdxf 回读校验；返回最现代(整数最大)可用格式的 (fmt, dxf_path)。"""
    base = src_path[:-4]
    candidates = list(range(1, 26)) + [50, 51, 52, 53, 54, 60, 61, 62, 63, 64, 65]
    valid = []
    for fmt in candidates:
        tmp = base + f"_tmp{fmt}.dxf"
        if os.path.exists(tmp):
            os.remove(tmp)
        try:
            doc.SaveAs(tmp, fmt)
        except Exception:
            continue
        if not os.path.exists(tmp):
            continue
        try:
            ezdxf.readfile(tmp)
        except Exception:
            os.remove(tmp)
            continue
        valid.append((fmt, tmp))
    if not valid:
        raise RuntimeError("未找到可用的 DXF SaveAs 格式整数")
    # 选最现代(整数最大)的可用格式
    valid.sort(key=lambda x: x[0], reverse=True)
    # 清理其余临时文件
    for fmt, p in valid[1:]:
        try:
            os.remove(p)
        except Exception:
            pass
    return valid[0]


def render(doc, png):
    qsave(doc.modelspace(), png, dpi=130)


def main():
    acad = wc.GetActiveObject("AutoCAD.Application")
    acad.Visible = True

    # 1) 源 DWG -> DXF -> before.png
    d1 = acad.Documents.Open(os.path.abspath(SRC_DWG))
    fmt, src_dxf = find_dxf_format(d1, os.path.abspath(SRC_DWG))
    print("source DXF format =", fmt, src_dxf)
    src_doc = ezdxf.readfile(src_dxf)
    render(src_doc, os.path.join(OUT_DIR, "92DZ1_xiaohuobeng_before.png"))
    d1.Close(False)
    os.remove(src_dxf)

    # 2) 成品 _HH.dwg -> DXF -> HH.png
    d2 = acad.Documents.Open(os.path.abspath(OUT_DWG))
    fmt2, out_dxf = find_dxf_format(d2, os.path.abspath(OUT_DWG))
    print("output DXF format =", fmt2, out_dxf)
    out_doc = ezdxf.readfile(out_dxf)
    render(out_doc, os.path.join(OUT_DIR, "92DZ1_xiaohuobeng_HH.png"))
    d2.Close(False)
    os.remove(out_dxf)

    # 3) 公司模板 A3 -> template.png
    tpl_doc = ezdxf.readfile(TPL_DXF)
    render(tpl_doc, os.path.join(OUT_DIR, "92DZ1_xiaohuobeng_template.png"))

    print("PNGs written to", OUT_DIR)
    for p in sorted(glob.glob(os.path.join(OUT_DIR, "*.png"))):
        print("  ", os.path.basename(p), os.path.getsize(p))


if __name__ == "__main__":
    main()
