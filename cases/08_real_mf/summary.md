# 案例八：真实多图框端到端验证（用真实 ESS 图纸拼多图框）

## 来源
4 张真实 ESS 图纸（一次设备表 / 二次系统信号表 / 二次系统柜体表 / 简化主接线图）平移拼成 2×2 多图框，内容 100% 真实，仅排布合成。

## 管线
- 检出 4 个真实图框，逐框抽取真实字段（图名/图号/比例/阶段）全部正确 ✅。
- `before` 786 实体 → `after` 749 实体（删旧框线 + 旧标题栏）。

## 验证 / Bug 修复
- 过程中发现并修复 `extract_frame_fields` **标题区越界泄漏** bug（相邻图框字段串味）→ 已加回归测试 `tests/test_finder.py::test_extract_no_leak_from_neighbor_frame`。

## 输出
`outputs/`：08_real_multiframe 的 `before` / `template` / `HH` PNG + `results.json`。
