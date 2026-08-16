# -*- coding: utf-8 -*-
"""DWG <-> DXF 无头转换层（Linux 服务器用，不依赖 AutoCAD/COM）。

转换优先级：
  1. LibreDWG 的 dwg2dxf / dxf2dwg（Debian/Ubuntu 包 libredwg-tools，Docker 内 apt 安装）
  2. ODA File Converter（需手动下载安装，目录批处理式 CLI）

两者皆缺则抛出清晰错误，提示安装方式。
"""
import os
import shutil
import subprocess
import tempfile


def _which(name):
    return shutil.which(name)


def _find_converter():
    """返回 (kind, path)。kind in {'libredwg','oda'}。"""
    if _which("dwg2dxf"):
        return "libredwg", _which("dwg2dxf")
    if _which("ODAFileConverter"):
        return "oda", _which("ODAFileConverter")
    return None, None


def dwg_to_dxf(src_dwg, dst_dxf=None):
    """把 DWG 转成 DXF，返回生成的 dxf 路径。

    src_dwg: 输入 .dwg 路径
    dst_dxf: 输出 .dxf 路径（默认与 src 同目录同名 .dxf）
    """
    if not src_dwg.lower().endswith(".dwg"):
        raise ValueError("dwg_to_dxf 需要 .dwg 输入: %s" % src_dwg)
    if dst_dxf is None:
        dst_dxf = os.path.splitext(src_dwg)[0] + ".dxf"
    dst_dxf = os.path.abspath(dst_dxf)

    kind, _ = _find_converter()
    if kind == "libredwg":
        # dwg2dxf 把结果写到「当前目录/<同名>.dxf」
        work = os.path.dirname(dst_dxf)
        base = os.path.splitext(os.path.basename(src_dwg))[0]
        produced = os.path.join(work, base + ".dxf")
        subprocess.run(
            ["dwg2dxf", os.path.basename(src_dwg)],
            cwd=work, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if produced != dst_dxf and os.path.exists(produced):
            os.replace(produced, dst_dxf)
        if not os.path.exists(dst_dxf):
            raise RuntimeError("dwg2dxf 未生成预期文件: %s" % dst_dxf)
        return dst_dxf

    if kind == "oda":
        ind = tempfile.mkdtemp(prefix="dwg_in_")
        outd = tempfile.mkdtemp(prefix="dwg_out_")
        shutil.copy(src_dwg, ind)
        # ODAFileConverter <in> <out> <version> <type> <recursive> <audit>
        subprocess.run(
            ["ODAFileConverter", ind, outd, "ACAD2013", "DXF", "0", "1"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        produced = None
        for f in os.listdir(outd):
            if f.lower().endswith(".dxf"):
                produced = os.path.join(outd, f)
                break
        if not produced:
            raise RuntimeError("ODAFileConverter 未生成 DXF")
        shutil.move(produced, dst_dxf)
        return dst_dxf

    raise RuntimeError(
        "未找到 DWG 转换器。请安装 LibreDWG（libredwg-tools，提供 dwg2dxf/dxf2dwg）"
        "或 ODA File Converter。Docker 镜像已在构建时 apt 安装 libredwg-tools。"
    )


def dxf_to_dwg(src_dxf, dst_dwg=None):
    """把 DXF 转回 DWG（用户要求导出 DWG 时）。"""
    if not src_dxf.lower().endswith(".dxf"):
        raise ValueError("dxf_to_dwg 需要 .dxf 输入: %s" % src_dxf)
    if dst_dwg is None:
        dst_dwg = os.path.splitext(src_dxf)[0] + ".dwg"
    dst_dwg = os.path.abspath(dst_dwg)

    if _which("dxf2dwg"):
        work = os.path.dirname(dst_dwg)
        base = os.path.splitext(os.path.basename(src_dxf))[0]
        produced = os.path.join(work, base + ".dwg")
        subprocess.run(
            ["dxf2dwg", os.path.basename(src_dxf)],
            cwd=work, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if produced != dst_dwg and os.path.exists(produced):
            os.replace(produced, dst_dwg)
        return dst_dwg

    if _which("ODAFileConverter"):
        ind = tempfile.mkdtemp(prefix="dxf_in_")
        outd = tempfile.mkdtemp(prefix="dxf_out_")
        shutil.copy(src_dxf, ind)
        subprocess.run(
            ["ODAFileConverter", ind, outd, "ACAD2013", "DWG", "0", "1"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        produced = None
        for f in os.listdir(outd):
            if f.lower().endswith(".dwg"):
                produced = os.path.join(outd, f)
                break
        if not produced:
            raise RuntimeError("ODAFileConverter 未生成 DWG")
        shutil.move(produced, dst_dwg)
        return dst_dwg

    raise RuntimeError(
        "未找到 DWG 写出器（dxf2dwg / ODAFileConverter）。"
        "Docker 镜像已含 libredwg-tools（提供 dxf2dwg）。"
    )


def converter_available():
    kind, _ = _find_converter()
    return kind is not None
