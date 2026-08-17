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

import ezdxf


def _which(name):
    return shutil.which(name)


def _repair_materials(doc):
    """修复 LibreDWG dwg2dxf 输出的 DXF 中材料字典指向不存在句柄的问题。

    dwg2dxf 生成的 DXF 常把 ACAD_MATERIAL 字典的值写成不存在的句柄字符串，
    ezdxf 读入后无法解析为实体；一旦 doc.saveas() 更新头变量就会抛
    AttributeError: 'str' object has no attribute 'dxf'。
    这里把坏条目替换成真实 MATERIAL 对象。
    """
    try:
        mat_dict = doc.rootdict.get_required_dict("ACAD_MATERIAL")
    except Exception:
        return
    for key in list(mat_dict.keys()):
        value = mat_dict.get(key)
        if isinstance(value, str):
            new_mat = doc.objects.new_entity("MATERIAL", dxfattribs={"name": key})
            mat_dict.take_ownership(key, new_mat)


def _open_knot_vector(n, p):
    """构造 open(clamped) B 样条节点向量，长度严格 = n + p + 1。

    LibreDWG 的 dwg2dxf 偶发把 HATCH 样条边的节点向量写成错误长度
    （例如 deg=3、4 个控制点却写了 12 个节点），ezdxf 在 bbox 计算 /
    绘图反汇编时会抛 ValueError('8 knot values required, got 12')，
    导致整图帧检测(bbox.extents)与预览渲染双双崩溃。这里用标准 clamped
    uniform 节点向量重写，既不改几何拓扑又能消除崩溃。
    """
    if n <= p:
        return [0.0] * (p + 1) + [1.0] * (p + 1)
    interior = n - p - 1
    inner = [i / (interior + 1) for i in range(1, interior + 1)]
    return [0.0] * (p + 1) + inner + [1.0] * (p + 1)


def _repair_hatch_splines(doc):
    """修复 dwg2dxf 输出 DXF 中节点向量长度错误的 HATCH 样条边。

    仅重写节点向量（及有理样条权重数量），不改动控制点，几何外形基本不变。
    """
    for hatch in doc.modelspace().query("HATCH"):
        for path in hatch.paths.paths:
            for e in getattr(path, "edges", []):
                if getattr(e, "EDGE_TYPE", None) != "SplineEdge":
                    continue
                cp = list(e.control_points)
                n = len(cp)
                if n <= 0:
                    continue
                deg = int(e.degree)
                if deg > n - 1:
                    deg = n - 1
                kv = list(e.knot_values)
                need = n + deg + 1
                if len(kv) == need:
                    continue
                try:
                    e.knot_values = _open_knot_vector(n, deg)
                except Exception:
                    continue
                if getattr(e, "rational", False):
                    w = list(getattr(e, "weights", []) or [])
                    if len(w) != n:
                        e.weights = [1.0] * n


def _postprocess_dxf(doc):
    """DWG 转换产物兜底修复：材料字典坏句柄 + HATCH 样条坏节点向量。"""
    _repair_materials(doc)
    _repair_hatch_splines(doc)


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
            ["dwg2dxf", "-y", os.path.basename(src_dwg)],
            cwd=work, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if produced != dst_dxf and os.path.exists(produced):
            os.replace(produced, dst_dxf)
        if not os.path.exists(dst_dxf):
            raise RuntimeError("dwg2dxf 未生成预期文件: %s" % dst_dxf)
        # 修复 dwg2dxf 常见的材料字典坏句柄与 HATCH 样条坏节点向量，
        # 否则后续 ezdxf.saveas / bbox 计算 / 预览渲染会崩溃
        doc = ezdxf.readfile(dst_dxf)
        _postprocess_dxf(doc)
        doc.saveas(dst_dxf)
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
        doc = ezdxf.readfile(dst_dxf)
        _postprocess_dxf(doc)
        doc.saveas(dst_dxf)
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
            ["dxf2dwg", "-y", os.path.basename(src_dxf)],
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
