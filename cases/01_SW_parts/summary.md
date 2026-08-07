# 案例一：SolidWorks 导出零件图/装配图

## 输入
- 9 张 DXF（A3/A4）：法兰、前叉、圆柱齿轮、龙门架、装配体图纸等
- 图框来源：SolidWorks 工程图导出，图框为打散 LINE/LWPOLYLINE，标题栏为右下角 TEXT/MTEXT 网格

## 处理要点
- 检测闭合矩形外框（支持内缩外框）
- 标题栏区域按右下象限关键词锚定，避免误删主视图
- 字段提取：图名、图号、比例、材料、重量、版本等
- 值类型预路由：ratio→SCALE、材料码→MATERIAL、图号格式→DWG_NO、小数→WEIGHT

## 输出
- `outputs/index.html`：生成前 / 公司模板 / 生成后 三栏对比
- `outputs/*_HH.dxf`：带公司图框与回填属性的成品 DXF
