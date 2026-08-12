# -*- coding: utf-8 -*-
"""重测两报告涉及的图纸：output_real/index.html（9 张 SW 图纸）与 cases/report.html（8 套案例）。

用【修复后】的管线重新生成 before/template/after 对比图 + _HH.dxf，并重建 cases/report.html / showcase.html。
- 修复影响路径：raw-frame 打散回退（#3 尊重 GUI 缩放 / #4 用 outer 框而非全局 sheet / #5 取面积最大框）。
  该路径被案例一(01_SW_parts)、output_real 的 9 张、案例三(03_ESS) 走，本脚本用 run_real.process_one（已含修复）重跑。
- 多框路径(07/08)、块式+COM(02/04) 不受本修复影响，仅做 smoke 复跑确认无回归（02/04 需本机 AutoCAD，沙箱跳过）。
"""
import os
import sys
import glob
import subprocess

import matplotlib
matplotlib.use("Agg")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_real as R

# 指向当前仓库自带模板（与 exe 打包一致），覆盖旧硬编码路径
R.TPL_DIR = os.path.join(HERE, "templates")


def regen_raw_frame(case_label, input_dir, out_dir):
    """用修复后的 run_real.process_one 重跑 raw-frame 图纸。返回 (ok, total)。"""
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(input_dir, "*.dxf")))
    ok = 0
    for fp in files:
        try:
            rec, err = R.process_one(fp, out_dir)
        except Exception as e:  # noqa
            print("  [EXC] %s -> %s" % (os.path.basename(fp), e))
            continue
        if err:
            print("  [SKIP] %s -> %s" % (os.path.basename(fp), err))
        else:
            ok += 1
            print("  [OK] %s  %s / %s  提取=%s 回填=%s" % (
                os.path.basename(rec["dxf"]), rec["size"], rec["tpl"],
                rec["fields"], rec["written"]))
    print("  -> %s: 成功 %d / %d" % (case_label, ok, len(files)))
    return ok, len(files)


def run_script(script, label):
    """复跑案例专属脚本（多框/合成/块式+COM），作为 smoke + 刷新。"""
    print("===== %s (%s) =====" % (label, script))
    try:
        r = subprocess.run([sys.executable, script], cwd=HERE,
                           capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip().splitlines()[-8:]
        for line in out:
            print("  ", line)
        print("  -> exit %d" % r.returncode)
        return r.returncode == 0
    except Exception as e:  # noqa
        print("  [EXC] %s -> %s" % (script, e))
        return False


def main():
    summary = []

    # 1) 案例一 outputs_v2：9 张用户 SW 图纸（raw-frame 路径，DXF 产出 + index.html）
    print("===== cases/01_SW_parts/outputs_v2（9 张 SW 图纸，raw-frame 路径）=====")
    ok, tot = regen_raw_frame(
        "01_SW_parts/outputs_v2",
        os.path.join(HERE, "cases", "01_SW_parts", "inputs"),
        os.path.join(HERE, "cases", "01_SW_parts", "outputs_v2"))
    summary.append(("01_SW_parts/outputs_v2 (9 SW 图纸)", ok, tot))

    # 2) 案例一 01_SW_parts（与 output_real 同一批图纸，raw-frame）
    print("===== cases/01_SW_parts（raw-frame）=====")
    ok, tot = regen_raw_frame(
        "01_SW_parts",
        os.path.join(HERE, "cases", "01_SW_parts", "inputs"),
        os.path.join(HERE, "cases", "01_SW_parts", "outputs"))
    summary.append(("01_SW_parts", ok, tot))

    # 3) 案例三 03_ESS_cad（4 张 A1 表，raw-frame）
    print("===== cases/03_ESS_cad（raw-frame）=====")
    ok, tot = regen_raw_frame(
        "03_ESS_cad",
        os.path.join(HERE, "cases", "03_ESS_cad", "inputs"),
        os.path.join(HERE, "cases", "03_ESS_cad", "outputs"))
    summary.append(("03_ESS_cad", ok, tot))

    # 4) 案例六 06_synth（合成异常样本，专属脚本，smoke + 刷新）
    summary.append(("06_synth", run_script("run_synth.py", "案例六 synth"), None))

    # 5) 案例七 07_multiframe / 案例八 08_real_mf（多框，不受本修复影响，smoke 确认无回归）
    summary.append(("07_multiframe", run_script("run_multiframe.py", "案例七 multiframe"), None))
    summary.append(("08_real_mf", run_script("run_real_mf.py", "案例八 real_mf"), None))

    # 6) 案例二 02_CNG / 案例四 04_assembly：DWG + AutoCAD COM，沙箱无 AutoCAD，跳过（既有成品有效）
    print("===== 02_CNG / 04_assembly：需本机 AutoCAD COM，沙箱跳过（既有成品 DWG/DXF 保留）=====")
    summary.append(("02_CNG_electrical", "skip(AutoCAD)", None))
    summary.append(("04_assembly", "skip(AutoCAD)", None))

    # 7) 重建 cases/report.html / showcase.html
    print("===== make_showcase.py（重建 cases/report.html / showcase.html）=====")
    rb = subprocess.run([sys.executable, os.path.join(HERE, "cases", "make_showcase.py")],
                        cwd=HERE, capture_output=True, text=True, timeout=120)
    print(rb.stdout.strip())
    if rb.stderr.strip():
        print("  [stderr]", rb.stderr.strip().splitlines()[-5:])
    summary.append(("cases/report.html", rb.returncode == 0, None))

    print("\n================ 重测汇总 ================")
    for name, ok, tot in summary:
        if tot is None:
            print("  %-22s %s" % (name, ok))
        else:
            print("  %-22s %s / %s" % (name, ok, tot))


if __name__ == "__main__":
    main()
