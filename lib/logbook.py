# -*- coding: utf-8 -*-
"""
执行日志与汇总报告：单张失败不影响整体；输出 run_report.json + Execution_Log.csv。

写入策略（针对 Windows 下文件被其他进程占用锁死的健壮性）：
- 运行期间「不长期持有」CSV 文件句柄，所有记录先缓存在内存（records）。
- 每次 log() 额外增量写到一个「本进程唯一」的临时 CSV，防止崩溃丢数据。
- 结束时一次性把完整记录用「临时文件 + os.replace 原子重命名」落到
  Execution_Log.csv；若目标被占用锁死（如另一实例正开着同一输出目录），
  则退化为带时间戳的备用文件名，绝不抛 PermissionError 中断主流程。
"""
import os
import csv
import json
import time
import io
import tempfile


def _atomic_write_text(path, text, encoding="utf-8-sig"):
    """把 text 落到 path：临时文件 + 原子替换；目标被锁则落到带时间戳的备用名。返回最终路径。"""
    d = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix="._log_", dir=d)
        with os.fdopen(fd, "w", newline="", encoding=encoding) as f:
            f.write(text)
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            # 目标被其他进程锁死：换一个带时间戳的名字，绝不中断主流程
            alt = os.path.join(d, "%s_%d%s" % (stem, int(time.time()), ext))
            os.replace(tmp, alt)
            return alt
    except PermissionError:
        # 连临时目录都写不进去（极端），直接写备用名
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        alt = os.path.join(d, "%s_%d%s" % (stem, int(time.time()), ext))
        with open(alt, "w", newline="", encoding=encoding) as f:
            f.write(text)
        return alt
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _rows_to_csv(header, records):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in records:
        w.writerow([
            r.get("src", ""), r.get("status", ""), r.get("found", ""),
            r.get("deleted", ""), ",".join(r.get("written", []) or []),
            r.get("out", "") or "", r.get("note", "") or "",
        ])
    return buf.getvalue()


def make_logbook(out_dir):
    csv_path = os.path.join(out_dir, "Execution_Log.csv")
    header = ["源文件", "状态", "检测数", "删除实体", "插入字段", "输出", "备注"]
    # 增量临时文件（本进程唯一，避免与可能被锁的 final CSV 冲突）
    incr_tmp = None
    try:
        fd, incr_tmp = tempfile.mkstemp(suffix=".tmp", prefix="._incr_", dir=out_dir)
        os.close(fd)
    except Exception:
        incr_tmp = None
    return {"dir": out_dir, "csv_path": csv_path, "header": header,
            "records": [], "incr_tmp": incr_tmp, "final_path": None}


def log(logbook, src, status, n_found, n_del, written, out_path, note=""):
    rec = {"src": src, "status": status, "found": n_found,
           "deleted": n_del, "written": written, "out": out_path, "note": note}
    logbook["records"].append(rec)
    # 增量落盘（崩溃也不丢），失败静默忽略，绝不影响主流程
    try:
        if logbook.get("incr_tmp"):
            with open(logbook["incr_tmp"], "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([src, status, n_found, n_del, ",".join(written or []),
                            out_path or "", note])
    except Exception:
        pass


def close(logbook, out_dir, report):
    # 最终 CSV：原子替换；若目标被锁则退化备用名
    text = _rows_to_csv(logbook["header"], logbook["records"])
    final = _atomic_write_text(logbook["csv_path"], text, encoding="utf-8-sig")
    logbook["final_path"] = final
    # 清理增量临时文件
    try:
        if logbook.get("incr_tmp") and os.path.exists(logbook["incr_tmp"]):
            os.remove(logbook["incr_tmp"])
    except OSError:
        pass
    # 汇总报告：同样走原子写 + 锁退化的健壮路径
    try:
        rp = os.path.join(out_dir, "run_report.json")
        _atomic_write_text(rp, json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except Exception:
        pass
    return final
