# -*- coding: utf-8 -*-
"""AutoCAD COM 直接处理原文件的泛化流水线。

把 CNG 策略二（run_cng_acad.py）抽象成通用接口：
  1. 调用方用 ezdxf 做“计划”——检测图框、提取字段、匹配模板；
  2. acad_pipeline 在 AutoCAD COM 中打开原始 DWG/DXF 副本，按 plan 删旧框/插新框/回填/保存。

这样所有图纸（SolidWorks DXF、ESS DXF、设计院 DWG）在本机有 AutoCAD 时，
都能输出真正被 AutoCAD 认可的 DWG，绕开 ezdxf saveas 后 AutoCAD 打不开的兼容性问题。
"""
import os
import shutil
import time

from . import acad_com
from .acad_com import _retry


def process_file(app, src, dst, plan, wait_open=2.0):
    """按 plan 在 AutoCAD 中处理原文件副本，输出 dst（DWG）。

    plan 格式：
      {
        "frames": [
          {
            "frame": [x0, y0, x1, y1],
            "titleblock": [x0, y0, x1, y1],   # 可选，默认等于 frame
            "tpl_dwg": ".../HH_FRAME_A3.dwg",  # WBLOCK 生成的 DWG 模板
            "fields": {"TITLE": "...", "DWG_NO": "...", ...},
            "mode": "raw-frame" | "block" | "multiframe" | "frame"
          },
          ...
        ]
      }

    mode 说明：
      - "raw-frame"：SolidWorks 打散图框，按坐标删外框线/标题栏/边缘区号。
      - "block" / "multiframe" / "frame"：块式标题栏或多图框，按图层删外框线，
        并删除 titleblock 区域内实体。

    返回处理结果列表（每帧一条 dict）。
    """
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)

    try:
        app.Visible = True
    except Exception:
        pass

    # 直接打开源文件（扩展名与内容一致，AutoCAD 可正常识别），编辑后 SaveAs 到 dst(.dwg)。
    # 注意：不能 shutil.copy(src, dst) 再把 dst 当 .dwg 打开——那样 DXF 内容会被套上 .dwg
    # 扩展名，Documents.Open 会报“不是有效的图形文件”。SaveAs 写新路径不会改动源文件。
    doc = _retry(lambda: app.Documents.Open(os.path.abspath(src)), label="Open src")
    time.sleep(wait_open)
    msp = _retry(lambda: doc.ModelSpace, label="ModelSpace")

    # 一次性采集全部实体（含类型/图层/bbox），逐帧只在 Python 内按区域过滤，
    # 避免“实体数 × 帧数”的 COM 往返（原来单张图 9000 实体 × 15 帧会极慢且易崩）。
    ents = acad_com.collect_entities(msp)

    results = []
    for item in plan.get("frames", []):
        frame = item["frame"]
        tb = item.get("titleblock", frame)
        mode = item.get("mode", "frame")
        tpl_dwg = item["tpl_dwg"]
        fields = item.get("fields", {})

        x0, y0, x1, y1 = frame
        maxdim = max(x1 - x0, y1 - y0)

        if mode == "raw-frame":
            n_edge = acad_com.del_frame_lines_acad(ents, [frame], margin=1.0)
            n_tb = acad_com.del_titleblock_acad(ents, tb, maxdim)
            n_mark = acad_com.del_edge_markers_acad(ents, frame, strip=10.0)
        else:
            # 块式/多图框：优先用图层名删外框线（设计院图纸常见“图框”层）
            n_edge = acad_com.del_frame_edges(ents, frame)
            n_tb = acad_com.del_in_region(ents, tb[0], tb[1], tb[2], tb[3])
            n_mark = 0

        insert, scale = acad_com.insert_frame(msp, frame, tpl_dwg, fields)

        results.append({
            "frame": frame,
            "mode": mode,
            "tpl_dwg": tpl_dwg,
            "scale": scale,
            "deleted_edges": n_edge,
            "deleted_titleblock": n_tb,
            "deleted_markers": n_mark,
            "fields": fields,
        })

    # 输出：COM 直接处理模式统一输出二进制 DWG（SaveAs(dst, 12) = acNative）。
    # 本机 AutoCAD 2026 的 SaveAs 写 .dxf 会在大量 COM 增删实体后报“保存文档时出错”，
    # 而 SaveAs(12) 写二进制 DWG 稳定可用；DWG 由 AutoCAD 本机写出，可正常打开。
    # 重算一次几何体，规避增删后的显示/数据库不一致（Regen 在 IAcadDocument 上可用）。
    try:
        _retry(lambda: doc.Regen(True), label="Regen")
    except Exception as e:
        print("   Regen warn:", e)
    dst_abs = os.path.abspath(dst)
    _retry(lambda: doc.SaveAs(dst_abs, 12), label="Save dst")
    _retry(lambda: doc.Close(False), label="Close dst")
    return results


def build_plan_from_mapping(doc, mappings, template, tpl_dwgs, fit="min"):
    """从 run_skill 的 mappings 列表构造 AutoCAD COM 执行计划。

    mappings: run_skill 中生成的 [{"region": [...], "extracted": {...}, ...}, ...]
    template: template_learn.learn_template 返回的模板 dict
    tpl_dwgs: {size_name: dwg_path}，由 acad_com.prepare_templates 生成
    fit: 模板缩放方式（仅用于推断幅面，COM 执行时按 frame 实际尺寸等比缩放）

    返回 plan dict。
    """
    from . import finder

    size_name = _guess_size_from_template(template)
    tpl_dwg = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))

    frames = []
    for m in mappings:
        region = m.get("region") or m.get("bbox")
        if not region:
            continue
        fields = m.get("extracted", {})
        # 如果 mapping 里已有回填后的字段值，优先用；否则从 extracted 按模板字段构造
        written = m.get("written", [])
        frames.append({
            "frame": [float(v) for v in region],
            "titleblock": [float(v) for v in region],
            "tpl_dwg": tpl_dwg,
            "fields": dict(fields),
            "mode": "block" if template.get("kind") == "block" else "frame",
        })
    return {"frames": frames}


def build_plan_for_raw_frame(doc, outer, tb, template, tpl_dwgs, fields):
    """为 SolidWorks 打散图框（raw-frame 回退路径）构造 plan。"""
    size_name = _guess_size_from_template(template)
    tpl_dwg = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))
    return {
        "frames": [{
            "frame": [float(v) for v in outer],
            "titleblock": [float(v) for v in tb],
            "tpl_dwg": tpl_dwg,
            "fields": dict(fields),
            "mode": "raw-frame",
        }]
    }


def _guess_size_from_template(template):
    """从模板文件名推断幅面名称。"""
    name = os.path.splitext(os.path.basename(template.get("path", "")))[0]
    for prefix in ("HH_FRAME_A3_WIDE", "HH_FRAME_A0", "HH_FRAME_A1",
                   "HH_FRAME_A2", "HH_FRAME_A3", "HH_FRAME_A4"):
        if name.startswith(prefix):
            return prefix.replace("HH_FRAME_", "")
    return "A3"
