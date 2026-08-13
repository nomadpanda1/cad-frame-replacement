# -*- coding: utf-8 -*-
"""幅面推断（lib.sheet）与模板重定向（lib.frame_gen）的单元测试。

这两个模块合起来修的是同一个 bug：新图框比例和旧图框不一致，导致
「内容溢出框外 / 内容跑到框上方」。测试分三层：

  1. 幅面推断：能从图形单位反推出图比例，认出竖版/加长/非标幅面；
  2. 模板重定向：从 A4 模板能精确重建出真实的 A0/A1/A2/A3 模板（黄金对照）；
  3. 端到端不变式：重定向出的模板比例 == 检出框比例，等比缩放后严丝合缝。
"""
import os
import ezdxf
import pytest

from lib import sheet, frame_gen


HERE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(HERE, "..", "templates")
ALL_SIZES = ["A0", "A1", "A2", "A3", "A4"]


def tpl(name):
    return os.path.join(TPL_DIR, "HH_FRAME_%s.dxf" % name)


# --------------------------------------------------------------------------
# 1. 幅面推断
# --------------------------------------------------------------------------

def test_mm_scale_1to1():
    for n, w, h in [("A0", 1189, 841), ("A2", 594, 420), ("A4", 297, 210)]:
        spec = sheet.guess_sheet(w, h)
        assert spec.name == n and spec.exact and spec.plot_scale == 1.0


def test_plot_scale_1to100_is_not_mistaken_for_a0():
    """84100x59400 是 1:100 出图的 A1，旧代码会判成 A0。

    旧实现拿图形单位直接和毫米制幅面表比大小，case 10 的 10 张建筑电气图
    全部被判成 A0。因为 A0~A4 同为 √2 比例，等比缩放后看不出来，所以这个
    bug 被长期掩盖。
    """
    spec = sheet.guess_sheet(84100, 59400)
    assert spec.name == "A1"
    assert spec.exact
    assert spec.plot_scale == 100.0
    assert (spec.width, spec.height) == (841.0, 594.0)


def test_plot_scale_1to150():
    spec = sheet.guess_sheet(89100, 63000)
    assert spec.name == "A2" and spec.plot_scale == 150.0


def test_portrait_gets_v_suffix():
    spec = sheet.guess_sheet(59400, 84100)
    assert spec.name == "A1V"
    assert (spec.width, spec.height) == (594.0, 841.0)


def test_elongated_sheet_keeps_exact_ratio():
    """加长图幅（长宽比 1.769，非 √2）必须保留精确比例，不能吸附到 √2。"""
    w, h = 105100.0, 59400.0
    spec = sheet.guess_sheet(w, h)
    assert not spec.exact                       # 不在标准幅面表里
    assert spec.width / spec.height == pytest.approx(w / h, rel=1e-6)
    assert spec.height == 594.0                 # 短边归一到标准短边
    assert spec.name == "C1051X594"


def test_custom_name_is_block_name_safe():
    """幅面名要用作 AutoCAD 块名后缀，只能含字母数字下划线。"""
    for w, h in [(105100, 59400), (118800, 99782), (55800, 40000)]:
        name = sheet.guess_sheet(w, h).name
        assert name.replace("_", "").isalnum(), name


def test_degenerate_input_does_not_crash():
    for w, h in [(0, 100), (100, 0), (-5, -5)]:
        assert sheet.guess_sheet(w, h).name


# --------------------------------------------------------------------------
# 2. 模板重定向：黄金对照
# --------------------------------------------------------------------------

def _signature(path, blk_name):
    """把块内所有实体归一成可比较的指纹（类型 + 定位点 + 文字内容/字高）。"""
    doc = ezdxf.readfile(path)
    blk = doc.blocks[blk_name]
    out = []
    for e in blk:
        pts = tuple((round(x, 3), round(y, 3)) for x, y in frame_gen.entity_points(e))
        key = e.dxftype()
        if key == "ATTDEF":
            key += "|%s|h%.2f" % (e.dxf.tag, e.dxf.height)
        elif key == "TEXT":
            key += "|%s|h%.2f" % (e.dxf.text, e.dxf.height)
        out.append((key, pts))
    return sorted(out)


@pytest.mark.parametrize("src", ["A4", "A0"])
@pytest.mark.parametrize("dst", ALL_SIZES)
def test_retarget_reproduces_real_templates(tmp_path, src, dst):
    """从任一模板重定向到另一幅面，结果必须与仓库里真实模板逐点一致。

    这是整个重定向算法的黄金对照：A0~A4 五个模板是人工设计的，如果算法能
    从 A4 精确重建出 A0，说明「留边保持拉伸 + 标题栏刚性右下锚定 + 对中符号
    锚中线」这套规则确实复现了设计者的意图，而不是碰巧凑出来的。
    """
    if src == dst:
        pytest.skip("同幅面无需重定向")
    real = tpl(dst)
    W, H = frame_gen.paper_size(real)
    gen = str(tmp_path / ("gen_%s.dxf" % dst))
    frame_gen.retarget(tpl(src), gen, "HH_FRAME_%s" % dst, W, H)
    assert _signature(gen, "HH_FRAME_%s" % dst) == _signature(real, "HH_FRAME_%s" % dst)


def test_titleblock_size_is_invariant(tmp_path):
    """标题栏必须恒为 180x56（GB/T 10609.1），与幅面大小无关。"""
    for name, W, H in [("A4V", 210, 297), ("C1051X594", 1051, 594),
                       ("C500X420", 500, 420), ("A0", 1189, 841)]:
        out = str(tmp_path / (name + ".dxf"))
        frame_gen.retarget(tpl("A4"), out, "HH_FRAME_" + name, W, H)
        doc = ezdxf.readfile(out)
        blk = doc.blocks["HH_FRAME_" + name]
        paper = frame_gen.paper_rect(blk)
        tb = frame_gen.title_rect(blk, paper)
        assert tb is not None, name
        assert (tb[2] - tb[0]) == pytest.approx(180.0, abs=0.01), name
        assert (tb[3] - tb[1]) == pytest.approx(56.0, abs=0.01), name


def test_retarget_preserves_margins(tmp_path):
    """内框留边（左 25 装订边、其余 5）在任意幅面下都必须保持不变。"""
    out = str(tmp_path / "wide.dxf")
    frame_gen.retarget(tpl("A4"), out, "HH_FRAME_W", 1051, 594)
    doc = ezdxf.readfile(out)
    blk = doc.blocks["HH_FRAME_W"]
    rects = sorted(frame_gen._closed_rects(blk),
                   key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    paper, inner = rects[0], rects[1]
    assert inner[0] - paper[0] == pytest.approx(25.0, abs=0.01)   # 装订边
    assert paper[2] - inner[2] == pytest.approx(5.0, abs=0.01)
    assert inner[1] - paper[1] == pytest.approx(5.0, abs=0.01)
    assert paper[3] - inner[3] == pytest.approx(5.0, abs=0.01)


def test_retarget_keeps_all_attdefs(tmp_path):
    """14 个可回填属性一个都不能丢，否则标题栏回填会失效。"""
    src_doc = ezdxf.readfile(tpl("A4"))
    want = sorted(e.dxf.tag for e in src_doc.blocks["HH_FRAME_A4"]
                  if e.dxftype() == "ATTDEF")
    out = str(tmp_path / "p.dxf")
    frame_gen.retarget(tpl("A4"), out, "HH_FRAME_A4V", 210, 297)
    doc = ezdxf.readfile(out)
    got = sorted(e.dxf.tag for e in doc.blocks["HH_FRAME_A4V"]
                 if e.dxftype() == "ATTDEF")
    assert got == want and len(got) == 14


def test_retarget_renames_modelspace_insert(tmp_path):
    """模型空间那个 INSERT 也要改名，否则 AutoCAD 打开模板会报块未定义。"""
    out = str(tmp_path / "v.dxf")
    frame_gen.retarget(tpl("A4"), out, "HH_FRAME_A4V", 210, 297)
    doc = ezdxf.readfile(out)
    names = [e.dxf.name for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert names == ["HH_FRAME_A4V"]


def test_ensure_template_caches(tmp_path):
    spec = sheet.guess_sheet(105100, 59400)
    p1, s1 = frame_gen.ensure_template(tpl("A4"), str(tmp_path), spec)
    mtime = os.path.getmtime(p1)
    p2, s2 = frame_gen.ensure_template(tpl("A4"), str(tmp_path), spec)
    assert p1 == p2 and s1 == s2
    assert os.path.getmtime(p2) == mtime      # 命中缓存，没有重写


# --------------------------------------------------------------------------
# 3. 端到端不变式：这是修复的核心保证
# --------------------------------------------------------------------------

@pytest.mark.parametrize("w,h", [
    (84100, 59400),     # 1:100 A1，标准
    (105100, 59400),    # 加长，比例 1.769
    (118800, 99782),    # 非标，比例 1.191
    (59400, 84100),     # 竖版
    (55800, 40000),     # 内框线（比例 1.395）
])
def test_scale_fits_exactly(tmp_path, w, h):
    """核心不变式：模板比例 == 检出框比例，故 W/tw == H/th，等比缩放严丝合缝。

    insert_frame 用 scale = min(W/tw, H/th)。只要两项相等，新框就正好覆盖旧框；
    一旦不等，取小的那项会让新框在另一方向留出空当 —— 内容溢出框外或跑到框上方。
    """
    spec = sheet.guess_sheet(w, h)
    out = str(tmp_path / (spec.name + ".dxf"))
    tw, th = frame_gen.retarget(tpl("A4"), out, "HH_FRAME_" + spec.name,
                                spec.width, spec.height)
    assert w / tw == pytest.approx(h / th, rel=1e-4), (
        "模板比例与检出框比例不一致，插框必然错位")
    # 缩放后模板幅面与检出框尺寸一致（容差 0.05%）
    scale = min(w / tw, h / th)
    assert tw * scale == pytest.approx(w, rel=5e-4)
    assert th * scale == pytest.approx(h, rel=5e-4)
