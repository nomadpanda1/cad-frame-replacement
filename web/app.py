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
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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


def _render_png(dxf_path, png_path, dpi=130):
    """把 DXF 渲染成比例正确的 PNG；失败返回 False（不影响主流程）。"""
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        try:
            ext = ezdxf.bbox.extents(msp)
            if ext.has_data:
                w, h = ext.size.x, ext.size.y
            else:
                w, h = 420.0, 297.0
        except Exception:
            w, h = 420.0, 297.0
        longest = max(w, h) or 1.0
        scale = 12.0 / longest
        figsize = (max(w * scale, 0.5), max(h * scale, 0.5))
        bg = "#1a2029"  # color 7 (white) lines visible on dark background
        fig = plt.figure(figsize=figsize, facecolor=bg)
        ax = fig.add_axes([0, 0, 1, 1], facecolor=bg)
        ctx = RenderContext(doc)
        ctx.set_current_layout(msp)
        Frontend(ctx, MatplotlibBackend(ax)).draw_layout(msp, finalize=True)
        ax.set_axis_off()
        fig.savefig(png_path, dpi=dpi, facecolor=bg, edgecolor="none")
        plt.close(fig)
        return True
    except Exception as e:  # 预览非关键
        print("[render-warn]", e)
        return False


def _residual_lines(dxf_path):
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        return sum(
            1 for e in msp
            if e.dxftype() in ("LINE", "LWPOLYLINE") and (e.dxf.layer or "") == "图框"
        )
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

        # 2) 选模板
        tpl = DEFAULT_TEMPLATE if template in (None, "", "auto") else TEMPLATE_MAP.get(template, DEFAULT_TEMPLATE)

        # 3) 调 run_skill 置换
        cmd = [PY, "run_skill.py", "--template", tpl,
               "--out", job_dir, "--mode", "auto", "--fit", fit, dxf_in]
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
        if res.returncode != 0:
            raise HTTPException(500, "置换失败:\n" + (res.stderr or res.stdout)[-2000:])

        hh = _hh_output(job_dir, base)
        if not hh:
            raise HTTPException(500, "未生成置换结果(_HH.dxf)")

        # 4) 预览
        before_png = os.path.join(job_dir, base + "_before.png")
        after_png = os.path.join(job_dir, base + "_after.png")
        _render_png(dxf_in, before_png)
        _render_png(hh, after_png)

        # 5) 可选导出 DWG
        dwg_out = None
        if export_dwg:
            from converter import dxf_to_dwg
            dwg_out = dxf_to_dwg(hh, os.path.splitext(hh)[0] + ".dwg")

        # 6) 诊断
        try:
            rep = json.load(open(os.path.join(job_dir, "run_report.json"), encoding="utf-8"))
            diag = rep.get("files", [{}])[0] if rep.get("files") else {}
        except Exception:
            diag = {}
        diag["residual_lines_图框层"] = _residual_lines(hh)

        files = {"dxf": "/api/download/%s/%s" % (job_id, os.path.basename(hh))}
        if dwg_out:
            files["dwg"] = "/api/download/%s/%s" % (job_id, os.path.basename(dwg_out))
        preview = {}
        if os.path.exists(before_png):
            preview["before"] = "/api/download/%s/%s" % (job_id, os.path.basename(before_png))
        if os.path.exists(after_png):
            preview["after"] = "/api/download/%s/%s" % (job_id, os.path.basename(after_png))

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
