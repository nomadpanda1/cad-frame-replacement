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
import argparse
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import template_learn, finder, extract, mapper, block_replace, acad, logbook  # noqa


def _count_entities(doc):
    n = 0
    for _ in doc.modelspace():
        n += 1
    return n


def _load_doc(path, conv_info):
    """读入图纸：DWG 先转 DXF。返回 (doc, working_path, is_dwg_input)。"""
    if path.lower().endswith(".dwg"):
        if not conv_info:
            raise RuntimeError("输入为 DWG，需要 DWG→DXF 转换器（ODA File Converter / LibreCAD），本机未检测到。请先转成 DXF，或安装转换器。")
        tmp = tempfile.mktemp(suffix=".dxf")
        if not acad.dwg_to_dxf(path, tmp):
            raise RuntimeError("DWG→DXF 转换失败：" + path)
        return ezdxf_read(tmp), tmp, True
    return ezdxf_read(path), path, False


def ezdxf_read(p):
    import ezdxf
    return ezdxf.readfile(p)


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
    if args.dwg and not conv_info:
        print("[WARN] 请求输出 DWG 但本机无转换器，将只输出 DXF。")

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
            regions = finder.find_titleblocks(doc)
            rec["found"] = len(regions)
            print("   检测到标题栏: %d 个" % len(regions))
            for i, r in enumerate(regions):
                print("     [%d] 置信度 %.2f 方法=%s 源=%s bbox=%s" % (
                    i, r["confidence"], r["method"], r["source"], [round(x, 1) for x in r["bbox"]]))

            if args.detect_only:
                det_path = os.path.join(args.out, os.path.splitext(os.path.basename(src))[0] + "_detection.json")
                with open(det_path, "w", encoding="utf-8") as f:
                    json.dump([{"bbox": r["bbox"], "confidence": r["confidence"],
                                "method": r["method"], "source": r["source"],
                                "confirmed": False} for r in regions], f, ensure_ascii=False, indent=2)
                rec["status"] = "detected"
                rec["out"] = os.path.basename(det_path)
                logbook.log(lb, src, "detected", len(regions), 0, [], det_path, "仅检测")
                report["files"].append(rec)
                continue

            # 提取 + 映射
            all_written = []
            total_del = 0
            mappings = []
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

            rec["mappings"] = mappings
            rec["deleted"] = total_del
            rec["written"] = list(dict.fromkeys(all_written))

            if args.dry_run:
                rec["status"] = "dry-run"
                logbook.log(lb, src, "dry-run", len(regions), 0, [], "", "未改图")
                report["files"].append(rec)
                continue

            # 保存
            base = os.path.splitext(os.path.basename(src))[0]
            out_dxf = os.path.join(args.out, base + args.suffix + ".dxf")
            doc.saveas(out_dxf)
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
            logbook.log(lb, src, "ok", len(regions), total_del, list(dict.fromkeys(all_written)),
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
