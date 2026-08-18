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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import template_learn, finder, extract, mapper, block_replace, acad, logbook, raw_replace, acad_pipeline, acad_com, sheet, frame_gen, validators  # noqa


def _count_entities(doc):
    n = 0
    for _ in doc.modelspace():
        n += 1
    return n


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

    编码处理：ezdxf 写出 UTF-8 字节流，而本机 AutoCAD 对中文 DXF 按 ANSI 码页解读。
    源图/本机中文多为 GBK(ANSI_936)，故落盘后把 UTF-8 字节转码为 GBK，并把
    $DWGCODEPAGE 声明为 ANSI_936，AutoCAD 即可正确显示中文且能正常打开。
    （ANSI_1200 实为 UTF-16，会与 UTF-8 字节冲突导致『解密数据时出错』；
     UTF-8 BOM 在本机 AutoCAD 2026 亦被拒绝，故采用 GBK 转码方案。）
    全程二进制操作，避免文本解码损坏结构。"""
    _sanitize_blocks(doc)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    base_name = os.path.basename(out_path)
    stem, ext = os.path.splitext(base_name)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix="._out_", dir=out_dir)
        os.close(fd)
        doc.saveas(tmp)
        # 编码修正：ezdxf 写出 UTF-8 字节，但 AutoCAD 需按 ANSI 码页解读中文。
        # 源图/本机中文多为 GBK(ANSI_936)，故把 UTF-8 字节转码为 GBK，并把
        # $DWGCODEPAGE 声明为 ANSI_936，AutoCAD 即可正确显示中文且能打开。
        # （ANSI_1200 是 UTF-16，会与 UTF-8 字节冲突导致『解密数据时出错』；
        #  UTF-8 BOM 在本机 AutoCAD 2026 亦被拒，故采用 GBK 转码方案。）
        try:
            import re as _re
            with open(tmp, "rb") as _f:
                _data = _f.read()
            _data = _data.decode("utf-8").encode("gbk", errors="replace")
            _data = _re.sub(rb"(\$DWGCODEPAGE\s+3\s+)[^\n]+", rb"\1ANSI_936", _data)
            with open(tmp, "wb") as _f:
                _f.write(_data)
        except Exception:
            pass
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

    def for_frame(self, bbox, inner=None):
        """返回 (tpl_dwg_path, (tpl_w, tpl_h), spec)。

        inner 给出同一图框的内层框线 bbox 时，用其边距反推出图比例作为 hint，
        消解「A0@1:100 vs A2@1:200」这类数值等价但比例不同的歧义（见 sheet.scale_from_margins）。
        """
        spec = sheet.guess_sheet_bbox(bbox, inner)
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

    def template_for(self, bbox, inner=None):
        """ezdxf 路径用：返回 (template_dict, spec)。

        template_dict 已按检出框比例从 --template 重定向出对应幅面并 learn 好，
        可直接喂给 block_replace.insert_template / mapper.map_fields。
        """
        _, _, spec = self.for_frame(bbox, inner)
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
            tpl_dwg, tpl_size, spec = tplctx.for_frame(outer_f, inner0)
            tplctx.note(outer_f, spec, tpl_size)
            plan["frames"].append({
                "frame": outer_f,
                "titleblock": [float(v) for v in tb],
                "tpl_dwg": tpl_dwg,
                "tpl_size": list(tpl_size),
                "sheet": spec.as_dict(),
                "fields": _values_to_fields(template["fields"], values),
                "mode": "raw-frame",
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
    ap.add_argument("--fit", default="min", choices=["min", "max", "width", "height"],
                    help="新框缩放方式：min 保比例居中(默认) / max 满填 / width 按宽 / height 按高")
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
                        tpl, spec = tplctx.template_for(list(outer))
                        if spec is not None:
                            tplctx.note(list(outer), spec, (spec.width, spec.height))
                        # 弱提取（extract：SW 单元式标题栏友好，正确抓 材料/比例/图名）
                        old = extract.extract_fields(doc, {"bbox": tb, "method": "keyword", "entity": None})
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
                            n_tb = raw_replace.delete_titleblock(doc, tb, maxdim)
                            # #7：清旧「打散」图框层残留（标题栏网格+字段标签）——这些常落在
                            #     tb 之外（左栏 x<111、页中分隔线 y=105/155），delete_titleblock
                            #     按 tb 区域删会漏，导致替换后残留横线。图框层只承载旧框几何，
                            #     新 HH_FRAME 在 HH_TITLE/0 层，整层清残留安全；INSERT/HATCH 保留。
                            n_grid = raw_replace.delete_old_frame_grid(doc)
                            # #8：清掉旧标题栏字段值（如 layer 0 上的“法兰”“PLA”），它们已
                            #     被提取回填到新模板 ATTRIB，不删会与新标题栏文字重叠。
                            n_txt = raw_replace.delete_titleblock_text(doc, tb)
                            n_mark = raw_replace.delete_edge_markers(doc, outer, strip=10.0)
                            region = {"bbox": outer, "confidence": 1.0, "method": "frame",
                                      "source": "sheet", "entity": None}
                            # #3：尊重 GUI「缩放」选择（args.fit），不再写死 "max"
                            _, written = block_replace.insert_template(
                                doc, tpl, region, values, fit=args.fit or "max")
                            rec["written"] = list(dict.fromkeys(written))
                            rec["deleted"] = n_edge + n_tb + n_grid + n_txt + n_mark
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
            total_del = 0
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
            logbook.log(lb, src, "ok", rec.get("found", len(regions)),
                        rec.get("deleted", total_del),
                        list(dict.fromkeys(all_written)) or rec.get("written", []),
                        out_final, "")
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
