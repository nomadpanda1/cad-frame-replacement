# 案例 12 · 检测负样本（已知局限）— S7-1200 / std_A3

> 目的：记录当前检测器**漏检**的两类真实图纸，作为「已知局限 / 回归负样本」归档。
> 这两张图在 `output_test/*_detection.json` 中均输出 `{"frames":[]}`，经核查确认是
> **检测器启发式不足**，而非图纸本身无框。

## 样本来源

| 文件 | 类型 | 内容 |
|------|------|------|
| `inputs/S7-1200.dwg` | PLC I/O 与梯形图 | 西门子 S7-1200 图纸（17 个 INSERT 块 + 32 个 DIMENSION + 32 个 MTEXT，全部在 `0` 层） |
| `inputs/std_A3.dwg` | 标准图框样张 | 一张标准 A3 图，外框/内框分别在 `总外框线` / `总内框线` 两个专用图层 |

转换：`_conv/*.dxf` 由 AutoCAD COM `SaveAs(ac2013_dxf)` 从源 DWG 转出，供 ezdxf 离线核查。

## 核查结论（2026-08-12，ezdxf 1.4.4 实测）

直接对 `_conv/*.dxf` 调用 `lib/finder`：

| 样本 | entity 概览 | `detect_frames` | `find_titleblocks` | 根因 |
|------|-------------|-----------------|--------------------|------|
| `std_A3.dxf` | LINE 242 / MTEXT 94 / ARC 25 / CIRCLE 6 / HATCH 3 / SPLINE 2；图层含 `总外框线`(16线)、`总内框线`(64线) | `[]` | `0` | 真框存在，但**水平边框覆盖不足** |
| `S7-1200.dxf` | INSERT 17 / DIMENSION 32 / MTEXT 32；仅 `0` 层；**0 条原始 LINE/LWPOLYLINE/POLYLINE** | `[]` | `0` | 无任何原始直线几何，块内不含标题栏 ATTDEF |

### std_A3 漏检根因（精确）

`detect_frames` 把全图轴对齐直线段按 x/y 坐标聚合，要求每条候选边覆盖 ≥ `0.6 × 图幅边长`：

- 全图 extents：`(921.5, 1086.7)` → `vmin = 0.6*sh = 652.0`，`hmin = 0.6*sw = 552.9`
- 竖向候选：`x=5382`(覆盖 840)、`x=5085`(覆盖 840) → 2 个 ✅
- **横向候选：空** ❌（`hcov` 中无任何 y 坐标覆盖 ≥ 552.9）

`len(y_cand) < 2` → 直接返回 `[]`。

水平边框达不到覆盖阈值的原因：该图外框（`总外框线` 16 线）的**上/下边框被拆成多段短直线**，
各段落在不同 y 坐标、无法在同一 y 键上 union 出 ≥ 0.6×图幅宽度的连续跨度；而抑制内部网格线
误检的最小覆盖启发式（0.6）对"分段边框"过于严格。这属于**检测器参数/分段合并逻辑的局限**，
不是图纸无框。

### S7-1200 漏检根因

整张图**没有任何原始直线/多段线实体**（内容全部封装在 17 个 INSERT 块与 32 个 DIMENSION 中）。
`detect_frames` 依赖轴对齐直线段，无线段可聚 → 立即返回 `[]`；`find_titleblocks` 依赖块名关键字 +
ATTDEF 标题栏属性，而 S7-1200 的 INSERT 均为 PLC 符号块、不含标题栏 ATTDEF → 返回 0。
该图框（若有）嵌在块几何内部，对线框与块式两条检测路径都不可见。

## 对产品的意义

1. **线框检测器**需增强：对"分段短直线边框"做跨 y 键的容差合并（或下调最小覆盖阈值、改判边框
   由外轮廓闭合性决定），否则类似 std_A3 的国标分段边框会持续漏检。
2. **块内图框**：当前两条路径均不展开 INSERT 块内部几何；S7-1200 类"全块化"图纸需新增
   "展开块 / 递归检测块内边框"能力才能覆盖。
3. 本案例作为**回归负样本**保留：`frames:[]` 的预期输出被显式记录，避免未来"假完成"误判。

## 复现

```bash
# 转换（需本机 AutoCAD + win32com）
python -c "import lib.acad_com as c; c.dwg_to_dxf('inputs/std_A3.dwg','_conv/std_A3.dxf')"

# 检测
python - <<'PY'
import ezdxf, lib.finder as F
for f in ('_conv/std_A3.dxf','_conv/S7-1200.dxf'):
    doc = ezdxf.readfile(f)
    print(f, 'frames=', F.detect_frames(doc), 'blocks=', len(F.find_titleblocks(doc)))
PY
```
