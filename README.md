# CAD 电路图图框批量置换工具

把历史 CAD 电路图纸上的旧图框，自动换成你们公司的标准图框，并**无损迁移**旧图框里的字段
（图名 / 图号 / 比例 / 阶段 / 日期 / 设计人 …）。支持批量处理，公司图框**随时会变**——换模板重跑即可，代码零改动。

纯 [ezdxf](https://ezdxf.readthedocs.io/) 离线核心，不依赖 AutoCAD，跨平台可跑。

---

## 0. 准备
- Python 3.13（已装 ezdxf 1.4.x）
- 运行环境：
  ```
  C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  ```

## 1. 目录结构
```
cad-frame-replacement/
├── run_skill.py            # 主入口
├── generate_demo.py        # 生成演示数据（公司图框模板 + 带旧图框的样例图纸）
├── lib/
│   ├── concepts.py         # 中英文/简写字段名 -> 统一“概念”中间层
│   ├── template_learn.py   # 模板自动学习（块 ATTDEF / 打散 <图名> 占位符）
│   ├── finder.py           # 旧版图框检测（块名 / 关键词+表格线吸附）
│   ├── extract.py          # 旧图属性提取（ATTRIB / TEXT 键值对）
│   ├── mapper.py           # 概念级字段映射
│   ├── block_replace.py    # 删旧框 + 插入新框 + 回填字段
│   ├── acad.py             # DWG <-> DXF 转换器探测（ODA / LibreCAD）
│   └── logbook.py          # 执行日志 + run_report.json
├── templates/              # ← 放“公司图框模板”
├── samples/                # ← 放“待处理的旧图纸”
└── output/                 # 生成的成品（原名 + _HH 后缀，不覆盖原图）
```

## 2. 你们的输入
1. **公司图框模板**：做成“块(Block) + ATTDEF 属性”的 DXF/DWG（这是 CAD 里最标准、最推荐的方式）。
   - 每个 ATTDEF 的 `Tag` 用英文（如 `TITLE`/`DWG_NO`/`SCALE`/`STAGE`/`DATE`/`DESIGN` …），
     `Prompt` 写中文（如 “图名”/“图号”）。
   - 放到 `templates/` 下，例如 `templates/公司图框.dxf`。
   - 也支持**打散模板**：用 `<图名>` `<图号>` 这类占位符文本 + 帧几何（无块）。
2. **历史图纸**：放到 `samples/`（或任意路径，支持 `*.dxf` / `*.dwg` 通配符）。

> 旧图框只要能被识别即可（块名命中、或图框里有“图名/图号”等关键词）。识别不到时可用
> `--detect-only` 生成 `detection.json`，人工确认后（标记 `"confirmed": true`）再跑。

## 3. 运行
```bash
# 进入工程目录
cd cad-frame-replacement

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
