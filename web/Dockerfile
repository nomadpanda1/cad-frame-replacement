# CAD 图框置换 · Web 服务镜像
# 基于 Debian 的 python:slim，内置 LibreDWG(libredwg-tools) 提供 dwg2dxf/dxf2dwg，
# 使 Linux 无头服务器也能处理 DWG。
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    CAD_PY=python3 \
    PORT=8000 \
    MPLCONFIGDIR=/tmp/matplotlib

# 系统依赖：LibreDWG 转换器 + 中文字体(预览用，避免 tofu) + 基础工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        libredwg-tools fonts-noto-cjk \
        && rm -rf /var/lib/apt/lists/*

# 仅复制运行时所需（不含 cases/ 大体积测试数据、.git）
WORKDIR /app
COPY run_skill.py /app/run_skill.py
COPY lib /app/lib
COPY templates /app/templates
COPY web /app/web

RUN pip install --no-cache-dir -r web/requirements.txt

EXPOSE 8000
CMD ["python", "web/app.py"]
