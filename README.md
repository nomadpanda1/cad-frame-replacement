# CAD 电路图图框批量置换工具

把历史 CAD 电路图纸上的旧图框，自动换成你们公司的标准图框，并**无损迁移**旧图框里的字段
（图名 / 图号 / 比例 / 阶段 / 日期 / 设计人 …）。支持批量处理，公司图框**随时会变**——换模板重跑即可，代码零改动。

**双引擎**：
- **策略一 · ezdxf 离线核心**——纯 [ezdxf](https://ezdxf.readthedocs.io/) 实现，不依赖 AutoCAD，跨平台，输出 DXF。
- **策略二 · AutoCAD COM 直接处理**——本机装了 AutoCAD 时，用 ezdxf 做「检测 + 字段计划」，
  实际删框 / 插框 / 回填 / 保存全部交给 AutoCAD COM 在原文件副本上完成，输出**真正被 AutoCAD 认可的 DWG**，
  彻底绕开 ezdxf `saveas` 后 AutoCAD 打不开的兼容性问题。

> 实测：微信发来的「打散」类真实图纸（0 个 INSERT 块标题栏、含中文 SHX 字体）走策略二，
> 住宅楼电气整套 11 张 DWG **11/11 全部成功**插入公司图框，旧框残线 **11/11 = 0**。

---

## 🚀 案例与效果（先看这里）

本仓库自带 **12 套案例**（10 套带前后对比渲染 + 2 套逻辑 / 负样本验证），覆盖真实机械图纸、电气系统图、
储能图纸、装配体、设计院标准图、合成异常样本、多图框逐框替换、**真实图纸拼接的多图框端到端验证**，
以及真实住宅楼电气设计方案（11 张 DWG）和给煤机控制原理图等：

- 📊 **[cases/report.html](cases/report.html)** —— 完整效果对比报告（链接图，含各案例前后对比 + 使用说明 + 修复记录）
- 📦 **[cases/showcase.html](cases/showcase.html)** —— 单文件离线版，图片全部内嵌（约 10 MB），可直接下载发微信 / 邮件
- 🏠 **[cases/index.html](cases/index.html)** —— 案例导航首页

### 前后对比缩略图

<table>
<tr>
<td align="center"><b>案例一：法兰零件图</b></td>
<td><img src="cases/01_SW_parts/outputs/从法兰(2)_before.png" width="380" alt="before"></td>
<td><img src="cases/01_SW_parts/outputs/从法兰(2)_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例二：CNG 电气系统图</b></td>
<td><img src="cases/02_CNG_electrical/outputs/CNG_电气系统图_before.png" width="380" alt="before"></td>
<td><img src="cases/02_CNG_electrical/outputs/CNG_电气系统图_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例三：储能 ESS 设备表</b></td>
<td><img src="cases/03_ESS_cad/outputs/16MW_32MWh_一次设备表_before.png" width="380" alt="before"></td>
<td><img src="cases/03_ESS_cad/outputs/16MW_32MWh_一次设备表_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例四：无图框装配体</b></td>
<td><img src="cases/04_assembly/outputs/装配体图纸(1)_before.png" width="380" alt="before"></td>
<td><img src="cases/04_assembly/outputs/装配体图纸(1)_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例五：标准设计院图纸（92DZ1 消火栓泵）</b></td>
<td><img src="cases/05_standard_dwg/outputs/92DZ1_xiaohuobeng_before.png" width="380" alt="before"></td>
<td><img src="cases/05_standard_dwg/outputs/92DZ1_xiaohuobeng_HH.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例六：合成异常样本</b></td>
<td><img src="cases/06_synth/outputs/06a_before.png" width="380" alt="before"></td>
<td><img src="cases/06_synth/outputs/06a_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例七：多图框逐框替换</b></td>
<td><img src="cases/07_multiframe/outputs/07b_side_by_side_before.png" width="380" alt="before"></td>
<td><img src="cases/07_multiframe/outputs/07b_side_by_side_HH.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例八：真实多图框（4×A1 拼接）</b></td>
<td><img src="cases/08_real_mf/outputs/08_real_multiframe_before.png" width="380" alt="before"></td>
<td><img src="cases/08_real_mf/outputs/08_real_multiframe_HH.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例九：馈电-电气原理图（A4 竖版）</b></td>
<td><img src="cases/09_kuidian_electrical/outputs/kuidian_before.png" width="380" alt="before"></td>
<td><img src="cases/09_kuidian_electrical/outputs/kuidian_HH.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例十：住宅楼电气设计方案（11 张 DWG）</b></td>
<td><img src="cases/10_residential_electrical/outputs/天面_before.png" width="380" alt="before"></td>
<td><img src="cases/10_residential_electrical/outputs/天面_HH.png" width="380" alt="after"></td>
</tr>
</table>

- **案例十一 · 给煤机控制原理图**（`cases/11_geimei_control/`）：边框 less 长条图（长宽比 ≈ 5.49，无 A 幅面图框），
  检测器正确判定「无有效图框、不改图」，并据此加固了 `detect_frames_hierarchical` 的全局占比护栏，杜绝把图内元件方框当图框误插。
  属逻辑验证案例，**配「原图/检测过滤」对比示意图**，详见 `cases/11_geimei_control/summary.md` 与 `cases/report.html`。
- **案例十二 · 检测负样本**（`cases/12_detect_negative/`）：记录当前检测器**漏检**的两类真实图纸
  （`std_A3` 分段短直线边框、`S7-1200` 全块化无原始直线）作为回归负样本，明确「已知局限」，避免未来「假完成」误判。
  属负样本归档，**配「漏检根因」示意对比图**，详见 `cases/12_detect_negative/summary.md` 与 `cases/report.html`。

### 📌 案例修复记录（v0.3，反映当前逻辑）

- **案例四 · 无图框装配体（已修复 ✅）**
  旧版 `clear_title_block_zone` 用「相交即删」且无白名单，会把右下角 BOM 表 / 原标题栏一并清掉，导致 HH 框盖在残留元素上。
  **修复**：清理逻辑改为白名单（只删文字 + 旧标题框闭合矩形，绝不碰线 / 几何 / 尺寸 / BOM）；并新增「标题区已有内容 → 只加外框、保留原标题栏」分支。实测装配体 4109 个实体零删除，原图完整保留。

- **案例六 · 合成异常样本（已修复 ✅）**
  - **06a 多图框混排**：旧版按「整图幅」插一张 A1 框，子图框没动。现已复用案例七的逐框替换逻辑，after 图含多个 HH_FRAME INSERT，真正逐框替换。
  - **06b 嵌套块 / 06d 会签栏**：插入公司框前先清理旧标题栏（删除旧 TITLEBLOCK 块、白名单清旧标题条），消除新旧标题栏重叠。

- **案例八 · 真实多图框字段串框（已修复 ✅）**
  `extract_frame_fields` 的标题区判定原本是个无限延伸象限（只卡 x / y 两个方向），在多图框里会把**邻框标题文字吸进来**（第 1 框读成右边第 2 框的「二次系统信号表」）。
  **修复**：标题区改为四边有界；并补 `test_extract_no_leak_from_neighbor_frame` 回归单测。修复后 4 个框的图名 / 图号全部正确回填，几何零丢失。

- **案例九 · A4 竖版方向缺口（已闭环 ✅）**
  本图为 A4 竖版 `210×297`。旧横版模板 `HH_FRAME_A4` 等比缩放后只填满竖版图幅下半部分。
  **闭环**：已补 `templates/HH_FRAME_A4V.dxf` 竖版模板（由 `HH_FRAME_A4` 经 `lib/frame_gen.py` 重定向生成），`lib/sheet.py` 幅面推断判为竖版 `A4V`，`run_skill --dwg` 自动切换为 `HH_FRAME_A4V`，新框严丝合缝填满整张 A4 竖版。

- **案例十 · 字段错填 + 旧框残线（2026-08-13 修复 ✅，核心回归点）**
  - **① 字段错填（TITLE 抓成「注：…」注记 / 电缆型号 / 房间号）**——根因为 COM 打散路径误用旧版 `extract.extract_fields`（抓「最长文本」）。已统一改用 `finder.extract_frame_fields`（按图名字号最大 + 标题栏标签定位真实图名，排除注记 / 电缆 / 房间号干扰）。重跑 11/11，TITLE 全部回填为真实图名。
  - **② 旧框残线（首层配电干线 18 条、首二层商场 1 条 FRAME 层线）**——根因为旧删除逻辑只删「精确贴外边」或「面积 > 80%」的线，框内旧框线漏删。已新增 `del_frame_layer_inside`（删「图框层 + 完全落在旧框内」全部线类实体）接入 COM 管线。浅层核验 11/11 确认**残留 = 0**。
  - **③ 非 √2 旧框比例失真（裙楼 1.77 / 首层配电 0.95 / 首二层商场 1.19）**——由 `lib/sheet.py`（幅面推断）+ `lib/frame_gen.py`（模板重定向）解决，见下文「幅面推断与模板重定向」。

- **案例十一 · 边框 less 密集小方框误检（已修复 ✅）**
  `detect_frames_hierarchical` 新增**全局占比护栏**：候选框面积须 ≥ 整图范围的 `min_drawing_share`（默认 2%），否则视为元件 / 符号方框剔除；过滤后若全空判定为「无有效图框」（不回退 raw，避免误插）。回归测试 `test_no_false_positive_borderless_dense` 复刻 15 元件方框 → 期望 `targets == []`。

---

## 架构：双策略管线（我们修改后的一些逻辑）

```
run_skill.py  (通用主入口，--dwg 控制是否走 AutoCAD COM)
   │
   ├─ 检测：lib/finder.py
   │     • find_titleblocks     块式标题栏（块名 + ATTDEF 词表）
   │     • detect_frames         线框检测（轴对齐直线聚合出闭合矩形外框）
   │     • detect_frames_hierarchical  多图框层级检测（含全局占比护栏）
   │     • extract_frame_fields  真实图名/图号提取（按字号最大 + 标题栏标签，排除注记/电缆/房间号）
   │
   ├─ 幅面推断：lib/sheet.py  ── 旧框图形尺寸 → 先猜出图比例(1:100…) → 再匹配 A0~A4 / 加长幅面
   │
   ├─ 模板重定向：lib/frame_gen.py  ── 按检出旧框真实比例即时重定向 HH_FRAME 模板（锚定拉伸），非 √2/竖版也能严丝合缝
   │
   ├─ 策略一（无 --dwg）：lib/raw_replace.py + lib/block_replace.py 经 ezdxf 直接读写 DXF
   │
   └─ 策略二（--dwg，本机有 AutoCAD）：lib/acad_pipeline.py + lib/acad_com.py
         用 ezdxf 做 plan，AutoCAD COM 在原文件副本上：删旧框/标题栏 → 插模板 DWG(双插法) → 回填 14 属性 → SaveAs .dwg
```

### 幅面推断与模板重定向（新增模块，解决「比例失真」）

- **`lib/sheet.py`**：旧代码把「图形单位下的框尺寸」直接和「毫米制 A 幅面表」比大小，导致 1:100 出图的 A1（84100×59400 单位）被误判成 A0。
  正确做法：先由「外框到内框的 GB/T 14689 标准边距」反推出图比例分母（如 100），再匹配标准幅面；
  匹配不上时返回 `exact=False` 的自定义幅面（保留旧框精确长宽比，短边归一到最近标准短边）。
- **`lib/frame_gen.py`**：旧方案只有 A0~A4 五个 √2 模板，遇非 √2 / 竖版图就套不住旧框（内容溢出或跑到框外）。
  现按检出旧框真实比例**即时重定向模板**：整幅矩形保留留边拉伸、标题栏刚性右下锚定、边缘小元素锚定到对应边。
  自校验：从 A4 重定向出的 A1 与仓库真实 A1 模板逐点一致（`tests/test_frame_gen.py`）。

### 策略二关键实现要点（AutoCAD COM 直接处理）

- `acad_pipeline.process_file` 直接 `Documents.Open` 源文件（扩展名与内容一致，AutoCAD 可识别），编辑后 `SaveAs(dst, 12)` 写二进制 DWG，**不改动源文件**。
- `InsertBlock` 不能直接吃 DXF，模板须先经 `doc.SaveAs(_HH_FRAME_Ax.dwg, 12)`（acNative）转成 DWG；插框用「双插法」拿到 14 个可回填属性，规避同名块自参照。
- 删框双保险：`del_frame_edges`（按图层删外框）+ `del_frame_layer_inside`（删图框层上完全落在旧框内的全部残线），杜绝新框压旧线。
- `_get_acad` 优先 `GetActiveObject`，失败则 `Dispatch` 自动启动 AutoCAD，`--dwg` 开箱即用。

---

## 0. 准备

- **核心库 / CLI**：Python 3.13+（已装 ezdxf 1.4.x）。本机 managed venv 即可：
  ```
  C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  ```
- **GUI / exe 打包**：必须用**系统 Python 3.14**（`C:\Python314\python.exe`）——managed 3.13 venv 编译时未带 tcl/tk，`import tkinter` 会失败。
- 依赖安装：`pip install -r requirements.txt`（装包请用官方源 `-i https://pypi.org/simple`，清华源个别包缺失）。

## 1. 目录结构

```
cad-frame-replacement/
├── run_skill.py            # 通用主入口：template + 旧图纸 → 新图纸（--dwg 切换 AutoCAD COM 策略二）
├── run_real.py             # 案例一：SolidWorks 导出零件图批量置换（策略一）
├── run_cng.py              # 案例二：CNG 电气系统图（策略一）
├── run_cng_acad.py         # 案例二（策略二早期形态，现已并入 run_skill --dwg）
├── run_ess.py              # 案例三：储能 ESS 图纸（策略一）
├── run_asm.py              # 案例四：无图框装配体（策略二）
├── run_synth.py            # 案例六：合成异常样本验证
├── run_multiframe.py       # 案例七：多图框逐框替换
├── run_real_mf.py          # 案例八：真实多图框（4×A1 拼接）端到端验证
├── run_residential.py      # 案例十：住宅楼电气 11 张 DWG（策略二）
├── gen_synth.py            # 生成合成异常样本图纸
├── gen_mf_samples.py       # 生成多图框测试样本
├── gen_real_mf.py          # 案例八：把 4 张真实 A1 图纸拼成 2×2 多图框 DXF
├── make_tpl_dwgs*.py       # 生成 HH 公司图框模板 / WBLOCK 转 DWG
├── gui_app.py              # 图文界面主程序（复用 run_skill.main，核心逻辑零改动）
├── build_exe.bat           # 重新打包 exe（Python 3.14）
├── lib/                    # 核心库（双策略管线）
│   ├── concepts.py         # 中英文/简写字段名 → 统一“概念”中间层
│   ├── template_learn.py   # 模板自动学习（块 ATTDEF / 打散 <图名> 占位符）
│   ├── finder.py           # 旧版图框检测（块式 / 线框 / 多图框层级）+ extract_frame_fields（真实图名提取）
│   ├── extract.py          # 旧图属性提取（ATTRIB / TEXT 键值对）
│   ├── mapper.py           # 概念级字段映射
│   ├── block_replace.py    # 策略一：删旧框 + 插入新框 + 回填字段
│   ├── raw_replace.py      # 策略一：打散图框（无块）删外框/标题栏/边缘区号 + 整图幅插模板
│   ├── sheet.py            # 【新增】幅面推断：图形尺寸 → 出图比例 → 标准/自定义幅面
│   ├── frame_gen.py        # 【新增】模板重定向：按旧框真实比例即时生成任意幅面模板
│   ├── acad.py             # DWG <-> DXF 转换器探测（ODA / LibreCAD）
│   ├── acad_com.py         # 【策略二】AutoCAD COM 助手（采集实体 / 删框 / 插框 / del_frame_layer_inside）
│   ├── acad_pipeline.py    # 【策略二】通用 COM 流水线：plan → 删框/插框/回填/SaveAs .dwg
│   └── logbook.py          # 执行日志 + run_report.json
├── templates/              # HH 公司图框模板 A0-A4（WBLOCK 出的 .dwg 由管线临时生成）
├── cases/                  # 12 套案例（输入/输出/对比图/报告/verify）
│   ├── report.html         # 完整对比报告（链接图）
│   ├── showcase.html       # 单文件内嵌图片版（约 10 MB）
│   ├── index.html          # 案例导航页
│   ├── 01_SW_parts/        # 真实机械零件图（9 张，策略一）
│   ├── 02_CNG_electrical/  # CNG 电气系统图（策略二）
│   ├── 03_ESS_cad/         # 储能 ESS 图纸（4 张，策略一）
│   ├── 04_assembly/        # 无图框装配体（策略二）
│   ├── 05_standard_dwg/    # 标准设计院图纸（92DZ1 消火栓泵，2×2 多图框，策略二）
│   ├── 06_synth/           # 合成异常样本
│   ├── 07_multiframe/      # 多图框逐框替换
│   ├── 08_real_mf/         # 真实多图框（4×A1 拼接）端到端验证
│   ├── 09_kuidian_electrical/  # 馈电-电气原理图（A4 竖版，策略二）
│   ├── 10_residential_electrical/  # 住宅楼电气设计方案（11 张 DWG，策略二，#99/#103 修复）
│   ├── 11_geimei_control/  # 给煤机控制原理图（边框 less，逻辑验证/检测器加固）
│   └── 12_detect_negative/ # 检测负样本（std_A3 / S7-1200，已知局限归档）
├── tests/                  # 64 个用例（62 passed / 2 skipped）
├── samples/  output/       # 运行期生成（不入库）：放待处理旧图 / 生成成品
└── requirements.txt  requirements-dev.txt  pytest.ini  MANUAL.md  SKILL.md
```

## 2. 快速开始（跑案例）

```bash
# 1) 安装依赖
pip install -r requirements.txt -i https://pypi.org/simple

# 2) 跑一个案例（策略一输出 DXF）
python run_real.py      # 案例一：9 张 SW 零件图
python run_cng.py       # 案例二：CNG 电气系统图（DXF）
python run_ess.py       # 案例三：ESS 储能
python run_asm.py       # 案例四：无图框装配体（COM 转 DXF）
python run_synth.py     # 案例六：合成异常样本
python run_multiframe.py # 案例七：多图框逐框替换
python gen_real_mf.py && python run_real_mf.py  # 案例八：真实 4×A1 拼接多图框

# 策略二（AutoCAD COM 直接输出 DWG）：案例五/九/十 用通用入口 --dwg
python run_skill.py --template templates/HH_FRAME_A3.dxf --dwg --fit max  cases/05_standard_dwg/inputs/*.dwg
python run_skill.py --template templates/HH_FRAME_A4.dxf --dwg --fit max  cases/09_kuidian_electrical/inputs/*.dwg
python run_residential.py   # 案例十：住宅楼电气 11 张 DWG（封装了上面的调用）

# 通用入口也能直接处理多图框：auto 自动判断单/多框，multi 强制逐框替换
python run_skill.py --template templates/HH_FRAME_A1.dxf --mode auto  cases/07_multiframe/inputs/*.dxf
python run_skill.py --template templates/HH_FRAME_A1.dxf --mode multi  cases/08_real_mf/inputs/*.dxf

# 3) 看报告（浏览器打开）
cases/report.html
```

## 3. 跑自己的图纸

```bash
# 默认：输出 DXF（策略一，核心稳定）
python run_skill.py --template templates/公司图框.dxf  samples/*.dxf

# 多张混批
python run_skill.py --template templates/公司图框.dxf  samples/old1.dxf samples/old2.dxf

# 需要 DWG 输入输出（本机有 AutoCAD 时走策略二，否则依赖 ODA / LibreCAD 转换器）
python run_skill.py --template templates/公司图框.dxf --dwg  samples/*.dwg

# 只检测标题栏，生成 detection.json（不改图）
python run_skill.py --template templates/公司图框.dxf --detect-only  samples/*.dxf

# 只提取+映射，预览迁移结果（不改图）
python run_skill.py --template templates/公司图框.dxf --dry-run  samples/*.dxf
```

常用参数：
| 参数 | 说明 |
|---|---|
| `--template` | 公司图框模板（必填） |
| `--out` | 输出目录（默认 `output/`） |
| `--suffix` | 输出文件后缀（默认 `_HH`） |
| `--dwg` | 输出 DWG（本机有 AutoCAD 走策略二；否则需 ODA / LibreCAD 转换器） |
| `--fit` | 新框缩放：`min` 保比例居中(默认) / `max` 满填 / `width` / `height` |
| `--margin` | 打散图框删除边距 |
| `--override` | 字段映射覆盖，如 `{"TITLE":"OLD_TITLE"}` |
| `--mode` | 单框/多图框判定：`auto` 自动(默认，≥2 框走逐框替换) / `single` 强制整图幅一张框 / `multi` 强制逐框替换 |
| `--detect-only` / `--dry-run` | 分阶段调试 |

## 4. 公司图框“随时会变”怎么办

**什么都不用改代码**，只要：
1. 用新版公司图框覆盖 `templates/` 下的模板文件（块名、字段措辞、字段增减都行）；
2. 重新跑一次 `run_skill.py`。

模板学习是**全自动**的：块模板读 ATTDEF，打散模板读 `<图名>` 占位符；字段按“概念”对齐
（图名↔TITLE、图号↔DWG_NO …），中英文/简写都能对上。新模板多出来的字段，旧图没有对应来源的会自动留空。

## 5. 输出与校验

- 每个源图生成 `原名_HH.dxf`（或 `--dwg` 时 `原名_HH.dwg`），原文件永不覆盖。
- `output/Execution_Log.csv`：逐张执行记录（检测数 / 删除实体 / 回填字段 / 状态）。
- `output/run_report.json`：完整报告，含每张图的字段提取与映射明细，便于核对。
- 案例十这类「打散真实图纸」额外用 `verify/verify_shallow.json`（ezdxf `bbox.extents` 统计 HH_FRAME 块数与框内残线）做浅层核验，11/11 残留 = 0。

## 6. 已知约束

- **DWG 输入**：策略二下本机有 AutoCAD 时直接 `Documents.Open` 读 DWG；无 AutoCAD 时，DWG 输入会先转 DXF 再处理（依赖 ODA File Converter / LibreCAD），输出也只给 DXF。
- **打散旧图框（无块）**：靠「关键词 + 附近表格线」吸附定位，复杂图纸建议先用 `--detect-only` 人工确认区域；块图框识别最稳。
- **缩放策略**：默认 `min`（保比例、不拉伸变形、居中）。若觉得“图框偏小有留白”，用 `--fit max` 满填（横向可能略溢出进上方电路，约 2% 形变，可接受）。**非 √2 / 竖版图**现已由 `lib/sheet.py` + `lib/frame_gen.py` 即时重定向模板解决，不再等比套不住。
- **多图框误检治理**：电气图里大量端子 / 符号 / 表格单元都是闭合矩形，早期检测会把它们全当成“图框”（CNG 电气系统图曾误检 61 个）。现用“面积占比下限(0.15) + 双线去重”两级过滤压到真实框数（CNG 实测 4 个）。注意**不能**用“长宽比接近 √2”筛——加长图幅在电气图里很常见（CNG 左侧三个真图框长宽比就是 2.00），按标准图幅比例会误杀真框。
- **边框 less / 全块化图纸**：案例十一（给煤机）正确判定「无有效图框、不改图」；案例十二（std_A3 分段边框、S7-1200 全块化）属当前检测器**已知局限 / 负样本**，线框检测器对「分段短直线边框」需跨 y 键容差合并、对「块内图框」需新增递归展开能力，后续版本增强。
- 双线图框（外框 + 内框两条矩形）会被去重为外框，替换时一并清理内框残线，避免新框上压一圈旧线。
- 若你手上有天然多图框的图纸，建议先 `--detect-only` 看一下识别出的框数是否符合预期。

---

## 7. 本分发版包含内容

- **核心**：`lib/`（图框检测、幅面推断、模板重定向、字段提取映射、替换、模板学习；策略一 ezdxf + 策略二 AutoCAD COM）
- **模板**：`templates/`（HH 公司图框 A0-A4）
- **12 套案例**：`cases/01_SW_parts` … `cases/12_detect_negative`，每套含输入图纸、输出成品、前后对比 PNG（11/12 为逻辑/负样本验证，无渲染图）
- **报告**：`cases/report.html`（链接图）、`cases/showcase.html`（内嵌图单文件，约 10 MB）、`cases/index.html`
- **入口脚本**：全部 `run_*.py` / `gen_*.py` / `make_*.py` / `gui_app.py`
- **其他**：`requirements.txt`、`pytest.ini`、`.gitignore`、`MANUAL.md`、`SKILL.md`

> 案例中的真实图纸（01–04、CNG、住宅楼等）已做脱敏处理；如你手上有更敏感的设计院图纸，请参照 `run_skill.py` 自行处理，不要直接上传到公开仓库。

---

## 8. 把这个仓库当作 WorkBuddy Skill 装载（给他人 / 其他智能体用）

本仓库根目录已包含 `SKILL.md`，因此**克隆到本地后即可被 WorkBuddy 当作 skill 直接调用**
（对话里说“帮我换图框”“图框置换”会自动触发）。

> ⚠️ GitHub 仓库**不能**被 WorkBuddy 直接“装载”——它只是源码托管。必须先把仓库放到
> WorkBuddy 的 skills 目录下，或使用“文件夹导入”。

### 方式 A：放到 skills 目录（推荐）

```bash
# 1) 克隆（或下载 ZIP 解压）
git clone https://github.com/nomadpanda1/cad-frame-replacement.git

# 2) 放到以下任一目录（目录名即 skill 名，可保持原名）
#    个人全局（所有项目可用）：
cp -r cad-frame-replacement ~/.workbuddy/skills/cad-frame-replacement
#    或仅当前项目（团队协作）：
cp -r cad-frame-replacement <你的项目>/.workbuddy/skills/cad-frame-replacement

# 3) 重启 WorkBuddy（或刷新），即可在对话中调用
```

### 方式 B：文件夹导入

打开 WorkBuddy 左侧「技能中心 / Skills」→ 添加技能 → 文件夹导入 → 选择克隆下来的
`cad-frame-replacement` 文件夹 → 确认。

### 装载后效果

- 对话中输入“把这套旧图纸换成公司图框”“批量换图框”等，WorkBuddy 会读取 `SKILL.md` 并
  调用 `run_skill.py` 等入口，按本仓库流程处理。
- 给**其他用户 / 其他机器**用：把仓库 clone 到他们的 skills 目录即可，无需改任何代码。
- 公司图框模板变化时，只需替换 `templates/` 下文件并重跑，skill 逻辑零改动。

---

## 9. 测试与持续集成（CI 回归保护）

改 `lib/`、`run_*.py` 或在真实图纸上修 bug 时，**务必先跑测试**，避免误删 / 误判被悄悄带上线。

### 本地跑测试

```bash
# 1) 装开发依赖（含 pytest；ezdxf 已在 requirements.txt）
pip install -r requirements.txt -i https://pypi.org/simple

# 2) 运行（仓库根目录，pytest.ini 已配好）
pytest -q
```

- **64 个用例，62 passed / 2 skipped**，全部纯函数、内存构造最小 DXF，**不依赖任何外部图纸 / 模板**，秒级跑完。
- 覆盖重点回归点：
  - `delete_title_strip` 白名单——**绝不误删尺寸线 / 几何 / 长格线**（最早出过 bug 的地方）；
  - `detect_frames_hierarchical` 多图框层级检测（单框 / 拼贴含子框 / 并排多框）+ 全局占比护栏（案例十一负样本）；
  - `extract_frame_fields` 真实图名抽取路由（比例 / 材料 / 图号 / 重量 / 图名高置信识别，排除注记/电缆/房间号）；
  - `lib/sheet.py` 幅面推断 + `lib/frame_gen.py` 模板重定向（A4 重定向 A1 与真实模板逐点一致）。

### CI 自动回归

`.github/workflows/test.yml` 在 **push / 开 PR 时自动触发**，于 ubuntu + Python 3.13 跑 `pytest`。
任何让测试变红的提交都会被立刻拦下，等于给「修 bug」上了回归保护。

---

## 10. 打包与分发（免装 Python 的同事用）

给不会用命令行的同事，把工具打成 **单个 exe**，双击即用，无需装任何 Python 环境。

### 分发物

- `dist/cad-frame-gui.exe` —— 图文界面主程序（**推荐**，双击出现窗口，选图纸 → 选模板 → 开始）。
- `dist/cad-frame-cli.exe` —— 命令行版（会命令行的同事用，参数同 `run_skill.py`）。
- `dist/templates/` —— 公司图框模板（HH_FRAME_A0~A4.dxf）。
- `dist/使用说明.txt` —— 给同事的图文使用指南。

> exe 已内嵌模板与 ezdxf，拷走 `cad-frame-gui.exe` 单独也能跑；附 `templates/` 只是为了便于换模板。
> exe 体积较大，**不入库**（`.gitignore` 已忽略 `dist/`、`*.exe`、`*.spec`）。

### 为什么打包要用系统 Python 3.14

标准 managed venv（3.13）编译时未带 tcl/tk，`import tkinter` 会失败。本工具界面用 tkinter，
故打包必须用**自带 tcl/tk 的 Python 3.14**（如 `C:\Python314\python.exe`），且已 `pip install ezdxf pyinstaller`。
GUI 入口 `gui_app.py` 通过构造 `sys.argv` + 重定向 stdout **复用** 已验证的 `run_skill.main()`，核心逻辑零改动。

### 重新打包

代码改动后想重新生成 exe，双击仓库根目录的 `build_exe.bat`（先按里面注释改一下 `PY=` 为你的 Python 3.14 路径）。
或直接：

```bash
C:\Python314\python.exe -m PyInstaller --noconfirm --onefile --windowed --name cad-frame-gui \
  --collect-all ezdxf --collect-all lib --add-data "templates;templates" gui_app.py
```

生成的 `dist/cad-frame-gui.exe` 即为分发包。
