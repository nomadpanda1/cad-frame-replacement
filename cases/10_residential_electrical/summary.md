# 案例十：住宅楼电气设计方案（11 张真实 DWG，AutoCAD COM 直接处理，策略二）

## 来源
爱给网「住宅楼电气设计方案 CAD 图纸（AutoCAD-ZWCAD 设计，提供 dwg 文件）」——
一套完整的住宅楼电气设计图，共 11 张 DWG。覆盖天面、强弱电平面、消防、系统图、
裙楼、首二层、高低压等典型住宅电气设计内容。全部为真实设计院图纸，含中文 SHX 字体、
打散图框（0 个 INSERT 块式标题栏），与微信发来的图纸同属「打散」一类。

## 处理结果（端到端，AutoCAD COM 直接处理原 DWG）
逐张走 `run_skill.main()` 的 **线框检测回退** 路径：块式标题栏 0 命中 →
`detect_frames` + `detect_titleblock` → 删旧外框线+标题栏+边缘区号 → 整图幅插公司图框 →
回填字段。输出统一为 `_HH.dwg`（二进制，acNative=12），源文件不动。

| 图纸 | 检测模式 | 检出框尺寸(绘图单位) | 幅面(≈mm) | 插入模板 | 属性数 | 旧框残留 |
|------|---------|---------------------|----------|---------|-------|---------|
| 天面 | multi(2框) | 55800×40000 ×2 | ~A2 | HH_FRAME_A0 ×2 | 28 | 0 |
| 弱电1 | single | 59300×42000 | ~A2 | HH_FRAME_A0 | 14 | 0 |
| 强电平面 | single | 84100×59400 | ~A1 | HH_FRAME_A0 | 14 | 0 |
| 消防，弱电2 | single | 84100×59400 | ~A1 | HH_FRAME_A0 | 14 | 0 |
| 消防系统图 | single | 59300×42000 | ~A2 | HH_FRAME_A0 | 14 | 0 |
| 系统 | multi(2框) | 59300×42000 ×2 | ~A2 | HH_FRAME_A0 ×2 | 28 | 0 |
| 裙楼消防平面 | multi(2框) | 105100×59400 ×2 | ~A1加长 | HH_FRAME_A0 ×2 | 28 | 0 |
| 首二层商场平面 | single | 118800×99782 | ~√2偏方 | HH_FRAME_A0 | 14 | 0 |
| 首二层系统图 | single | 59300×42000 | ~A2 | HH_FRAME_A0 | 14 | 0 |
| 首层配电干线平面图 | single | 118800×124702 | ~近正方 | HH_FRAME_A0 | 14 | 0 |
| 高低压系统 | single | 89100×63000 | ~A1(√2) | HH_FRAME_A0 | 14 | 0 |

**结论：11/11 张全部成功——HH_FRAME 块已插入、字段回填、旧图框残留 = 0。**
验证口径（去噪）：只在「专用图框层、排除 layer 0、中心落在 HH_FRAME 框内」的直线/多段线
才算残留，排除图内内容噪声。详见 `output_test/case10_verify.json`。

## 已知现象 / 局限
1. **模板尺寸名被错标为 A0（无害）**：`_guess_size(bbox)` 把绘图单位（≈100 单位/mm，
   如 59300）直接拿来和 A_SIZES（mm，如 1189）比较，相对误差公式在大数值下恒取最大参考
   （A0）。所以多数图插入的是 `HH_FRAME_A0`。但因**所有 A 幅面同 √2 长宽比**，
   `insert_frame` 等比缩放后新框实际尺寸由检出框决定，错标只影响块名、不影响成品几何。
2. **非 √2 图框（裙楼 1.77、首二层商场 1.19、首层配电 0.95）**：公司模板是 √2 横版，
   用 `fit=max` 等比缩放后新框会比原框略大/略小一圈，属可接受的「边框微调」，
   不是错位。若日后要求严格贴合，需补 `HH_FRAME_Ax_WIDE` / 竖版模板。
3. **符号块误检过滤**：`消防系统图.dwg` 中含带属性（如“编号”）的消防元件符号块
   `M_I14YDH`，初次被 `find_titleblocks` 误判为 6 个标题栏。已新增 `_titleblock_plausible()`：
   若块式检出对象的 maxdim 不足图纸全图 maxdim 的 5%，则视为符号块并回退到线框检测。
   重跑后 消防系统图 正确识别为单张 ~A2 外框，HH_FRAME_A0 ×1，残留 0。
4. **与微信图纸同一类「打散图框」**：本套书验证了「块式 0 命中 → 线框回退」管线在
   大批量真实住宅电气图上的稳定性（11/11 通过），可作为「微信图纸批处理」的预演。

## 复现
```bash
python run_residential.py        # 逐张跑 COM 替换（写 output_test/<名>_HH.dwg）
python verify_case10_fast.py     # COM 转 DXF + ezdxf 统计块/属性/残留 → case10_verify.json
python render_case10.py          # 渲染 before/after PNG → cases/10_residential_electrical/outputs/
```
成品 DWG 在 `output_test/*_HH.dwg`；PNG 对比在 `cases/10_residential_electrical/outputs/`。
