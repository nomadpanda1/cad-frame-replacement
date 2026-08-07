# -*- coding: utf-8 -*-
"""
DWG 转换器探测与转换（ezdxf 只能读写 DXF）。
优先级：ODA File Converter（免费）> LibreCAD > AutoCAD COM。
本机若无转换器，则 DWG 输入回退为：提示用户先转 DXF；输出只给 DXF。
"""
import shutil
import subprocess
import os
import tempfile


def _which(name):
    p = shutil.which(name)
    if p:
        return p
    # 常见安装位置
    for base in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\Program Files"):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return None


def find_converter():
    """返回 (name, path) 或 None。"""
    oda = _which("ODAFileConverter.exe") or _which("ODAFileConverter")
    if oda:
        return ("ODAFileConverter", oda)
    lc = _which("librecad.exe") or _which("librecad")
    if lc:
        return ("LibreCAD", lc)
    return None


def dwg_to_dxf(src, dst):
    """把 DWG 转成 DXF，成功返回 True。"""
    conv = find_converter()
    if not conv:
        return False
    name, path = conv
    if name == "ODAFileConverter":
        indir = tempfile.mkdtemp()
        outdir = tempfile.mkdtemp()
        shutil.copy(src, indir)
        # ODAFileConverter <in> <out> <version> <type:DWG/DXF> <recursive:0/1>
        subprocess.run([path, indir, outdir, "ACAD2010", "DXF", "0"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for f in os.listdir(outdir):
            if f.lower().endswith(".dxf"):
                shutil.copy(os.path.join(outdir, f), dst)
                return True
    return False


def dxf_to_dwg(src, dst):
    """把 DXF 转成 DWG，成功返回 True。"""
    conv = find_converter()
    if not conv:
        return False
    name, path = conv
    if name == "ODAFileConverter":
        indir = tempfile.mkdtemp()
        outdir = tempfile.mkdtemp()
        shutil.copy(src, indir)
        subprocess.run([path, indir, outdir, "ACAD2010", "DWG", "0"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for f in os.listdir(outdir):
            if f.lower().endswith(".dwg"):
                shutil.copy(os.path.join(outdir, f), dst)
                return True
    return False
