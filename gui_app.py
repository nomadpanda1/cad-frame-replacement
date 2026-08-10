# -*- coding: utf-8 -*-
"""CAD 图框批量置换 —— 图形界面（打包成 exe 供免装 Python 的同事使用）。

界面只做「选文件 / 选模板 / 选输出目录 / 选项」，点击开始后把参数组装成
sys.argv 并调用已验证的 run_skill.main()，其 print 输出实时回流到日志框。
核心逻辑零改动，保证与命令行版本行为一致。
"""
import os
import sys
import io
import queue
import threading
from tkinter import (
    Tk, Frame, Label, Button, Entry, Listbox, Combobox, Checkbutton,
    StringVar, BooleanVar, filedialog, messagebox, scrolledtext, END,
)

# ---- 资源定位：frozen(exe) 与源码两种形态都兼容 ----
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
    MEIPASS = getattr(sys, "_MEIPASS", BASE)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    MEIPASS = BASE

if BASE not in sys.path:
    sys.path.insert(0, BASE)


def default_template():
    for base in (BASE, MEIPASS):
        p = os.path.join(base, "templates", "HH_FRAME_A1.dxf")
        if os.path.exists(p):
            return p
    return os.path.join(BASE, "templates", "HH_FRAME_A1.dxf")


# ---- 日志：run_skill 的 print 经 QueueStream 回流到界面 ----
log_q = queue.Queue()


class QueueStream(io.TextIOBase):
    def write(self, s):
        log_q.put(s)
        return len(s)


def drain_log(text_widget):
    try:
        while True:
            text_widget.insert(END, log_q.get_nowait())
            text_widget.see(END)
    except queue.Empty:
        pass
    text_widget.after(80, drain_log, text_widget)


class App:
    def __init__(self, root):
        self.root = root
        root.title("CAD 图框批量置换 (HH 图框)")
        root.geometry("760x600")

        self.files = []
        self.template = StringVar(value=default_template())
        self.outdir = StringVar(value=os.path.join(BASE, "output"))
        self.mode = StringVar(value="auto")
        self.fit = StringVar(value="min")
        self.detect_only = BooleanVar(value=False)
        self.dry_run = BooleanVar(value=False)
        self.running = False

        self._build()
        self.log.after(80, drain_log, self.log)

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 8, "pady": 4}

        # 说明
        Label(self.root, text="选择旧图纸 → 选公司图框模板 → 选输出目录 → 开始。",
              fg="#555").pack(anchor="w", **pad)

        # 图纸列表
        f1 = Frame(self.root)
        f1.pack(fill="x", **pad)
        Label(f1, text="① 源图纸 (支持多选 .dxf/.dwg):").pack(anchor="w")
        self.lb = Listbox(f1, height=5, selectmode="extended")
        self.lb.pack(fill="x")
        b1 = Frame(f1)
        b1.pack(fill="x")
        Button(b1, text="添加图纸", command=self.add_files).pack(side="left")
        Button(b1, text="移除选中", command=self.remove_sel).pack(side="left")
        Button(b1, text="清空", command=self.clear_files).pack(side="left")

        # 模板
        f2 = Frame(self.root)
        f2.pack(fill="x", **pad)
        Label(f2, text="② 公司图框模板 (.dxf):").pack(anchor="w")
        e2 = Entry(f2, textvariable=self.template)
        e2.pack(side="left", fill="x", expand=True)
        Button(f2, text="选择模板", command=self.choose_template).pack(side="left")

        # 输出
        f3 = Frame(self.root)
        f3.pack(fill="x", **pad)
        Label(f3, text="③ 输出目录:").pack(anchor="w")
        e3 = Entry(f3, textvariable=self.outdir)
        e3.pack(side="left", fill="x", expand=True)
        Button(f3, text="选择目录", command=self.choose_out).pack(side="left")

        # 选项
        f4 = Frame(self.root)
        f4.pack(fill="x", **pad)
        Label(f4, text="模式:").pack(side="left")
        Combobox(f4, textvariable=self.mode, width=10,
                 values=["auto", "single", "multi"], state="readonly").pack(side="left")
        Label(f4, text="  缩放:").pack(side="left")
        Combobox(f4, textvariable=self.fit, width=10,
                 values=["min", "max", "width", "height"], state="readonly").pack(side="left")
        Checkbutton(f4, text="仅检测(写 detection.json)", variable=self.detect_only).pack(side="left")
        Checkbutton(f4, text="仅提取不改图", variable=self.dry_run).pack(side="left")

        # 开始
        f5 = Frame(self.root)
        f5.pack(fill="x", **pad)
        self.btn_start = Button(f5, text="开始处理", bg="#2a7", fg="white",
                                height=1, command=self.start)
        self.btn_start.pack(side="left", ipadx=12)
        Label(f5, text="处理中会禁用按钮，完成弹窗。").pack(side="left")

        # 日志
        Label(self.root, text="运行日志:").pack(anchor="w", **pad)
        self.log = scrolledtext.ScrolledText(self.root, height=12, state="normal")
        self.log.pack(fill="both", expand=True, **pad)

    # ---------- 交互 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择源图纸", filetypes=[("CAD 图纸", "*.dxf;*.dwg"), ("全部", "*.*")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.lb.insert(END, p)

    def remove_sel(self):
        for i in reversed(self.lb.curselection()):
            self.lb.delete(i)
            del self.files[i]

    def clear_files(self):
        self.lb.delete(0, END)
        self.files.clear()

    def choose_template(self):
        p = filedialog.askopenfilename(title="选择公司图框模板",
                                       filetypes=[("DXF", "*.dxf"), ("全部", "*.*")])
        if p:
            self.template.set(p)

    def choose_out(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir.set(d)

    def start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showwarning("未选图纸", "请先添加至少一个源图纸。")
            return
        if not os.path.exists(self.template.get()):
            messagebox.showwarning("模板缺失", "模板文件不存在：\n" + self.template.get())
            return
        self.running = True
        self.btn_start.config(state="disabled")
        self.log.insert(END, "\n=== 开始处理 ===\n")
        threading.Thread(target=self.worker, daemon=True).start()

    # ---------- 后台执行 run_skill.main() ----------
    def worker(self):
        argv = ["run_skill.py",
                "--template", self.template.get(),
                "--out", self.outdir.get(),
                "--mode", self.mode.get(),
                "--fit", self.fit.get()]
        if self.detect_only.get():
            argv.append("--detect-only")
        if self.dry_run.get():
            argv.append("--dry-run")
        argv += list(self.files)

        old_stdout = sys.stdout
        sys.stdout = QueueStream()
        try:
            import run_skill
            sys.argv = argv
            run_skill.main()
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
        self.root.after(0, self.on_done)

    def on_done(self):
        self.running = False
        self.btn_start.config(state="normal")
        self.log.insert(END, "\n=== 处理结束 ===\n")
        messagebox.showinfo("完成", "处理结束。\n结果在输出目录：\n" + self.outdir.get())


def main():
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
