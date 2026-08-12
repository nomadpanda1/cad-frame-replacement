# -*- coding: utf-8 -*-
"""回归：detect_frames 必须能处理「被分段绘制的图框线」。

国标图框常把外框拆成多段短直线（而非 4 条贯穿整边的长直线）。
旧实现以「单段长度 > 0.5×图幅最大边」为阈值，分段短线的单段长度远小于
阈值，导致整框被漏检（返回 []）。新实现按 x/y 坐标聚合线段覆盖度重建矩形，
只要各边框线段在竖直/水平方向累计覆盖达到图幅主要部分即可拼出外框。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ezdxf
from lib import finder
from helpers import new_doc, add_rect_segments


def test_detect_segmented_frame():
    """一个 1000x700 的矩形，每条边拆成 3 段短直线（单段 < 0.5×图幅）。"""
    doc = new_doc()
    msp = doc.modelspace()
    # 用分段直线画一个矩形（非闭合单实体），每边 3 段
    add_rect_segments(msp, 0, 0, 1000, 700, segs_per_side=3)
    fd, p = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        doc.saveas(p)
        d = ezdxf.readfile(p)
        frames = finder.detect_frames(d)
        assert frames, "分段边框应被检测到，而非返回 []"
        chosen = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        assert chosen == (0.0, 0.0, 1000.0, 700.0), "应检出最外矩形 (0,0,1000,700)，得到 %s" % (chosen,)
    finally:
        os.remove(p)
