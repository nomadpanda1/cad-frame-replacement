# 测试与验证总录（TESTS.md）

本文件汇总本项目全部**自动化单元测试**与**案例验证结论**，作为「所有测试写入案例」的归口文档。
案例级详情见各 `cases/NN_*/summary.md`；对比图见 `cases/report.html` 与 `cases/showcase.html`。

---

## 一、自动化单元测试（pytest）

- 运行环境：本仓库使用 managed venv 的 `pytest 9.1.1`（`C:\Users\86308\.workbuddy\binaries\python\envs\default`）。
- 运行命令：`python -m pytest tests/ -q`
- 当前结果：**37 passed**（8 个测试文件）。

| 测试文件 | 数量 | 覆盖点 |
|----------|------|--------|
| `tests/test_acad_pipeline.py` | 6 | AutoCAD COM 管线：图幅推断（A3 横/A4 竖/A1）、空字段跳过、按映射块/原始图框构建执行计划 |
| `tests/test_block_replace.py` | 4 | 标题栏占位删除（保留跨边界尺寸线、保留框外文本）、仅删匹配闭合矩形的边框、变换缩放与居中计算 |
| `tests/test_concepts.py` | 4 | 标题栏概念推断（中/英/带前缀冒号/垃圾串返回 None） |
| `tests/test_detect_segmented_frame.py` | 1 | 分段短直线边框重建为整框 |
| `tests/test_extract.py` | 5 | 字段抽取启发式：比例/物料/图号/重量/名称判定 |
| `tests/test_finder.py` | 11 | 层级检测（单框/整图+子框/并排）、字段抽取与防越界泄漏、双线边框去重、最小面积占比过滤小符号、`detect` 不误检（CNG 类/无框密集小方框） |
| `tests/test_raw_frame_fallback.py` | 2 | 线框回退取最大外框、插入区域用外框而非整图 |
| `tests/test_run_skill.py` | 4 | `run_skill` 单/多文档自动判定与强制模式 |

### 与案例绑定的关键回归测试
- `test_finder.py::test_detect_no_false_positive_like_cng` — 案例二 CNG 误检治理（61→4）。
- `test_finder.py::test_no_false_positive_borderless_dense` — 案例十一 给煤机无框密集小方框加固（15→0）。
- `test_finder.py::test_extract_no_leak_from_neighbor_frame` — 案例八 多图框字段越界泄漏修复。
- `test_block_replace.py::test_delete_title_strip_preserves_dimension_and_skips_long_line` — 标题栏删框残留治理（跨边界长线保护）。

---

## 二、案例验证结论（12 个案例）

| # | 案例 | 输入 | 策略 | 验证结论 |
|---|------|------|------|----------|
| 01 | SolidWorks 零件/装配图 | 9 张 DXF | 策略一(纯 ezdxf) | ✅ 9/9 换框成功，字段回填 |
| 02 | CNG 电气系统图（设计院） | 2 张 | 策略二(COM) | ✅ 2/2，误检治理后干净 |
| 03 | 储能 ESS 成果包 | 4 张 DXF | 策略一 | ✅ 4/4，A1 闭合多段线外框 |
| 04 | 装配体图纸（无框） | 1 张 DWG | 策略二 | ✅ 无框鲁棒性：清 63 占位+插空 A3 框 |
| 05 | 标准设计院 92DZ1 | 1 张 DWG | 策略二 | ✅ 4 图框 PUB_TITLE 层逐框替换 |
| 06 | 合成异常样本 | 4 子样本 | 策略一 | ✅ 06b/06c/06d 通过；**06a 不逐图框替换为已知局限** |
| 07 | 多图框逐框替换 | 2 子样本 | 策略一 | ✅ 07a 纸边保留、07b 无整图纸框分支均通过 |
| 08 | 真实多图框端到端 | 4 框(ESS 拼) | 策略一 | ✅ 真实字段全对；修复字段越界泄漏 bug |
| 09 | 馈电电气原理图 | 1 张 DWG | 策略二 | ✅ A4 竖版 BORDER 层双线图框兼容 |
| 10 | 住宅楼电气设计方案 | 11 张 DWG | 策略二(COM) | ⚠️ 换框 11/11 成功，**深度核验发现 3 类未完工缺陷**（见下） |
| 11 | 给煤机控制原理图 | 1 张 DWG | 策略二 | ✅ 正确判定「无框可换」(0 框不改图) + 检测器加固 |
| 12 | 检测负样本 | 2 张 DWG | — | 📌 已知局限：S7-1200 全块化漏检 / std_A3 分段边框覆盖不足漏检 |

### 案例十深度核验结论（2026-08-12，重要）
浅核验曾记「11/11 完成、残留=0」为**假零**（核验脚本 `e.bbox()` 在 ezdxf 1.4.4 无此方法、异常被吞）。
深度核验（改用 `ezdxf.bbox.extents`）发现 3 类真实未完工：
1. **标题栏属性空/错填 11/11** —— 旧框字段未正确迁移到 HH_FRAME 属性。
2. **旧框残线 2 张** —— 双线图框内框未删净，压在新框上。
3. **非 √2 比例失真 3 张** —— 原图幅非标准比例，整图幅 fit=max 插入导致形变。

→ 案例十属「换框成功但非完工」，待补：标题栏字段映射、加强旧框删除、非 √2 图幅处理。详见 `cases/10_residential_electrical/summary.md` 与 `verify/verify_deep.json`。

---

## 三、如何复现
```bash
# 单元测试
python -m pytest tests/ -q

# 案例报告页（聚合 before/template/after 对比）
python cases/gen_report.py      # 生成 cases/report.html
python cases/make_showcase.py   # 生成 cases/showcase.html

# 单案例重跑（示例：案例十深度核验）
python verify_case10_deep.py
python verify_case10_fast.py
```
