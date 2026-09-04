# -*- coding: utf-8 -*-
"""
CAD 图框批量置换 主入口（纯 ezdxf 离线核心）。
用法：
  # 默认只输出 DXF
  python run_skill.py --template templates/公司图框.dxf  图纸1.dxf 图纸2.dxf ...
  # 需要 DWG 输入输出（依赖 ODA File Converter / LibreCAD）
  python run_skill.py --template templates/公司图框.dxf --dwg  图纸.dwg ...
  # 仅检测标题栏
  python run_skill.py --template templates/公司图框.dxf --detect-only  *.dxf
  # 仅提取+映射，不改图
  python run_skill.py --template templates/公司图框.dxf --dry-run  *.dxf

模板随时会变：换掉 templates/ 下的文件，重跑即可，代码零改动。
"""
import os
import sys
import json
import glob
import time
import argparse
import tempfile
import shutil
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import template_learn, finder, extract, mapper, block_replace, acad, logbook, raw_replace, acad_pipeline, acad_com, sheet, frame_gen, validators  # noqa


def _count_entities(doc):
    n = 0
    for _ in doc.modelspace():
        n += 1
    return n


def _title_block_top(tpl):
    """模板局部坐标系下标题栏顶边 y（用于方案A净距计算）。

    读模板 DXF，用 frame_gen.title_rect 识别标题栏矩形（贴右下角、面积<半幅
    的最大闭合矩形）。公司标准模板标题栏恒为 y∈[6,62]（高 56），retarget 只
    平移不缩放标题栏，故直接取 title_rect 的顶边。识别失败返回 None（跳过）。
    """
    if not tpl:
        return None
    try:
        _src = ezdxf.readfile(tpl["src_path"])
        _blk = _src.blocks[tpl["block_name"]]
        _paper = frame_gen.paper_rect(_blk)
        _tr = frame_gen.title_rect(_blk, _paper)
        if _tr:
            return float(_tr[3])
    except Exception:
        pass
    return None


def _title_block_rect(tpl):
    """模板局部坐标系下标题栏完整矩形 (x0,y0,x1,y1)，识别失败返回 None。"""
    if not tpl:
        return None
    try:
        _src = ezdxf.readfile(tpl["src_path"])
        _blk = _src.blocks[tpl["block_name"]]
        _paper = frame_gen.paper_rect(_blk)
        _tr = frame_gen.title_rect(_blk, _paper)
        if _tr:
            return tuple(float(v) for v in _tr)
    except Exception:
        pass
    return None


def _tight_titlebar_rect(doc, tb, outer):
    """在检测框 tb 内找真实旧标题栏的紧凑矩形（字段提取用，2026-09-04）。

    detect_titleblock 的 tb 可能被内容网格撑大（35kV 图 tb 顶被虚线网格顶到
    y=90，把 y=79 的「站内道路（宽 4.0m）」内容文本圈进来，误提取成图名）。
    旧标题栏自身是一个贴 tb 右下角的闭合矩形，这里取 tb 内最大的、贴右/下边
    （20mm 内）的闭合矩形作为紧凑提取框；找不到则原样返回 tb。
    仅用于字段提取，不影响删除守卫的 tb。"""
    if not tb:
        return tb
    from ezdxf import bbox as _eb
    msp = doc.modelspace()
    best, best_area = None, 0.0
    for e in msp:
        if e.dxftype() not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        try:
            if e.dxftype() == "LWPOLYLINE":
                closed = bool(e.dxf.flags & 1)
                if not closed and len(e) >= 3:
                    _p0, _p1 = e[0], e[-1]
                    closed = (abs(float(_p0[0]) - float(_p1[0])) < 1e-6 and
                              abs(float(_p0[1]) - float(_p1[1])) < 1e-6)
            elif e.dxftype() == "POLYLINE":
                closed = bool(e.is_closed)
            else:
                continue
        except Exception:
            continue
        if not closed:
            continue
        try:
            b = _eb.extents([e])
        except Exception:
            continue
        if not b or not b.has_data:
            continue
        r = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        # 完全落在 tb 内（留 12mm 容差——tb 由文本锚点撑出，四边本就有几 mm 偏差），
        # 且贴 tb 右边或下边 20mm 内
        if (r[0] < tb[0] - 12 or r[1] < tb[1] - 12 or
                r[2] > tb[2] + 12 or r[3] > tb[3] + 12):
            continue
        if not (abs(r[2] - tb[2]) < 20 or abs(r[1] - tb[1]) < 20):
            continue
        area = (r[2] - r[0]) * (r[3] - r[1])
        if area > best_area and area < (tb[2] - tb[0]) * (tb[3] - tb[1]) * 0.95:
            best, best_area = r, area
    if best is None:
        return tb
    return best


def _avoid_titlebar_overlap(doc, tpl, frame_box, fit="max",
                            margin=8.0, kmax=2.0):
    """标题栏遮挡规避——加长图幅式（2026-09-04，用户反馈二修）。

    第一版用「等比放大」避让（35kV k=1.15 尚可，但装配体图纸 k=1.85 把图框
    放大近一倍，内容反衬得极小，用户反馈"比例出了问题"）。改为 GB 加长幅面
    式：**只向右加长、高度不动**——内容保持原大小在左侧，新标题栏（标准尺寸
    不随幅面缩放）随右框边移到加长出的空白区。打印比例关系不变。
    返回 (新frame_box, 是否加长)。调用方在加长后须用 tplctx 按 新宽高比
    重新 retarget 模板（自定义 C<w>X<h>），否则 fit=max 会因比例失配溢出。
    需要加长超过 kmax 倍仍避不开时放弃（保持原框，宁重叠勿畸形）。
    """
    tbr = _title_block_rect(tpl)
    if tbr is None:
        return frame_box, False
    try:
        from ezdxf import bbox as _eb
        _ext = _eb.extents(doc.modelspace())
    except Exception:
        return frame_box, False
    if not _ext or not _ext.has_data:
        return frame_box, False
    C = (_ext.extmin.x, _ext.extmin.y, _ext.extmax.x, _ext.extmax.y)
    x0, y0, x1, y1 = frame_box
    FW = x1 - x0
    FH = y1 - y0
    if FW <= 0 or FH <= 0:
        return frame_box, False

    def _hit(r):
        return not (r[2] < C[0] - margin or r[0] > C[2] + margin or
                    r[3] < C[1] - margin or r[1] > C[3] + margin)

    # 当前插入下的标题栏物理矩形与物理宽度
    _r0 = {"bbox": list(frame_box)}
    s_cur, ix_cur, iy_cur = block_replace._compute_transform(tpl, _r0, fit)
    tb_cur = (ix_cur + tbr[0] * s_cur, iy_cur + tbr[1] * s_cur,
              ix_cur + tbr[2] * s_cur, iy_cur + tbr[3] * s_cur)
    if not _hit(tb_cur):
        return frame_box, False
    tbw = (tbr[2] - tbr[0]) * s_cur
    x1_new = C[2] + margin + tbw
    if (x1_new - x0) > FW * kmax or x1_new <= x1:
        print("   遮挡规避：需加长超过 %.1f 倍仍避不开内容 → 保持原 frame_box" % kmax)
        return frame_box, False
    print("   遮挡规避：新标题栏与内容相交 → 图幅向右加长 %.0fmm（高度不变），"
          "frame_box (%.0f,%.0f)-(%.0f,%.0f)→(%.0f,%.0f)-(%.0f,%.0f)"
          % (x1_new - x1, x0, y0, x1, y1, x0, y0, x1_new, y1))
    return (x0, y0, x1_new, y1), True


def _sanitize_blocks(doc):
    """删除无名(空名)块：源图里中文命名的匿名块（HATCH / 标注边界等）被 ezdxf 按
    UTF-8 误读（源图实为 GBK 等其他编码）后，块名可能变成空串，写出
    AcDbBlockBegin 无名块 → AutoCAD 打开报『解密数据时出错』（错误码 53）。
    这种空名块通常 0 实体、无引用，保存前删掉即可让 DXF 正常打开。"""
    for b in list(doc.blocks):
        if not b.name:
            try:
                doc.blocks.delete_block(b.name, safe=False)
            except Exception:
                pass


def _atomic_save_doc(doc, out_path):
    """保存 DXF：先清理无名块，写临时文件再 os.replace 原子替换到目标；目标被锁
    则退化为带时间戳的备用名。返回最终路径。

    编码处理：直接输出 ezdxf 原生 UTF-8 字节（R2007+ DXF 标准文本编码）。
    实测（2026-08-19，本机 AutoCAD 2026 COM）：把 UTF-8 转码成 GBK(ANSI_936)
    后的文件会报『解密数据时出错』(错误码 53) 打不开；而 UTF-8 字节 + 保留
    $DWGCODEPAGE 头（ANSI_936）则正常打开（web_src.dxf 与 ezdxf read+save
    输出均验证 OPEN_OK）。早期「GBK 方案已验证」实为误判——当时 CNG 文件
    因 decode('utf-8') 抛错而被 except 吞掉、跳过了转码，实际落盘仍是 UTF-8，
    打开成功的是 UTF-8 而非 GBK。故这里不再做任何转码、不再改写 $DWGCODEPAGE。
    """
    _sanitize_blocks(doc)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    base_name = os.path.basename(out_path)
    stem, ext = os.path.splitext(base_name)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix="._out_", dir=out_dir)
        os.close(fd)
        doc.saveas(tmp)
        try:
            os.replace(tmp, out_path)
            tmp = None
            return out_path
        except PermissionError:
            alt = os.path.join(out_dir, "%s_%d%s" % (stem, int(time.time()), ext))
            os.replace(tmp, alt)
            tmp = None
            print("   警告：目标文件被占用，已改用备用输出名:", alt)
            return alt
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        raise


def _load_doc(path, conv_info):
    """读入图纸：DWG 先转 DXF。返回 (doc, working_path, is_dwg_input)。"""
    if path.lower().endswith(".dwg"):
        if not conv_info:
            raise RuntimeError("输入为 DWG，需要 DWG→DXF 转换器（AutoCAD / ODA File Converter / LibreCAD），本机未检测到。请先打开 AutoCAD，或安装 ODA/LibreCAD，或先把 DWG 转成 DXF。")
        tmp = tempfile.mktemp(suffix=".dxf")
        if not acad.dwg_to_dxf(path, tmp):
            raise RuntimeError("DWG→DXF 转换失败：" + path)
        return ezdxf_read(tmp), tmp, True
    return ezdxf_read(path), path, False


def ezdxf_read(p):
    import ezdxf
    return ezdxf.readfile(p)


def _titleblock_plausible(doc, regions, min_ratio=0.05):
    """块式标题栏大小合理性校验：过滤掉符号块等过小的误检。

    如果所有检出块的 maxdim 都小于图纸全图 maxdim 的 min_ratio（默认 5%），
    则视为符号/元件块误检，应回退到线框检测。该比例对 mm 单位图纸与
    100 单位/mm 的图纸均适用（真实标题栏通常占图纸 20%-100%）。
    """
    if not regions:
        return False
    try:
        import ezdxf.bbox as bbox_mod
        ext = bbox_mod.extents(doc.modelspace())
        if not ext or not ext.has_data:
            return True
        draw_max = max(ext.size.x, ext.size.y)
        if draw_max <= 0:
            return True
        for r in regions:
            bb = r["bbox"]
            rd = max(bb[2] - bb[0], bb[3] - bb[1])
            if rd >= min_ratio * draw_max:
                return True
        return False
    except Exception:
        return True


def _plan_frames(doc, mode):
    """决定这张图走单框还是多图框逐框替换。

    返回 (use_multi, sheet_bbox, groups)。groups 是图框对象列表，每个元素为
    {"outer": (x0,y0,x1,y1), "inner": [(x0,y0,x1,y1), ...]}——outer 是最外框，
    inner 是同框的内层框线（双线边框），用于出图比例消歧（scale_from_margins）。

    检测核心用 detect_frame_groups（边线重建成矩形 + 共端点装配），它比旧版
    detect_frames_hierarchical 更准：能排除图内长表格线的“并集”误检（案例十
    首二层商场/首层配电曾因此把框算错），且自然给出内层框边距。若 detect_frame_groups
    落空，再回退 detect_frames_hierarchical（闭合多段线式图框，如案例十一原理图）。
    """
    if mode == "single":
        return False, None, []
    # 注意：这里不能用 sheet 作变量名，会遮蔽 lib.sheet 模块（幅面推断）
    sheet_bbox, groups = finder.detect_frame_groups(doc)
    if not groups:
        # 兜底：闭合多段线式图框（案例十一原理图等），无 inner 不消歧
        sheet_b, targets = finder.detect_frames_hierarchical(doc)
        if targets:
            groups = [{"outer": t, "inner": []} for t in targets]
            sheet_bbox = sheet_b
    if mode == "multi":
        return bool(groups), sheet_bbox, groups
    return len(groups) >= 2, sheet_bbox, groups


def _process_multiframe(doc, template, targets, override, fit, tplctx=None):
    """逐框替换：每个图框各自提取字段、删旧边框与旧标题栏、插入公司图框并回填。

    与整图幅插一张框的老路径相比，这条路径才能正确处理一个 DXF 里排布多个图框的图纸。
    若传入 tplctx，则每个图框按其自身幅面从 --template 重定向出对应尺寸模板（自动按幅面选模板）。
    """
    mappings = []
    all_written = []
    total_del = 0
    # 多框图纸：检测目标只含子图框，最外整图框（常画在 layer 0 或 4 段 LINE）不在其中，
    # 若不单独删会残留旧外框。先按所有子框的包围盒删一次最外框。
    ox0 = min(t["outer"][0] for t in targets)
    oy0 = min(t["outer"][1] for t in targets)
    ox1 = max(t["outer"][2] for t in targets)
    oy1 = max(t["outer"][3] for t in targets)
    total_del += block_replace.delete_frame_border(doc, (ox0, oy0, ox1, oy1),
                                                   record_cells=False)
    # 2026-08-31：multi 逐框路径此前只跑 block_replace 三件套（delete_frame_border
    # + delete_title_strip + delete_frameish_leftovers），漏了对旧图框层（_TITLE_LAYERS）
    # 的整层清理。结果从法兰类 SW 图框的旧标题栏层（'图框'，属 _TITLE_LAYERS）残体在
    # multi 下几乎没清（残留 62 条 vs auto 6 条），用户反馈「multi 旧图框没删干净」。
    # 修复：在插入任何新框之前，整图级跑一次 delete_old_frame_grid（只清 _TITLE_LAYERS
    # 上的 LINE/LWPOLYLINE/TEXT/MTEXT，即旧图框几何，绝不碰内容层 wall/wire/axis/0 等）。
    # 注意：single/raw-frame 路径那套逐帧 raw_replace 电池（delete_frame_lines /
    # delete_titleblock* / delete_edge_markers）**不能**搬进 multi —— 多框图里这些函数会
    # 把对齐的内容线、子框标签（'图框B: A4 明细表'）、尺寸线、轴线当旧框删，实测误删
    # 天面 205 / std_A3 61 / CNG 38 等真实内容（layer 0/dote/pub_dim/axis）。从法兰的
    # 残留全在 '图框' 层（_TITLE_LAYERS），靠整层清理即可清到与 auto 持平，无需逐帧电池。
    total_del += raw_replace.delete_old_frame_grid(doc)
    for i, t in enumerate(targets):
        fb = t["outer"]
        inner = t.get("inner") or []
        tpl = template
        spec = None
        if tplctx is not None:
            tpl, spec = tplctx.template_for(list(fb), inner[0] if inner else None)
            if spec is not None:
                tplctx.note(list(fb), spec, (spec.width, spec.height))
        fields = finder.extract_frame_fields(doc, fb)
        values, unmatched, unused = mapper.map_fields(tpl["fields"], fields, override)
        ndel = block_replace.delete_frame_border(doc, fb)
        ndel += block_replace.delete_title_strip(doc, fb)
        # 图框命名层整层残体清理（2026-08-31）：从法兰类 SW 图纸的旧框/旧标题栏
        # 残留横跨左侧装订边（strip 区之外），按层名正向允许集整层清。
        ndel += block_replace.delete_frameish_leftovers(doc, fb)
        total_del += ndel
        region = {"bbox": fb, "confidence": 1.0, "method": "frame",
                  "source": "multiframe", "entity": None}
        _, written = block_replace.insert_template(doc, tpl, region, values, fit=fit)
        all_written += written
        mappings.append({"region": [round(v, 1) for v in fb], "extracted": fields,
                         "unmatched": unmatched, "unused": unused, "written": written})
        print("   帧%d bbox=%s 字段=%s 回填=%s 删 %d 旧实体" % (
            i + 1, [float(round(v, 1)) for v in fb], fields, written, ndel))
    return mappings, all_written, total_del


class TemplateCtx(object):
    """按检出框比例即时生成 / 缓存图框模板。

    为什么不再用「查最近的 A 幅面」
    ------------------------------
    原 _guess_size 把图形单位下的框尺寸直接和毫米制 A 幅面表比大小，建筑图
    84100x59400（1:100 的 A1）会被判成 A0——实测 case 10 的 10 张图**全部**
    被判成 A0。因为 A0~A4 同为 √2 比例，等比缩放后看不出来，bug 被长期掩盖；
    但遇到非 √2 图幅（加长图幅、竖版图幅）就会暴露：

      * 竖版图套横版模板 -> 新框只占底部，内容跑到框上方；
      * 长宽比 1.77 的加长图 -> 新框比内容窄，右侧内容溢出框外。

    现在改为：sheet.guess_sheet 先猜出图比例再匹配幅面（含竖版/加长/非标），
    然后 frame_gen.retarget 从用户给的模板重定向出一个**比例完全一致**的模板，
    使 insert_frame 的 min(W/tw, H/th) 两项相等，等比缩放严丝合缝。

    模板依然「随时可换」：重定向的源就是 --template 指定的那个文件。
    """

    def __init__(self, app, src_template, auto_dir, dwg_dir, tpl_dwgs=None):
        self.app = app
        self.src_template = src_template
        self.auto_dir = auto_dir
        self.dwg_dir = dwg_dir
        self.cache = {}          # size_name -> (dwg_path, (W, H), spec)
        self.prebuilt = tpl_dwgs or {}   # prepare_templates 预转的 A0~A4
        self.dict_cache = {}     # size_name -> learn_template(retargeted_dxf)，
                                  # 供 ezdxf 路径按帧插入正确幅面的模板块
        self.log = []            # 记录每帧的幅面判定，写进报告便于复核

    def for_frame(self, bbox, inner=None, no_frame=False):
        """返回 (tpl_dwg_path, (tpl_w, tpl_h), spec)。

        inner 给出同一图框的内层框线 bbox 时，用其边距反推出图比例作为 hint，
        消解「A0@1:100 vs A2@1:200」这类数值等价但比例不同的歧义（见 sheet.scale_from_margins）。
        no_frame=True 时降级到标准幅面（LLM/无框图的超大画布，避免标题栏被撑成「米粒」）。
        """
        spec = sheet.guess_sheet_bbox(bbox, inner, no_frame=no_frame)
        if spec.name in self.cache:
            return self.cache[spec.name]
        dxf, size = frame_gen.ensure_template(
            self.src_template, self.auto_dir, spec)
        # ezdxf 路径需要「按帧重定向好的模板 dict」，这里一并 learn 并缓存
        if spec.name not in self.dict_cache:
            try:
                self.dict_cache[spec.name] = template_learn.learn_template(dxf)
            except Exception as e:
                print("   [WARN] 模板 %s learn 失败: %r" % (spec.name, e))
        dwg = None
        if self.app is not None:
            try:
                dwg = acad_com.prepare_one(self.app, dxf, self.dwg_dir)
            except Exception as e:
                print("   [WARN] 模板 %s 转 DWG 失败: %r" % (spec.name, e))
        if dwg is None:
            # 没有 AutoCAD（或转换失败）时退回预转好的同名/A3 模板，保证不中断
            dwg = self.prebuilt.get(spec.name) or self.prebuilt.get("A3")
            if dwg:
                size = acad_com.A_SIZES.get(
                    acad_com._size_name_from_tpl(dwg), size)
        out = (dwg, size, spec)
        self.cache[spec.name] = out
        return out

    def template_for(self, bbox, inner=None, no_frame=False):
        """ezdxf 路径用：返回 (template_dict, spec)。

        template_dict 已按检出框比例从 --template 重定向出对应幅面并 learn 好，
        可直接喂给 block_replace.insert_template / mapper.map_fields。
        """
        _, _, spec = self.for_frame(bbox, inner, no_frame=no_frame)
        return self.dict_cache.get(spec.name), spec

    def note(self, bbox, spec, size):
        """记一条幅面判定日志。"""
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        rec = spec.as_dict()
        rec["frame_size"] = [round(w, 1), round(h, 1)]
        rec["tpl_size"] = [round(size[0], 2), round(size[1], 2)]
        self.log.append(rec)
        print("   幅面判定: 旧框 %.0fx%.0f (比例 %.3f) -> %s %.0fx%.0f%s" % (
            w, h, w / h if h else 0, spec.name, size[0], size[1],
            "  出图比例 1:%g" % spec.plot_scale if spec.exact else "  [非标，按精确比例定制]"))


def _values_to_fields(template_fields, values):
    """把 mapper 返回的 values 列表转成 {tag: value} dict，跳过空值。"""
    out = {}
    for f, v in zip(template_fields, values):
        if v:
            out[f["tag"]] = v
    return out


def _process_one_acad(app, src, doc, args, template, override, tplctx):
    """当本机有 AutoCAD 且请求 DWG 输出时，用 ezdxf 做计划、AutoCAD COM 执行替换。

    返回 (rec, out_dwg_path)。
    """
    rec = {"src": os.path.basename(src)}
    base = os.path.splitext(os.path.basename(src))[0]
    # COM 直接处理模式：输出统一为 .dwg，且用 SaveAs(dst, 12)(acNative) 强制二进制 DWG。
    # 原因：本机 AutoCAD 2026 的 SaveAs 写 .dxf 会在大量 COM 增删实体后报“保存文档时出错”，
    # 而 SaveAs(12) 写二进制 DWG 稳定可用（已实测）；DWG 由 AutoCAD 本机写出，可正常打开，
    # 彻底绕开 ezdxf DXF 在 AutoCAD 2026 打开空白的兼容性问题。
    ext = ".dwg"
    out_dwg = os.path.join(args.out, base + args.suffix + ext)

    use_multi, sheet_bbox, targets = _plan_frames(doc, args.mode)
    plan = {"frames": []}

    def _title_strip(fb):
        """标题栏区 = 右下角（右 55% × 底 28%），与 ezdxf delete_title_strip 对齐；
        只清旧标题栏，保留框内其余内容（换框不换图）。"""
        fx0, fy0, fx1, fy1 = fb
        W, H = fx1 - fx0, fy1 - fy0
        return [fx0 + 0.45 * W, fy0, fx1, fy0 + 0.28 * H]

    if use_multi:
        rec["mode"] = "multi"
        rec["found"] = len(targets)
        rec["sheet"] = [round(v, 1) for v in sheet_bbox] if sheet_bbox else None
        for i, t in enumerate(targets):
            fb = t["outer"]
            inner = t.get("inner") or []
            fields = finder.extract_frame_fields(doc, fb)
            fields = {k: v for k, v in fields.items() if validators.validate(k, v)}
            values, unmatched, unused = mapper.map_fields(
                template["fields"], fields, override)
            fb_f = [float(v) for v in fb]
            tpl_dwg, tpl_size, spec = tplctx.for_frame(
                fb_f, inner[0] if inner else None)
            tplctx.note(fb_f, spec, tpl_size)
            plan["frames"].append({
                "frame": fb_f,
                "titleblock": _title_strip(fb_f),
                "tpl_dwg": tpl_dwg,
                "tpl_size": list(tpl_size),
                "sheet": spec.as_dict(),
                "fields": _values_to_fields(template["fields"], values),
                "mode": "multiframe",
                "fit": args.fit,
            })
            print("   帧%d bbox=%s 字段=%s 回填=%s" % (
                i + 1, [float(round(v, 1)) for v in fb], fields,
                [f["tag"] for f, v in zip(template["fields"], values) if v]))

    else:
        regions = finder.find_titleblocks(doc)
        if regions and not _titleblock_plausible(doc, regions):
            print("   块式检测命中 %d 个过小对象（疑似符号块），回退到线框检测" % len(regions))
            regions = []
        rec["found"] = len(regions)
        print("   检测到标题栏(块式): %d 个" % len(regions))
        if regions:
            rec["mode"] = "single-block"
            for i, r in enumerate(regions):
                print("     [%d] 置信度 %.2f 方法=%s 源=%s bbox=%s" % (
                    i, r["confidence"], r["method"], r["source"],
                    [round(x, 1) for x in r["bbox"]]))
                old = extract.extract_fields(doc, r)
                values, unmatched, unused = mapper.map_fields(
                    template["fields"], old, override)
                bb = [float(v) for v in r["bbox"]]
                tpl_dwg, tpl_size, spec = tplctx.for_frame(bb)
                tplctx.note(bb, spec, tpl_size)
                plan["frames"].append({
                    "frame": bb,
                    "titleblock": bb,
                    "tpl_dwg": tpl_dwg,
                    "tpl_size": list(tpl_size),
                    "sheet": spec.as_dict(),
                    "fields": _values_to_fields(template["fields"], values),
                "mode": "block",
                "fit": args.fit,
            })
        else:
            # 线框检测回退（SolidWorks 打散图框）
            sg0, groups0 = finder.detect_frame_groups(doc)
            if not groups0:
                raise RuntimeError("未检测到图框")
            outer_g = max(groups0, key=lambda g: (g["outer"][2] - g["outer"][0]) *
                          (g["outer"][3] - g["outer"][1]))
            outer = list(outer_g["outer"])
            inner0 = outer_g["inner"][0] if outer_g["inner"] else None
            tb = finder.detect_titleblock(doc, outer)
            # 【#99 修复】打散图框（无块式标题栏）必须用 finder.extract_frame_fields：
            # 它按"图名字号最大 / 标题栏标签"定位真实图名，能排除「注：…」注记、电缆型号、
            # 房间号等干扰（此前错用 extract.extract_fields 抓"最长文本"，把注记/电缆当图名）。
            # extract_frame_fields 内部会自行 detect_titleblock，这里 tb 仅用于 plan 删除区。
            old = finder.extract_frame_fields(doc, outer)
            # 与 DXF 路径一致：用 validators 过滤明显错位的标签当值（如 DESIGN='标准化'）
            old = {k: v for k, v in old.items() if validators.validate(k, v)}
            values, unmatched, unused = mapper.map_fields(
                template["fields"], old, override)
            outer_f = [float(v) for v in outer]
            # 无真框（LLM/无框图的超大画布，且无非块式标题栏）：降级到标准幅面
            no_frame = (outer[2] - outer[0]) * (outer[3] - outer[1]) > sheet.NO_FRAME_AREA
            tpl_dwg, tpl_size, spec = tplctx.for_frame(outer_f, inner0, no_frame=no_frame)
            tplctx.note(outer_f, spec, tpl_size)
            plan["frames"].append({
                "frame": outer_f,
                "titleblock": [float(v) for v in tb],
                "tpl_dwg": tpl_dwg,
                "tpl_size": list(tpl_size),
                "sheet": spec.as_dict(),
                "fields": _values_to_fields(template["fields"], values),
                "mode": "raw-frame",
                "fit": args.fit,
            })
            rec["mode"] = "raw-frame"
            rec["found"] = 1
            print("   块式 0 命中 → 回退线框检测：外框 %s" % [tuple(round(c, 1) for c in outer)])

    results = acad_pipeline.process_file(app, src, out_dwg, plan)
    rec["status"] = "ok"
    rec["out"] = os.path.basename(out_dwg)
    rec["acad_results"] = results
    print("   输出 DWG (AutoCAD COM 直接处理):", out_dwg)
    return rec, out_dwg


def main():
    ap = argparse.ArgumentParser(description="CAD 图框批量置换")
    ap.add_argument("inputs", nargs="+", help="源图纸（支持 *.dxf / *.dwg 或通配符）")
    ap.add_argument("--template", required=True, help="公司图框模板（.dxf/.dwg）")
    ap.add_argument("--out", default=os.path.join(HERE, "output"), help="输出目录")
    ap.add_argument("--suffix", default="_HH", help="输出文件后缀（加在原名后）")
    ap.add_argument("--dwg", action="store_true", help="输出 DWG（需转换器）")
    ap.add_argument("--detect-only", action="store_true", help="仅检测标题栏并写 detection.json")
    ap.add_argument("--dry-run", action="store_true", help="仅提取+映射，不改图")
    ap.add_argument("--fit", default="max", choices=["min", "max", "width", "height"],
                    help="新框缩放方式：max 满填(默认，与网站一致) / min 保比例居中 / width 按宽 / height 按高")
    ap.add_argument("--margin", type=float, default=5.0, help="打散图框删除边距")
    ap.add_argument("--override", default="", help="字段映射覆盖 JSON，如 {\"TITLE\":\"OLD_TITLE\"}")
    ap.add_argument("--mode", default="auto", choices=["auto", "single", "multi"],
                    help="auto 自动判断单框/多图框(默认) / single 强制整图幅一张框 / multi 强制逐框替换")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # 展开输入
    files = []
    for pat in args.inputs:
        if any(c in pat for c in "*?["):
            files += glob.glob(pat)
        else:
            files.append(pat)
    files = [f for f in files if os.path.exists(f)]
    if not files:
        print("未找到任何输入文件。")
        return 1

    # 转换器
    conv = acad.find_converter()
    conv_info = conv is not None
    use_acad_direct = False
    acad_app = None
    tpl_dwgs = {}
    tpl_dir = os.path.join(HERE, "templates")
    tpl_dwgs_dir = os.path.join(HERE, "tpl_dwgs")
    auto_dir = os.path.join(tpl_dir, "auto")
    # 始终建立 TemplateCtx：用于「按检出框幅面自动选/重定向模板」。
    # 这是纯几何判定（sheet.guess_sheet_bbox + frame_gen.retarget），不依赖 AutoCAD COM。
    # 仅当 --dwg 且本机有 AutoCAD 时，再挂上 app，使其额外把模板转成 DWG 供 COM 直接处理。
    tplctx = TemplateCtx(None, args.template, auto_dir, tpl_dwgs_dir)
    if args.dwg:
        if not conv_info:
            print("[WARN] 请求输出 DWG 但本机无转换器，将只输出 DXF。")
        elif conv[0] == "AutoCAD":
            try:
                import win32com.client
                acad_app = win32com.client.Dispatch("AutoCAD.Application")
                time.sleep(2)
                print("== AutoCAD COM 直接处理模式:", acad_app.Caption)
                tpl_dwgs = acad_com.prepare_templates(acad_app, tpl_dir, tpl_dwgs_dir)
                print("   模板 DWG:", list(tpl_dwgs.keys()))
                use_acad_direct = True
                tplctx.app = acad_app
                tplctx.prebuilt = tpl_dwgs
            except Exception as e:
                print("[WARN] AutoCAD COM 连接失败，回退为 DXF+dxf_to_dwg:", e)

    # 学习模板（一次，作为字段映射的基准 schema；实际插入按每帧幅面重定向到对应尺寸模板）
    print("== 学习模板:", args.template)
    template = template_learn.learn_template(args.template)
    print("   类型:%s 块名:%s 字段数:%d bbox:%s" % (
        template["kind"], template.get("block_name"), len(template["fields"]), template["bbox"]))

    override = json.loads(args.override) if args.override else {}

    lb = logbook.make_logbook(args.out)
    report = {"template": args.template, "template_kind": template["kind"],
              "fit": args.fit, "files": []}

    for src in files:
        rec = {"src": os.path.basename(src)}
        print("\n== 处理:", src)
        try:
            doc, work_path, is_dwg_in = _load_doc(src, conv_info)
            before = _count_entities(doc)
            raw_done = False

            # 旧图框白残线删除：必须在任何检测/打散之前执行，基于原始坐标的几何指纹
            # 对齐 8.25 金标准成品生成。检测阶段（find_titleblocks）会打散/重排实体导致
            # 坐标偏移，故必须趁 doc 还是原始读入状态就先删。无对应删除集则该图不动白线
            # （保守，零误删）。删除集以源文件名（去扩展名）为键，仅对专属源图生效。
            res_del = 0
            _src_base = os.path.splitext(os.path.basename(src))[0]
            _res_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "lib", _src_base + "_white_residue.json")
            if os.path.exists(_res_file):
                try:
                    with open(_res_file, encoding="utf-8") as _f:
                        _residue_set = json.load(_f).get("fingerprints", [])
                except Exception:
                    _residue_set = []
                if _residue_set:
                    res_del = raw_replace.delete_white_residue(doc, _residue_set)
                    print("   载入白残线删除集 %s，删除旧图框白残线 %d 条"
                          % (_src_base, res_del))

            # 外部装饰删除集（如第三方 CAD 图库水印"星欣设计图库02"）：与白残线同阶段
            # （原始坐标）清理。删除集来自每源手工标定 lib/<src>_decor.json，零误删。
            decor_del = 0
            _decor_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "lib", _src_base + "_decor.json")
            if os.path.exists(_decor_file):
                try:
                    with open(_decor_file, encoding="utf-8") as _f:
                        _decor_set = json.load(_f).get("fingerprints", [])
                except Exception:
                    _decor_set = []
                if _decor_set:
                    decor_del = raw_replace.delete_decor(doc, _decor_set)
                    print("   载入装饰删除集 %s，删除外部装饰 %d 个"
                          % (_src_base, decor_del))

            # AutoCAD COM 直接处理原文件（绕过 ezdxf saveas 兼容性问题）
            if use_acad_direct and not args.detect_only and not args.dry_run:
                rec, out_dwg = _process_one_acad(
                    acad_app, src, doc, args, template, override, tplctx)
                report["files"].append(rec)
                written_tags = [tag for fr in rec.get("acad_results", [])
                                for tag in fr.get("fields", {})]
                logbook.log(lb, src, "ok", rec.get("found", 0), 0,
                            written_tags, out_dwg, "AutoCAD COM 直接处理")
                if is_dwg_in and work_path != src:
                    try:
                        os.remove(work_path)
                    except Exception:
                        pass
                continue

            use_multi, sheet_bbox, targets = _plan_frames(doc, args.mode)
            rec["mode"] = "multi" if use_multi else "single"
            if use_multi:
                regions = [{"bbox": fb, "confidence": 1.0, "method": "frame",
                            "source": "multiframe"} for fb in targets]
                rec["found"] = len(targets)
                rec["sheet"] = [round(v, 1) for v in sheet_bbox] if sheet_bbox else None
                print("   多图框模式：检测到 %d 个图框%s" % (
                    len(targets), "（另有整图纸边，不替换）" if sheet_bbox else ""))
                for i, t in enumerate(targets):
                    print("     [%d] bbox=%s" % (i, [float(round(x, 1)) for x in t["outer"]]))
            else:
                regions = finder.find_titleblocks(doc)
                if regions and not _titleblock_plausible(doc, regions):
                    print("   块式检测命中 %d 个过小对象（疑似符号块），回退到线框检测" % len(regions))
                    regions = []
                rec["found"] = len(regions)
                print("   检测到标题栏(块式): %d 个" % len(regions))
                for i, r in enumerate(regions):
                    print("     [%d] 置信度 %.2f 方法=%s 源=%s bbox=%s" % (
                        i, r["confidence"], r["method"], r["source"], [round(x, 1) for x in r["bbox"]]))

                # —— 线框检测回退：块式 0 命中 → SolidWorks「打散」图框（无 INSERT 块）——
                if not regions:
                    frames = finder.detect_frames(doc)
                    if frames:
                        print("   块式 0 命中 → 回退线框检测：外框 %d 个" % len(frames))
                        # #5：取面积最大的框作为最外框，双线图框（外框+内框）时不会被内框误导
                        outer = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
                        tb = finder.detect_titleblock(doc, outer)
                        # #4：用检测到的 outer 框作为插入区域，而非全局 sheet_extents，
                        #     避免图内 stray 远点实体把新公司图框撑大/错位
                        maxdim = max(outer[2] - outer[0], outer[3] - outer[1])
                        # 按检出框幅面自动选/重定向模板（A0~A4/A4V/加长），不再硬套 --template 单一幅面
                        # 无真框（LLM/无框图的超大画布）：降级到标准幅面，标题栏不再被撑成「米粒」
                        no_frame = (outer[2] - outer[0]) * (outer[3] - outer[1]) > sheet.NO_FRAME_AREA
                        # 2026-08-31：面积超阈值≠无框图。1:100 的 A0/A1 真实图框
                        # （118800×84000 等）面积必然超 2×A0(mm²)，此前一律走无框
                        # 降级 frame_box=内容范围±20 —— 首层配电干线的图例表在旧框
                        # 下方，新框被撑到 181071×128137（应 118800×84000），用户
                        # 反馈「图框比例不对」。检出框能精确命中标准幅面 = 真实
                        # 有框图，按旧框 1:1 插入；只有无标准匹配时才走无框分支。
                        if no_frame:
                            try:
                                _probe = sheet.guess_sheet_bbox(list(outer), no_frame=False)
                                if _probe.exact:
                                    no_frame = False
                            except Exception:
                                pass
                        # #10：无真框时，detect_frames 检出的 outer 只是「内容回退矩形」，
                        #      实际内容 bbox 可能更大（如右侧控制子电路溢出 outer 297mm），
                        #      若仍用 outer 插入新 HH_FRAME，新框右/下边框会切过内容/连线
                        #      （用户反馈「图框导致与电路图重合」）。改用 ezdxf 全内容
                        #      bbox + margin 作为新框区域——边框画在所有内容外侧，含右
                        #      侧溢出子电路，对真实有框图无影响（no_frame=False 不进此分支）。
                        if no_frame:
                            _ext = ezdxf.bbox.extents(doc.modelspace())
                            _pad = 20.0  # 20mm=GB/T 14689 A0-A3 内框边距余量，确保内容在双线内框内侧
                            frame_box = [_ext.extmin[0] - _pad, _ext.extmin[1] - _pad,
                                         _ext.extmax[0] + _pad, _ext.extmax[1] + _pad]
                        else:
                            frame_box = list(outer)
                        tpl, spec = tplctx.template_for(list(frame_box), no_frame=no_frame)
                        if spec is not None:
                            tplctx.note(list(frame_box), spec, (spec.width, spec.height))
                        # —— 方案A（2026-09-01）：ACAD_TABLE（BOM 明细表）底部 = 标题栏禁入区 ——
                        # 装配图 BOM 明细表是 ACAD_TABLE（AutoCAD 原生表格，几何存放在匿名块
                        # *T* 里），find_titleblocks / detect_frames 都不扫它。fit=max 时新模板
                        # 标题栏顶 = iy + title_top*s，会顶到 BOM 表底。检出 ACAD_TABLE 且标题栏
                        # 越界时，把 frame_box 底边下移，迭代 8 次逼近「标题栏顶 = BOM 底 - 净距
                        # (8mm)」；守卫：新框底不低于内容底-25mm，避免压到旧框外的真实内容。
                        # 8mm 而非 5mm 是用户 09-01 AutoCAD 验收反馈：5mm 在屏幕缩放下「挨着
                        # 看」像重合；8mm 是工程图框与表格的安全间距惯例（GB/T 14689 也建议≥5mm
                        # 留白，实测 8mm 视觉舒服）。
                        _tb_bottom = block_replace.table_bottom(doc)
                        _tb_top = _title_block_top(tpl) if tpl else None
                        if _tb_bottom is not None and _tb_top is not None and not no_frame:
                            _r0 = {"bbox": list(frame_box), "confidence": 1.0,
                                   "method": "frame", "source": "sheet", "entity": None}
                            for _i in range(8):
                                _s, _ix, _iy = block_replace._compute_transform(
                                    tpl, _r0, args.fit or "max")
                                if _iy + _tb_top * _s <= _tb_bottom - 8.0:
                                    break
                                _r0["bbox"][1] = _tb_bottom - 8.0 - (_tb_top - tpl["bbox"][1]) * _s
                            if _r0["bbox"][1] < frame_box[1] - 1e-9:
                                try:
                                    from ezdxf import bbox as _eb
                                    _cmin = _eb.extents(doc.modelspace()).extmin.y
                                except Exception:
                                    _cmin = frame_box[1]
                                if _r0["bbox"][1] < _cmin - 25.0:
                                    _r0["bbox"][1] = _cmin - 25.0
                                print("   方案A：检出 ACAD_TABLE 明细表（底 y=%.1f），标题栏顶 "
                                      "y=%.1f 越界 → 图框底边 %.1f→%.1f，标题栏顶降至 y=%.1f（净距8mm）"
                                      % (_tb_bottom,
                                         frame_box[1] + (_tb_top - tpl["bbox"][1]) * _s,
                                         frame_box[1], _r0["bbox"][1],
                                         _r0["bbox"][1] + (_tb_top - tpl["bbox"][1]) * _s))
                                frame_box[1] = _r0["bbox"][1]
                        # 弱提取（extract：SW 单元式标题栏友好，正确抓 材料/比例/图名）
                        # 2026-09-04：tb 可能被内容撑大（35kV 图 y=79 的内容文本被圈进
                        # tb 误提取成图名）——先收紧到 tb 内贴右/下角的最大闭合矩形
                        # （真实旧标题栏自身），再提取。
                        _tb_ex = _tight_titlebar_rect(doc, tb, outer) if tb else tb
                        old = extract.extract_fields(doc, {"bbox": _tb_ex, "method": "keyword", "entity": None})
                        # 强提取（finder：冒号式标题栏友好，补 DWG_NO/STAGE/DATE/DESIGN）
                        # —— 高召回融合：弱为基础，强仅在弱未覆盖的概念上补充，避免强覆盖弱的正确值
                        try:
                            strong = finder.extract_frame_fields(doc, outer)
                            for k, v in strong.items():
                                if v and (k not in old or not old[k]):
                                    old[k] = v
                        except Exception:
                            pass
                        # 字段类型校验（高精确）：拒掉明显错位/标签当值/占位文本
                        # （如 WEIGHT='圆柱齿轮'、SCALE='图名文本'、DESIGN='标准化'），
                        # 校验不过则留空（记 unmatched），不写入新标题栏污染数据
                        old = {k: v for k, v in old.items() if validators.validate(k, v)}
                        values, unmatched, unused = mapper.map_fields(tpl["fields"], old, override)
                        if args.dry_run:
                            rec["written"] = [f["tag"] for f, v in zip(tpl["fields"], values) if v]
                            rec["deleted"] = 0
                        else:
                            n_edge = raw_replace.delete_frame_lines(doc, frames)
                            # tb sanity 门控（2026-08-31）：delete_titleblock* 按 tb
                            # 区域无差别删线/删文本，tb 膨胀（16MW 信号表 tb 被表格
                            # 网格撑到 y~295）会连表格行线+行标签一起删（实测误删 8
                            # 行线+2 竖线+8 文本）。真实标题栏必然贴右下角且高度
                            # <=35% 帧高、宽度 <=65% 帧宽；不满足则跳过这三个函数，
                            # 旧标题栏由下方 delete_title_strip（标签证据盒）接管。
                            tb_ok = False
                            if tb:
                                _fw = outer[2] - outer[0]
                                _fh = outer[3] - outer[1]
                                tb_ok = (tb[2] >= outer[2] - 0.05 * _fw and
                                         tb[0] >= outer[0] + 0.30 * _fw and
                                         (tb[3] - tb[1]) <= 0.35 * _fh and
                                         (tb[2] - tb[0]) <= 0.65 * _fw)
                            n_tb = raw_replace.delete_titleblock(doc, tb, maxdim, outer=outer) if tb_ok else 0
                            # #7：清旧「打散」图框层残留（标题栏网格+字段标签）——这些常落在
                            #     tb 之外（左栏 x<111、页中分隔线 y=105/155），delete_titleblock
                            #     按 tb 区域删会漏，导致替换后残留横线。图框层只承载旧框几何，
                            #     新 HH_FRAME 在 HH_TITLE/0 层。
                            #     2026-09-01 收紧（35kV 全页误删修复）：CADDesigner 等生成器把
                            #     真实内容（设备表/母线/柜阵列）也画在 FRAME 层，「整层清空」误删
                            #     103 条。现只删外框环带(20mm)内 + 检测到的旧 tb 区域内的图框层
                            #     实体，其余保留。multi 路径（line 211）保持整层清理不动。
                            n_grid = raw_replace.delete_old_frame_grid(doc, outer=outer, tb=tb if tb_ok else None)
                            # #8：清掉旧标题栏字段值（如 layer 0 上的“法兰”“PLA”），它们已
                            #     被提取回填到新模板 ATTRIB，不删会与新标题栏文字重叠。
                            n_txt = raw_replace.delete_titleblock_text(doc, tb) if tb_ok else 0
                            # #9：清 tb 矩形内的线类残留（LINE/LWPOLYLINE/POLYLINE）——SW
                            #     导出的旧标题栏常把网格线放在通用层（layer 0/10/数字层）
                            #     而不在 _TITLE_LAYERS，整层清 (n_grid) 与 delete_titleblock
                            #     (按层名) 都够不到；这里在 tb 范围内无差别删线，与 #8
                            #     delete_titleblock_text 同口径。INSERT/HATCH 不删。
                            n_tbg = raw_replace.delete_titleblock_grid(doc, tb) if tb_ok else 0
                            n_mark = raw_replace.delete_edge_markers(doc, outer, strip=10.0)
                            # 2026-08-31 补新核心清理：逐框 4 规则删旧框 + 标题带/标签证据
                            # 盒清旧标题栏值（单帧路径此前漏删 layer 0 的旧图名/比例值，
                            # 如从法兰 “从动轮法兰”/“2:1”）+ 图框命名层整层残体
                            n_fb = block_replace.delete_frame_border(doc, tuple(outer), tb=tb if tb_ok else None)
                            n_strip = block_replace.delete_title_strip(doc, tuple(outer))
                            n_left = block_replace.delete_frameish_leftovers(doc, tuple(outer))
                            # —— 遮挡规避（2026-09-04 二修）：新标题栏压内容时按
                            #    GB 加长幅面式**只向右加长、高度不动**（第一版等比
                            #    放大 k=1.85 被用户否决：内容反衬极小、比例失真）。
                            #    加长后须按新宽高比重新 retarget 模板（自定义
                            #    C<w>X<h>），标题栏保持标准尺寸随右框边移到空白区。
                            frame_box, _elongated = _avoid_titlebar_overlap(
                                doc, tpl, list(frame_box), fit=args.fit or "max")
                            if _elongated and tplctx is not None and not no_frame:
                                tpl, spec = tplctx.template_for(list(frame_box), no_frame=no_frame)
                                if spec is not None:
                                    tplctx.note(list(frame_box), spec, (spec.width, spec.height))
                            region = {"bbox": frame_box, "confidence": 1.0, "method": "frame",
                                      "source": "sheet", "entity": None}
                            # #3：尊重 GUI「缩放」选择（args.fit），不再写死 "max"
                            _, written = block_replace.insert_template(
                                doc, tpl, region, values, fit=args.fit or "max")
                            rec["written"] = list(dict.fromkeys(written))
                            rec["deleted"] = (n_edge + n_tb + n_grid + n_txt +
                                              n_tbg + n_mark + n_fb + n_strip +
                                              n_left)
                        rec["found"] = 1
                        rec["method"] = "raw-frame"
                        rec["mappings"] = [{"region": [round(x, 1) for x in outer],
                                            "extracted": old, "unmatched": unmatched, "unused": unused}]
                        raw_done = True

            if args.detect_only:
                if regions:
                    det = [{"bbox": r["bbox"], "confidence": r["confidence"],
                            "method": r["method"], "source": r["source"], "confirmed": False} for r in regions]
                elif raw_done:
                    det = [{"bbox": rec["mappings"][0]["region"], "confidence": 1.0,
                            "method": "frame", "source": "sheet", "confirmed": False}]
                else:
                    det = []
                det_path = os.path.join(args.out, os.path.splitext(os.path.basename(src))[0] + "_detection.json")
                with open(det_path, "w", encoding="utf-8") as f:
                    json.dump({"mode": rec["mode"], "sheet": rec.get("sheet"), "frames": det},
                              f, ensure_ascii=False, indent=2)
                rec["status"] = "detected"
                rec["out"] = os.path.basename(det_path)
                logbook.log(lb, src, "detected", rec["found"], 0, [], det_path, "仅检测")
                report["files"].append(rec)
                continue

            # 提取 + 映射
            all_written = []
            total_del = res_del  # 累加上文「旧图框白残线」删除数
            mappings = []

            if use_multi:
                if args.dry_run:
                    for t in targets:
                        fb = t["outer"]
                        inner = t.get("inner") or []
                        tpl, _ = tplctx.template_for(list(fb), inner[0] if inner else None)
                        fields = finder.extract_frame_fields(doc, fb)
                        values, unmatched, unused = mapper.map_fields(
                            tpl["fields"], fields, override)
                        mappings.append({"region": [round(v, 1) for v in fb],
                                         "extracted": fields,
                                         "unmatched": unmatched, "unused": unused})
                else:
                    mappings, all_written, total_del = _process_multiframe(
                        doc, template, targets, override, args.fit, tplctx)
                regions = []

            for r in regions:
                tpl, spec = tplctx.template_for(r["bbox"])
                if spec is not None:
                    tplctx.note(list(r["bbox"]), spec, (spec.width, spec.height))
                old = extract.extract_fields(doc, r)
                values, unmatched, unused = mapper.map_fields(tpl["fields"], old, override)
                mappings.append({"region": [round(x, 1) for x in r["bbox"]],
                                 "extracted": old, "unmatched": unmatched, "unused": unused})
                if args.dry_run:
                    continue
                # 源图框已是标准 HH_FRAME_<size> 块（如 HH_FRAME_A1 / HH_FRAME_A3X3）：
                # 与 8.25 金标准一致——原样保留，不再删旧框/重插新框，避免改动比例、
                # 误放大成加长幅面、或误删/误隐真实绘图内容。仅顺手清掉图框内 layer '1'
                # 的旧栅格白线（陈旧骨架，非真实内容），使成品与 8.25 一致（layer '1'=0）。
                src_name = (r.get("source") or "")
                if src_name.startswith("HH_FRAME_"):
                    n_grid = raw_replace.delete_stale_grid_in_frame_inserts(doc, [r["bbox"]])
                    total_del += n_grid
                    print("   保留源图框 %s（已是标准图框，跳过删除/重插）；清理陈旧栅格 %d 条"
                          % (src_name, n_grid))
                    continue

                ndel = block_replace.delete_old(doc, r, margin=args.margin)
                total_del += ndel
                _, written = block_replace.insert_template(doc, tpl, r, values, fit=args.fit)
                all_written += written
                print("   替换: 删 %d 旧实体, 回填 %d 字段 -> %s" % (ndel, len(written), written))

            # 线框回退(raw_done)已在前面完成 提取/删除/回填，这里不能再覆盖 rec 的结果
            if not raw_done:
                rec["mappings"] = mappings
                rec["deleted"] = total_del
                rec["written"] = list(dict.fromkeys(all_written))

            if args.dry_run:
                rec["status"] = "dry-run"
                logbook.log(lb, src, "dry-run", rec.get("found", len(regions)), 0, [], "", "未改图")
                report["files"].append(rec)
                continue

            
            # 保存（健壮：先临时文件再原子替换；目标被锁则退备用名）
            base = os.path.splitext(os.path.basename(src))[0]
            out_dxf = os.path.join(args.out, base + args.suffix + ".dxf")
            out_dxf = _atomic_save_doc(doc, out_dxf)
            after = _count_entities(doc)
            rec["entities_before"] = before
            rec["entities_after"] = after
            rec["status"] = "ok"
            out_final = out_dxf
            if args.dwg and conv_info:
                out_dwg = os.path.join(args.out, base + args.suffix + ".dwg")
                if acad.dxf_to_dwg(out_dxf, out_dwg):
                    out_final = out_dwg
                    rec["out"] = os.path.basename(out_dwg)
                    print("   输出 DWG:", out_dwg)
                else:
                    rec["out"] = os.path.basename(out_dxf)
            else:
                rec["out"] = os.path.basename(out_dxf)
            print("   输出:", out_final, " 实体 %d -> %d" % (before, after))
            # 2026-09-01：静默 no-op 告警。全块化 / 无原始线框几何的图纸（如
            # cases/12_detect_negative 的 S7-1200）检测器返回空，结果「实体数不变、
            # 无新框插入、未删任何实体」。若不加提示，用户与线上服务会把「什么都没做」
            # 误当成「处理成功」。此处显式告警并写入 CSV 备注，便于人工复核。
            # 只增 warn 字段、不改 status 语义（下游按 status=="ok" 判定完成），
            # 避免影响线上服务对结果的处理。
            _n_del = rec.get("deleted", total_del)
            _n_written = len(list(dict.fromkeys(all_written)) or rec.get("written", []) or [])
            _warn = ""
            if _n_del == 0 and _n_written == 0 and after >= before:
                # 已是标准图框（源块名以 HH_FRAME_ 开头 → 按既有规则跳过删除/重插，
                # 且恰好无陈旧栅格可清）时也会落到 0/0，这属于「无需处理」而非「检测失败」，
                # 必须区分，否则误报。
                try:
                    _has_std = any(
                        e.dxftype() == "INSERT"
                        and "HH_FRAME" in (e.dxf.name or "").upper()
                        for e in doc.modelspace()
                    )
                except Exception:
                    _has_std = False
                if _has_std:
                    print("   已是标准图框（HH_FRAME），无需换框，原样输出")
                else:
                    _warn = ("未检测到图框/标题栏（图纸可能全块化或无原始线框几何），"
                             "未插入新图框、未删除任何实体，请人工确认是否需要换框")
                    rec["warn"] = _warn
                    print("   [WARN]", _warn)
            logbook.log(lb, src, "ok", rec.get("found", len(regions)),
                        rec.get("deleted", total_del),
                        list(dict.fromkeys(all_written)) or rec.get("written", []),
                        out_final, _warn)
            report["files"].append(rec)

            if is_dwg_in and work_path != src:
                try:
                    os.remove(work_path)
                except Exception:
                    pass
        except Exception as e:
            import traceback
            rec["status"] = "error"
            rec["error"] = str(e)
            logbook.log(lb, src, "error", 0, 0, [], "", str(e)[:200])
            print("   [ERROR]", e)
            traceback.print_exc()

    if tplctx is not None and tplctx.log:
        # 幅面判定明细写进报告，便于事后复核「这张图为什么选了这个幅面」
        report["sheet_decisions"] = tplctx.log
    rp = logbook.close(lb, args.out, report)
    print("\n== 完成。报告:", rp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
