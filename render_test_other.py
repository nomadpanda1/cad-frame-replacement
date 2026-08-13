# -*- coding: utf-8 -*-
"""把「其他场景」测试的输入/输出 DXF 渲染成 SVG，供 test_other.html 内联前后对照。
复用 render_exe_test.py 的 render()，保证与 exe_test.html 同一渲染口径。"""
import os
import json
import glob
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
SVG_DIR = os.path.join(HERE, "test_other", "svg")
os.makedirs(SVG_DIR, exist_ok=True)

# 复用 render_exe_test.py 的 render()（仅定义，不执行其 __main__）
spec = importlib.util.spec_from_file_location("rex", os.path.join(HERE, "render_exe_test.py"))
rex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rex)

CASES = ["01", "03", "06", "07", "08"]


def main():
    # 清空 svg 目录，整体重渲（旧 03_before/03_after 等命名已弃用）
    for f in os.listdir(SVG_DIR):
        try:
            os.remove(os.path.join(SVG_DIR, f))
        except OSError:
            pass

    total = 0
    for cid in CASES:
        indirs = glob.glob(os.path.join("cases", f"{cid}*", "inputs"))
        if not indirs:
            print(f"[skip] case {cid}: 找不到 inputs 目录")
            continue
        indir = indirs[0]
        rep = json.load(open(os.path.join(HERE, "test_other", cid, "run_report.json"), encoding="utf-8"))
        for it in rep.get("files", []):
            src = it["src"]
            out = it["out"]
            name = src.rsplit(".", 1)[0]
            inp = os.path.join(indir, src)
            outp = os.path.join(HERE, "test_other", cid, out)
            tag = f"{cid}__{name}"
            if not (os.path.exists(inp) and os.path.exists(outp)):
                print(f"[skip] {tag}: 缺输入或输出")
                continue
            try:
                si = rex.render(inp, os.path.join(SVG_DIR, tag + "_in.svg"))
                so = rex.render(outp, os.path.join(SVG_DIR, tag + "_out.svg"))
                print(f"[ok] {tag}: in {si}B / out {so}B")
                total += 1
            except Exception as e:
                print(f"[ERR] {tag}: {e}")
    print(f"[done] 共渲染 {total} 组前后 SVG -> {SVG_DIR}")


if __name__ == "__main__":
    main()
