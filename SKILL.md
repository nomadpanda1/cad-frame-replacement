---
name: cad-frame-replacement
description: 'This skill should be used when the user needs to replace old CAD drawing title blocks or frames (图框) with a company-standard frame and migrate the title-block fields (图名/图号/比例/阶段/设计/审核/日期 etc.) without loss. Supports batch processing, swappable company templates (no code change, rerun to switch), multi-frame per-frame replacement, frameless drawings, and synthetic anomaly samples. Pure ezdxf, no AutoCAD dependency. Triggers include 换图框, 图框置换, 替换CAD图纸图框, 图纸换公司框, CAD frame replacement, title block migration, 批量换图框.'
agent_created: true
---

# CAD 图框批量置换

把历史 CAD 图纸上的旧图框换成公司标准图框，并无损迁移标题栏字段。支持批量处理、模板可换
（重跑即换、零改码）、多图框逐框替换、无图框装配体、合成异常样本。纯 ezdxf 离线核心，
不依赖 AutoCAD。

## 何时使用

- 用户持有旧 CAD 图纸（DXF / DWG），需要统一换成公司标准图框并保留图名 / 图号 / 比例 /
  阶段 / 设计 / 审核等字段。
- 触发词：换图框、图框置换、替换 CAD 图纸图框、图纸换公司框、CAD frame replacement、
  title block migration、批量换图框。

## 依赖与环境

- Python 3.13 + ezdxf >= 1.4.0（纯离线核心，不依赖 AutoCAD）。
- DWG 输入 / 输出需要本机 ODA File Converter 或 LibreCAD（见 `README.md` §6）。无转换器时
  仅处理 DXF；DWG 输入会先转 DXF。
- 运行环境示例（替换为当前机器的 python）：
  `C:/Users/86308/.workbuddy/binaries/python/envs/default/Scripts/python.exe`

## 通用调用方式

使用 `run_skill.py` 作为主入口，以 `templates/` 下的公司图框为模板：

```
python run_skill.py --template templates/[公司图框].dxf [旧图纸...]
```

常用参数：
`--out` 输出目录（默认 `output/`）、`--suffix _HH`、`--fit min|max|width|height`、
`--dwg`（输出 DWG）、`--detect-only`（只检测不改图）、`--dry-run`（只提取+映射预览）。

## 各案例入口（均在仓库根）

| 脚本 | 用途 |
|---|---|
| `run_real.py` | 案例一：SolidWorks 导出零件 / 装配图批量置换 |
| `run_cng.py` / `run_cng_acad.py` | 案例二：CNG 电气系统图（后者走 AutoCAD COM 解密 DWG） |
| `run_ess.py` | 案例三：储能 ESS 设备表 |
| `run_asm.py` | 案例四：无图框装配体（白名单保护，保留原 BOM / 标题栏） |
| `run_synth.py` | 案例六：合成异常样本（多图框 / 嵌套块 / 缺字体 / 会签栏） |
| `run_multiframe.py` | 案例七：多图框逐框检测 → 逐框插公司框 → 逐框回填 |

## 核心库（lib/）

- `finder.py` — 旧图框检测（块名 / 关键词 + 表格线吸附 / 多图框层次检测）
- `extract.py` — 旧图属性提取（ATTRIB / TEXT 键值对）
- `mapper.py` + `concepts.py` — 概念级字段映射（中英文 / 简写对齐）
- `block_replace.py` — 删旧框 + 插新框 + 回填；`delete_title_strip` 白名单避免误删尺寸线 / BOM
- `template_learn.py` — 模板自动学习（块 ATTDEF / 打散占位符）

## 关键约束与已知行为

- 标题栏清理用白名单：仅删除文字与旧标题框闭合矩形，绝不触碰 DIMENSION / 线 / 几何 / BOM。
  检测到标题区已有内容时只加外框、保留原内容（案例四已验证零数据丢失）。
- `--fit max` 满填约 2% 形变；默认 `min` 保比例居中。
- 多图框图纸用 `run_multiframe.py` 逐框处理；整图幅插框会遗漏子图框。
- ATTRIB 是 INSERT 的嵌套子实体，校验请用 `insert.attribs` 读取，勿用 modelspace 顶层遍历计数。

## 参考文档

- `README.md` — 完整使用说明、案例与效果缩略图、已知约束、修复记录。
- `MANUAL.md` — 详细操作手册（各案例复现命令、模板学习机制、边界情况）。
- `cases/report.html` / `cases/showcase.html` — 前后对比报告（各 54 张图）。
