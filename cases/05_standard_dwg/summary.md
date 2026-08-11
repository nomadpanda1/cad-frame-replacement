# 案例五：标准设计院图纸 — 92DZ1 单电源单台消火栓泵

## 输入
- 1 张 DWG：`92DZ1单电源单台消火栓泵.dwg`
- 典型设计院电气原理图，2×2 四张独立电路图平铺排列
- 每个图框为闭合 LWPOLYLINE，位于 `PUB_TITLE` 层；标题栏在图框右下角，含图名/图号等字段

## 处理要点
- 全图未使用 INSERT 块式标题栏，属于“打散图框”
- `run_skill.py` 检测阶段先尝试块式标题栏匹配，返回 0 后自动回退到线框检测 + 标题栏锚点
- `detect_frames_hierarchical` 识别出 4 个独立图框，无单一“整图纸框”，全部作为替换目标
- 逐框删除旧外框线（含 `PUB_TITLE` 层 LWPOLYLINE）与旧标题栏，插入 `HH_FRAME_A3`（fit=max）并回填字段

## 输出
- `outputs/92DZ1_xiaohuobeng_HH.dwg`：成品 DWG（4 个图框均替换为公司图框，源文件未被修改）
- `outputs/92DZ1_xiaohuobeng_before.png`：生成前效果
- `outputs/92DZ1_xiaohuobeng_template.png`：公司 A3 模板
- `outputs/92DZ1_xiaohuobeng_HH.png`：生成后效果

## 关键修复
- 原 `del_frame_edges` 只识别 `tukuang`/`图框`/`0` 等图层，导致 `PUB_TITLE` 层外框未被删除，新框叠在旧框上。
- 已扩展 `frame_layers` 词表（`pub_title`、`图签`、`tk`、`title`、`frame`）并增加“几何兜底”分支：当按图层未删除外框时，删除与目标 bbox 重合的闭合多段线。
