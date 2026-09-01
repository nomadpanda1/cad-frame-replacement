# -*- coding: utf-8 -*-
"""幅面推断：从检出图框的实际尺寸（图形单位）反推它对应的标准图幅。

为什么需要这个模块
------------------
旧代码 run_skill._guess_size 直接把「图形单位下的框尺寸」和「毫米制 A 幅面表」比大小::

    err = abs(w - 1189) / 1189 + abs(h - 841) / 841

建筑电气图常见框是 84100 x 59400 图形单位（1:100 出图的 A1），代入后与 A0 的误差最小，
于是所有图都被判成 A0。因为 A0~A4 比例同为 √2，等比缩放后看不出问题，所以这个 bug
一直被掩盖；但一旦遇到**非 √2 图幅**（加长图幅、竖版图幅），选错幅面就会让新框
比例和旧框不一致，出现「内容溢出框外 / 内容跑到框上方」。

正确做法：先猜出图比例（1:1 / 1:100 ...），再匹配幅面。
  84100 / 100 = 841, 59400 / 100 = 594  ->  A1 横版，出图比例 1:100

匹配不上任何标准幅面时（真非标图幅），返回 exact=False 的自定义幅面：
保留旧框的**精确长宽比**，短边归一到最接近的标准短边，这样后续重定向出来的
模板既能严丝合缝套住旧框，标题栏占比又是正常的。
"""

from __future__ import annotations

# GB/T 14689 基本幅面（长边, 短边），单位 mm
A_SERIES = [
    ("A0", 1189.0, 841.0),
    ("A1", 841.0, 594.0),
    ("A2", 594.0, 420.0),
    ("A3", 420.0, 297.0),
    ("A4", 297.0, 210.0),
]

# GB/T 14689 加长幅面（短边 x 长边 的加长系列），单位 mm
# 命名用 AutoCAD 块名安全字符（字母数字下划线），故 A3x3 写成 A3X3
ELONGATED = [
    ("A4X3", 297.0, 630.0),
    ("A4X4", 297.0, 841.0),
    ("A4X5", 297.0, 1051.0),
    ("A3X3", 420.0, 891.0),
    ("A3X4", 420.0, 1189.0),
    ("A2X3", 594.0, 1261.0),
    ("A2X4", 594.0, 1682.0),
    ("A1X3", 841.0, 1783.0),
    ("A0X2", 1189.0, 1682.0),
    ("A0X3", 1189.0, 2523.0),
]

# 常见出图比例分母（1:N）。含 1 表示图纸本身就是 mm 实尺。
PLOT_SCALES = [1.0, 2.0, 2.5, 4.0, 5.0, 10.0, 20.0, 25.0, 30.0, 40.0, 50.0,
               75.0, 100.0, 150.0, 200.0, 250.0, 500.0, 1000.0]

# 标准短边，自定义幅面归一化时用
STD_SHORT = [210.0, 297.0, 420.0, 594.0, 841.0, 1189.0]

# 判定「命中标准幅面」的相对误差上限（两个方向误差之和）。
# 2026-08-31：0.06 过松——400×600（比例 0.667）被吸成 A2V、84100×42000（比例 2.002）
# 被吸成 A3X3（比例 2.121），fit=max 保模板比例导致新框比检出框宽 6%、插入框
# 与邻框重叠/外扩（用户验收反馈「图框比例问题」）。收紧到 0.02 后，这类非标
# 幅面走 custom C<w>X<h> 分支，比例精确保留；真标准幅面（误差 <1%）不受影响。
EXACT_TOL = 0.02

# 无真框判定阈值（图形单位面积）：检出框面积超过 2×A0 且无非块式标题栏时，
# 视为「LLM/无框图的超大画布」而非真实图框，降级到标准幅面，避免标题栏被撑成「米粒」。
# 注意：图形单位面积随出图比例放大（1:100 的 A1 面积 = (84100×59400)），这类真实大图
# 触发后也会正确降级到其真实标准幅面（如 A1），输出不变，故阈值用图形单位也安全。
NO_FRAME_AREA = 2.0 * 1189.0 * 841.0

# GB/T 14689 图框内边距（mm）：装订边 25，其余边 A0/A1 取 10、A2~A4 取 5。
# 这组固定毫米值是**反推出图比例的锚**：外框到内框的间距 / 标准边距 = 出图比例。
BINDING_MARGIN = 25.0
OTHER_MARGINS = (10.0, 5.0)

# scale_hint 与候选出图比例的相对容差（±25%，足以区分 1:100 与 1:200/1:50）
HINT_TOL = 0.25


def scale_from_margins(outer, inner, snap_tol=0.30):
    """由「外框 + 内框」的边距反推出图比例，返回比例分母或 None。

    为什么需要它
    ------------
    只看框的尺寸是**有歧义**的：118800x84000 图形单位既可以是 A0 @1:100
    （1188x840），也可以是 A2 @1:200（594x420），两者数值上完全等价，纯误差
    最小化会选 A2（因为 594x420 整除得到零误差），于是插入的标题栏在纸面上
    大了一倍。

    但图框的**内边距是固定毫米值**（装订边 25mm、其余边 10 或 5mm），不随幅面
    变化。实测案例十：外框 118800x84000、内框左边距 2500 其余 1000
      -> 2500 / 25 = 100，1000 / 10 = 100  ->  出图比例 1:100  ->  A0。
    这就把歧义彻底消掉了。
    """
    try:
        gl = inner[0] - outer[0]
        gr = outer[2] - inner[2]
        gb = inner[1] - outer[1]
        gt = outer[3] - inner[3]
    except Exception:
        return None
    gaps = [g for g in (gl, gr, gb, gt) if g > 0]
    if len(gaps) < 3:
        return None
    gaps.sort()
    binding = gaps[-1]
    other = gaps[len(gaps) // 2 - 1] if len(gaps) >= 4 else gaps[0]
    cands = []
    if binding > 0:
        cands.append(binding / BINDING_MARGIN)
    for m in OTHER_MARGINS:
        if other > 0:
            cands.append(other / m)
    # 落到标准出图比例上；多个候选取「与标准比例最接近」的那个
    best = None
    best_err = 1e18
    for c in cands:
        for s in PLOT_SCALES:
            err = abs(c - s) / s
            if err < best_err:
                best_err = err
                best = s
    if best is None or best_err > snap_tol:
        return None
    return best


class SheetSpec(object):
    """一个幅面规格。

    name        幅面名，同时用作模板块名后缀（HH_FRAME_<name>），只含字母数字下划线
    width/height 模板要生成的尺寸（mm），已按检出框的方向摆放（width 是 x 向）
    plot_scale  推断出的出图比例分母（1:N），仅作信息展示
    exact       True = 命中标准幅面；False = 非标，按精确比例定制
    ratio       检出框的长宽比 width/height，模板必须严格保持这个比例
    """

    __slots__ = ("name", "width", "height", "plot_scale", "exact", "ratio")

    def __init__(self, name, width, height, plot_scale, exact, ratio):
        self.name = name
        self.width = float(width)
        self.height = float(height)
        self.plot_scale = float(plot_scale)
        self.exact = bool(exact)
        self.ratio = float(ratio)

    def __repr__(self):  # pragma: no cover - 调试用
        return ("SheetSpec(%s %.1fx%.1f 1:%g exact=%s ratio=%.4f)"
                % (self.name, self.width, self.height, self.plot_scale,
                   self.exact, self.ratio))

    def as_dict(self):
        return {"name": self.name, "width": round(self.width, 2),
                "height": round(self.height, 2), "plot_scale": self.plot_scale,
                "exact": self.exact, "ratio": round(self.ratio, 4)}


def _candidates():
    """标准幅面候选：基本幅面 + 加长幅面，各含横/竖两个方向。"""
    out = []
    for name, long_e, short_e in A_SERIES:
        out.append((name, long_e, short_e))          # 横版：宽 = 长边
        out.append((name + "V", short_e, long_e))    # 竖版
    for name, short_e, long_e in ELONGATED:
        out.append((name, long_e, short_e))          # 加长横版
        out.append((name + "V", short_e, long_e))    # 加长竖版
    return out


def _nearest_standard(ratio):
    """返回与给定长宽比最接近的标幅面 SheetSpec（A 系列 + 加长，含横竖）。

    用于「无真框」降级：优先选面积最小的匹配幅面，使 fit=max 缩放后标题栏最大、
    最易读。返回 exact=True 的标准幅面（不再生成自定义 C<w>X<h> 巨型幅面）。
    """
    best = None
    best_score = 1e18
    for name, cw, ch in _candidates():
        r = cw / ch
        err = abs(r - ratio) / ratio
        # 面积做次要惩罚（err 占主导），err 相近时选更小幅面 -> 标题栏更大
        score = err + (cw * ch) / 5.0e7
        if score < best_score:
            best_score = score
            best = (name, cw, ch, r)
    name, cw, ch, r = best
    return SheetSpec(name, cw, ch, 1.0, True, r)


def guess_sheet(width, height, scale_hint=None, no_frame=False):
    """按检出框尺寸（图形单位）推断幅面。

    width/height: 检出框的宽高，单位是图纸自身的图形单位（不一定是 mm）。
    scale_hint:   已知/估出的出图比例分母（可由 scale_from_margins 从内框边距得到）。
                  给了它就只在该比例附近选幅面，用来消解「A0@1:100 vs A2@1:200」这类歧义。
    返回 SheetSpec。
    """
    w = float(width)
    h = float(height)
    if w <= 0 or h <= 0:
        return SheetSpec("A3", 420.0, 297.0, 1.0, False, 420.0 / 297.0)
    ratio = w / h

    scales = list(PLOT_SCALES)
    if scale_hint:
        near = [s for s in PLOT_SCALES
                if abs(s - scale_hint) / scale_hint <= HINT_TOL]
        if near:
            scales = near

    def search(scale_pool):
        best = None
        best_err = 1e18
        for name, cw, ch in _candidates():
            # 比例先过滤：比例差太多就没必要试比例尺了（省一层循环、也避免误命中）
            if abs((cw / ch) - ratio) / ratio > 0.12:
                continue
            for s in scale_pool:
                err = abs(w / s - cw) / cw + abs(h / s - ch) / ch
                if err < best_err:
                    best_err = err
                    best = (name, cw, ch, s)
        return best, best_err

    best, best_err = search([1.0])   # 优先按 1:1 实尺判定：CAD 图纸在模型空间通常按 1:1 绘制
    if best is None or best_err > EXACT_TOL:
        best, best_err = search(scales)
    if best is None or best_err > EXACT_TOL:
        # 限定比例后找不到标准幅面，说明它本来就是非标幅面；
        # 此时**不要**放开比例去硬凑标准幅面（那会选错纸面大小），走非标定制分支。
        if not scale_hint:
            best, best_err = search(PLOT_SCALES)
    if best is not None and best_err <= EXACT_TOL:
        name, cw, ch, s = best
        return SheetSpec(name, cw, ch, s, True, ratio)

    # 无真框（LLM/无框图的超大画布）：按真实出图比例降级到标准幅面。
    # 关键修复：旧逻辑无脑降级到最小 A 幅面 + 1:1，导致大图（如强电平面
    # 101273×59440 图形单位）被放大 ~340 倍、标题栏占满图纸、把电路图挡住。
    # 现在优先用标题栏里读到的出图比例（scale_hint，如 1:100）反推真实纸面，
    # 套「能完整容纳该纸面的最小标准幅面」，标题栏保持 GB/T 标准 180mm，
    # 插入缩放仅 ~85~120 倍（= content/纸面mm），不再遮挡图纸。
    if no_frame:
        return _guess_frameless(w, h, scale_hint)

    # 非标幅面：保留精确比例
    if scale_hint:
        # 有可靠比例时直接按「图形单位 / 比例」定纸面，标题栏在纸面上就是标准大小
        scale = float(scale_hint)
        out_w, out_h = w / scale, h / scale
    else:
        # 否则只能把短边归一到最接近的标准短边（比例仍严格保留）
        short_du = min(w, h)
        scale, short_mm = _normalize_short(short_du)
        if w >= h:
            out_w, out_h = short_mm * ratio, short_mm
        else:
            out_w, out_h = short_mm, short_mm / ratio
    name = "C%dX%d" % (int(round(out_w)), int(round(out_h)))
    return SheetSpec(name, out_w, out_h, scale, False, ratio)


def _normalize_short(short_du):
    """把短边（图形单位）归一到最接近的标准短边，返回 (出图比例, 短边 mm)。"""
    best = (1.0, STD_SHORT[-1])
    best_err = 1e18
    for s in PLOT_SCALES:
        v = short_du / s
        for std in STD_SHORT:
            err = abs(v - std) / std
            if err < best_err:
                best_err = err
                best = (s, std)
    return best


def _guess_frameless(width, height, scale_hint):
    """无真框（LLM/无框图超大画布）的幅面判定。

    与 _nearest_standard 的根本区别：_nearest_standard 不看比例、永远按 1:1 把内容
    塞进「比例最接近」的最小 A 幅面，遇到大图就产生灾难性放大（强电平面 340 倍、
    标题栏占满图纸）。本函数：

      * 若拿到标题栏出图比例 scale_hint（如 1:100），按 content/scale 算出真实纸面，
        套「能完整容纳该纸面的最小标准幅面」，标题栏保持 GB/T 标准 180mm，
        插入缩放仅 ~85~120 倍（= content/纸面mm），不再遮挡图纸。
      * 若没拿到比例，在所有标准出图比例里挑一个让内容恰好套进标准幅面的
        （优先贴合最紧；贴合相近时优先大纸面=最小分母，标题栏占比最小、最不易遮挡），
        同样杜绝放大灾难。

    width/height 仍是图形单位下的内容 bbox 尺寸。
    """
    w = float(width)
    h = float(height)
    ratio = w / h

    def best_sheet_for(pw, ph):
        """返回能完整容纳 (pw, ph) 的最小标准幅面 (name, cw, ch)，可旋转；无则 None。"""
        best = None
        best_waste = 1e18
        for name, cw, ch in _candidates():
            for a, b in ((cw, ch), (ch, cw)):   # 允许横/竖两种朝向
                if a + 1e-6 >= pw and b + 1e-6 >= ph:
                    waste = (a * b) / (pw * ph)
                    if waste < best_waste:
                        best_waste = waste
                        best = (name, a, b)
        return best

    if scale_hint:
        s = float(scale_hint)
        if s > 0:
            paper = (w / s, h / s)
            hit = best_sheet_for(*paper)
            if hit:
                name, cw, ch = hit
                return SheetSpec(name, cw, ch, s, True, cw / ch)
        # 连最大加长幅面都装不下（比例过小）——退回按 ratio 的最近标准幅面
        return _nearest_standard(ratio)

    # 无比例提示：在所有标准出图比例里找一个能让内容套进标准幅面的，
    # 优先「贴合最紧」，贴合相近时优先大纸面（小分母，标题栏占比小、易读）。
    best = None
    best_score = 1e18
    for s in PLOT_SCALES:
        paper = (w / s, h / s)
        hit = best_sheet_for(*paper)
        if not hit:
            continue
        name, cw, ch = hit
        waste = (cw * ch) / (paper[0] * paper[1])
        score = waste + s * 1e-6   # waste 相同时取更大纸面（更小 s）
        if score < best_score:
            best_score = score
            best = (name, cw, ch, s)
    if best:
        name, cw, ch, s = best
        return SheetSpec(name, cw, ch, s, True, cw / ch)
    return _nearest_standard(ratio)


def guess_sheet_bbox(bbox, inner=None, no_frame=False, scale_hint=None):
    """bbox = (x0, y0, x1, y1) 版本的 guess_sheet。

    inner 给出同一个图框的内层框线 bbox 时，用它的边距反推出图比例作为 hint。
    no_frame=True 时降级到标准幅面（见 guess_sheet 同名参数）。
    scale_hint 为标题栏读到的出图比例（如 1:100），无框大图据此按真实比例选幅面。
    """
    x0, y0, x1, y1 = [float(v) for v in bbox]
    hint = None
    if inner:
        hint = scale_from_margins([x0, y0, x1, y1], [float(v) for v in inner])
    if hint is None:
        hint = scale_hint
    return guess_sheet(x1 - x0, y1 - y0, scale_hint=hint, no_frame=no_frame)
