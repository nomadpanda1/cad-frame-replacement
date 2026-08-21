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
import uuid

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
    dst_abs = os.path.abspath(dst)
    os.makedirs(os.path.dirname(dst_abs) or ".", exist_ok=True)

    try:
        app.Visible = True
    except Exception:
        pass

    src_abs = os.path.abspath(src)
    src_ext = os.path.splitext(src_abs)[1] or ".dwg"
    # 健壮性：用“唯一临时副本”打开，避免与 AutoCAD 中已打开的同名文件冲突——
    # 同名再 Open 会弹“以只读打开？”模态框，COM 无法应答而永久卡死，并污染实例
    # 让后续所有 COM 调用雪崩式挂起。副本与原文件扩展名一致，AutoCAD 可正常识别。
    work = os.path.join(os.path.dirname(dst_abs),
                        "%s__w%s%s" % (os.path.splitext(os.path.basename(src_abs))[0],
                                       uuid.uuid4().hex[:8], src_ext))
    shutil.copy(src_abs, work)
    _close_if_open(app, src_abs)  # 兜底：关掉同名原文件，进一步降低模态框概率
    # doc / msp 保持 early-binding：SaveAs / Regen / Close / ModelSpace / InsertBlock
    # 都是 IAcadDocument / IAcadModelSpace 基接口方法，early-binding 稳定可用；
    # 仅“实体子类型属性”（StartPoint/Coordinates/TextString/GetAttributes 等）需要
    # 在 collect_entities / insert_frame 内部对单个对象做 late-binding（见 _dyn）。
    doc = _retry(lambda: app.Documents.Open(os.path.abspath(work)), label="Open src")
    time.sleep(wait_open)
    msp = _retry(lambda: doc.ModelSpace, label="ModelSpace")

    # 一次性采集全部实体（含类型/图层/bbox），逐帧只在 Python 内按区域过滤，
    # 避免“实体数 × 帧数”的 COM 往返（原来单张图 9000 实体 × 15 帧会极慢且易崩）。
    ents = acad_com.collect_entities(msp)

    results = []
    for idx, item in enumerate(plan.get("frames", [])):
        frame = item["frame"]
        tb = item.get("titleblock", frame)
        mode = item.get("mode", "frame")
        tpl_dwg = item["tpl_dwg"]
        fields = item.get("fields", {})

        x0, y0, x1, y1 = frame
        maxdim = max(x1 - x0, y1 - y0)

        # 逐帧容错：单帧失败只记录该帧，不中断整图处理（多图框场景下
        # 一帧的旧框格式异常不应让其余帧全部白跑）。
        try:
            if mode == "raw-frame":
                n_edge = acad_com.del_frame_lines_acad(ents, [frame], margin=1.0)
                # 双线图框：外框坐标删净后，内框（与外框重叠>80%、落在图框层）一并删掉。
                # margin=1.0 使 near_edge 几乎不触发，仅按图层+面积重叠兜底，不会误删贴边内容。
                n_edge += acad_com.del_frame_edges(ents, frame, margin=1.0)
                # 整框清除：图框层上完全落在旧框内的全部线（内框/标题栏网格/竖向分隔线等
                # 不在外边坐标上、面积也<80% 的旧框残线），彻底杜绝残线压在新框上。
                n_edge += acad_com.del_frame_layer_inside(ents, frame, margin=20.0)
                n_tb = acad_com.del_titleblock_acad(ents, tb, maxdim)
                n_mark = acad_com.del_edge_markers_acad(ents, frame, strip=10.0)
            else:
                # 块式/多图框：优先用图层名删外框线（设计院图纸常见“图框”层）
                n_edge = acad_com.del_frame_edges(ents, frame)
                # 同样整框清除旧框层残留线（块式图框背后可能仍有 FRAME 层旧边框线）
                n_edge += acad_com.del_frame_layer_inside(ents, frame, margin=20.0)
                n_tb = acad_com.del_in_region(ents, tb[0], tb[1], tb[2], tb[3])
                n_mark = 0

            # tpl_size 由上游（run_skill._tpl_for_frame）按检出框比例即时生成模板时给出，
            # 是该模板真实的幅面尺寸（mm）。必须显式传下来：非标幅面模板（如 C1051X594）
            # 不在 acad_com.A_SIZES 静态表里，缺了它 insert_frame 会退化成 scale=1.0，
            # 模板按毫米原尺寸插进图形单位的图里，等于插了个看不见的小框。
            size_table = None
            tpl_size = item.get("tpl_size")
            if tpl_size:
                size_table = {acad_com._size_name_from_tpl(tpl_dwg):
                              (float(tpl_size[0]), float(tpl_size[1]))}
            insert, scale = acad_com.insert_frame(
                msp, frame, tpl_dwg, fields, size_table=size_table,
                fit=item.get("fit", "max"))
            status = "ok"
        except Exception as e:
            print("   帧 %d 处理失败: %r" % (idx, e))
            insert, scale, n_edge, n_tb, n_mark = None, None, 0, 0, 0
            status = "error: %r" % (e,)

        results.append({
            "frame": frame,
            "mode": mode,
            "status": status,
            "tpl_dwg": tpl_dwg,
            "tpl_size": tpl_size,
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
    _retry(lambda: doc.SaveAs(dst_abs, 12), label="Save dst")
    _retry(lambda: doc.Close(False), label="Close dst")
    # 清理临时副本（失败也不影响结果）
    try:
        if os.path.exists(work) and os.path.abspath(work) != src_abs:
            os.remove(work)
    except Exception:
        pass
    return results


def _close_if_open(app, path):
    """若同名文件已在 AutoCAD 中打开，先关闭它，避免 Documents.Open 弹“以只读打开”模态框。"""
    try:
        target = os.path.abspath(path).lower()
        docs = _retry(lambda: app.Documents, label="Documents")
        n = _retry(lambda: docs.Count, label="Docs.Count")
        for i in range(n):
            try:
                d = _retry(lambda: docs.Item(i), label="Doc.Item")
                fn = _retry(lambda: d.FullName, label="FullName")
                if os.path.abspath(fn).lower() == target:
                    try:
                        d.Close(False)
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass


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

    frames = []
    for m in mappings:
        region = m.get("region") or m.get("bbox")
        if not region:
            continue
        fields = m.get("extracted", {})
        # 如果 mapping 里已有回填后的字段值，优先用；否则从 extracted 按模板字段构造
        written = m.get("written", [])
        tpl_dwg = _pick_template_dwg(tpl_dwgs, size_name, [float(v) for v in region])
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
    tpl_dwg = _pick_template_dwg(tpl_dwgs, size_name, [float(v) for v in outer])
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


def _pick_template_dwg(tpl_dwgs, size_name, frame):
    """按图纸方向选择模板 DWG：竖版图纸优先用 *V 竖版模板，无则回退并警告。"""
    fallback = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))
    W = frame[2] - frame[0]
    H = frame[3] - frame[1]
    # 仅在真实幅面尺寸附近才做方向检查（毫米单位）
    if min(W, H) < 100 or max(W, H) > 1300:
        return fallback
    if H > W * 1.1:  # 竖版
        alt = size_name + "V"
        if alt in tpl_dwgs:
            return tpl_dwgs[alt]
        print("   警告: 当前图纸为竖版(%s)，未找到竖版模板 %s.dxf，使用横版 %s 回退（框架将填不满）。" %
              ("%dx%d" % (W, H), alt, size_name))
    return fallback
