# -*- coding: utf-8 -*-
"""生成 cases/report.html：聚合两案例的 before/模板/after 对比图。
数据驱动；图片相对路径引用 cases/ 下的 outputs 目录。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 案例一：SolidWorks 零件/装配图（9 张，纯 ezdxf 策略一）
SW = [
    ("从法兰(2)", "A4", "HH_FRAME_A4", "提取：SCALE 2:1 / MATERIAL PLA / TITLE “从动轮法兰”", "回填：TITLE, SCALE, MATERIAL"),
    ("前叉(1)", "A4", "HH_FRAME_A4", "提取：MATERIAL ABS / TITLE 前叉", "回填：TITLE, MATERIAL"),
    ("圆柱齿轮13×1(2)", "A4", "HH_FRAME_A4", "提取：SCALE 2:1 / MATERIAL 亚克力 / TITLE “圆柱齿轮”", "回填：TITLE, SCALE, MATERIAL"),
    ("圆柱齿轮65×1(1)", "A4", "HH_FRAME_A4", "提取：SCALE 1:1 / MATERIAL 亚克力 / TITLE “圆柱齿轮”", "回填：TITLE, SCALE, MATERIAL"),
    ("法兰(2)", "A4", "HH_FRAME_A4", "提取：VERSION 0.001 / SCALE 2:1 / MATERIAL PLA / TITLE 法兰", "回填：TITLE, SCALE, MATERIAL, VERSION"),
    ("等轴测图(1)", "A3", "HH_FRAME_A3", "提取：SCALE 1:5 / WEIGHT 0.681", "回填：SCALE, WEIGHT"),
    ("装配体图纸(1)", "A3", "HH_FRAME_A3", "提取：SCALE 1:5 / DWG_NO 1-1", "回填：DWG_NO, SCALE"),
    ("装配体爆炸图1(1)", "A3", "HH_FRAME_A3", "提取：SCALE 1:10 / DWG_NO 1-2 / WEIGHT 0.681 / TITLE 爆炸图", "回填：TITLE, DWG_NO, SCALE, WEIGHT"),
    ("龙门架", "A4", "HH_FRAME_A4", "提取：MATERIAL ABS / TITLE 龙门架", "回填：TITLE, MATERIAL"),
]

# 案例三：储能(ESS) CAD 成果包（4 张，纯 ezdxf 策略一）
ESS = [
    ("16MW_32MWh_一次设备表", "A1", "HH_FRAME_A1",
     "提取：TITLE 16MW/32MWh 储能电站 一次设备表 / DWG_NO BESS-LST-001 / SCALE NTS / STAGE 学习/概念设计",
     "回填：TITLE, DWG_NO, SCALE, STAGE"),
    ("16MW_32MWh_二次系统信号表", "A1", "HH_FRAME_A1",
     "提取：TITLE 16MW/32MWh 储能电站 二次系统信号表 / DWG_NO BESS-LST-003 / SCALE NTS / STAGE 学习/概念设计",
     "回填：TITLE, DWG_NO, SCALE, STAGE"),
    ("16MW_32MWh_二次系统柜体表", "A1", "HH_FRAME_A1",
     "提取：TITLE 16MW/32MWh 储能电站 二次系统柜体表 / DWG_NO BESS-LST-002 / SCALE NTS / STAGE 学习/概念设计",
     "回填：TITLE, DWG_NO, SCALE, STAGE"),
    ("16MW_32MWh_储能系统简化主接线图", "A1", "HH_FRAME_A1",
     "提取：TITLE 16MW/32MWh 储能电站 简化主接线图 / DWG_NO BESS-SLD-001 / SCALE NTS / STAGE 学习/概念设计",
     "回填：TITLE, DWG_NO, SCALE, STAGE"),
]

# 案例五：标准设计院图纸（92DZ1 消火栓泵，多图框 PUB_TITLE 层，策略二）
STANDARD = [
    ("92DZ1 单电源单台消火栓泵", "4×A3", "HH_FRAME_A3×4",
     "检测：4 个闭合 LWPOLYLINE 外框位于 PUB_TITLE 层，典型设计院打散图框，无 INSERT 块式标题栏",
     "处理：块式检测回退到线框检测 → 逐框删除旧外框+标题栏 → 插入 HH_FRAME_A3(fit=max) → 回填图名/图号/阶段/比例等字段 ✅"),
]

# 案例四：装配体图纸（无图框/无标题栏，AutoCAD COM 转 DXF + 清标题栏占位，策略二）
ASM = [
    ("装配体图纸(1)", "A3", "HH_FRAME_A3",
     "提取：原图无 TEXT 标题栏、无外框矩形（仅零散零件几何 + 右下角零散标注）",
     "回填：无（字段留空，清标题栏占位 63 个零散标注后插入公司 A3 图框，14 字段均为可编辑空占位）"),
]

# 案例六：合成异常样本（程序化生成，可控可复现）
SYNTH = [
    ("06a 多图框混排", "A1", "HH_FRAME_A1",
     "检测：4 个闭合矩形（外 A1 + 内嵌 A3/A4/A1 小图框）",
     "局限：当前按整图幅插一张图框，不逐图框(视口)替换 —— 已知局限，待增强"),
    ("06b 嵌套块标题栏", "A4", "HH_FRAME_A4",
     "检测：learn_template 正确穿透到含 ATTDEF 的子块 TB_FIELDS，识别 9 字段 ✅",
     "结论：嵌套块标题栏可正常识别并替换"),
    ("06c 缺字体 SHX", "A4", "HH_FRAME_A4",
     "检测：引用不存在字体 hzdx_ghost.shx，文字串照常抽取、渲染不崩溃 ✅",
     "结论：缺字体不影响处理（matplotlib 回退默认字体）"),
    ("06d 会签栏差异", "A4", "HH_FRAME_A4",
     "检测：标题栏多出'会签'列，图名/图号/比例/阶段 仍正确抽取 ✅",
     "结论：会签栏差异不影响字段按标签映射"),
]

# 案例七：多图框逐框替换（本开发项成果，程序化生成可控样本）
MULTI = [
    ("07a 平铺多框（含整图纸框）", "A1", "HH_FRAME_A1×3",
     "检测：识别整图纸框(0,0)-(841,594)为纸边、非替换目标；3 个子图框为替换目标，逐框抽取 图名/图号/比例/阶段 并回填 ✅",
     "结论：每子框独立插入公司图框，纸边保留；删旧框线+旧标题栏(各 12 实体)，无重叠"),
    ("07b 并排多框（无整图纸框）", "A3×4", "HH_FRAME_A3×4",
     "检测：无单一整图纸框（CNG 真实场景简化版），4 个并排 A3 图框均为替换目标，逐框抽取+回填全部成功 ✅",
     "结论：并排多框逐框替换 ✅ —— 验证 detect_frames_hierarchical 的'无整图纸框'分支"),
]

# 案例八：真实多图框端到端验证（用真实 ESS 图纸拼多图框，内容 100% 真实）
REAL_MF = [
    ("08 真实多图框端到端", "4×A1", "HH_FRAME_A1×4",
     "检测：4 个真实图框（由 4 张真实 ESS 图纸——一次设备表/二次系统信号表/二次系统柜体表/简化主接线图——平移拼成 2×2 网格，内容 100% 真实，仅排布合成）；逐框抽取真实字段 图名/图号/比例/阶段 全部正确 ✅",
     "结论：真实标题栏结构的多图框逐框替换端到端验证通过；过程中发现并修复 extract_frame_fields 标题区越界泄漏 bug（已加回归测试）"),
]

CSS = """
body { font-family: "Microsoft YaHei","SimHei",sans-serif; background:#1e1e1e; color:#ddd; margin:40px; }
h1 { color:#fff; border-bottom:2px solid #4a9eff; padding-bottom:12px; }
h2 { color:#4a9eff; margin-top:40px; }
h3 { color:#9cdcfe; margin:24px 0 8px; }
.card { background:#252526; border:1px solid #3c3c3c; border-radius:8px; padding:16px; margin:14px 0; }
.tag { display:inline-block; background:#0e639c; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:6px; }
.warn { color:#ffcc6e; } .ok { color:#7ee787; }
table { border-collapse:collapse; width:100%; }
td { vertical-align:top; padding:10px; border:1px solid #3c3c3c; }
img { max-width:100%; border:1px solid #444; display:block; }
.cap { color:#9cd; font-size:13px; line-height:1.7; }
a { color:#4a9eff; text-decoration:none; } a:hover { text-decoration:underline; }
"""

def sw_section():
    rows = []
    for name, size, tpl, ext, fill in SW:
        b = f"01_SW_parts/outputs/{name}_before.png"
        t = f"01_SW_parts/outputs/{name}_template.png"
        a = f"01_SW_parts/outputs/{name}_after.png"
        # 跳过不存在的图片
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            continue
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def cng_section():
    b = "02_CNG_electrical/outputs/CNG_电气系统图_before.png"
    t1 = "02_CNG_electrical/outputs/template_A3_WIDE.png"
    t2 = "02_CNG_electrical/outputs/template_A1.png"
    a = "02_CNG_electrical/outputs/CNG_电气系统图_after.png"
    frames = [
        ("图框 1", "A3_WIDE", "低压配电系统图二", "CNG-0501/17"),
        ("图框 2", "A3_WIDE", "低压配电系统图一", "CNG-0501/16"),
        ("图框 3", "A3_WIDE", "10kV主接线图", "CNG-0501/15"),
        ("图框 4", "A1", "平面布置图", "CNG-0501/14"),
    ]
    frows = "".join(
        f"<tr><td><b>{n}</b><br>{s}<br>{t}<br>{d}</td></tr>" for n, s, t, d in frames
    )
    return f"""
<div class="card">
  <p class="warn"><b>注意：</b>此 DWG 由 AutoCAD COM 直接处理原 DWG 生成，绕过了 ezdxf 对设计院加密实体的兼容性问题。请用 AutoCAD 2026 打开 <code>CNG_电气系统图_HH.dwg</code>。</p>
  <p class="ok"><b>已修复：</b>此前 AutoCAD 打开空白/报错"解密数据时出错"的问题已解决（策略二）。</p>
</div>
<h3>处理结果（4 个图框）</h3>
<table>{frows}</table>
<h3>生成前 / 公司模板 / 生成后</h3>
<p class="cap">效果图由 ezdxf 渲染，与 AutoCAD 打开 DWG 所见一致。</p>
<table><tr>
  <td width="45%"><b>生成前</b><br><img src="{b}"></td>
  <td width="10%"><b>模板</b><br>A3_WIDE<br><img src="{t1}"><br>A1<br><img src="{t2}"></td>
  <td width="45%"><b>生成后</b><br><img src="{a}"></td>
</tr></table>
"""


def ess_section():
    rows = []
    for name, size, tpl, ext, fill in ESS:
        b = f"03_ESS_cad/outputs/{name}_before.png"
        t = f"03_ESS_cad/outputs/{name}_template.png"
        a = f"03_ESS_cad/outputs/{name}_after.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            continue
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def asm_section():
    rows = []
    for name, size, tpl, ext, fill in ASM:
        b = f"04_assembly/outputs/{name}_before.png"
        t = f"04_assembly/outputs/{name}_template.png"
        a = f"04_assembly/outputs/{name}_after.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            continue
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def standard_section():
    rows = []
    for name, size, tpl, ext, fill in STANDARD:
        b = "05_standard_dwg/outputs/92DZ1_xiaohuobeng_before.png"
        t = "05_standard_dwg/outputs/92DZ1_xiaohuobeng_template.png"
        a = "05_standard_dwg/outputs/92DZ1_xiaohuobeng_HH.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            return ""
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap ok">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def synth_section():
    rows = []
    for name, size, tpl, ext, fill in SYNTH:
        pre = name.split()[0]  # 06a/06b/06c/06d
        b = f"06_synth/outputs/{pre}_before.png"
        a = f"06_synth/outputs/{pre}_after.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, a))):
            continue
        ok = "ok" if "✅" in ext else "warn"
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="50%"><b>生成前</b><br><img src="{b}"></td>
    <td width="50%"><b>生成后（插入公司图框）</b><br><br>（合成异常图的工具实际行为演示）<br><img src="{a}"></td>
  </tr></table>
  <p class="cap {ok}">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def multi_section():
    rows = []
    for name, size, tpl, ext, fill in MULTI:
        pre = name.split()[0]  # 07a / 07b
        b = f"07_multiframe/outputs/{pre}_before.png"
        t = f"07_multiframe/outputs/{pre}_template.png"
        a = f"07_multiframe/outputs/{pre}_HH.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            continue
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板（首帧所选）</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后（逐框插入公司图框）</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap ok">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def real_mf_section():
    rows = []
    for name, size, tpl, ext, fill in REAL_MF:
        b = "08_real_mf/outputs/08_real_multiframe_before.png"
        t = "08_real_mf/outputs/08_real_multiframe_template.png"
        a = "08_real_mf/outputs/08_real_multiframe_HH.png"
        if not (os.path.exists(os.path.join(HERE, b)) and
                os.path.exists(os.path.join(HERE, t)) and
                os.path.exists(os.path.join(HERE, a))):
            return ""
        rows.append(f"""
<div class="card">
  <h3>{name} <span class="tag">{size}</span><span class="tag">{tpl}</span></h3>
  <table><tr>
    <td width="33%"><b>生成前（4 张真实 ESS 图拼成多图框）</b><br><img src="{b}"></td>
    <td width="33%"><b>公司模板（首帧所选）</b><br><img src="{t}"></td>
    <td width="34%"><b>生成后（逐框插入公司图框）</b><br><img src="{a}"></td>
  </tr></table>
  <p class="cap ok">{ext}<br>{fill}</p>
</div>""")
    return "\n".join(rows)


def main():
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CAD 图框批量置换 — 效果对比报告</title>
<style>{CSS}</style>
</head>
<body>
<h1>CAD 图框批量置换 — 效果对比报告</h1>
<p>本页聚合八套案例的 <b>生成前 / 公司模板 / 生成后</b> 对比图。案例一为普通图纸（纯 ezdxf 离线，策略一）；案例二为设计院加密 DWG（AutoCAD COM 直接处理，策略二）；案例三为储能 ESS 成果包（纯 ezdxf，策略一）；案例四为无图框/无标题栏的装配体图纸（COM 转 DXF + 清标题栏占位，策略二）；<b>案例五</b>为标准设计院图纸（92DZ1 消火栓泵，2×2 多图框，图框位于 PUB_TITLE 层，策略二）；<b>案例六</b>为程序化生成的<b>异常场景合成样本</b>（多图框混排 / 嵌套块标题栏 / 缺字体 / 会签栏差异）；<b>案例七</b>为<b>多图框逐框替换</b>开发项成果（平铺多框含整图纸框 / 并排多框无整图纸框），验证"检测多图框 → 逐框插公司图框 → 逐框回填"；<b>案例八</b>为<b>真实多图框端到端验证</b>：用 4 张真实 ESS 图纸拼成 2×2 多图框。</p>

<h2>案例一：SolidWorks 导出零件图 / 装配图（9 张，策略一）</h2>
<p><span class="tag">9 张图纸</span><span class="tag">A3/A4</span><span class="tag">标准标题栏</span> 来源：SolidWorks 工程图导出的 DXF，图框为打散 LINE/LWPOLYLINE，标题栏为右下角 TEXT/MTEXT 网格。</p>
{sw_section()}

<h2>案例二：CNG 电气系统图（设计院图纸，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">4 个图框</span><span class="tag">A3_WIDE / A1</span><span class="tag">会签栏</span> 来源：设计院电气系统图，DWG 格式，modelspace 内 4 张大坐标图框（左侧 3 个 A3_WIDE、右侧 1 个 A1）。图纸含加密/代理实体，ezdxf 写回后 AutoCAD 无法打开，因此采用 AutoCAD COM 直接处理原 DWG。</p>
{cng_section()}

<h2>案例三：储能(ESS) CAD 成果包（4 张，策略一）</h2>
<p><span class="tag">4 张 DXF</span><span class="tag">A1 幅面</span><span class="tag">标题栏右下角小条</span> 来源：储能 CAD 成果包（一次设备表 / 二次系统信号表 / 二次系统柜体表 / 简化主接线图）。外框为单个闭合 LWPOLYLINE（≈A1），标题栏为右下角小条含 4 个字段，无日期/设计/审核等。走纯 ezdxf 策略一，字段自动提取回填。</p>
{ess_section()}

<h2>案例四：装配体图纸（无图框 / 无标题栏，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">A3 横放</span><span class="tag">无 TEXT 标题栏</span><span class="tag">无外框矩形</span> 来源：装配体图纸，二进制 DWG 无代理实体。AutoCAD COM 转 DXF 后，因原图无图框/标题栏，采用"清标题栏占位 + 插公司 A3 图框"：先删右下角 63 个零散标注，再插入 HH_FRAME_A3（14 字段均为可编辑空占位）。这是"无图框"异常场景的鲁棒性验证。</p>
{asm_section()}

<h2>案例五：标准设计院图纸 — 92DZ1 单电源单台消火栓泵（PUB_TITLE 层，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">4 个图框</span><span class="tag">A3</span><span class="tag">PUB_TITLE 层</span><span class="tag">打散图框</span> 来源：标准设计院电气原理图，2×2 平铺排列，图框为 PUB_TITLE 层闭合 LWPOLYLINE，无 INSERT 块式标题栏。处理时先走块式检测（返回 0）再回退到线框检测，逐框替换为公司 A3 图框。</p>
{standard_section()}

<h2>案例六：合成异常样本（多图框 / 嵌套块 / 缺字体 / 会签栏差异）</h2>
<p><span class="tag">4 个合成 DXF</span><span class="tag">程序化生成</span><span class="tag">可控可复现</span> 用 ezdxf 直接生成，无需外部图纸。每个异常图都经过"检测图框/抽取字段/插入公司图框/渲染"全流程，下面给出工具<b>实际行为</b>与结论。</p>
{synth_section()}

<h2>案例七：多图框逐框替换（检测多图框 → 逐框插公司图框）</h2>
<p><span class="tag">2 个合成 DXF</span><span class="tag">平铺多框</span><span class="tag">并排多框</span><span class="tag">逐框回填</span> 新开发项：在 <code>lib/finder.py</code> 新增 <code>detect_frames_hierarchical</code>（识别整图纸框为纸边、其余为替换目标），在 <code>lib/block_replace.py</code> 新增 <code>delete_frame_border</code>/<code>delete_title_strip</code>（外科手术式删除，保留图内几何）。逐框选模板尺寸 → 抽字段 → 删旧框线+标题栏 → 插公司图框(fit=max) → 回填。</p>
{multi_section()}

<h2>文件位置</h2>
<ul>
  <li><a href="index.html">案例集总览 index.html</a></li>
  <li>案例一输出：<a href="01_SW_parts/outputs/">01_SW_parts/outputs/</a></li>
  <li>案例二输出（成品 DWG）：<a href="02_CNG_electrical/outputs/CNG_电气系统图_HH.dwg">CNG_电气系统图_HH.dwg</a></li>
  <li>案例三输出：<a href="03_ESS_cad/outputs/">03_ESS_cad/outputs/</a></li>
  <li>案例四输出（成品 DXF）：<a href="04_assembly/outputs/装配体图纸(1)_HH.dxf">装配体图纸(1)_HH.dxf</a></li>
  <li>案例六输出（合成样本 + 结论）：<a href="06_synth/outputs/index.html">06_synth/outputs/index.html</a> / <a href="06_synth/outputs/results.json">results.json</a></li>
  <li>案例七输出（多图框逐框替换）：<a href="07_multiframe/outputs/index.html">07_multiframe/outputs/index.html</a> / <a href="07_multiframe/outputs/results.json">results.json</a></li>
  <li>使用手册：<a href="../MANUAL.md">MANUAL.md</a></li>
</ul>

</body>
</html>"""
    out = os.path.join(HERE, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("written:", out, len(html), "bytes")


if __name__ == "__main__":
    main()
