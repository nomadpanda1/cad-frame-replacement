# -*- coding: utf-8 -*-
"""用 Python 子进程驱动 onefile exe，可靠捕获其 stdout（含退出码）。
- start_new_session=True 让 exe 子进程自成会话，其引导器退出时的临时目录
  清理尽量不波及本驱动进程。
- exe 的打包 Python 控制台把中文以「UTF-8 字节的 cp1251 误读」双重编码输出，
  故逐块修复：bytes->utf-8(replace) 得到乱码串 -> encode('utf-8','ignore')
  -> decode('cp1251','replace') 还原中文。数字/ASCII/文件名不受影响。
- 每读一块立即写盘并 flush，避免 exe 收尾时把本进程带死导致日志丢失。
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
exe = os.path.join(HERE, "dist", "cad-frame-cli.exe")
out_dir = os.path.join(HERE, "exe_test_out")
os.makedirs(out_dir, exist_ok=True)
log_path = os.path.join(out_dir, "run_utf8.log")


def fix(b):
    s = b.decode("utf-8", "replace")
    return s.encode("utf-8", "ignore").decode("cp1251", "replace")


args = sys.argv[1:]
cmd = [exe] + args
f = open(log_path, "w", encoding="utf-8")


def emit(s):
    sys.stdout.write(s)
    sys.stdout.flush()
    f.write(s)
    f.flush()


emit("=== CMD ===\n" + " ".join(cmd) + "\n=== OUTPUT ===\n")
p = subprocess.Popen(
    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    bufsize=0, start_new_session=True,
)
while True:
    ch = p.stdout.read(4096)
    if not ch:
        break
    emit(fix(ch))
try:
    rc = p.wait()
    emit(f"\n=== EXIT CODE: {rc} ===\n")
except Exception as e:
    emit(f"\n=== wait err: {e} ===\n")
f.close()
