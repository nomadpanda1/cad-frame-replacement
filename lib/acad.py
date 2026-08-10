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
    # 常见安装位置（根目录，旧逻辑兜底）
    for base in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\Program Files"):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return None


def find_converter():
    """返回 (name, path) 或 None。

    检测顺序：PATH → 常见默认安装父目录递归。
    ODA File Converter 默认装在 C:\\Program Files\\ODA\\ODAFileConverter 20xx\\ 子目录，
    旧逻辑只查根目录会漏，这里改为递归扫描默认安装父目录。
    （不递归 AppData/Program Files 巨树——权限/沙盒下 walk 不可靠且慢。）
    """
    # 1) PATH（含用户安装时勾选加入 PATH 的情况）
    oda = _which("ODAFileConverter.exe") or _which("ODAFileConverter")
    if oda:
        return ("ODAFileConverter", oda)
    lc = _which("librecad.exe") or _which("librecad")
    if lc:
        return ("LibreCAD", lc)

    # 2) 默认安装父目录递归（ODA/LibreCAD 都装在这几个确定位置）
    for base in (r"C:\Program Files\ODA", r"C:\Program Files (x86)\ODA",
                 r"C:\Program Files\LibreCAD", r"C:\Program Files (x86)\LibreCAD"):
        if not os.path.isdir(base):
            continue
        for cur, _dirs, files in os.walk(base):
            for f in files:
                fl = f.lower()
                if fl == "odafileconverter.exe":
                    return ("ODAFileConverter", os.path.join(cur, f))
                if fl == "librecad.exe":
                    return ("LibreCAD", os.path.join(cur, f))
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
