# CAD 电路图图框批量置换工具

把历史 CAD 电路图纸上的旧图框，自动换成你们公司的标准图框，并**无损迁移**旧图框里的字段
（图名 / 图号 / 比例 / 阶段 / 日期 / 设计人 …）。支持批量处理，公司图框**随时会变**——换模板重跑即可，代码零改动。

纯 [ezdxf](https://ezdxf.readthedocs.io/) 离线核心，不依赖 AutoCAD，跨平台可跑。

---

## 🚀 案例与效果（先看这里）

本仓库自带 **7 套完整案例**，覆盖真实机械图纸、电气系统图、储能图纸、装配体、合成异常样本以及多图框逐框替换：

- 📊 **[cases/report.html](cases/report.html)** —— 完整效果对比报告（含 54 张前后对比图 + 使用说明）
- 📦 **[cases/showcase.html](cases/showcase.html)** —— 单文件离线版，图片全部内嵌，可直接下载发微信/邮件
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
<td align="center"><b>案例六：合成异常样本</b></td>
<td><img src="cases/06_synth/outputs/06a_before.png" width="380" alt="before"></td>
<td><img src="cases/06_synth/outputs/06a_after.png" width="380" alt="after"></td>
</tr>
<tr>
<td align="center"><b>案例七：多图框逐框替换</b></td>
<td><img src="cases/07_multiframe/outputs/07b_side_by_side_before.png" width="380" alt="before"></td>
<td><img src="cases/07_multiframe/outputs/07b_side_by_side_HH.png" width="380" alt="after"></td>
</tr>
</table>

### 📌 案例修复记录（v0.2）

以下两处早期版本观感/逻辑有问题，已在当前版本修复并通过测试：

- **案例四 · 无图框装配体（已修复 ✅）**
  旧版 `clear_title_block_zone` 用「相交即删」且无白名单，会把右下角 BOM 表 / 原标题栏一并清掉，导致 HH 框盖在残留元素上（既丢数据又重叠）。
  **修复**：清理逻辑改为白名单（只删文字 + 旧标题框闭合矩形，绝不碰线 / 几何 / 尺寸 / BOM）；并新增「标题区已有内容 → 只加外框、保留原标题栏」分支。实测装配体 4109 个实体零删除，原图完整保留。

- **案例六 · 合成异常样本（已修复 ✅）**
  - **06a 多图框混排**：旧版按「整图幅」插一张 A1 框，子图框没动，看起来像没处理完。现已复用案例七的逐框替换逻辑，after 图含 3 个 HH_FRAME INSERT，真正逐框替换（「多图框混排」不再是局限）。
  - **06b 嵌套块 / 06d 会签栏**：插入公司框前先清理旧标题栏（删除旧 TITLEBLOCK 块、白名单清旧标题条），消除新旧标题栏重叠。

---

## 0. 准备
- Python 3.13（已装 ezdxf 1.4.x）
- 运行环境：
  ```
  C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  ```
- 依赖安装：`pip install -r requirements.txt`

## 1. 目录结构
```
cad-frame-replacement/
├── run_skill.py            # 通用主入口：template + 旧图纸 → 新图纸
├── run_real.py             # 案例一：SolidWorks 导出零件图批量置换
├── run_cng.py              # 案例二：CNG 电气系统图
├── run_cng_acad.py         # 案例二（AutoCAD COM 解密 DWG 版本）
├── run_ess.py              # 案例三：储能 ESS 图纸
├── run_asm.py              # 案例四：无图框装配体
├── run_synth.py            # 案例六：合成异常样本验证
├── run_multiframe.py       # 案例七：多图框逐框替换
├── gen_synth.py            # 生成合成异常样本图纸
├── gen_mf_samples.py       # 生成多图框测试样本
├── make_tpl_dwgs*.py       # 生成 HH 公司图框模板
├── lib/                    # 核心库
│   ├── concepts.py         # 中英文/简写字段名 -> 统一“概念”中间层
│   ├── template_learn.py   # 模板自动学习（块 ATTDEF / 打散 <图名> 占位符）
│   ├── finder.py           # 旧版图框检测（块名 / 关键词+表格线吸附）
│   ├── extract.py          # 旧图属性提取（ATTRIB / TEXT 键值对）
│   ├── mapper.py           # 概念级字段映射
│   ├── block_replace.py    # 删旧框 + 插入新框 + 回填字段
│   ├── acad.py             # DWG <-> DXF 转换器探测（ODA / LibreCAD）
│   └── logbook.py          # 执行日志 + run_report.json
├── templates/              # HH 公司图框模板 A0-A4
├── cases/                  # 7 套案例（输入/输出/对比图/报告）
│   ├── report.html         # 完整对比报告
│   ├── showcase.html       # 单文件内嵌图片版
│   ├── index.html          # 案例导航页
│   ├── 01_SW_parts/        # 真实机械零件图
│   ├── 02_CNG_electrical/  # CNG 电气系统图
│   ├── 03_ESS_cad/         # 储能 ESS 图纸
│   ├── 04_assembly/        # 无图框装配体
│   ├── 06_synth/           # 合成异常样本
│   └── 07_multiframe/      # 多图框逐框替换
├── samples/                # 通用：放“待处理的旧图纸”
└── output/                 # 通用：生成的成品（原名 + _HH 后缀，不覆盖原图）
```

## 2. 快速开始（跑案例）
```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 跑一个案例
python run_real.py      # 案例一：9 张 SW 零件图
python run_cng.py       # 案例二：CNG 电气系统图
python run_ess.py       # 案例三：ESS 储能
python run_asm.py       # 案例四：无图框装配体
python run_synth.py     # 案例六：合成异常样本
python run_multiframe.py # 案例七：多图框逐框替换

# 3) 看报告
cases/report.html       # 浏览器打开
```

## 3. 跑自己的图纸
```bash
# 默认：输出 DXF（核心稳定）
python run_skill.py --template templates/公司图框.dxf  samples/*.dxf

# 多张混批
python run_skill.py --template templates/公司图框.dxf  samples/old1.dxf samples/old2.dxf

# 需要 DWG 输入输出（依赖本机 ODA File Converter / LibreCAD）
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
| `--dwg` | 输出 DWG（需转换器） |
| `--fit` | 新框缩放：`min` 保比例居中(默认) / `max` 满填 / `width` / `height` |
| `--margin` | 打散图框删除边距 |
| `--override` | 字段映射覆盖，如 `{"TITLE":"OLD_TITLE"}` |
| `--detect-only` / `--dry-run` | 分阶段调试 |

## 4. 公司图框“随时会变”怎么办
**什么都不用改代码**，只要：
1. 用新版公司图框覆盖 `templates/` 下的模板文件（块名、字段措辞、字段增减都行）；
2. 重新跑一次 `run_skill.py`。

模板学习是**全自动**的：块模板读 ATTDEF，打散模板读 `<图名>` 占位符；字段按“概念”对齐
（图名↔TITLE、图号↔DWG_NO …），中英文/简写都能对上。新模板多出来的字段，旧图没有对应来源的会自动留空。

## 5. 输出与校验
- 每个源图生成 `原名_HH.dxf`（原文件永不覆盖）。
- `output/Execution_Log.csv`：逐张执行记录（检测数 / 删除实体 / 回填字段 / 状态）。
- `output/run_report.json`：完整报告，含每张图的字段提取与映射明细，便于核对。

## 6. 已知约束
- **DWG 需要转换器**：ezdxf 只能读写 DXF。输入 DWG 会先转 DXF 再处理；输出 DWG 用
  ODA File Converter / LibreCAD。本机没装转换器时，DWG 输入会提示先转 DXF，输出只给 DXF。
- **打散旧图框（无块）**：靠“关键词+附近表格线”吸附定位，复杂图纸建议先用 `--detect-only`
  人工确认区域；块图框识别最稳。
- **缩放策略**：默认 `min`（保比例、不拉伸变形、居中）。若觉得“图框偏小有留白”，
  用 `--fit max` 满填（横向可能略溢出进上方电路，约 2% 形变，可接受）。
- ATTRIB 是 INSERT 的嵌套子实体，不会出现在 modelspace 顶层迭代里；校验请用
  `insert.attribs` 读取，不要用 `msp` 遍历计数。

---

## 7. 本分发版包含内容
- **核心**：`lib/`（图框检测、字段提取映射、替换、模板学习）
- **模板**：`templates/`（HH 公司图框 A0-A4）
- **7 套完整案例**：`cases/01_SW_parts`、`cases/02_CNG_electrical`、`cases/03_ESS_cad`、
  `cases/04_assembly`、`cases/06_synth`、`cases/07_multiframe`，每套含输入图纸、输出成品、前后对比 PNG
- **报告**：`cases/report.html`（链接图）、`cases/showcase.html`（内嵌图单文件）、`cases/index.html`
- **入口脚本**：全部 `run_*.py` / `gen_*.py` / `make_*.py`
- **其他**：`requirements.txt`、`.gitignore`

> 案例中的真实图纸（01–04、CNG）已做脱敏处理；如你手上有更敏感的设计院图纸，请参照 `run_skill.py` 自行处理，不要直接上传到公开仓库。

---

## 8. 把这个仓库当作 WorkBuddy Skill 装载（给他人 / 其他智能体用）

本仓库根目录已包含 `SKILL.md`，因此**克隆到本地后即可被 WorkBuddy 当作 skill 直接调用**
（对话里说"帮我换图框""图框置换"会自动触发）。

> ⚠️ GitHub 仓库**不能**被 WorkBuddy 直接"装载"——它只是源码托管。必须先把仓库放到
> WorkBuddy 的 skills 目录下，或使用"文件夹导入"。

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

- 对话中输入"把这套旧图纸换成公司图框""批量换图框"等，WorkBuddy 会读取 `SKILL.md` 并
  调用 `run_skill.py` / `run_multiframe.py` 等入口，按本仓库流程处理。
- 给**其他用户 / 其他机器**用：把仓库 clone 到他们的 skills 目录即可，无需改任何代码。
- 公司图框模板变化时，只需替换 `templates/` 下文件并重跑，skill 逻辑零改动。

---

## 9. 测试与持续集成（CI 回归保护）

改 `lib/`、`run_*.py` 或在真实图纸上修 bug 时，**务必先跑测试**，避免误删 / 误判被悄悄带上线。

### 本地跑测试
```bash
# 1) 装开发依赖（含 pytest；ezdxf 已在 requirements.txt）
pip install -r requirements.txt

# 2) 运行（仓库根目录，pytest.ini 已配好）
pytest -q
```
- 17 个用例，全部纯函数、内存构造最小 DXF，**不依赖任何外部图纸 / 模板**，秒级跑完。
- 覆盖重点回归点：
  - `delete_title_strip` 白名单——**绝不误删尺寸线 / 几何 / 长格线**（最早出过 bug 的地方）；
  - `detect_frames_hierarchical` 多图框层级检测（单框 / 拼贴含子框 / 并排多框）；
  - `extract_frame_fields` 与字段抽取路由（比例 / 材料 / 图号 / 重量 / 图名高置信识别）。

### CI 自动回归
`.github/workflows/test.yml` 在 **push / 开 PR 时自动触发**，于 ubuntu + Python 3.13 跑 `pytest`。
任何让测试变红的提交都会被立刻拦下，等于给「修 bug」上了回归保护。

### 装包提示（环境）
本机 pip 全局镜像（清华源）个别时段不可用，装包请改用官方源：
```bash
pip install -r requirements.txt -i https://pypi.org/simple
```
