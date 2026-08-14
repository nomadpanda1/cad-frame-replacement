# CAD 图框批量置换 · 使用说明书

> 把历史 CAD 图纸上的旧图框，自动换成你们公司的标准图框，并**无损迁移**旧图框里的字段
> （图名 / 图号 / 比例 / 阶段 / 日期 / 设计人 …）。支持批量处理，公司图框**随时会变**——换模板重跑即可，代码零改动。
> 适用：电气 / 电路图、机械零件图、装配图、设计院系统图、住宅楼电气设计方案等一切"换公司图框"场景。

> ⚠️ **分发方式：源码运行，不提供 exe。** 本工具以源码方式分发——clone 仓库后直接用 Python 运行，无需打包成 exe。
> 曾试过 PyInstaller 单文件 exe，但冻结后目标机生成的 DXF 打不开、CLI 也起不来，故弃用 exe 方案。
> **弃用 exe 不会丢失任何测试效果**——下方"§6 已验证的测试效果"全部由源码直接跑出，与 exe 无关，全部完好保留。

---

## 0. 两条策略，先看清再选

| 策略 | 适用对象 | 核心引擎 | 稳定性 | 入口命令 |
|---|---|---|---|---|
| **一 · 离线核心** | DXF / 普通 DWG（无加密实体） | 纯 ezdxf 离线读→写，跨平台 | 高（零 AutoCAD 依赖，输出 DXF） | `python run_skill.py ...`（不加 `--dwg`） |
| **二 · AutoCAD COM 直接处理** | 本机装有 AutoCAD 时的 DWG（含设计院原图、含中文 SHX 字体、"打散"无块图框） | ezdxf 做"检测 + 字段计划"，实际删框 / 插框 / 回填 / 保存全部交给 AutoCAD COM 在原文件副本上完成，输出**真正被 AutoCAD 认可的 DWG** | 中（需本机 AutoCAD） | `python run_skill.py ... --dwg` |

**怎么判断走哪条？**
- 手上是 DXF、或只要 DXF 成品 → 策略一（默认，最稳）。
- 手上是 DWG、且本机装了 AutoCAD、想要真正可被 AutoCAD 打开的 DWG → 策略二（加 `--dwg`）。策略二会先用 ezdxf 检测 + 抽字段，再用 AutoCAD COM 在源文件**副本**上删旧框 / 插公司框 / 回填 14 属性 / `SaveAs .dwg`，**不改动源文件**。
- 微信发来的"打散"类真实图纸（0 个 INSERT 块标题栏、含中文 SHX 字体）走策略二；实测住宅楼电气整套 11 张 DWG **11/11 全部成功**插入公司图框，旧框残线 **11/11 = 0**。

---

## 1. 环境准备

- **命令行 / 批量（CLI + 离线核心）**：Python 3.13+，已装 `ezdxf` 1.4.x。本机 managed venv 即可：
  ```
  C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  ```
- **图文界面（GUI）**：用**系统 Python 3.14** 运行 `python gui_app.py`（`C:\Python314\python.exe`）。
  managed 3.13 venv 未带 `tcl/tk`，`import tkinter` 会失败，所以 GUI 必须走系统 3.14。
- **策略二依赖**：本机装 AutoCAD（测试环境为 AutoCAD 2026）；`pywin32`（`import win32com.client`）。
- **字体映射（策略二处理中文 SHX 时建议做，否则 COM 可能卡在 SHX 弹窗）**：
  编辑 `acad.fmp`，格式严格 `原字体;替代字体`（分号紧贴无空格），替代字体只写纯文件名如 `simhei.ttf`；
  改完**重启 AutoCAD** 生效。
- **公司图框模板**：`templates/` 下已带 `HH_FRAME_A0/A1/A2/A3/A4.dxf` + 竖版 `HH_FRAME_A4V.dxf`（块名、字段措辞、字段增减都能自动学习，无需改代码）。
  注：COM 插框时模板须是 DWG，`lib/acad_com.py` 会先用 `SaveAs(_HH_FRAME_Ax.dwg, 12)`（acNative）把 DXF 模板即时转成 DWG，无需手工预转。

依赖安装（装包请用官方源，清华源个别包缺失）：
```
pip install -r requirements.txt -i https://pypi.org/simple
```

---

## 2. 快速开始（跑你自己的图）

通用主入口是 **`run_skill.py`**：`--template` 指定公司图框，`inputs` 接一张或多张源图（支持 `*.dxf` / `*.dwg` 或通配符）。

```bash
# 默认：输出 DXF（策略一，核心稳定）
python run_skill.py --template templates/HH_FRAME_A3.dxf  samples/*.dxf

# 多张混批
python run_skill.py --template templates/HH_FRAME_A4.dxf  samples/old1.dxf samples/old2.dxf

# 需要 DWG 输入输出（本机有 AutoCAD 时走策略二）
python run_skill.py --template templates/HH_FRAME_A3.dxf --dwg --fit max  samples/*.dwg

# 只检测标题栏，生成 detection.json（不改图，先确认识别对不对）
python run_skill.py --template templates/HH_FRAME_A3.dxf --detect-only  samples/*.dxf

# 只提取+映射，预览迁移结果（不改图）
python run_skill.py --template templates/HH_FRAME_A3.dxf --dry-run  samples/*.dxf
```

**常用参数（`run_skill.py`）**

| 参数 | 说明 |
|---|---|
| `--template` | 公司图框模板（**必填**，`.dxf`/`.dwg`） |
| `--out` | 输出目录（默认 `output/`） |
| `--suffix` | 输出文件后缀（默认 `_HH`，即 `原名_HH.dxf` / `原名_HH.dwg`） |
| `--dwg` | 输出 DWG（本机有 AutoCAD 走策略二；否则依赖 ODA / LibreCAD 转换器） |
| `--fit` | 新框缩放：`min` 保比例居中(默认) / `max` 满填 / `width` 按宽 / `height` 按高 |
| `--margin` | 打散图框删除边距（默认 5.0） |
| `--override` | 字段映射覆盖，如 `{"TITLE":"OLD_TITLE"}` |
| `--mode` | 单框/多图框判定：`auto` 自动(默认，≥2 框走逐框替换) / `single` 强制整图幅一张框 / `multi` 强制逐框替换 |
| `--detect-only` / `--dry-run` | 分阶段调试，不改图 |

> 其它入口脚本也都可用（见 §8）：`run_real.py`(案例一)、`run_cng.py`(案例二)、`run_ess.py`(案例三)、`run_asm.py`(案例四)、`run_synth.py`(案例六)、`run_multiframe.py`(案例七)、`run_real_mf.py`(案例八)、`run_residential.py`(案例十) 等。

**图文界面（GUI）**——不想敲命令时用：
```bash
C:\Python314\python.exe gui_app.py
```
GUI 复用 `run_skill.main`，核心逻辑零改动；界面里选模板、加文件、勾选 `--dwg` 即可，输出同名 `_HH` 文件。

---

## 3. 跑案例（验证工具好不好用）

仓库自带 **12 套案例**（10 套带前后对比渲染 + 2 套逻辑 / 负样本验证），覆盖真实机械图纸、电气系统图、储能图纸、装配体、设计院标准图、合成异常样本、多图框逐框替换、真实图纸拼接的多图框端到端验证，以及真实住宅楼电气设计方案（11 张 DWG）和给煤机控制原理图。

```bash
# 装依赖后，直接跑各案例脚本
python run_real.py        # 案例一：9 张 SW 零件图（策略一）
python run_cng.py         # 案例二：CNG 电气系统图（策略一）
python run_ess.py         # 案例三：储能 ESS（策略一）
python run_asm.py         # 案例四：无图框装配体（策略二）
python run_synth.py       # 案例六：合成异常样本
python run_multiframe.py  # 案例七：多图框逐框替换
python gen_real_mf.py && python run_real_mf.py   # 案例八：真实 4×A1 拼接多图框

# 策略二（AutoCAD COM 直接输出 DWG）：案例五/九/十
python run_skill.py --template templates/HH_FRAME_A3.dxf --dwg --fit max  cases/05_standard_dwg/inputs/*.dwg
python run_skill.py --template templates/HH_FRAME_A4.dxf --dwg --fit max  cases/09_kuidian_electrical/inputs/*.dwg
python run_residential.py   # 案例十：住宅楼电气 11 张 DWG（封装了上面的调用）

# 通用入口也能直接处理多图框：auto 自动判断单/多框，multi 强制逐框替换
python run_skill.py --template templates/HH_FRAME_A1.dxf --mode auto  cases/07_multiframe/inputs/*.dxf
python run_skill.py --template templates/HH_FRAME_A1.dxf --mode multi  cases/08_real_mf/inputs/*.dxf
```

**看效果（浏览器打开）**：
- `cases/report.html` —— 完整效果对比报告（链接图，含各案例前后对比 + 使用说明 + 修复记录）
- `cases/showcase.html` —— 单文件离线版，图片全部内嵌（约 10 MB），可直接下载发微信 / 邮件
- `cases/index.html` —— 案例导航首页
- `gallery.html` —— 一次性看全部 12 案例、122 张渲染（原图 / 模板 / 换框后对照）；本地用 `python -m http.server` 起静态服务后浏览器打开，相对图片才能加载

---

## 4. 公司图框"随时会变"怎么办

**什么都不用改代码**，只要：
1. 用新版公司图框覆盖 `templates/` 下的模板文件（块名、字段措辞、字段增减都行）；
2. 重新跑一次 `run_skill.py`。

模板学习是**全自动**的：块模板读 ATTDEF，打散模板读 `<图名>` 占位符；字段按"概念"对齐
（图名↔TITLE、图号↔DWG_NO …），中英文 / 简写都能对上。新模板多出来的字段，旧图没有对应来源的会自动留空。

---

## 5. 输出与校验

- 每个源图生成 `原名_HH.dxf`（或 `--dwg` 时 `原名_HH.dwg`），**原文件永不覆盖**。
- `output/Execution_Log.csv`：逐张执行记录（检测数 / 删除实体 / 回填字段 / 状态）。
- `output/run_report.json`：完整报告，含每张图的字段提取与映射明细，便于核对。
- 案例十这类"打散真实图纸"额外用 `verify/verify_shallow.json`（ezdxf `bbox.extents` 统计 HH_FRAME 块数与框内残线）做浅层核验。

---

## 6. 已验证的测试效果（放弃 exe 后**全部仍在** ✅）

> 这些效果都是**源码直接运行** `run_skill.py` / `run_real.py` 等入口产出的；exe 只是同一份源码的冻结副本。
> 弃用 exe 后，以下产物在仓库里**一件没少**：

| 产物 | 路径 | 内容 |
|---|---|---|
| 完整对比报告 | `cases/report.html` | 12 案例前后对比 + 修复记录 + 使用说明 |
| 内嵌图单文件版 | `cases/showcase.html` | 图片全内嵌（约 10 MB），可直接发微信 / 邮件 |
| 案例导航页 | `cases/index.html` | 12 案例入口 |
| 全案例渲染图集 | `gallery.html` | 12 案例 / 122 张（原图·模板·换框后），本地静态服务查看 |
| 源码实测报告 | `src_test_out/exe_test.html` | 源码 `run_skill.py` 实测 9 张 SolidWorks 图纸（命令 + 逐图指标 + 提取到的真实字段） |
| 其他场景测试 | `test_other/test_other.html` | 其他场景 20 张前后对比（自动选模板 + 标题栏残线修复） |
| 缩略图 | `assets/thumbnails/*.png`（64 张） | README / 报告里引用的前后对比缩略图 |
| 案例成品 DWG | `cases/*/outputs/dwg/*_HH.dwg`（12 个） | 住宅楼电气 11 张 + 给煤机 1 张，可直接在 AutoCAD 打开 |

**并行的修复保证了"好效果"不被破坏**——你之前看到的高质量结果，靠的是源码里的这几处加固（都在 `lib/` 里，弃用 exe 不影响）：
- **`del_titleblock` / `delete_titleblock` 只删旧图框层残线 + 标题栏字段标签文本**，绝不碰真实墙 / 窗 / 轴线 / 管线 / 标注 / 块；住宅电气图内容铺满全图也能 100% 保留（`run_report.json` 的 `deleted_titleblock` 由 497 降到 0~22，仅剩应删项）。
- **`del_frame_layer_inside`** 删"图框层 + 完全落在旧框内"的全部线类实体，新框不再压旧线（案例十浅层核验 11/11 残线 = 0）。
- **`lib/sheet.py` + `lib/frame_gen.py`** 按检出旧框真实比例即时重定向模板（锚定拉伸），非 √2 / 竖版图也能严丝合缝，不再等比套不住。
- 已沉淀为可复用 skill `cad-frame-del-titleblock`，逻辑稳定。

---

## 7. 已知约束 / 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| AutoCAD 打开生成文件是空白 `Drawing1`、报"解密数据时出错" | 原图含加密 / 代理实体，ezdxf 写回破坏 | 改用策略二（`--dwg`，AutoCAD COM 直接处理原 DWG） |
| AutoCAD COM 全部"拒绝接收呼叫" | SHX 字体弹窗阻塞 | 修 `acad.fmp` 字体映射（纯文件名 + 重启 AutoCAD） |
| `doc.ModelSpace` 报"被呼叫方拒绝接收呼叫" | Open 后未等加载 | `Documents.Open` 后 `time.sleep(2)`（管线已处理） |
| `InsertBlock` 报"图形文件标题无效" | 用 DXF 作块源 | 管线已先用 `SaveAs` 把 DXF 模板转 DWG 再插，无需手工处理 |
| 图框缩成一团 / 被压扁 | region 只取到标题栏内框 / 非等比缩放 | 检测完整外框；用 `min(W/tw,H/th)` 等比 |
| 第 N 张图丢失 | 替换后 frame 被过滤误删 | frame 标记策略保留 |
| 多图框误检（把端子 / 符号 / 表格单元当图框） | 电气图里大量闭合矩形 | 面积占比下限(0.15) + 双线去重两级过滤；注意**不能**用"长宽比接近 √2"筛（加长图幅很常见，按标准比例会误杀真框） |
| 边框 less / 全块化图纸识别不出框 | 当前检测器已知局限（负样本） | 案例十一（给煤机）正确判定"无有效图框、不改图"；案例十二（std_A3 分段边框、S7-1200 全块化）归档为已知局限，后续版本增强 |

其它要点：
- **打散旧图框（无块）**：靠"关键词 + 附近表格线"吸附定位，复杂图纸建议先用 `--detect-only` 人工确认区域；块图框识别最稳。
- **缩放策略**：默认 `min`（保比例、不拉伸变形、居中）。若觉得"图框偏小有留白"，用 `--fit max` 满填（约 2% 形变，可接受）。
- **多图框图纸**：建议先 `--detect-only` 看一下识别出的框数是否符合预期。
- 双线图框（外框 + 内框两条矩形）会被去重为外框，替换时一并清理内框残线。

---

## 8. 文件索引

| 文件 | 作用 |
|---|---|
| `run_skill.py` | **通用主入口**：`--template` + 旧图纸 → 新图纸（`--dwg` 切换 AutoCAD COM 策略二） |
| `run_real.py` | 案例一：SolidWorks 导出零件图批量置换（策略一） |
| `run_cng.py` | 案例二：CNG 电气系统图（策略一） |
| `run_ess.py` | 案例三：储能 ESS 图纸（策略一） |
| `run_asm.py` | 案例四：无图框装配体（策略二） |
| `run_synth.py` | 案例六：合成异常样本验证 |
| `run_multiframe.py` | 案例七：多图框逐框替换 |
| `run_real_mf.py` | 案例八：真实多图框（4×A1 拼接）端到端验证 |
| `run_residential.py` | 案例十：住宅楼电气 11 张 DWG（封装 `run_skill --dwg`） |
| `gui_app.py` | 图文界面主程序（复用 `run_skill.main`，需系统 Python 3.14） |
| `lib/finder.py` | 旧版图框检测（块式 / 线框 / 多图框层级）+ `extract_frame_fields`（真实图名提取） |
| `lib/sheet.py` | 幅面推断：图形尺寸 → 出图比例 → 标准 / 自定义幅面 |
| `lib/frame_gen.py` | 模板重定向：按旧框真实比例即时生成任意幅面模板 |
| `lib/block_replace.py` / `lib/raw_replace.py` | 策略一：删旧框 + 插入新框 + 回填字段 |
| `lib/acad_com.py` / `lib/acad_pipeline.py` | 策略二：AutoCAD COM 助手 / 通用 COM 流水线（plan→删框/插框/回填/SaveAs .dwg） |
| `lib/del_titleblock` 相关 | 只删旧图框层残线 + 标题栏字段标签文本，保留真实图元 |
| `templates/` | HH 公司图框模板 A0-A4 + A4V（DXF，COM 时即时转 DWG） |
| `cases/` | 12 套案例（输入 / 输出 / 对比图 / 报告 / verify） |
| `tests/` | 64 个用例（62 passed / 2 skipped），纯函数、内存构造最小 DXF，秒级跑完 |
| `MANUAL.md` | 本使用说明书 |
| `SKILL.md` | 可作为 WorkBuddy Skill 装载的说明 |

---

## 9. 测试与持续集成（改代码前必跑）

```bash
pip install -r requirements.txt -i https://pypi.org/simple
pytest -q        # 仓库根目录，pytest.ini 已配好
```
- 覆盖重点回归点：`delete_title_strip` 白名单（绝不误删尺寸线 / 几何 / 长格线）、`detect_frames_hierarchical` 多图框 + 全局占比护栏、`extract_frame_fields` 真实图名抽取路由、`lib/sheet.py` 幅面推断 + `lib/frame_gen.py` 模板重定向。
- `.github/workflows/test.yml` 在 push / 开 PR 时自动跑 `pytest`，任何让测试变红的提交都会被立刻拦下。

---

## 10. 把这个仓库当作 WorkBuddy Skill 装载（给他人 / 其他智能体用）

本仓库根目录已含 `SKILL.md`，克隆到本地后即可被 WorkBuddy 当作 skill 直接调用（对话里说"帮我换图框""图框置换"会自动触发）。
> ⚠️ GitHub 仓库**不能**被 WorkBuddy 直接"装载"——它只是源码托管。必须先把仓库放到 WorkBuddy 的 skills 目录下，或使用"文件夹导入"。

```bash
git clone https://github.com/nomadpanda1/cad-frame-replacement.git
# 个人全局（所有项目可用）：
cp -r cad-frame-replacement ~/.workbuddy/skills/cad-frame-replacement
# 或仅当前项目（团队协作）：
cp -r cad-frame-replacement <你的项目>/.workbuddy/skills/cad-frame-replacement
```
装载后对话中输入"把这套旧图纸换成公司图框"等，WorkBuddy 会读取 `SKILL.md` 并调用 `run_skill.py` 处理。公司图框模板变化时，只需替换 `templates/` 下文件并重跑，skill 逻辑零改动。
