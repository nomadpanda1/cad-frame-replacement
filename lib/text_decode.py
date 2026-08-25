# -*- coding: utf-8 -*-
"""解码 AutoCAD / ODA 导出的 MText 转义文本。

背景
----
用 ODA File Converter 把 DWG 转 DXF 后，中文常以 ``\\M+HHHHH`` 这种 Teigha/ODA 专用
转义序列出现（AutoCAD 原生 MText 用 ``\\U+XXXX``，ezdxf 的 plain_text() 能解，但 ODA
的 ``\\M+`` 它不认）。实测 ``\\M+5D5AA`` 等序列的「低 16 位」就是 GBK 码位
（0xD5AA=小 / 0xD7D4=画 / 0xBBAA=水 / 0xB1B1=泵），直接当 GBK 解码即得正确中文；
若 GBK 解不出（如超 BMP 的真 Unicode 码位）则退回按整值当 Unicode。

不解码的后果：extract 把 ``\\M+5A3A8\\M+5D5AA...`` 当成标题/字段值原样回填，
新标题栏里出现一堆 ``\\M+`` 乱码 → 用户看到的「属性值混乱」。
"""
import re

_MPAT = re.compile(r"\\M\+([0-9A-Fa-f]{1,6})")
_UPAT = re.compile(r"\\U\+([0-9A-Fa-f]{1,6})")


def _decode_mgroup(hexs):
    val = int(hexs, 16)
    # 优先按 GBK 解（ODA 的 \\M+ 低 16 位即 GBK 码位）
    low = val & 0xFFFF
    b = bytes([(low >> 8) & 0xFF, low & 0xFF])
    try:
        s = b.decode("gbk")
        if s and s != "\ufffd":
            return s
    except Exception:
        pass
    # 退回：整值当 Unicode 码位
    if 0 <= val <= 0x10FFFF:
        try:
            return chr(val)
        except Exception:
            pass
    return ""


def _decode_ugroup(hexs):
    try:
        return chr(int(hexs, 16))
    except Exception:
        return ""


def decode_mtext(s):
    """把字符串里的 \\M+ / \\U+ 转义解码成真实字符；非字符串原样返回。"""
    if not isinstance(s, str):
        return s
    if "\\M+" not in s and "\\U+" not in s and "\\u+" not in s:
        return s
    s = _MPAT.sub(lambda m: _decode_mgroup(m.group(1)), s)
    s = _UPAT.sub(lambda m: _decode_ugroup(m.group(1)), s)
    return s


def decode_values(d):
    """批量解码 dict 的值（字段提取结果）。"""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = decode_mtext(v)
        else:
            out[k] = v
    return out
