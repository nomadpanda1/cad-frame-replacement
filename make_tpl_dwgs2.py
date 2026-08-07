# -*- coding: utf-8 -*-
"""用 AutoCAD SendCommand 把模板 DXF 另存为 DWG。"""
import os
import glob
import win32com.client

TPL_DIR = r"C:\Users\86308\WorkBuddy\2026-08-04-09-31-00\outputs\cad-frame-replacement\templates"
OUT_DIR = r"C:\Users\86308\WorkBuddy\2026-08-06-10-55-23\cad-frame-replacement\tpl_dwgs"
os.makedirs(OUT_DIR, exist_ok=True)

app = win32com.client.Dispatch("AutoCAD.Application")
print("AutoCAD:", app.Caption)

for src in sorted(glob.glob(os.path.join(TPL_DIR, "HH_FRAME_*.dxf"))):
    name = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(OUT_DIR, name + ".dwg")
    if os.path.exists(dst):
        print("skip", dst)
        continue
    doc = app.Documents.Open(src)
    # 发送 SAVEAS 命令：格式 2018，文件名
    cmd = f"_.-SAVEAS _.? {dst}\n"
    try:
        doc.SendCommand(cmd)
    except Exception as e:
        print("sendcommand err:", e)
    doc.Close(False)
    print("saved?", dst, os.path.exists(dst))

print("done")
