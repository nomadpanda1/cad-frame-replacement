# -*- coding: utf-8 -*-
"""把案例十的 11 张源 DWG 一次性转成 DXF 缓存到 verify/_conv_src/。

目的：检测算法（图框识别、字段提取）需要反复迭代，每次都用 AutoCAD COM 转 DWG
太慢（每张 3~8s）。先转一次缓存下来，后续诊断脚本直接 ezdxf.readfile。

已存在且非空的 DXF 会跳过；用 --force 强制重转。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CASE = os.path.dirname(HERE)
IN_DIR = os.path.join(CASE, "inputs")
OUT_DIR = os.path.join(HERE, "_conv_src")
os.makedirs(OUT_DIR, exist_ok=True)

FORCE = "--force" in sys.argv


def get_acad():
    import win32com.client as wc
    try:
        return wc.GetActiveObject("AutoCAD.Application")
    except Exception:
        print("[info] 启动 AutoCAD ...", flush=True)
        a = wc.Dispatch("AutoCAD.Application")
        try:
            a.Visible = True
        except Exception:
            pass
        time.sleep(5)
        return a


def to_dxf(app, src, dst):
    doc = None
    for _ in range(6):
        try:
            doc = app.Documents.Open(os.path.abspath(src))
            break
        except Exception as e:
            print("  Open retry (%s)" % e, flush=True)
            time.sleep(3)
    if doc is None:
        return False
    time.sleep(1.0)
    try:
        doc.SaveAs(os.path.abspath(dst))   # 本机 SaveAs 默认写 DXF（见项目记忆）
    finally:
        time.sleep(0.5)
        try:
            doc.Close(False)
        except Exception:
            pass
    time.sleep(0.3)
    return os.path.exists(dst) and os.path.getsize(dst) > 2000


def main():
    files = sorted(f for f in os.listdir(IN_DIR) if f.lower().endswith(".dwg"))
    todo = []
    for fn in files:
        dst = os.path.join(OUT_DIR, os.path.splitext(fn)[0] + ".dxf")
        if not FORCE and os.path.exists(dst) and os.path.getsize(dst) > 2000:
            continue
        todo.append((os.path.join(IN_DIR, fn), dst))
    print("共 %d 张，需转换 %d 张" % (len(files), len(todo)), flush=True)
    if not todo:
        return 0
    app = get_acad()
    ok = 0
    for src, dst in todo:
        t0 = time.time()
        r = to_dxf(app, src, dst)
        ok += 1 if r else 0
        print("  %-24s %s  %.1fs" % (os.path.basename(src),
                                     "OK" if r else "FAILED", time.time() - t0),
              flush=True)
    print("完成 %d/%d" % (ok, len(todo)), flush=True)
    return 0 if ok == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
