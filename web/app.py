# -*- coding: utf-8 -*-
"""CAD 图框批量置换 · Web 服务（FastAPI）。

直接复用仓库根的 run_skill.py 置换管线与 lib/ 逻辑：
  - DXF：直接走 ezdxf 管线
  - DWG：Linux 无头环境下先经 converter(LibreDWG/ODA) 转 DXF，再走同一条管线

端点：
  GET  /                      前端页面
  GET  /api/templates         可用模板列表(auto + A0~A4/A4V)
  POST /api/process           上传 DXF/DWG -> 置换 -> 返回下载+预览
  GET  /api/download/<job>/<fn>  取结果/预览文件
"""
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import ezdxf
from ezdxf.addons.drawing import Frontend
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.addons.drawing.properties import RenderContext
from ezdxf.addons.drawing import layout as layout_mod

# ---------------------------------------------------------------------------
# CJK 字体注册：容器无头环境只有 Noto Sans CJK（TTC），但 ezdxf 的 FontManager
# 缓存是在镜像构建时生成的，TTC 未被收录，导致中文标题栏渲染为 □□□□。
# 这里在进程启动时把 TTC 注册进 ezdxf 字体缓存，并把回退字体与常见中文字体
# 族名（宋体/黑体/仿宋/楷体…）指向它，确保预览里的汉字可正确绘制。
# ---------------------------------------------------------------------------
# 注册成功后保存 TTC 文件名（不含路径），供 _render_svg 强制套用到所有文字样式。
_CJK_FONT_FILE = None


def _register_cjk_font():
    global _CJK_FONT_FILE
    try:
        import ezdxf.fonts.fonts as _ezfonts
        from ezdxf.fonts import font_manager as _fmmod
        from pathlib import Path as _Path
        import matplotlib.font_manager as _mfm

        # ezdxf 1.4.x：FontManager 单例在 ezdxf.fonts.fonts.font_manager；
        # get_ttf_font_face 则在模块 ezdxf.fonts.font_manager 上。二者易混，注意区分。
        _fmgr = _ezfonts.font_manager

        cjk_file = None
        # 优先从 matplotlib 已知字体里挑 Noto CJK Regular（避开 Bold：
        # 之前误注册 NotoSansCJK-Bold.ttc 导致预览中文偏粗、观感明显变差）
        for _fp in _mfm.fontManager.ttflist:
            if _fp.name == "Noto Sans CJK SC" and "CJK" in _fp.fname and "Bold" not in _fp.fname:
                cjk_file = _Path(_fp.fname)
                break
        # 兜底：只在没找到 Regular 时退而求其次用任意 Noto CJK SC
        if cjk_file is None:
            for _fp in _mfm.fontManager.ttflist:
                if _fp.name == "Noto Sans CJK SC" and "CJK" in _fp.fname:
                    cjk_file = _Path(_fp.fname)
                    break
        # 兜底：直接在字体目录里找 Regular 文件
        if cjk_file is None:
            for _cand in (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            ):
                if os.path.exists(_cand):
                    cjk_file = _Path(_cand)
                    break
        if cjk_file is None:
            print("[font-warn] 未找到 Noto CJK 字体文件，中文预览可能缺字")
            return

        # 把 TTC/OTF 注册进 ezdxf 字体缓存（键 = 小写文件名）
        _ff = _fmmod.get_ttf_font_face(cjk_file)
        _fmgr._font_cache.add_entry(cjk_file, _ff)
        # 回退字体必须 = 缓存键（小写文件名），否则 has_font 永远 False
        _fmgr._fallback_font_name = cjk_file.name.lower()
        # 常见中文字体族名 / 文件名 -> 该 TTC 条目
        # （add_synonyms 内部 reverse 会把键翻转为族名；同时把 simhei.ttf、
        #  txt/txt.shx 等真实用到的字体名也直接指向 CJK，确保万无一失）
        _fmgr.add_synonyms({
            "宋体": cjk_file.name,
            "SimSun": cjk_file.name,
            "黑体": cjk_file.name,
            "SimHei": cjk_file.name,
            "仿宋": cjk_file.name,
            "FangSong": cjk_file.name,
            "楷体": cjk_file.name,
            "KaiTi": cjk_file.name,
            "微软雅黑": cjk_file.name,
            "Microsoft YaHei": cjk_file.name,
            "simhei.ttf": cjk_file.name,
            "simsun.ttf": cjk_file.name,
            "txt": cjk_file.name,
            "txt.shx": cjk_file.name,
        })
        # matplotlib 侧：把 TTC 加入其字体列表，避免它自己回退到缺 CJK 的默认字体
        try:
            _mfm.fontManager.addfont(str(cjk_file))
        except Exception as _e:
            print("[font-warn] matplotlib addfont 失败:", _e)
        _CJK_FONT_FILE = cjk_file.name
        print("[font-ok] 已注册 CJK 字体:", cjk_file.name)
    except Exception as _e:
        print("[font-warn] CJK 字体注册异常:", _e)


_register_cjk_font()

# ---------------------------------------------------------------------------
# GBK 乱码修复：LibreDWG 的 DWG->DXF 导出器把 GBK(ANSI_936) 中文标题文字按字节
# 写成 surrogate-escape 残体（每个原字节 b -> U+DC00+b），部分 2 字节序列还会
# 残合成真实 Unicode 字符。这会导致预览标题栏显示 □□□□（tofu）。这里在渲染前
# 把残体还原回原始字节流并用 GBK/GB18030 重新解码，恢复中文。
# 验证：website_output.dxf 15/15 标题栏字段（名/号/比例/阶段/材料/重量/日期/
# 幅/设计/对/审核/批/会 + 项目名“东方宏·钻机电控”）均可恢复。
# ---------------------------------------------------------------------------
def _decode_strict(raw):
    for _enc in ("gb18030", "gbk"):
        try:
            return raw.decode(_enc)
        except Exception:
            continue
    return None


def _repair_text(s):
    if not s:
        return None
    _units = [ord(c) for c in s]
    if not any(0xDC00 <= _u <= 0xDFFF for _u in _units):
        return None
    _cands = []
    # A: 仅 lone-surrogate 字节（最干净）
    _cands.append(bytes(_u & 0xFF for _u in _units if 0xDC00 <= _u <= 0xDFFF))
    # C: ASCII->1 字节, lone surrogate->1 字节, 残合真实字符->2 字节
    _rc = bytearray()
    for _u in _units:
        if _u < 0x80 or 0xDC00 <= _u <= 0xDFFF:
            _rc.append(_u & 0xFF)
        else:
            _rc += _u.to_bytes(2, "little")
    _cands.append(bytes(_rc))
    # B: 整体 utf-16-le 重编码（含 lone surrogate 时会抛错，忽略）
    try:
        _cands.append(s.encode("utf-16-le"))
    except Exception:
        pass
    _best = None
    for _raw in _cands:
        if not _raw:
            continue
        _txt = _decode_strict(_raw)
        if _txt is None:
            try:
                _txt = _raw.decode("gb18030", "ignore")
            except Exception:
                continue
        _cjk = sum(1 for _c in _txt if 0x4E00 <= ord(_c) <= 0x9FFF)
        if "\ufffd" in _txt:
            _cjk -= 5
        if _best is None or _cjk > _best[0]:
            _best = (_cjk, _txt)
    return _best[1] if _best else None


def _repair_dxf_text(path):
    """读取 DXF，修复其中 TEXT/MTEXT/ATTRIB 的 GBK 乱码并写回；返回修复条数。"""
    try:
        _doc = ezdxf.readfile(path)
    except Exception as _e:
        print("[gbk-repair-warn] readfile 失败:", _e)
        return 0
    _fixed = 0
    _layouts = [_doc.modelspace()] + list(_doc.blocks)
    for _layout in _layouts:
        for _e in _layout:
            if _e.dxftype() == "TEXT":
                _t = _e.dxf.text
            elif _e.dxftype() == "MTEXT":
                _t = _e.text
            elif _e.dxftype() == "ATTRIB":
                _t = _e.dxf.text
            else:
                continue
            if _t and any(0xDC00 <= ord(_c) <= 0xDFFF for _c in _t):
                _rec = _repair_text(_t)
                if _rec is not None:
                    if _e.dxftype() == "MTEXT":
                        _e.text = _rec
                    else:
                        _e.dxf.text = _rec
                    _fixed += 1
    if _fixed:
        try:
            _doc.saveas(path)
            print("[gbk-repair] 修复 %d 处中文乱码: %s" % (_fixed, path))
        except Exception as _e:
            print("[gbk-repair-warn] saveas 失败:", _e)
    return _fixed


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)  # cad-frame-replacement/
TEMPLATES_DIR = os.path.join(REPO_ROOT, "templates")
JOBS_ROOT = os.path.join(tempfile.gettempdir(), "cadframe_jobs")
os.makedirs(JOBS_ROOT, exist_ok=True)

# 调起置换管线用的解释器（容器内为 python3；本地测试可设 CAD_PY 指向带 ezdxf 的解释器）
PY = os.environ.get("CAD_PY") or os.environ.get("PYTHON") or "python3"
RUN_SKILL = os.path.join(REPO_ROOT, "run_skill.py")

TEMPLATE_SIZES = ["A0", "A1", "A2", "A3", "A4", "A4V"]
TEMPLATE_MAP = {s: os.path.join(TEMPLATES_DIR, "HH_FRAME_%s.dxf" % s) for s in TEMPLATE_SIZES}
DEFAULT_TEMPLATE = TEMPLATE_MAP["A4"]  # auto 模式下传 A4，run_skill 会按幅面重定向

app = FastAPI(title="CAD 图框置换", version="0.1.0")


# ---------- 工具 ----------
def _safe_name(name):
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9_.一-鿿\-]", "_", name)
    return name or "input"


def _crisp_svg(svg):
    """把 ezdxf 按 viewBox 用户单位发出的描边宽度，改成「分辨率无关」的像素宽度。

    ezdxf 的 SVGBackend 默认把 stroke-width 写成 viewBox 用户单位（如 179~2505，
    对应 77 万单位的视口）。在网页 2 栏 ~460px 的窄列里，这些宽度被缩到 0.1~0.7px，
    细线直接变成亚像素、发虚发灰——这正是「预览效果差」的根因。

    这里把每个线宽类（.C1~.C6）改成固定像素宽度（最细 ~1.1px、最粗 ~2.8px），
    并加 vector-effect:non-scaling-stroke，使线宽不再随显示尺寸伸缩，
    在任意栏宽/缩放下都清晰锐利，观感稳定且明显优于原 report 的细线。
    """
    import re as _re
    nums = _re.findall(r'stroke-width:\s*([0-9.]+)', svg)
    if not nums:
        return svg
    vals = sorted(set(float(n) for n in nums))
    wmin, wmax = vals[0], vals[-1]

    def mapw(w):
        if wmax == wmin:
            return 1.4
        t = (float(w) - wmin) / (wmax - wmin)
        return round(1.1 + t * (2.8 - 1.1), 2)

    def repl(m):
        block = m.group(0)
        block = _re.sub(
            r'stroke-width:\s*([0-9.]+)',
            lambda mm: 'stroke-width: %spx' % mapw(mm.group(1)),
            block,
        )
        if 'vector-effect' not in block:
            block = block.replace('{', '{ vector-effect: non-scaling-stroke;', 1)
        return block

    return _re.sub(r'<style>\.C[0-9]+\s*\{[^}]*\}</style>', repl, svg)


def _ensure_utf8_copy(dxf_path):
    """确保 dxf_path 可被 ezdxf 以 UTF-8 读入（预览渲染专用）。

    run_skill 输出的 DXF 是 GBK(ANSI_936) 编码（AutoCAD 兼容方案，已验证可
    正常打开）。ezdxf 读 R2007+ 时按 UTF-8+surrogateescape 解码，GBK 字节会被
    误读成 surrogate 残体；且 0xEB 0xBB 0xAA 这类「恰成合法 UTF-8 序列」的字节
    组合会被吞并成一个私有区字符，导致预览中文丢字（如 东方宏华 → 东方宏）。
    这里对非 UTF-8 文件做无损转码：GB18030 解码 → UTF-8 写临时文件，供预览渲染
    使用；下载文件保持 GBK 原样，不改动用户拿到的结果。
    """
    try:
        with open(dxf_path, "rb") as f:
            raw = f.read()
        raw.decode("utf-8")
        return dxf_path  # 已是 UTF-8，直接读原文件
    except UnicodeDecodeError:
        txt = raw.decode("gb18030", errors="replace")
        tmp = os.path.join(os.path.dirname(os.path.abspath(dxf_path)),
                           "._preview_" + os.path.basename(dxf_path) + ".utf8")
        with open(tmp, "w", encoding="utf-8", errors="replace") as f:
            f.write(txt)
        return tmp


def _render_svg(dxf_path, svg_path):
    """把 DXF 渲染成矢量 SVG（文字转 path，中文不依赖浏览器字体）。

    与 render_exe_test.py 同一口径：SVGBackend 默认把文字描成填充路径，
    浏览器端无需安装任何中文字体即可正确显示标题栏；矢量线条也比 PNG 更清晰，
    与 test_other.html / exe_test.html 的「之前」预览观感一致。
    """
    src = _ensure_utf8_copy(dxf_path)
    try:
        doc = ezdxf.readfile(src)
        # 预览专用：强制所有文字样式改用已注册的 CJK 字体，确保中文标题栏的
        # 字形能被正确取轮廓（文字→path）。不改用户数据，导出 DXF 保持原字体。
        if _CJK_FONT_FILE:
            try:
                for _st in doc.styles:
                    try:
                        _st.dxf.font = _CJK_FONT_FILE
                    except Exception:
                        pass
            except Exception:
                pass
        layout = doc.modelspace()
        backend = SVGBackend()
        ctx = RenderContext(doc)
        Frontend(ctx, backend).draw_layout(layout)
        # 页面尺寸：模型空间没有真实的纸面页设置，
        # Page.from_dxf_layout(layout) 会返回默认的 US Letter 竖版
        # (215.9×279.4mm, viewBox 长宽比 0.77)，导致横版图纸（A4/A3 横放、
        # 占工程图纸绝大部分）被强行塞进竖版画布 → 上下大量留白、
        # 图纸缩成一窄条 → 网页 2 栏预览看上去「很乱」。
        # 改为按内容包围盒构建页面，让 SVG viewBox 长宽比与图纸一致，
        # 图纸自然填满画布，与 test_other.html 的 PNG 报告观感一致。
        page = None
        try:
            from ezdxf.bbox import extents as _bbox_extents
            _bb = _bbox_extents(layout)
            if _bb.has_data and _bb.size.x > 0 and _bb.size.y > 0:
                _w, _h = _bb.size.x, _bb.size.y
                # 防 LibreDWG 残留远端退化几何把 extents 撑爆：
                # 正常 CAD 图纸边长 < 5000mm (>5m 几乎都是退化实体)。
                if max(_w, _h) < 5000:
                    _m = max(_w, _h) * 0.02  # 2% 边距
                    page = layout_mod.Page(_w + _m, _h + _m, layout_mod.Units.mm)
        except Exception:
            page = None
        if page is None:
            try:
                page = layout_mod.Page.from_dxf_layout(layout)
            except Exception:
                page = layout_mod.Page(0, 0, layout_mod.Units.mm)
        svg = backend.get_string(page)
        # 去掉根 <svg> 的 width/height（单位可能是 mm），保留 viewBox，
        # 让前端 <img> 按 viewBox 纯 CSS 缩放，避免 mm 单位导致尺寸异常。
        m = re.search(r"<svg[^>]*>", svg)
        if m:
            tag = re.sub(r'\s+(width|height)="[^"]*"', "", m.group(0))
            svg = svg[:m.start()] + tag + svg[m.end():]
        # 统一注入深色背景矩形：插入到 <svg> 开标签之后（避免破坏 XML 结构）。
        # 判定是否有背景：以本渲染器专用的深色标记 fill="#212830" 为准。
        if 'fill="#212830"' not in svg[:5000]:
            m = re.search(r"<svg[^>]*>", svg)
            if m:
                pos = m.end()
                svg = svg[:pos] + '\n<rect x="0" y="0" width="100%" height="100%" fill="#212830"/>' + svg[pos:]
            else:
                svg = svg.replace(">", '>\n<rect x="0" y="0" width="100%" height="100%" fill="#212830"/>', 1)
        svg = _crisp_svg(svg)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
        return True
    except Exception as e:  # 预览非关键
        print("[render-warn]", e)
        return False
    finally:
        if src != dxf_path and os.path.exists(src):
            try:
                os.remove(src)
            except Exception:
                pass


def _residual_lines(dxf_path):
    try:
        src = _ensure_utf8_copy(dxf_path)
        try:
            doc = ezdxf.readfile(src)
            msp = doc.modelspace()
            return sum(
                1 for e in msp
                if e.dxftype() in ("LINE", "LWPOLYLINE") and (e.dxf.layer or "") == "图框"
            )
        finally:
            if src != dxf_path and os.path.exists(src):
                try:
                    os.remove(src)
                except Exception:
                    pass
    except Exception:
        return -1


def _hh_output(job_dir, base):
    cand = os.path.join(job_dir, "%s_HH.dxf" % base)
    if os.path.exists(cand):
        return cand
    # 兜底：找第一个 *_HH.dxf
    for f in os.listdir(job_dir):
        if f.endswith("_HH.dxf"):
            return os.path.join(job_dir, f)
    return None


# ---------- 路由 ----------
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/templates")
def templates():
    out = [{"id": "auto", "label": "自动（按幅面检测）"}]
    for s in TEMPLATE_SIZES:
        out.append({"id": s, "label": "HH_FRAME_%s" % s})
    return {"templates": out}


@app.post("/api/process")
def process(
    file: UploadFile = File(...),
    template: str = Form("auto"),
    template_file: UploadFile = File(None),
    fit: str = Form("max"),
    export_dwg: bool = Form(False),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".dxf", ".dwg"):
        raise HTTPException(400, "仅支持 .dxf / .dwg 文件")

    job_id = uuid.uuid4().hex
    job_dir = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    safe = _safe_name(file.filename)
    in_path = os.path.join(job_dir, safe)
    with open(in_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    is_dwg = ext == ".dwg"
    try:
        # 1) DWG -> DXF
        if is_dwg:
            from converter import dwg_to_dxf
            dxf_in = os.path.join(job_dir, os.path.splitext(safe)[0] + ".dxf")
            dxf_in = dwg_to_dxf(in_path, dxf_in)
        else:
            dxf_in = in_path

        base = os.path.splitext(os.path.basename(dxf_in))[0]

        # 2) 选模板：优先用用户上传的自定义模板（.dxf），否则按内置幅面选择
        tpl = None
        if template_file is not None and (template_file.filename or "").strip():
            tpl_ext = os.path.splitext(template_file.filename or "")[1].lower()
            if tpl_ext not in (".dxf",):
                raise HTTPException(400, "自定义模板仅支持 .dxf（.dwg 模板请先在 AutoCAD 中另存为 DXF）")
            tpl_name = _safe_name(template_file.filename)
            tpl_path = os.path.join(job_dir, tpl_name)
            with open(tpl_path, "wb") as f:
                shutil.copyfileobj(template_file.file, f)
            tpl = tpl_path
        if tpl is None:
            tpl = DEFAULT_TEMPLATE if template in (None, "", "auto") else TEMPLATE_MAP.get(template, DEFAULT_TEMPLATE)

        # 3) 调 run_skill 置换
        cmd = [PY, "run_skill.py", "--template", tpl,
               "--out", job_dir, "--mode", "auto", "--fit", fit, dxf_in]
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
        if res.returncode != 0:
            # 仅失败时保留 run_skill 输出，便于排查（成功任务不落盘多余日志）
            try:
                with open(os.path.join(job_dir, "run_skill.err.log"), "w", encoding="utf-8") as _lf:
                    _lf.write((res.stderr or res.stdout or "")[-4000:])
            except Exception:
                pass
            raise HTTPException(500, "置换失败:\n" + (res.stderr or res.stdout)[-2000:])

        hh = _hh_output(job_dir, base)
        if not hh:
            try:
                with open(os.path.join(job_dir, "run_skill.err.log"), "w", encoding="utf-8") as _lf:
                    _lf.write("STDOUT:\n" + (res.stdout or "") + "\nSTDERR:\n" + (res.stderr or ""))
            except Exception:
                pass
            raise HTTPException(500, "未生成置换结果(_HH.dxf)")

        # 3.4) 修复 LibreDWG 把 GBK 中文标题写成 surrogate 残体导致的预览 tofu。
        #      只修输入（dxf_in，仅影响 before 预览）；**绝不修 hh 输出**——
        #      run_skill 的 _atomic_save_doc 已把输出写成 AutoCAD 可打开的
        #      GBK(ANSI_936) 编码，再经 ezdxf 读→saveas 会把 GBK 字节误读成
        #      surrogate 残体（EB BB AA 等恰成合法 UTF-8 的字节组合还会吞字），
        #      重写后变成 UTF-8+GBK 混编，AutoCAD 直接拒读（错误码 53）。
        try:
            _repair_dxf_text(dxf_in)
        except Exception as _e:
            print("[gbk-repair-warn] dxf_in:", _e)

        # 4) 预览：矢量 SVG（文字转 path，中文不依赖浏览器字体，线条更清晰）
        before_svg = os.path.join(job_dir, base + "_before.svg")
        after_svg = os.path.join(job_dir, base + "_after.svg")
        _render_svg(dxf_in, before_svg)
        _render_svg(hh, after_svg)

        # 5) DWG 导出：ODA 优先（可靠，标准 ACAD2018 DWG、中文正常）；
        #    LibreDWG dxf2dwg 兜底（对 R2007+/UTF-8 输入会生成损坏 DWG）。
        #    未装转换器时静默跳过，仅返回 DXF。
        dwg_out = None
        if export_dwg:
            try:
                from converter import dxf_to_dwg
                dwg_out = os.path.join(job_dir, base + "_HH.dwg")
                dwg_out = dxf_to_dwg(hh, dwg_out)
                print("[dwg-export] ok:", dwg_out)
            except Exception as _e:
                print("[dwg-export-warn]", _e)
                dwg_out = None

        # 6) 诊断
        try:
            rep = json.load(open(os.path.join(job_dir, "run_report.json"), encoding="utf-8"))
            diag = rep.get("files", [{}])[0] if rep.get("files") else {}
        except Exception:
            diag = {}
        diag["residual_lines_图框层"] = _residual_lines(hh)
        diag["dwg_export"] = "ok" if dwg_out else "skipped/unavailable"

        files = {"dxf": "/api/download/%s/%s" % (job_id, os.path.basename(hh))}
        if dwg_out:
            files["dwg"] = "/api/download/%s/%s" % (job_id, os.path.basename(dwg_out))
        preview = {}
        if os.path.exists(before_svg):
            preview["before"] = "/api/download/%s/%s" % (job_id, os.path.basename(before_svg))
        if os.path.exists(after_svg):
            preview["after"] = "/api/download/%s/%s" % (job_id, os.path.basename(after_svg))

        return {
            "ok": True,
            "job_id": job_id,
            "files": files,
            "preview": preview,
            "diagnostics": diag,
        }
    except HTTPException:
        raise
    except Exception as e:
        # 容器日志保留完整堆栈，便于排查
        traceback.print_exc()
        raise HTTPException(500, "处理异常: %s" % e)


@app.get("/api/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    job_dir = os.path.join(JOBS_ROOT, job_id)
    # 防目录穿越
    target = os.path.abspath(os.path.join(job_dir, os.path.basename(filename)))
    if not target.startswith(os.path.abspath(job_dir)) or not os.path.exists(target):
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=filename)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
