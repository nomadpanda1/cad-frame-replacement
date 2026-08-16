#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a self-contained gallery of ALL test-drawing renders across cases.

Images are downscaled to thumbnails and base64-inlined so the single HTML file
renders standalone on GitHub / offline (no local server, no relative-path 404s).
"""
import os, re, html, io, base64

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

ROOT = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(ROOT, "cases")
MAX_DIM = 760  # longest side; renders are ~878px, downscale a bit to shrink payload

SUFFIX_MAP = [
    (r"^(before|orig|original|input|old|src)$", "原图", 0),
    (r"^template$", "模板", 1),
    (r"^(after|HH|new|result|fixed|out)$", "换框后", 2),
]

def classify(name):
    base = name[:-4] if name.lower().endswith(".png") else name
    if "_" in base:
        stem, tail = base.rsplit("_", 1)
        for pat, label, w in SUFFIX_MAP:
            if re.match(pat, tail, re.I):
                return stem, label, w
    return base, "渲染", 3

def thumb_b64(path):
    if not HAVE_PIL:
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    im = Image.open(path).convert("RGBA")
    # composite onto white so JPEG (no alpha) looks clean for both light/dark renders
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    w, h = im.size
    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / max(w, h)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

def main():
    cases = []
    for c in sorted(os.listdir(CASES_DIR)):
        cdir = os.path.join(CASES_DIR, c)
        if not os.path.isdir(cdir) or not re.match(r"^\d+_", c):
            continue
        # 若同时存在 outputs 与 outputs_v2，优先用 outputs_v2（最新管线输出），避免重复
        out_dirs = []
        for sub in sorted(os.listdir(cdir)):
            sd = os.path.join(cdir, sub)
            if os.path.isdir(sd) and re.match(r"^outputs", sub):
                out_dirs.append(sd)
        if not out_dirs:
            continue
        preferred = [d for d in out_dirs if os.path.basename(d) == "outputs_v2"]
        chosen = preferred[0] if preferred else out_dirs[0]
        pngs = []
        for fn in sorted(os.listdir(chosen)):
            if fn.lower().endswith(".png"):
                pngs.append((chosen, fn))
        if not pngs:
            continue
        groups = {}
        for sd, fn in pngs:
            stem, label, w = classify(fn)
            groups.setdefault(stem, []).append((w, label, os.path.join(sd, fn)))
        cases.append((c, groups))

    parts = []
    parts.append("""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>CAD 换框 · 全部测试图集</title>
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
  header{padding:18px 22px;border-bottom:1px solid #2a2f3a;position:sticky;top:0;background:#0f1115;z-index:5}
  header h1{margin:0;font-size:20px}
  header p{margin:6px 0 0;color:#9aa4b2;font-size:13px}
  .toc{display:flex;flex-wrap:wrap;gap:8px;padding:14px 22px;border-bottom:1px solid #1c2129}
  .toc a{color:#7db3ff;text-decoration:none;font-size:13px;padding:4px 10px;border:1px solid #243042;border-radius:20px}
  .toc a:hover{background:#16202c}
  .case{padding:18px 22px;border-bottom:1px solid #1c2129}
  .case h2{font-size:16px;margin:0 0 12px;color:#ffd479}
  .draw{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:18px}
  .card{background:#161b22;border:1px solid #232b36;border-radius:8px;padding:8px;width:300px}
  .card .lbl{font-size:12px;color:#9aa4b2;margin-bottom:6px;display:flex;justify-content:space-between}
  .card .tag{color:#ffd479;font-weight:600}
  .card img{width:100%;height:auto;display:block;border-radius:4px;background:#fff}
  .nores{color:#9aa4b2;font-style:italic}
</style></head><body>""")
    n_img = sum(len(v) for _, g in cases for v in g.values())
    parts.append('<header><h1>CAD 图框批量置换 · 全部测试图集</h1>'
                 '<p>共 %d 个案例、%d 张渲染（原图 / 模板 / 换框后 对照）。自包含离线版，图片已内嵌（JPEG 缩略图）。</p></header>'
                 % (len(cases), n_img))
    parts.append('<nav class="toc">')
    for c, _ in cases:
        parts.append('<a href="#%s">%s</a>' % (c, html.escape(c)))
    parts.append('</nav>')
    for c, groups in cases:
        parts.append('<section class="case" id="%s"><h2>%s</h2>' % (c, html.escape(c)))
        if not groups:
            parts.append('<p class="nores">（无渲染图）</p>')
        for stem in sorted(groups.keys()):
            items = sorted(groups[stem])
            parts.append('<div class="draw">')
            for w, label, fpath in items:
                data = thumb_b64(fpath)
                parts.append('<div class="card"><div class="lbl"><span>%s</span><span class="tag">%s</span></div>'
                             '<img loading="lazy" src="%s" alt="%s"></div>'
                             % (html.escape(stem), html.escape(label), data, html.escape(stem)))
            parts.append('</div>')
        parts.append('</section>')
    parts.append('</body></html>')
    out = os.path.join(ROOT, "gallery.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    sz = os.path.getsize(out) / 1048576
    print("wrote", out, "cases:", len(cases), "images:", n_img, "size_MB=%.1f" % sz)

if __name__ == "__main__":
    main()
