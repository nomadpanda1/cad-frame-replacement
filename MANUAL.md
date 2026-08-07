# CAD 图框批量置换 · 使用手册（说明书）

> 对历史 CAD 图纸做"换芯手术"：识别旧图框 → 插入公司标准图框 → 无损迁移图号/图名/阶段/比例/日期等属性 → 输出符合标准的图纸。
> 适用：电气/电路图、零件图、装配图、设计院系统图等一切"换公司图框"场景。

---

## 0. 两条策略，先看清再选

| 策略 | 适用对象 | 核心引擎 | 稳定性 | 命令 |
|---|---|---|---|---|
| **一 · 普通图纸** | 自己导出的 DXF/DWG、无加密实体 | 纯 ezdxf 离线读→写 | 高（零 AutoCAD 依赖） | `python run_skill.py ...` |
| **二 · 加密/代理实体图纸** | 设计院原图（打开空白 `Drawing1`、报"解密数据时出错"） | ezdxf 提字段 + **AutoCAD COM 直接处理原 DWG** | 中（需 AutoCAD 已打开） | `python run_cng_acad.py` |

**怎么判断走哪条？** 先用策略一跑；若 AutoCAD 打开生成文件是空白/报错而 PNG 正常 → 原图含加密实体，改用策略二。

---

## 1. 环境准备

- **Python 3.13**（项目用 managed venv：`C:/Users/86308/.workbuddy/binaries/python/versions/3.13.12/python.exe`）
- **依赖**：`ezdxf`（已装）、`pywin32`（策略二需要，脚本里 `import win32com.client`）
- **AutoCAD 2026**：策略二必须**手动先打开**（脚本用 `GetActiveObject`，不自动启动实例）
- **字体映射**（策略二必做，否则 COM 卡死）：
  - 编辑 `acad.fmp`，格式严格 `原字体;替代字体`（分号紧贴无空格），替代字体只写纯文件名如 `simhei.ttf`
  - 改完**重启 AutoCAD** 生效；否则会一直弹 SHX 对话框 → COM 全部"拒绝接收呼叫"
- **公司图框模板**（WBLOCK 二进制 DWG）：`tpl_dwgs/HH_FRAME_*.dwg`
  - 若缺失，用 `python make_tpl_dwgs_wblock.py` 从 `HH_FRAME_*.dxf` 生成（magic=AC1032）
  - `InsertBlock` **不支持 DXF 源**，模板必须是 DWG

---

## 2. 快速开始

### 策略一 · 普通图纸（纯 ezdxf）
```bash
# 默认只输出 DXF
python run_skill.py --template templates/公司图框.dwg 图纸1.dwg 图纸2.dxf ...
# 完整 DWG（自动简化 + COM 转换，失败降级 DXF）
python run_skill.py --template templates/公司图框.dwg --dwg 图纸.dwg ...
```
- 模板"随时会变"：重跑自动适应（ATTDEF tag 或 `<图名>` 占位符都识别），代码零改动
- 输出 DXF（核心稳定）；DWG 需 COM 转换（不稳定，降级交付 DXF）

### 策略二 · 设计院加密 DWG（AutoCAD COM 直接处理）
```bash
# 前提：先手动打开 AutoCAD 2026
python run_cng_acad.py
# 产出 output_cng_acad/CNG_电气系统图_HH.dwg（可直接在 AutoCAD 打开）
```
- ezdxf 只读提取字段（`plan()`），删框/插框/回填全部由 `lib/acad_com.py` 经 AutoCAD COM 在原 DWG 副本上完成
- 换别的加密图纸：只改 `run_cng_acad.py` 里的 `plan()`（图框检测 + 字段提取），COM 通用函数零改动

---

## 3. 标准流程（设计院加密 DWG，逐步）

1. **准备输入**：原 DWG 放 `input_cng/`，其 ezdxf 可读 DXF 放 `dxf_cng/`（用 ODA/LibreCAD 转一份，仅用于字段提取，不写回）
2. **准备模板**：`tpl_dwgs/HH_FRAME_A0..A4/A3_WIDE.dwg`（WBLOCK 生成）
3. **手动打开 AutoCAD 2026**（关键，脚本不自动启动）
4. **运行**：`python run_cng_acad.py`
   - `plan()`：ezdxf 检测大坐标图框（LWPOLYLINE 闭合矩形）、按比例选模板、提取标题栏字段
   - COM 循环每个图框：`del_frame_edges` 删外框线 → `del_in_region` 删会签栏 → `insert_frame` 插公司图框块并回填属性
5. **保存**：`doc.Save()` 在副本上保存（不用 SaveAs，format 本机失效）
6. **验收**：用 AutoCAD 打开 `output_cng_acad/CNG_电气系统图_HH.dwg`，确认不再是空白

> 关键约束（逐一踩过）：打开副本后 `time.sleep(2)` 等加载；实体 bbox 用 `GetBoundingBox()`；插入点用 `VARIANT(VT_ARRAY|VT_R8,[x,y,0])`；属性用 `insert.GetAttributes()` 的 `.TextString` 写。

---

## 4. 模板规范

- **命名**：`HH_FRAME_<尺寸>.dwg`，尺寸 ∈ {A0, A1, A2, A3, A3_WIDE, A4}
- **尺寸表**（毫米，用于按外框比例选模板 + 等比缩放）：

  | 名称 | 宽×高 | 比例 | 备注 |
  |---|---|---|---|
  | A0 | 1189×841 | 1.41 | |
  | A1 | 841×594 | 1.41 | |
  | A2 | 594×420 | 1.41 | |
  | A3 | 420×297 | 1.41 | 标准 |
  | A3_WIDE | 604×299 | 2.02 | 自定义加长横条 |
  | A4 | 297×210 | 1.41 | |

- **字段（ATTDEF tag）**：`TITLE`(图名) / `DWG_NO`(图号) / `STAGE`(阶段) / `MATERIAL`(材料/专业) / `SCALE`(比例) / `DATE`(日期) 等
- **多比例外框 → 多模板匹配**：标准 A 系列覆盖不了自定义宽图框（如 A3_WIDE）。`run_skill.py` 自动加载 `HH_FRAME_*.dxf` 全部模板，按 region 比例匹配最合适者（差异超阈值 0.25 才切换备选）
- **缩放原则**：`scale = min(W/tw, H/th)` 等比缩放，保持模板自身比例不变，不压扁标题栏；region 必须是**完整图框外框**，不能只用标题栏内框

---

## 5. 故障排查表

| 现象 | 原因 | 解决 |
|---|---|---|
| 打开生成文件是空白 `Drawing1`、报"解密数据时出错" | 原图含加密/代理实体，ezdxf 写回破坏 | 改用策略二（AutoCAD COM 直接处理原 DWG） |
| AutoCAD COM 全部"拒绝接收呼叫" | SHX 字体弹窗阻塞 | 修 `acad.fmp` 字体映射（纯文件名+重启 AutoCAD） |
| `doc.ModelSpace` 报"被呼叫方拒绝接收呼叫" | Open 后未等加载 | `Documents.Open` 后 `time.sleep(2)` |
| `InsertBlock` 报"图形文件标题无效" | 用 DXF 作块源 | 改用 WBLOCK 生成的 `.dwg` 模板 |
| `e.GeometricExtents` AttributeError | COM 实体无此属性 | 改用 `e.GetBoundingBox()` |
| SaveAs 写出的是 DXF 不是 DWG | 本机 SaveAs format 失效 | 用 `doc.Save()` 保存在已打开副本上 |
| 图框缩成一团/被压扁 | region 只取到标题栏内框 / 非等比缩放 | 检测完整外框；用 `min(W/tw,H/th)` 等比 |
| 第 N 张图丢失 | 替换后 frame 被 strong 过滤误删 | frame 标记 `"frame"` 策略保留 |
| 底部电路标注被删空 | 按百分比删"表格"误伤 | 仅删外框边界 + 精确标题栏区域，保留电路几何 |

更完整的 30+ 条踩坑见 `../.workbuddy/skills/cad-frame-replace/SKILL.md` 的"本机关键踩坑"。

---

## 6. 输出文件说明

- `output_cng_acad/CNG_电气系统图_HH.dwg` —— 成品（可直接 AutoCAD 打开，magic=AC1032）
- `output_cng_acad/plan.json` —— 图框检测 + 字段提取计划
- `output_cng_acad/results.json` —— 每图框删除数 / 缩放 / 回填结果
- `output_real/*_HH.dxf` —— 策略一产出的普通图纸换框结果
- `cases/` —— 案例集（`01_SW_parts` 9 张零件图 / `02_CNG_electrical` 电气系统图 / `03_ESS_cad` 储能成果包 4 张 / `04_assembly` 无图框装配体 1 张 / `06_synth` 合成异常样本 4 类 / `07_multiframe` 多图框逐框替换 2 类），含 `index.html` 与 `report.html` 对比图

---

## 7. 文件索引

| 文件 | 作用 |
|---|---|
| `run_skill.py` | 策略一主入口（纯 ezdxf 离线） |
| `run_cng_acad.py` | 策略二主入口（加密 DWG，CNG 特定 plan） |
| `lib/acad_com.py` | 策略二核心：AutoCAD COM 通用函数库 |
| `lib/acad.py` | DWG↔DXF 转换（ODA/LibreCAD） |
| `lib/template_learn.py` | 模板自动学习（不硬编码） |
| `lib/block_replace.py` | 语义概念映射 + bbox 删旧框 + INSERT 块 |
| `lib/finder.py` | 多层图框识别（block/text/geometry，置信度评分） |
| `lib/extract.py` | 属性提取（ATTRIB + TEXT/MTEXT 键值对） |
| `make_tpl_dwgs_wblock.py` | 用 WBLOCK 把模板块写成二进制 DWG 模板 |
| `run_ess.py` | 储能 ESS 成果包专用脚本（策略一：纯 ezdxf，A1 外框 + 右下角标题条 → HH_FRAME_A1） |
| `run_asm.py` | 无图框装配体专用脚本（策略二：COM 转 DXF + 清标题栏占位 → HH_FRAME_A3） |
| `gen_synth.py` | 程序化生成异常场景测试样本（06a 多图框 / 06b 嵌套块 / 06c 缺字体 / 06d 会签栏差异），输出到 `cases/06_synth/inputs/` |
| `run_synth.py` | 对合成样本跑工具验证，输出 before/after 对比 + `results.json` 行为结论到 `cases/06_synth/outputs/` |
| `gen_mf_samples.py` | 程序化生成多图框逐框替换测试样本（07a 平铺含整图纸框 / 07b 并排无整图纸框），输出到 `cases/07_multiframe/inputs/` |
| `run_multiframe.py` | 多图框逐框替换 runner：检测帧层级 → 逐框选模板 → 抽字段 → 删旧框线+标题栏 → 插公司图框(fit=max) → 回填，输出 before/模板/after + `results.json` 到 `cases/07_multiframe/outputs/` |
| `MANUAL.md` | 本使用手册 |
| `cases/report.html` | 案例对比报告（生成前/模板/生成后） |

---

## 8. 异常场景 · 无图框 / 无标题栏图纸

部分图纸（如某些装配体、白模导出图）**没有旧图框矩形、也没有 TEXT 标题栏**——只有零散零件几何 + 右下角零散标注。这类图不能直接"删旧框"，否则无物可删；直接插公司图框又会和右下角标注重叠。

**处理方式（以 `run_asm.py` 为例）：**
1. 用 AutoCAD COM `SaveAs(fmt=1)` 把二进制 DWG 转成 ezdxf 可读的 ASCII DXF（本机 SaveAs format 参数生效，区别于设计院加密图）；
2. 计算公司模板标题栏矩形（模板里面积最小的闭合 LWPOLYLINE，A3 下约 `x[235,415] y[6,62]`）；
3. **清标题栏占位**：删除该矩形内所有原始实体（实测 63 个，均为 4×5~37×5 的小标注/尺寸文本，非零件主体）；
4. 插入 `HH_FRAME_A3`（`fit="max"` 近 1:1），14 个字段全部建为**可编辑空占位**（见 `lib/block_replace.py` 改动：值缺失时写空串而非跳过，保证标题栏在 CAD 里可双击编辑）。

> 注意：清理前务必确认该区域确为"应让位于标题栏"的零散标注，而非关键尺寸线。生产环境建议把清理矩形做成参数，并对被删实体做白名单/数量告警。

---

## 9. 异常场景 · 合成样本测试包（案例六 `06_synth`）

真实"多样化异常图"（不同设计院标题栏、多种加密、缺字体、嵌套块、多图框混排、会签栏差异）难以从公开网络批量获取，因此用 `gen_synth.py` **程序化生成可控、可复现**的异常 DXF，再用 `run_synth.py` 跑全流程验证工具行为。当前覆盖四类：

| 样本 | 异常点 | 工具实际行为 | 结论 |
|---|---|---|---|
| `06a` 多图框混排 | 一张 A1 内含 A3/A4/A1 三张小图框 | 检测到 4 个闭合矩形；当前按**整图幅**插 1 张公司图框 | ⚠ 历史局限（**已在案例七解决**）：现已支持逐图框替换 |
| `06b` 嵌套块标题栏 | 标题栏=块，内部又 INSERT 含 ATTDEF 的子块 | `learn_template` 正确穿透到子块，识别 9 字段 | ✅ 支持嵌套块 |
| `06c` 缺字体(SHX) | TEXT 引用不存在字体 `hzdx_ghost.shx` | 文字串照常抽取、渲染不崩溃（matplotlib 回退默认字体） | ✅ 缺字体不影响处理 |
| `06d` 会签栏差异 | 标题栏多出"会签"列 | 图名/图号/比例/阶段 仍按标签正确抽取 | ✅ 会签栏差异不影响映射 |

> 加密/代理实体 DWG 无法用 ezdxf 合成真实代理实体，该类异常由**案例二 CNG**（设计院含代理实体 DWG，策略二 COM 直接处理）覆盖。

生成 / 验证命令：
```bash
python gen_synth.py     # 生成 06a~06d 到 cases/06_synth/inputs/
python run_synth.py     # 跑验证，输出 before/after + results.json 到 cases/06_synth/outputs/


---

## 10. 多图框逐框替换（案例七 `07_multiframe` · 开发项成果）

一张图纸内含多个图框（平铺子图、并排多图）时，需要**逐框**插入公司图框并分别回填，而不是整图幅插一张。

### 10.1 核心函数

**`lib/finder.py` · `detect_frames_hierarchical(doc)`** → `(sheet_bbox_or_None, [target_frame_bbox, ...])`
- 收集 modelspace 所有闭合矩形（轴对齐、side>80、area>5000）；
- 若存在"整图纸框"（bbox 包含其它所有框且面积明显更大），判定为**纸边 sheet**，不作为替换目标；
- 其余为**替换目标**；并排多框（互不包合）则**全部**为目标；
- 只有 1 个框时退化为单框替换（兼容旧行为）。

**`lib/finder.py` · `extract_frame_fields(doc, frame_bbox)`** → `{concept: value}`
- 在单个图框的右下角标题区（右 45% × 底 60%）抽取 图名/图号/比例/阶段；
- 支持两种写法：① 合并文本 `"图名：减速器"`（冒号后取值）；② 标签与值分两个 TEXT（按同行右侧配对）；
- 未抽到图名时用标题区最长文本兜底。

**`lib/block_replace.py` · `delete_frame_border(doc, frame_bbox)`** → 删除数
- 只删除与该帧 bbox 重合的闭合矩形**旧边框**，不动图内几何（外科手术式）。

**`lib/block_replace.py` · `delete_title_strip(doc, frame_bbox, strip_ratio=0.28)`** → 删除数
- 只删除该帧右下角标题区（右 45% × 底 28%）内**完全落在该区**的实体（旧标题栏线+文本）；
- 保留图内几何；已知局限：若图内尺寸线恰好落在右下角标题区也会被删，生产环境建议加白名单/数量告警。

### 10.2 处理流程（`run_multiframe.py`）
1. `detect_frames_hierarchical` 得到 sheet（可能 None）与 targets；
2. 对每个 target：按宽高比 `pick_template(fb)` 选最近 A 幅面模板 → `learn_template` → `extract_frame_fields` 抽字段 → `mapper.map_fields` 对齐；
3. `delete_frame_border` + `delete_title_strip` 清旧框线+旧标题栏；
4. `insert_template(..., fit="max")` 插公司图框（填满该帧 bbox），14 字段回填（缺失写空占位）；
5. 渲染 before/模板/after + 写 `results.json` 与 `index.html`。

### 10.3 测试结果
| 样本 | 场景 | 检测结果 | 结论 |
|---|---|---|---|
| `07a` | 平铺多框（含整图纸框） | sheet=(0,0)-(841,594)；3 个子框全部逐框替换，字段正确回填 | ✅ 纸边保留、子框各插公司图框 |
| `07b` | 并排多框（无整图纸框） | sheet=None；4 个 A3 框全部为目标，逐框替换成功 | ✅ 覆盖 CNG 真实场景的"无整图纸框"分支 |

```bash
python gen_mf_samples.py   # 生成 07a/07b 到 cases/07_multiframe/inputs/
python run_multiframe.py   # 逐框替换，输出 before/模板/after + results.json 到 cases/07_multiframe/outputs/
```
```

