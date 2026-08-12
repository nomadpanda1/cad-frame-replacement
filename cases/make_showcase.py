# -*- coding: utf-8 -*-
"""生成综合展示页：
  - report.html   : 链接式图片（GitHub 友好，仓库内含 PNG 即可渲染）
  - showcase.html : 图片 base64 内嵌，单文件，可单独发送/离线打开
两份都含：使用说明 + 全部 7 套案例的前后对比图。
复用 gen_report.py 里的各案例分段函数与 CSS。
"""
import os, re, base64, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

# 复用 gen_report 的分段函数 + CSS
spec = importlib.util.spec_from_file_location("gen_report", os.path.join(HERE, "gen_report.py"))
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)

INTRO = """<p>本页聚合九套案例的 <b>生成前 / 公司模板 / 生成后</b> 对比图。案例一为普通图纸（纯 ezdxf 离线，策略一）；案例二为设计院加密 DWG（AutoCAD COM 直接处理，策略二）；案例三为储能 ESS 成果包（纯 ezdxf，策略一）；案例四为无图框/无标题栏的装配体图纸（COM 转 DXF + 清标题栏占位，策略二）；<b>案例五</b>为标准设计院图纸（92DZ1 消火栓泵，2×2 多图框，图框位于 PUB_TITLE 层，策略二）；<b>案例六</b>为程序化生成的<b>异常场景合成样本</b>（多图框混排 / 嵌套块标题栏 / 缺字体 / 会签栏差异）；<b>案例七</b>为<b>多图框逐框替换</b>开发项成果（平铺多框含整图纸框 / 并排多框无整图纸框），验证"检测多图框 → 逐框插公司图框 → 逐框回填"；<b>案例八</b>为<b>真实多图框端到端验证</b>：用 4 张真实 ESS 图纸拼成 2×2 多图框（内容 100% 真实，仅排布合成），在真实标题栏结构上跑逐框替换管线，过程中发现并修复了标题区越界泄漏 bug；<b>案例九</b>为<b>真实电气原理图（馈电）</b>：单张 A4 竖版、BORDER 层双线图框，验证了「BORDER 标准边框层」的兼容修复（del_frame_edges 词表补 border，内外框一并删净）。</p>"""

USAGE = """
<h2>使用说明</h2>
<div class="card">
  <h3>0. 环境准备</h3>
  <p class="cap">Python 3.13 + <a href="https://ezdxf.readthedocs.io/">ezdxf</a> 1.4.x（见仓库 <code>requirements.txt</code>）。纯离线核心，不依赖 AutoCAD。本机运行环境示例：<br>
  <code>C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe</code></p>

  <h3>1. 快速开始</h3>
  <pre style="background:#1e1e1e;padding:12px;border-radius:6px;overflow:auto;color:#d4d4d4;white-space:pre-wrap;"># 进入工程目录
cd cad-frame-replacement

# 默认：输出 DXF（核心稳定）
python run_skill.py --template templates/公司图框.dxf  samples/*.dxf

# 多张混批
python run_skill.py --template templates/公司图框.dxf  samples/old1.dxf samples/old2.dxf

# 只检测标题栏，生成 detection.json（不改图）
python run_skill.py --template templates/公司图框.dxf --detect-only  samples/*.dxf

# 只提取+映射，预览迁移结果（不改图）
python run_skill.py --template templates/公司图框.dxf --dry-run  samples/*.dxf</pre>

  <h3>2. 常用参数</h3>
  <table>
    <tr><td><b>--template</b></td><td>公司图框模板（必填）</td></tr>
    <tr><td><b>--out</b></td><td>输出目录（默认 output/）</td></tr>
    <tr><td><b>--suffix</b></td><td>输出文件后缀（默认 _HH）</td></tr>
    <tr><td><b>--fit</b></td><td>新框缩放：min 保比例居中(默认) / max 满填 / width / height</td></tr>
    <tr><td><b>--detect-only</b> / <b>--dry-run</b></td><td>分阶段调试，不改图</td></tr>
  </table>

  <h3>3. 各案例复现</h3>
  <table>
    <tr><td>案例一 SolidWorks 零件/装配</td><td><code>python run_real.py</code>（输入 cases/01_SW_parts/inputs）</td></tr>
    <tr><td>案例二 CNG 电气系统图（DWG）</td><td><code>python run_cng_acad.py</code>（AutoCAD COM 策略二）</td></tr>
    <tr><td>案例三 储能 ESS 成果包</td><td><code>python run_ess.py</code></td></tr>
    <tr><td>案例四 无图框装配体</td><td><code>python run_asm.py</code></td></tr>
    <tr><td>案例五 标准设计院图纸（92DZ1）</td><td><code>python run_skill.py --template templates/HH_FRAME_A3.dxf --dwg cases/05_standard_dwg/inputs/92DZ1_xiaohuobeng.dwg</code></td></tr>
    <tr><td>案例六 合成异常样本</td><td><code>python gen_synth.py</code> 生成 → <code>python run_synth.py</code></td></tr>
    <tr><td>案例七 多图框逐框替换</td><td><code>python gen_mf_samples.py</code> 生成 → <code>python run_multiframe.py</code></td></tr>
    <tr><td>案例八 真实多图框端到端</td><td><code>python gen_real_mf.py</code> 拼图 → <code>python run_real_mf.py</code></td></tr>
    <tr><td>案例九 真实电气原理图（馈电，BORDER 层）</td><td><code>python run_skill.py --template templates/HH_FRAME_A4.dxf --dwg cases/09_kuidian_electrical/inputs/kuidian.dwg</code></td></tr>
  </table>

  <h3>4. 已知约束</h3>
  <p class="cap">• DWG 需要转换器：ezdxf 只读写 DXF；DWG 用 ODA File Converter / LibreCAD 或 AutoCAD COM 处理。<br>
  • 打散旧图框靠"关键词+表格线"吸附；复杂图建议先用 <code>--detect-only</code> 人工确认区域。<br>
  • 默认 <code>--fit min</code> 保比例居中；图框偏小有留白时用 <code>--fit max</code> 满填（约 2% 形变）。<br>
  • ATTRIB 是 INSERT 嵌套子实体，校验用 <code>insert.attribs</code> 读取，勿用 msp 遍历计数。</p>
</div>
"""

FOOTER = """
<h2>文件位置</h2>
<ul>
  <li><a href="index.html">案例集总览 index.html</a></li>
  <li>案例一输出：<a href="01_SW_parts/outputs/">01_SW_parts/outputs/</a></li>
  <li>案例二输出（成品 DWG）：<a href="02_CNG_electrical/outputs/CNG_电气系统图_HH.dwg">CNG_电气系统图_HH.dwg</a></li>
  <li>案例三输出：<a href="03_ESS_cad/outputs/">03_ESS_cad/outputs/</a></li>
  <li>案例四输出（成品 DXF）：<a href="04_assembly/outputs/装配体图纸(1)_HH.dxf">装配体图纸(1)_HH.dxf</a></li>
  <li>案例五输出（成品 DWG，本地运行生成，体积大不入库）：<a href="05_standard_dwg/inputs/92DZ1_xiaohuobeng.dwg">92DZ1_xiaohuobeng.dwg（源）</a> / <a href="05_standard_dwg/outputs/92DZ1_xiaohuobeng_HH.png">92DZ1_xiaohuobeng_HH.png（效果图）</a></li>
  <li>案例九输出（成品 DWG，本地运行生成，体积大不入库）：<a href="09_kuidian_electrical/inputs/kuidian.dwg">kuidian.dwg（源）</a> / <a href="09_kuidian_electrical/outputs/kuidian_HH.png">kuidian_HH.png（效果图）</a></li>
  <li>案例六输出（合成样本 + 结论）：<a href="06_synth/outputs/index.html">06_synth/outputs/index.html</a> / <a href="06_synth/outputs/results.json">results.json</a></li>
  <li>案例七输出（多图框逐框替换）：<a href="07_multiframe/outputs/index.html">07_multiframe/outputs/index.html</a> / <a href="07_multiframe/outputs/results.json">results.json</a></li>
  <li>使用手册：<a href="../MANUAL.md">MANUAL.md</a></li>
</ul>
"""


def assemble(embed):
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CAD 图框批量置换 — 效果对比报告</title>
<style>{gr.CSS}</style>
</head>
<body>
<h1>CAD 图框批量置换 — 效果对比报告</h1>
{INTRO}
{USAGE}

<h2>案例一：SolidWorks 导出零件图 / 装配图（9 张，策略一）</h2>
<p><span class="tag">9 张图纸</span><span class="tag">A3/A4</span><span class="tag">标准标题栏</span> 来源：SolidWorks 工程图导出的 DXF，图框为打散 LINE/LWPOLYLINE，标题栏为右下角 TEXT/MTEXT 网格。</p>
{gr.sw_section()}

<h2>案例二：CNG 电气系统图（设计院图纸，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">4 个图框</span><span class="tag">A3_WIDE / A1</span><span class="tag">会签栏</span> 来源：设计院电气系统图，DWG 格式，modelspace 内 4 张大坐标图框（左侧 3 个 A3_WIDE、右侧 1 个 A1）。图纸含加密/代理实体，ezdxf 写回后 AutoCAD 无法打开，因此采用 AutoCAD COM 直接处理原 DWG。</p>
{gr.cng_section()}

<h2>案例三：储能(ESS) CAD 成果包（4 张，策略一）</h2>
<p><span class="tag">4 张 DXF</span><span class="tag">A1 幅面</span><span class="tag">标题栏右下角小条</span> 来源：储能 CAD 成果包（一次设备表 / 二次系统信号表 / 二次系统柜体表 / 简化主接线图）。外框为单个闭合 LWPOLYLINE（≈A1），标题栏为右下角小条含 4 个字段，无日期/设计/审核等。走纯 ezdxf 策略一，字段自动提取回填。</p>
{gr.ess_section()}

<h2>案例四：装配体图纸（无图框 / 无标题栏，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">A3 横放</span><span class="tag">无 TEXT 标题栏</span><span class="tag">无外框矩形</span> 来源：装配体图纸，二进制 DWG 无代理实体。AutoCAD COM 转 DXF 后，因原图无图框/标题栏，采用"清标题栏占位 + 插公司 A3 图框"：先删右下角 63 个零散标注，再插入 HH_FRAME_A3（14 字段均为可编辑空占位）。这是"无图框"异常场景的鲁棒性验证。</p>
{gr.asm_section()}

<h2>案例五：标准设计院图纸 — 92DZ1 单电源单台消火栓泵（PUB_TITLE 层，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">4 个图框</span><span class="tag">A3</span><span class="tag">PUB_TITLE 层</span><span class="tag">打散图框</span> 来源：标准设计院电气原理图，2×2 平铺排列，图框为 PUB_TITLE 层闭合 LWPOLYLINE，无 INSERT 块式标题栏。处理时先走块式检测（返回 0）再回退到线框检测，逐框替换为公司 A3 图框，并修复了 `del_frame_edges` 对 PUB_TITLE 等设计院图框图层的兼容性问题。</p>
{gr.standard_section()}

<h2>案例九：真实电气原理图 — 馈电-电气原理图（BORDER 层双线图框，策略二）</h2>
<p><span class="tag">1 张 DWG</span><span class="tag">A4 竖版</span><span class="tag">BORDER 层</span><span class="tag">双线图框</span> 来源：真实电气原理图（爱给网），单张 A4 竖版，图框为 BORDER 层双线矩形（外框 [0,0,210,297]+内框 [25,5,205,292]），无 INSERT 块式标题栏。验证了「BORDER 标准边框层」的兼容修复（del_frame_edges 词表补 border，内外框一并删净），并暴露了当前模板库缺少 A4 竖版模板的问题。</p>
{gr.kuidian_section()}

<h2>案例六：合成异常样本（多图框 / 嵌套块 / 缺字体 / 会签栏差异）</h2>
<p><span class="tag">4 个合成 DXF</span><span class="tag">程序化生成</span><span class="tag">可控可复现</span> 用 ezdxf 直接生成，无需外部图纸。每个异常图都经过"检测图框/抽取字段/插入公司图框/渲染"全流程，下面给出工具<b>实际行为</b>与结论。</p>
{gr.synth_section()}

<h2>案例七：多图框逐框替换（检测多图框 → 逐框插公司图框）</h2>
<p><span class="tag">2 个合成 DXF</span><span class="tag">平铺多框</span><span class="tag">并排多框</span><span class="tag">逐框回填</span> 新开发项：在 <code>lib/finder.py</code> 新增 <code>detect_frames_hierarchical</code>（识别整图纸框为纸边、其余为替换目标），在 <code>lib/block_replace.py</code> 新增 <code>delete_frame_border</code>/<code>delete_title_strip</code>（外科手术式删除，保留图内几何）。逐框选模板尺寸 → 抽字段 → 删旧框线+标题栏 → 插公司图框(fit=max) → 回填。</p>
{gr.multi_section()}

<h2>案例八：真实多图框端到端验证（4 张真实 ESS 图拼 2×2 多图框）</h2>
<p><span class="tag">4×A1</span><span class="tag">真实标题栏</span><span class="tag">逐框回填</span><span class="tag">发现并修复 bug</span> 用 4 张<b>真实</b> ESS 图纸（一次设备表 / 二次系统信号表 / 二次系统柜体表 / 简化主接线图）平移拼成 2×2 网格多图框，内容 100% 真实、仅排布合成。在真实标题栏结构上跑"检测多图框 → 逐框插公司图框 → 逐框回填"，4 个真实图名/图号均正确归位；过程中暴露并修复了 <code>extract_frame_fields</code> 标题区越界泄漏 bug（已加 pytest 回归测试）。</p>
{gr.real_mf_section()}

{FOOTER}
</body>
</html>"""
    if embed:
        def repl(m):
            src = m.group(1)
            p = os.path.join(HERE, src)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    data = f.read()
                b64 = base64.b64encode(data).decode()
                return f'<img src="data:image/png;base64,{b64}">'
            return m.group(0)
        html = re.sub(r'<img src="([^"]+)">', repl, html)
    return html


def main():
    linked = assemble(embed=False)
    with open(os.path.join(HERE, "report.html"), "w", encoding="utf-8") as f:
        f.write(linked)
    print("written report.html", len(linked), "bytes")
    single = assemble(embed=True)
    with open(os.path.join(HERE, "showcase.html"), "w", encoding="utf-8") as f:
        f.write(single)
    print("written showcase.html", len(single), "bytes (images embedded)")


if __name__ == "__main__":
    main()
