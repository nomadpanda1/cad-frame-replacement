"""Production fixer for ezdxf 1.4.4 -> AutoCAD 2026 DXF incompatibilities.

Problems observed when run_skill inserts the HH_FRAME block + attributes:
  1. Title-block field entities are emitted with a DUPLICATE `100 AcDbText`
     subclass marker (must be exactly one). AutoCAD aborts with
     "读取 TEXT ... 无效的 DXF 数据".
  2. Text is UTF-8 bytes but $DWGCODEPAGE defaults to ANSI_1252/ANSI_1200
     (UTF-16). For correct Chinese rendering we declare ANSI_65001 (UTF-8).

This operates on raw DXF text and only touches what is needed, so it is safe
to run on every generated file right after doc.saveas().
"""


def _fix_entity(ent):
    """ent = list of lines for one entity (first line is the group-code '0').
    Removes any DUPLICATE `100 AcDbText` subclass marker pair (ezdxf 1.4.4
    bug when writing title-block attribute fields). An entity may legitimately
    carry at most one AcDbText subclass marker; extras are dropped as a pair."""
    out = []
    seen_text = False
    k = 0
    while k < len(ent):
        s = ent[k].strip()
        nxt = ent[k + 1].strip() if k + 1 < len(ent) else ""
        if s == "100" and nxt == "AcDbText":
            if seen_text:
                k += 2  # drop the '100' AND its 'AcDbText' value line together
                continue
            seen_text = True
        out.append(ent[k])
        k += 1
    return out


def fix_dxf_for_autocad(text, codepage="ANSI_65001"):
    import re
    lines = text.split("\n")
    # DXF entities start with a '0' line; split before each '0' (the next
    # entity's start). Keep i on the next '0' so every entity is collected.
    i = 0
    n = len(lines)
    out = []
    while i < n:
        if lines[i].strip() == "0" and i + 1 < n:
            j = i + 1
            while j < n:
                if lines[j].strip() == "0" and j > i:
                    break
                j += 1
            ent = lines[i:j]
            fixed = _fix_entity(ent)
            out.extend(fixed)
            i = j  # next iteration starts at the next entity's '0'
        else:
            out.append(lines[i])
            i += 1
    result = "\n".join(out)
    result = re.sub(
        r"(\$DWGCODEPAGE\s*\r?\n\s*\d+\s*\r?\n)\S+",
        r"\1" + codepage,
        result,
    )
    return result


if __name__ == "__main__":
    import io, ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$DWGCODEPAGE"] = "ANSI_1252"
    msp = doc.modelspace()
    blk = doc.blocks.new("TB")
    blk.add_attdef("UNIT", (1, 1), dxfattribs={"height": 2.5})
    ins = msp.add_blockref("TB", (0, 0))
    ins.add_auto_attribs({"UNIT": "东方宏华 · 钻机电控"})
    buf = io.StringIO()
    doc.write(buf)
    raw = buf.getvalue()
    fixed = fix_dxf_for_autocad(raw)
    open("C:/temp/acadtest/repro_fixed2.dxf", "w", encoding="utf-8").write(fixed)
    print("self-test wrote repro_fixed2.dxf; has ANSI_65001:", "ANSI_65001" in fixed)
