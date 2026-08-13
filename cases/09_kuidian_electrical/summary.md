# 案例九：馈电-电气原理图（SolidWorks 打散图框，A4 竖版）

## 图纸来源
- 原始文件：`input_real_test/kuidian.dwg`（来自 `D:\edge\学习3\...`）
- 类型：电气原理图 / SolidWorks 导出的打散图框（0 个 INSERT 块标题栏）

## 检测结果
- 幅面：A4 竖版 `210 mm × 297 mm`
- 线框识别：双线图框
  - 外框：`[0, 0, 210, 297]`
  - 内框：`[25, 5, 205, 292]`（BORDER 层闭合多段线）
- 标题栏：右下角旧标题栏，从表格文字中提取到 `TITLE = 壳式断路器`

## 处理过程
1. 块式标题栏检测命中 0 → 自动回退到线框检测。
2. 删除旧外框线（4 条）与内框线（1 条 BORDER 层闭合多段线）。
3. 删除旧标题栏区域实体 48 个。
4. 幅面推断：`lib/sheet.py` 由外框 210×297 判为 **A4V 竖版**，触发方向感知模板选择。
5. 插入公司图框 `HH_FRAME_A4V`（竖版 210×297），回填 14 个属性字段，标题 `壳式断路器`。
6. AutoCAD COM 直接写出 `_HH.dwg`。

## 验证结果
- HH_FRAME_A4V 块引用数：1
- 属性标签数：14
- 残留旧外框（边框层直线/多段线）：**0**
- 旧标题栏区域内残留：**0**
- 竖版模板是否严丝合缝：**是**，新图框填满整张 A4 竖版。

## 修复闭环（2026-08-13）
已新增 `templates/HH_FRAME_A4V.dxf` 竖版模板（由 `HH_FRAME_A4.dxf` 经 `lib/frame_gen.py` 模板重定向生成）。
本图重新跑 `run_skill --dwg` 后：
- `幅面判定：旧框 210x297 -> A4V 210x297`；
- `模板 HH_FRAME_A4V` 被 `prepare_templates` 转成 DWG 并用于插框；
- 旧横版模板只填下半部分的问题彻底解决。

## 输出文件
- 原图：`inputs/kuidian.dwg`
- 结果：`outputs/kuidian_HH.dwg`
- 示意图：`outputs/kuidian_before.png`、`outputs/kuidian_template.png`、`outputs/kuidian_HH.png`
