# 案例二：CNG 电气系统图（设计院图纸）

## 输入
- 1 张 DWG：`CNG_电气系统图.dwg`
- 内含 4 个独立电路图：低压配电系统图一/二、10kV主接线图、平面布置图
- 坐标为大工程坐标，图框为 LWPOLYLINE 闭合矩形，右下角为设计院会签栏

## 处理要点
- DWG 先经 AutoCAD COM 转为 DXF
- 检测大坐标闭合矩形，内外框去重
- 幅面匹配：84100×42000 → A3_WIDE（加长），84100×59400 → A1
- 删除旧外框线、旧会签栏全部内容、旧图框 INSERT 块引用
- 专用右下角会签栏字段提取：图名、图号、阶段、室别

## 输出
- `outputs/CNG_电气系统图_HH.dwg`：成品 DWG（4 个图框均替换为公司图框，可直接在 AutoCAD 中打开）
- `outputs/index.html`：生成前 / 公司模板 / 生成后 三栏对比
- `outputs/CNG_电气系统图_after.png`：整体效果图
- `outputs/plan.json` / `results.json`：处理计划与回填结果记录

## 关键修复
- 设计院 DWG 含加密/代理实体，经 ezdxf 读写后会被 AutoCAD 报“解密数据时出错”。
- 改为 `run_cng_acad.py`：ezdxf 只做字段提取/图框检测，实际删框、插公司图框、填属性全部通过 AutoCAD COM 在原 DWG 副本上完成，保存为 DWG。
