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
from lib import template_learn, finder, extract, mapper, block_replace, acad, logbook, raw_replace, acad_pipeline, acad_com  # noqa


def _count_entities(doc):
    n = 0
    for _ in doc.modelspace():
        n += 1
    return n


def _atomic_save_doc(doc, out_path):
    """保存 DXF：先写临时文件，再 os.replace 原子替换到目标；目标被锁则退化为带时间戳的备用名。返回最终路径。"""
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

    返回 (use_multi, sheet_bbox, targets)。auto 模式下只有检出 >= 2 个图框才走多框分支，
    单框图纸继续走原来的 find_titleblocks 逻辑，保证向后兼容。
    """
    if mode == "single":
        return False, None, []
    sheet, targets = finder.detect_frames_hierarchical(doc)
    if mode == "multi":
        return bool(targets), sheet, targets
    return len(targets) >= 2, sheet, targets


def _process_multiframe(doc, template, targets, override, fit):
    """逐框替换：每个图框各自提取字段、删旧边框与旧标题栏、插入公司图框并回填。

    与整图幅插一张框的老路径相比，这条路径才能正确处理一个 DXF 里排布多个图框的图纸。
    """
    mappings = []
    all_written = []
    total_del = 0
    for i, fb in enumerate(targets):
        fields = finder.extract_frame_fields(doc, fb)
        values, unmatched, unused = mapper.map_fields(template["fields"], fields, override)
        ndel = block_replace.delete_frame_border(doc, fb)
        ndel += block_replace.delete_title_strip(doc, fb)
        total_del += ndel
        region = {"bbox": fb, "confidence": 1.0, "method": "frame",
                  "source": "multiframe", "entity": None}
        _, written = block_replace.insert_template(doc, template, region, values, fit=fit)
        all_written += written
        mappings.append({"region": [round(v, 1) for v in fb], "extracted": fields,
                         "unmatched": unmatched, "unused": unused, "written": written})
        print("   帧%d bbox=%s 字段=%s 回填=%s 删 %d 旧实体" % (
            i + 1, [float(round(v, 1)) for v in fb], fields, written, ndel))
    return mappings, all_written, total_del


A_SIZES = [("A0", 1189, 841), ("A1", 841, 594), ("A2", 594, 420),
           ("A3", 420, 297), ("A4", 297, 210)]


def _guess_size(bbox):
    """按外框尺寸推断幅面（返回 A0/A1/A2/A3/A4）。

    注：insert_frame 会把模板等比缩放到检出框的实际尺寸，故这里只需选到
    最近的 A 幅面即可；不再设严格阈值回退 A3，否则大图/非标图幅会被错判成 A3。
    """
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return "A3"
    best, best_err = None, 1e9
    for name, sw, sh in A_SIZES:
        for cand in [(sw, sh), (sh, sw)]:
            err = abs(w - cand[0]) / cand[0] + abs(h - cand[1]) / cand[1]
            if err < best_err:
                best_err, best = err, name
    return best


def _values_to_fields(template_fields, values):
    """把 mapper 返回的 values 列表转成 {tag: value} dict，跳过空值。"""
    out = {}
    for f, v in zip(template_fields, values):
        if v:
            out[f["tag"]] = v
    return out


def _process_one_acad(app, src, doc, args, template, override, tpl_dwgs):
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
        for i, fb in enumerate(targets):
            fields = finder.extract_frame_fields(doc, fb)
            values, unmatched, unused = mapper.map_fields(
                template["fields"], fields, override)
            size_name = _guess_size(fb)
            tpl_dwg = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))
            fb_f = [float(v) for v in fb]
            plan["frames"].append({
                "frame": fb_f,
                "titleblock": _title_strip(fb_f),
                "tpl_dwg": tpl_dwg,
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
                size_name = _guess_size(r["bbox"])
                tpl_dwg = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))
                plan["frames"].append({
                    "frame": [float(v) for v in r["bbox"]],
                    "titleblock": [float(v) for v in r["bbox"]],
                    "tpl_dwg": tpl_dwg,
                    "fields": _values_to_fields(template["fields"], values),
                    "mode": "block",
                })
        else:
            # 线框检测回退（SolidWorks 打散图框）
            frames = finder.detect_frames(doc)
            if not frames:
                raise RuntimeError("未检测到图框")
            outer = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
            tb = finder.detect_titleblock(doc, outer)
            old = extract.extract_fields(doc, {"bbox": tb, "method": "keyword", "entity": None})
            values, unmatched, unused = mapper.map_fields(
                template["fields"], old, override)
            size_name = _guess_size(outer)
            tpl_dwg = tpl_dwgs.get(size_name) or tpl_dwgs.get("A3") or next(iter(tpl_dwgs.values()))
            plan["frames"].append({
                "frame": [float(v) for v in outer],
                "titleblock": [float(v) for v in tb],
                "tpl_dwg": tpl_dwg,
                "fields": _values_to_fields(template["fields"], values),
                "mode": "raw-frame",
            })
            rec["mode"] = "raw-frame"
            rec["found"] = 1
            print("   块式 0 命中 → 回退线框检测：外框 %s" % [tuple(round(c, 1) for c in f) for f in frames])

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
    if args.dwg:
        if not conv_info:
            print("[WARN] 请求输出 DWG 但本机无转换器，将只输出 DXF。")
        elif conv[0] == "AutoCAD":
            try:
                import win32com.client
                acad_app = win32com.client.Dispatch("AutoCAD.Application")
                time.sleep(2)
                print("== AutoCAD COM 直接处理模式:", acad_app.Caption)
                tpl_dir = os.path.join(HERE, "templates")
                tpl_dwgs_dir = os.path.join(HERE, "tpl_dwgs")
                tpl_dwgs = acad_com.prepare_templates(acad_app, tpl_dir, tpl_dwgs_dir)
                print("   模板 DWG:", list(tpl_dwgs.keys()))
                use_acad_direct = True
            except Exception as e:
                print("[WARN] AutoCAD COM 连接失败，回退为 DXF+dxf_to_dwg:", e)

    # 学习模板（一次）
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
                    acad_app, src, doc, args, template, override, tpl_dwgs)
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
                for i, fb in enumerate(targets):
                    print("     [%d] bbox=%s" % (i, [float(round(x, 1)) for x in fb]))
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
                        old = extract.extract_fields(doc, {"bbox": tb, "method": "keyword", "entity": None})
                        values, unmatched, unused = mapper.map_fields(template["fields"], old, override)
                        if args.dry_run:
                            rec["written"] = [f["tag"] for f, v in zip(template["fields"], values) if v]
                            rec["deleted"] = 0
                        else:
                            n_edge = raw_replace.delete_frame_lines(doc, frames)
                            n_tb = raw_replace.delete_titleblock(doc, tb, maxdim)
                            n_mark = raw_replace.delete_edge_markers(doc, outer, strip=10.0)
                            region = {"bbox": outer, "confidence": 1.0, "method": "frame",
                                      "source": "sheet", "entity": None}
                            # #3：尊重 GUI「缩放」选择（args.fit），不再写死 "max"
                            _, written = block_replace.insert_template(
                                doc, template, region, values, fit=args.fit or "max")
                            rec["written"] = list(dict.fromkeys(written))
                            rec["deleted"] = n_edge + n_tb + n_mark
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
                    for fb in targets:
                        fields = finder.extract_frame_fields(doc, fb)
                        values, unmatched, unused = mapper.map_fields(
                            template["fields"], fields, override)
                        mappings.append({"region": [round(v, 1) for v in fb],
                                         "extracted": fields,
                                         "unmatched": unmatched, "unused": unused})
                else:
                    mappings, all_written, total_del = _process_multiframe(
                        doc, template, targets, override, args.fit)
                regions = []

            for r in regions:
                old = extract.extract_fields(doc, r)
                values, unmatched, unused = mapper.map_fields(template["fields"], old, override)
                mappings.append({"region": [round(x, 1) for x in r["bbox"]],
                                  "extracted": old, "unmatched": unmatched, "unused": unused})
                if args.dry_run:
                    continue
                ndel = block_replace.delete_old(doc, r, margin=args.margin)
                total_del += ndel
                _, written = block_replace.insert_template(doc, template, r, values, fit=args.fit)
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

    rp = logbook.close(lb, args.out, report)
    print("\n== 完成。报告:", rp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
