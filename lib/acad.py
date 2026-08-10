# -*- coding: utf-8 -*-
"""
DWG 转换器探测与转换（ezdxf 只能读写 DXF）。

优先级（从高到低）：
  1) AutoCAD COM —— 本机装了且已打开 AutoCAD 即可直接读写 DWG（win32com 连接已运行实例，
     不自动启动）。对设计院加密/代理实体图纸也比 ODA 更可靠，是 skill 策略二的核心通道。
  2) ODA File Converter（免费）
  3) LibreCAD
本机若三者皆无，则 DWG 输入回退为：提示用户先转 DXF；输出只给 DXF。
"""
import shutil
import subprocess
import os
import tempfile


def _which(name):
    p = shutil.which(name)
    if p:
        return p
    # 常见安装位置（根目录，旧逻辑兜底）
    for base in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\Program Files"):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return None


def _get_acad():
    """返回已打开的 AutoCAD COM 实例；连不上返回 None（不会自动启动 AutoCAD）。

    用 GetActiveObject 而非 Dispatch：Dispatch 在 AutoCAD 未开时会自动启动一个实例，
    而 SKILL 实测自动启动的实例 COM 不稳；这里要求用户手动打开 AutoCAD（与本机工作流一致）。
    """
    try:
        import win32com.client
        return win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        return None


def find_converter():
    """返回 (name, path) 或 None。

    检测顺序：
      1) AutoCAD COM（已打开的实例）—— 直接读写 DWG，最优先；
      2) PATH 中的 ODAFileConverter / LibreCAD（用户安装时勾选加入 PATH 的情况）；
      3) 默认安装父目录递归扫描（ODA 默认装在 C:\\Program Files\\ODA\\ODAFileConverter 20xx\\
         子目录，旧逻辑只查根目录会漏，这里递归扫描确定父目录）。
    """
    # 1) AutoCAD COM（已打开实例）
    app = _get_acad()
    if app is not None:
        try:
            _ = app.Caption  # 探活：能取到说明 COM 可用
            return ("AutoCAD", None)
        except Exception:
            pass

    # 2) PATH → ODA / LibreCAD
    oda = _which("ODAFileConverter.exe") or _which("ODAFileConverter")
    if oda:
        return ("ODAFileConverter", oda)
    lc = _which("librecad.exe") or _which("librecad")
    if lc:
        return ("LibreCAD", lc)

    # 3) 默认安装父目录递归（ODA/LibreCAD 都装在这几个确定位置）
    for base in (r"C:\Program Files\ODA", r"C:\Program Files (x86)\ODA",
                 r"C:\Program Files\LibreCAD", r"C:\Program Files (x86)\LibreCAD"):
        if not os.path.isdir(base):
            continue
        for cur, _dirs, files in os.walk(base):
            for f in files:
                fl = f.lower()
                if fl == "odafileconverter.exe":
                    return ("ODAFileConverter", os.path.join(cur, f))
                if fl == "librecad.exe":
                    return ("LibreCAD", os.path.join(cur, f))
    return None


def _acad_saveas(src, dst):
    """用已打开的 AutoCAD 把 src 另存为 dst（按 dst 扩展名推断 DXF/DWG）。

    依赖：本机已打开 AutoCAD；win32com 可用。Documents.Open 后须 sleep 等加载，
    否则 ModelSpace 报“被呼叫方拒绝接收呼叫”。SaveAs 的 format 参数在本机失效，
    故不传 format，完全靠扩展名（.dxf→DXF，.dwg→DWG）。

    健壮性：AutoCAD COM 偶发“被呼叫方拒绝接收呼叫”(call rejected)，常在 AutoCAD
    正忙/弹模态框时出现。这里用「重试 + 退避」兜底，单次失败不直接判死。
    """
    import time
    app = _get_acad()
    if app is None:
        return False
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    last_err = None
    for attempt in range(5):
        doc = None
        try:
            # 先把 AutoCAD 提到前台，避免它在后台弹模态框导致 COM 调用被拒
            try:
                app.Visible = True
            except Exception:
                pass
            time.sleep(0.5 * (attempt + 1))
            doc = app.Documents.Open(src)
            time.sleep(2)
            doc.SaveAs(dst)
            doc.Close(False)
            return os.path.exists(dst)
        except Exception as e:
            last_err = e
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            time.sleep(1.5 * (attempt + 1))
    if last_err is not None:
        import sys
        sys.stderr.write("[WARN] AutoCAD 转换失败（已回退为只输出 DXF）: %s\n" % last_err)
    return False


def dwg_to_dxf(src, dst):
    """把 DWG 转成 DXF，成功返回 True。"""
    conv = find_converter()
    if not conv:
        return False
    name, path = conv
    if name == "AutoCAD":
        return _acad_saveas(src, dst)
    if name == "ODAFileConverter":
        indir = tempfile.mkdtemp()
        outdir = tempfile.mkdtemp()
        shutil.copy(src, indir)
        # ODAFileConverter <in> <out> <version> <type:DWG/DXF> <recursive:0/1>
        subprocess.run([path, indir, outdir, "ACAD2010", "DXF", "0"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for f in os.listdir(outdir):
            if f.lower().endswith(".dxf"):
                shutil.copy(os.path.join(outdir, f), dst)
                return True
    return False


def dxf_to_dwg(src, dst):
    """把 DXF 转成 DWG，成功返回 True。"""
    conv = find_converter()
    if not conv:
        return False
    name, path = conv
    if name == "AutoCAD":
        return _acad_saveas(src, dst)
    if name == "ODAFileConverter":
        indir = tempfile.mkdtemp()
        outdir = tempfile.mkdtemp()
        shutil.copy(src, indir)
        subprocess.run([path, indir, outdir, "ACAD2010", "DWG", "0"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for f in os.listdir(outdir):
            if f.lower().endswith(".dwg"):
                shutil.copy(os.path.join(outdir, f), dst)
                return True
    return False
