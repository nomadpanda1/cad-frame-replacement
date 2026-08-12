# -*- coding: utf-8 -*-
"""住宅楼电气方案 11 张图：逐张跑 AutoCAD COM 替换管线（含重试/落盘校验）。

每张独立调用 run_skill.main()，调用前关闭 AutoCAD 残留文档清锁；
每次确认 cases/10_residential_electrical/outputs/dwg/<名>_HH.dwg 真正写盘
（存在且 size>2KB）才算成功，否则重试。
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CASE = os.path.join(HERE, "cases", "10_residential_electrical")
IN_DIR = os.path.join(CASE, "inputs")
OUT = os.path.join(CASE, "outputs", "dwg")
os.makedirs(OUT, exist_ok=True)
TPL = os.path.join(HERE, "templates", "HH_FRAME_A4.dxf")
FILES = sorted(
    f for f in os.listdir(IN_DIR)
    if f.lower().endswith(".dwg")
)


def close_all():
    try:
        import win32com.client as wc
        acad = wc.GetActiveObject("AutoCAD.Application")
        for n in [d.Name for d in acad.Documents]:
            try:
                acad.Documents.Item(n).Close(False)
            except Exception:
                pass
            time.sleep(0.3)
    except Exception:
        pass


import run_skill

MAX_ATTEMPT = 4
results = []

for fn in FILES:
    src = os.path.join(IN_DIR, fn)
    base = os.path.splitext(fn)[0]
    out_path = os.path.join(OUT, base + "_HH.dwg")
    ok = False
    for attempt in range(MAX_ATTEMPT):
        close_all()
        time.sleep(2)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        print("\n===== %s (attempt %d/%d) =====" % (fn, attempt + 1, MAX_ATTEMPT))
        sys.argv = ["run_skill.py", "--template", TPL, "--dwg", "--fit", "max",
                    "--out", OUT, src]
        try:
            run_skill.main()
        except SystemExit:
            pass
        except Exception as e:
            print("  main() 异常:", e)
        time.sleep(1)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 2000:
            print("落盘成功:", out_path, os.path.getsize(out_path), "bytes")
            ok = True
            break
        else:
            print("  ! 本次未落盘，重试...")
            time.sleep(3)
    results.append((fn, "OK" if ok else "FAILED"))
    print("进度: %d/%d  %s" % (len(results), len(FILES), dict(results)))

print("\n汇总:")
for fn, st in results:
    print("  %-22s %s" % (fn, st))
print("最终:", "全部成功" if all(s == "OK" for _, s in results) else "有失败")
