import sys, os, time
import ezdxf
import win32com.client

out_dwg = sys.argv[1]
src_dxf = sys.argv[2]

# detect titleblock bbox from source (same logic as pipeline)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import finder
src = ezdxf.readfile(src_dxf)
frames = finder.detect_frames(src)
outer = max(frames, key=lambda r: (r[2]-r[0])*(r[3]-r[1]))
tb = finder.detect_titleblock(src, outer)
print("frame:", [round(x,1) for x in outer])
print("titleblock bbox:", [round(x,1) for x in tb])

# count residual lines/polylines fully inside titleblock bbox in output DWG
app = win32com.client.GetActiveObject("AutoCAD.Application")
doc = app.Documents.Open(os.path.abspath(out_dwg))
time.sleep(1.0)
msp = doc.ModelSpace
x0,y0,x1,y1 = tb
count = 0
for i in range(msp.Count):
    e = msp.Item(i)
    try:
        en = e.EntityName
    except Exception:
        continue
    if en not in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline"):
        continue
    try:
        bb = e.GeometricExtents
        emin, emax = bb.minPoint, bb.maxPoint
        ex0, ey0 = emin[0], emin[1]
        ex1, ey1 = emax[0], emax[1]
    except Exception:
        continue
    if ex0 >= x0 and ex1 <= x1 and ey0 >= y0 and ey1 <= y1:
        count += 1
print("residual lines fully inside titleblock:", count)
doc.Close(False)
