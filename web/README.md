# CAD 图框置换 · Web 服务

把仓库根的图框置换能力（`run_skill.py` + `lib/`）包装成网页：上传 DWG/DXF → 自动按幅面套用公司标准图框（HH_FRAME）→ 预览 + 下载。

## 功能
- 支持 **DXF** 与 **DWG** 上传（Linux 无头环境用 LibreDWG 把 DWG 转 DXF 后处理）
- 自动按幅面检测并选模板（A0~A4 / A4V / 加长），也可手动指定
- 返回替换前 / 替换后预览图 + 结果文件下载（DXF，可选导出 DWG）
- 多图框图纸自动逐框置换

## 本地运行（不用 Docker）
依赖：Python 3.11+、ezdxf、matplotlib、fastapi、uvicorn、python-multipart。
DWG 支持（可选）：`apt install libredwg-tools`（提供 `dwg2dxf`/`dxf2dwg`）。

```bash
pip install -r web/requirements.txt
CAD_PY=python3 python web/app.py
# 打开 http://localhost:8000
```
`CAD_PY` 指向实际带 ezdxf 的解释器（调起置换管线的子进程用它）。

## Docker 部署（推荐，到 Linux 服务器）
在**仓库根目录**执行（compose 的 build context 是仓库根）：

```bash
docker compose up -d --build
# 访问 http://<服务器IP>:8000
```

镜像已 `apt` 安装 `libredwg-tools`，开箱即可处理 DWG。

### 环境变量
- `PORT`：监听端口（默认 8000）
- `CAD_PY`：子进程解释器（容器内默认 `python3`）

### 数据卷
`cadframe_jobs` 卷持久化任务产物（预览图 / 下载文件），容器重启不丢。

## API
- `GET /api/templates` → 可用模板列表
- `POST /api/process`（`multipart`：`file`, `template=auto`, `fit=max`, `export_dwg=false`）
  → `{ ok, job_id, files:{dxf,dwg?}, preview:{before,after}, diagnostics }`
- `GET /api/download/<job_id>/<filename>` → 取结果 / 预览文件

## 已知限制
- 预览图中文可能因字体回退显示为方框（几何正确，不影响 DXF 结果；镜像已装 noto-cjk 缓解）。
- 不规则拼版（如一张大图内散落多个不同幅面 A4）当前识别能力有限，会退化为整图幅单框。
- DWG↔DXF 往返转换由 LibreDWG 完成，极少数新版/复杂 DWG 可能损失部分特性；如需更高质量可手动安装 ODA File Converter（`converter.py` 会自动优先选用）。
