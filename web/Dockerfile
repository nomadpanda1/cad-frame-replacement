# CAD 图框置换 · Web 服务镜像
# 基于 Debian 的 python:slim，从源码构建 LibreDWG(提供 dwg2dxf/dxf2dwg)，
# 使 Linux 无头服务器也能处理 DWG（Debian/Ubuntu 官方源已不再打包 libredwg-tools）。
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    CAD_PY=python3 \
    PORT=8000 \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/root \
    XDG_CACHE_HOME=/root/.cache

# 系统依赖：中文字体(预览避免 tofu) + LibreDWG 构建工具 + fontconfig(matplotlib 字体回退)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential autoconf automake libtool pkg-config curl \
        fonts-noto-cjk fontconfig \
        && rm -rf /var/lib/apt/lists/*

# 从源码构建 LibreDWG（Pin 稳定版，避免 master 波动）。
# 提供 dwg2dxf / dxf2dwg，DWG 经它转 DXF 后再走 ezdxf 管线、可选转回 DWG。
ARG LIBREDWG_VER=0.14
RUN curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VER}/libredwg-${LIBREDWG_VER}.tar.gz" -o /tmp/libredwg.tar.gz \
    && tar xzf /tmp/libredwg.tar.gz -C /tmp \
    && cd /tmp/libredwg-${LIBREDWG_VER} \
    && (test -x ./configure || ./autogen.sh) \
    && ./configure --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig \
    && cd / && rm -rf /tmp/libredwg-${LIBREDWG_VER} /tmp/libredwg.tar.gz

# 仅复制运行时所需（不含 cases/ 大体积测试数据、.git）
WORKDIR /app
COPY run_skill.py /app/run_skill.py
COPY lib /app/lib
COPY templates /app/templates
COPY web /app/web

RUN pip install --no-cache-dir -r web/requirements.txt

# 预建 ezdxf 字体缓存：否则无头容器里 ezdxf 的 FontManager 在 import 时读不到
# ~/.cache/ezdxf/font_manager_cache.json，保持空(0 字体)。一旦渲染含 TEXT/MTEXT 的
# DXF(SW 零件图标题栏全是文字)就抛 FontNotFoundError: no fonts available，导致网站
# 预览图生成失败(preview={})。这里在构建期扫描 /usr/share/fonts 写缓存，运行时直接命中。
RUN python -c "import ezdxf.fonts.fonts as f; f.build_system_font_cache()" \
    && echo "ezdxf font cache built:" \
    && python -c "import ezdxf.fonts.fonts as f; print(len(f.font_manager._font_cache), 'fonts cached')"

EXPOSE 8000
CMD ["python", "web/app.py"]
