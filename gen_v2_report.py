# -*- coding: utf-8 -*-
"""用【修复后】的 raw-line 整框替换管线，对 9 张用户微信图纸重跑效果对比。

复用 run_real.process_one（已含 #2 竖直 LINE 端点顺序修复），输出到 output_real_v2/：
  每张图: <名>_before.png / _template.png / _after.png + <名>_HH.dxf
  汇总: index.html（生成前 / 公司模板 / 生成后 三栏对比 + 提取/回填字段）

目的：给用户可验证的“测试结果”，对齐 cases/02 CNG 案例的展示格式。
"""
import os
import sys
import glob

import matplotlib
matplotlib.use("Agg")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_real as R

# 指向当前仓库自带的模板（与 exe 打包一致），而非旧硬编码路径
R.TPL_DIR = os.path.join(HERE, "templates")

INPUT_DIR = os.path.join(HERE, "input_real")  # 已随仓库自带（从旧草稿副本迁入，避免依赖已冻结的草稿副本）
OUT_DIR = os.path.join(HERE, "output_real_v2")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.dxf")))
    print("输入图纸:", len(files), "张")
    results = []
    for fp in files:
        rec, err = R.process_one(fp, OUT_DIR)
        if err:
            print("   [跳过]", os.path.basename(fp), "->", err)
        else:
            results.append(rec)

    print("\n== 完成，成功处理", len(results), "/", len(files), "张 ==")
    html = os.path.join(OUT_DIR, "index.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><style>"
                "body{font-family:sans-serif;background:#1e1e1e;color:#ddd}"
                "img{max-width:100%;border:1px solid #444;margin:4px;background:#fff}"
                "h2{color:#fff;border-top:1px solid #444;padding-top:10px}"
                "table{margin:0 auto}.k{color:#9cd;font-size:13px}"
                ".ok{color:#6f6}.n{color:#f99}</style></head><body>\n")
        f.write("<h1>CAD 图框批量置换 · 效果对比（修复版 #2 + 打散回退）</h1>\n")
        f.write("<p class='k'>管线：run_real 线框检测（detect_frames + detect_titleblock）→ 删旧外框线/标题栏/边缘区号 → 整图幅插 HH_FRAME_A* 模板并回填字段。"
                "已修复竖直 LINE 框线端点顺序漏删（#2）。</p>\n")
        for r in results:
            f.write(f"<h2>{os.path.basename(r['dxf'])} &nbsp;<span class='k'>({r['size']}, 模板 {r['tpl']})</span></h2>\n")
            f.write("<p class='k'>提取字段：" + str(r['fields']) +
                    "<br>回填字段：" + str(r['written']) + "</p>\n")
            f.write("<table><tr>\n")
            f.write(f"<td><b>生成前</b><br><img src='{os.path.basename(r['before'])}'></td>\n")
            f.write(f"<td><b>公司模板</b><br><img src='{os.path.basename(r['template'])}'></td>\n")
            f.write(f"<td><b>生成后</b><br><img src='{os.path.basename(r['after'])}'></td>\n")
            f.write("</tr></table>\n")
        f.write("</body></html>\n")
    print("对比索引:", html)


if __name__ == "__main__":
    main()
