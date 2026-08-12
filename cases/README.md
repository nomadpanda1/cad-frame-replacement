# CAD 图框批量置换 · 案例集（cases/）

本目录收纳「CAD 电路图通用图框批量置换与属性智能迁移」项目的全部验证案例与产物。
顶层说明见仓库 `README.md`；测试总录见 [`TESTS.md`](TESTS.md)；对比报告见 [`report.html`](report.html) 与 [`showcase.html`](showcase.html)。

## 快速索引

| # | 目录 | 案例 | 策略 | 一句话结论 |
|---|------|------|------|------------|
| 01 | [01_SW_parts](01_SW_parts/) | SolidWorks 零件/装配图（9 张） | 策略一 纯 ezdxf | 9/9 换框成功，字段回填 ✅ |
| 02 | [02_CNG_electrical](02_CNG_electrical/) | CNG 电气系统图（设计院） | 策略二 COM | 误检治理后 2/2 干净 ✅ |
| 03 | [03_ESS_cad](03_ESS_cad/) | 储能 ESS 成果包（4 张） | 策略一 | A1 闭合多段线外框，4/4 ✅ |
| 04 | [04_assembly](04_assembly/) | 装配体图纸（无框） | 策略二 | 无框鲁棒性：清占位+插空 A3 框 ✅ |
| 05 | [05_standard_dwg](05_standard_dwg/) | 标准设计院 92DZ1 | 策略二 | 4 图框 PUB_TITLE 层逐框替换 ✅ |
| 06 | [06_synth](06_synth/) | 合成异常样本（4 子） | 策略一 | 06b/06c/06d 通过；06a 不逐框为已知局限 |
| 07 | [07_multiframe](07_multiframe/) | 多图框逐框替换（2 子） | 策略一 | 纸边保留 / 无整图纸框分支均通过 ✅ |
| 08 | [08_real_mf](08_real_mf/) | 真实多图框端到端 | 策略一 | 真实字段全对 + 修复越界泄漏 bug ✅ |
| 09 | [09_kuidian_electrical](09_kuidian_electrical/) | 馈电电气原理图 | 策略二 | A4 竖版 BORDER 层双线图框兼容 ✅ |
| 10 | [10_residential_electrical](10_residential_electrical/) | 住宅楼电气设计方案（11 张） | 策略二 COM | ⚠️ 换框 11/11 成功，深度核验发现 3 类未完工 |
| 11 | [11_geimei_control](11_geimei_control/) | 给煤机控制原理图 | 策略二 | 正确判定无框可换(0 框) + 检测器加固 ✅ |
| 12 | [12_detect_negative](12_detect_negative/) | 检测负样本 | — | 📌 已知局限：S7-1200 / std_A3 漏检 |

## 策略说明
- **策略一（纯 ezdxf）**：`detect_frames` 线框检测 → 提取标题栏字段 → 整图幅插 `HH_FRAME_*` → 回填。适用于无 AutoCAD / 打散图框。
- **策略二（AutoCAD COM 直接处理）**：ezdxf 仅做检测+计划，删框/插框/回填/保存全部交给 AutoCAD COM 在原 DWG 副本上完成。适用于本机有 AutoCAD、需保真 DWG 的场景。

## 目录约定
每个案例目录通常含：
- `inputs/` 源图纸（DWG/DXF）
- `outputs/`（或 `outputs/dwg`、`outputs_v2`）置换产物 + `before`/`template`/`after` 对比图
- `summary.md` 案例说明与结论
- `verify/`、`outputs/detection/` 等核验中间产物

> 注：`cases/12_detect_negative/_conv/` 与 `cases/**/outputs/dwg/`、`verify/_conv*` 等二进制/中间产物按 `.gitignore` 不入库。
