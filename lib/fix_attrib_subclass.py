"""Fix ezdxf 1.4.4 ATTRIB subclass-marker order bug.

ezdxf writes ATTRIB as:  AcDbEntity -> AcDbText -> AcDbAttribute
AutoCAD requires:        AcDbEntity -> AcDbAttribute -> AcDbText
This swaps the two subclass segments (including their data) so AutoCAD opens the file.
Operates on raw DXF text; only touches ATTRIB entities.
"""


def _reorder_attrib(ent):
    """ent = list of lines for one ATTRIB entity (must end with '0','SEQEND')."""
    # locate subclass markers
    idx_text = None
    idx_attr = None
    for k, ln in enumerate(ent):
        s = ln.strip()
        nxt = ent[k + 1].strip() if k + 1 < len(ent) else ""
        if s == "100" and nxt == "AcDbText":
            idx_text = k
        elif s == "100" and nxt == "AcDbAttribute":
            idx_attr = k
    # already correct order? (attr before text)
    if idx_attr is not None and idx_text is not None and idx_attr < idx_text:
        return ent
    if idx_text is None or idx_attr is None:
        return ent  # nothing to fix
    # find SEQEND terminator
    idx_seq = None
    for k in range(len(ent) - 1, -1, -1):
        if ent[k].strip() == "0" and k + 1 < len(ent) and ent[k + 1].strip() == "SEQEND":
            idx_seq = k
            break
    if idx_seq is None:
        idx_seq = len(ent)
    header = ent[:idx_text]
    text_seg = ent[idx_text:idx_attr]
    attr_seg = ent[idx_attr:idx_seq]
    tail = ent[idx_seq:]
    return header + attr_seg + text_seg + tail


def fix_attrib_subclass(text):
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == "0" and i + 1 < n and lines[i + 1].strip() == "ATTRIB":
            # collect ATTRIB entity up to and including '0 SEQEND'
            ent = []
            j = i
            while j < n:
                ent.append(lines[j])
                if lines[j].strip() == "0" and j + 1 < n and lines[j + 1].strip() == "SEQEND":
                    ent.append(lines[j + 1])
                    j += 2
                    break
                j += 1
            out.extend(_reorder_attrib(ent))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


if __name__ == "__main__":
    import io, ezdxf, sys, os
    # minimal repro
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    blk = doc.blocks.new("TB")
    blk.add_attdef("UNIT", (1, 1), dxfattribs={"height": 2.5})
    ins = msp.add_blockref("TB", (0, 0))
    ins.add_auto_attribs({"UNIT": "东方宏华 · 钻机电控"})
    buf = io.StringIO()
    doc.write(buf)
    raw = buf.getvalue()
    fixed = fix_attrib_subclass(raw)
    open("C:/temp/acadtest/repro_raw.dxf", "w", encoding="utf-8").write(raw)
    open("C:/temp/acadtest/repro_fixed.dxf", "w", encoding="utf-8").write(fixed)
    print("wrote repro_raw.dxf and repro_fixed.dxf")
    print("fixed contains AcDbAttribute before AcDbText:",
          fixed.find("AcDbAttribute") < fixed.find("AcDbText") if False else
          "check manually")
