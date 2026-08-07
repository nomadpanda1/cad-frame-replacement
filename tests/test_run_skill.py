# -*- coding: utf-8 -*-
"""run_skill 通用入口的 --mode 规划逻辑（single/auto/multi）。

_plan_frames 决定单张图走整图幅一张框（旧 find_titleblocks）还是逐框替换
（多图框层级检测）。这是"打通通用入口"的核心：把案例七/八验证过的逐框能力
暴露给普通同事，而不再锁在案例脚本里。
"""
import run_skill
from helpers import new_doc, add_rect


def _single_doc():
    doc = new_doc()
    add_rect(doc.modelspace(), 0, 0, 200, 100, closed=True)
    return doc


def _multi_doc():
    doc = new_doc()
    add_rect(doc.modelspace(), 0, 0, 200, 100, closed=True)
    add_rect(doc.modelspace(), 300, 0, 500, 100, closed=True)
    return doc


def test_plan_frames_auto_single_doc_false():
    use_multi, sheet, targets = run_skill._plan_frames(_single_doc(), "auto")
    assert use_multi is False
    assert len(targets) == 1


def test_plan_frames_auto_multi_doc_true():
    use_multi, sheet, targets = run_skill._plan_frames(_multi_doc(), "auto")
    assert use_multi is True
    assert len(targets) == 2


def test_plan_frames_mode_single_forces_false():
    # 即便图纸有多个框，single 也强制走整图幅一张框（targets 置空）
    use_multi, sheet, targets = run_skill._plan_frames(_multi_doc(), "single")
    assert use_multi is False
    assert targets == []


def test_plan_frames_mode_multi_forces_true_on_single_frame():
    # multi 模式下，即使只有 1 个框也走逐框替换路径
    use_multi, sheet, targets = run_skill._plan_frames(_single_doc(), "multi")
    assert use_multi is True
    assert len(targets) == 1
