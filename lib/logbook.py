# -*- coding: utf-8 -*-
"""
执行日志与汇总报告：单张失败不影响整体；输出 run_report.json + Execution_Log.csv。
"""
import os
import csv
import json


def make_logbook(out_dir):
    csv_path = os.path.join(out_dir, "Execution_Log.csv")
    f = open(csv_path, "w", newline="", encoding="utf-8-sig")
    w = csv.writer(f)
    w.writerow(["源文件", "状态", "检测数", "删除实体", "插入字段", "输出", "备注"])
    return {"file": f, "writer": w, "csv_path": csv_path, "records": []}


def log(logbook, src, status, n_found, n_del, written, out_path, note=""):
    logbook["writer"].writerow([src, status, n_found, n_del, ",".join(written), out_path or "", note])
    logbook["file"].flush()
    logbook["records"].append({
        "src": src, "status": status, "found": n_found,
        "deleted": n_del, "written": written, "out": out_path, "note": note,
    })


def close(logbook, out_dir, report):
    logbook["file"].close()
    rp = os.path.join(out_dir, "run_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return rp
