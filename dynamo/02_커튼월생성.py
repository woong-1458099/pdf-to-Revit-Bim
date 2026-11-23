# -*- coding: utf-8 -*-
# [Revit 2] 커튼월(직선 + 곡면 유리) 생성
# - 데이터 : extract/cw.json
# - 재실행 : 주석 = 'PDF자동생성_커튼월' 요소만 교체
# 실행 : Dynamo > Python Script 노드(엔진 PythonNet3)에 붙여 넣거나 같은 이름의 .dyn 을 열어 실행
#
# PDF 평면도 → Revit 커튼월(유리면) 자동 생성
# 벽·바닥·창·문은 건드리지 않습니다. 다시 실행하면 이 스크립트가 만든 커튼월만 지우고 새로 만듭니다.
import clr, json, math
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ───────── 설정 ─────────
FLOOR_LEVEL = {'1': '1F', '2': '2F', '3': '3F', '4': '4F', '5': '5F', '6': '6F', '7': '옥상'}
RUN_FLOORS_LIST = ['1', '2', '3', '4', '5', '6']
# 커튼월 유형: 아래 단어가 이름에 들어간 유형을 순서대로 찾습니다 (멀리언 있는 유형 우선)
CW_TYPE_KEYWORDS = ['점포', 'Storefront', '외부 유리', 'Exterior Glazing', '커튼월', 'Curtain']
TAG = 'PDF자동생성_커튼월'
PX_W = 840.0
# ────────────────────────

DATA = json.loads(r'''{"1":{"lines":[[230.378,670.798,363.605,793.736],[661.468,560.248,641.091,777.353],[198.22,641.016,224.112,665.125]],"curves":[[644.196,774.842,567.655,748.618,511.491,690.379]]},"2":{"lines":[[363.562,395.347,358.288,418.737],[328.427,709.849,376.522,710.09],[176.701,709.052,224.049,709.292],[189.883,665.848,179.455,712.508],[486.282,579.89,416.211,573.286]],"curves":[[555.859,740.476,500.41,668.048,489.445,577.494]]},"3":{"lines":[[363.562,395.347,358.288,418.737],[392.841,677.974,516.365,689.671],[634.163,548.495,613.785,765.72],[322.096,755.223,363.109,793.023],[616.983,308.256,658.542,317.51],[656.342,314.471,652.26,356.875]],"curves":[[616.609,769.937,555.564,740.151,510.758,689.101]]},"4":{"lines":[[198.853,638.419,314.889,664.614],[534.384,597.838,518.903,667.009],[404.047,240.402,357.074,229.782]],"curves":[]},"5":{"lines":[[363.562,395.347,358.288,418.737],[248.732,402.885,235.059,463.737],[687.979,279.454,684.02,321.841],[643.919,272.165,690.188,282.481],[518.903,667.009,534.384,597.838]],"curves":[]},"6":{"lines":[[205.917,620.125,508.382,687.903],[561.25,295.765,602.681,305.035],[600.59,301.664,591.339,343.19]],"curves":[]},"7":{"lines":[],"curves":[]}}''')
doc = DocumentManager.Instance.CurrentDBDocument
MM = 1.0 / 304.8
log = []


def ename(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)


levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
lv_by_name = dict((ename(l), l) for l in levels)
images = {}
for img in FilteredElementCollector(doc).OfClass(ImageInstance).ToElements():
    images[ename(doc.GetElement(img.GetTypeId())).strip().lower()] = img

TransactionManager.Instance.EnsureInTransaction(doc)

# 이전 결과 삭제
old = []
for w in FilteredElementCollector(doc).OfClass(Wall).ToElements():
    p = w.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and p.AsString() == TAG:
        old.append(w.Id)
for i in old:
    try: doc.Delete(i)
    except Exception: pass
if old:
    log.append('이전 자동생성 커튼월 %d개 삭제' % len(old))

# 커튼월 유형 선택
cw_types = [t for t in FilteredElementCollector(doc).OfClass(WallType).ToElements() if t.Kind == WallKind.Curtain]
cw = None
for kw in CW_TYPE_KEYWORDS:
    cw = next((t for t in cw_types if kw in ename(t)), None)
    if cw: break
cw = cw or (cw_types[0] if cw_types else None)

if cw is None:
    log.append('프로젝트에 커튼월 유형이 없습니다')
else:
    log.append('커튼월 유형: %s' % ename(cw))
    total = 0
    for fl in RUN_FLOORS_LIST:
        img = images.get('%s.pdf' % fl)
        lvl = lv_by_name.get(FLOOR_LEVEL[fl])
        if img is None or lvl is None:
            log.append('%s층: PDF 또는 레벨 없음' % fl); continue
        c = img.GetLocation(BoxPlacement.Center)
        k = img.Width / PX_W
        left, top = c.X - img.Width / 2.0, c.Y + img.Height / 2.0
        P = lambda x, y: XYZ(left + x * k, top - y * k, lvl.Elevation)
        idx = levels.index(lvl)
        nxt = levels[idx + 1] if idx + 1 < len(levels) else None
        h = (nxt.Elevation - lvl.Elevation) if nxt else 3000 * MM
        made = 0
        items = [('L', l) for l in DATA[fl]['lines']] + [('A', a) for a in DATA[fl]['curves']]
        for kind, g in items:
            try:
                if kind == 'L':
                    crv = Line.CreateBound(P(g[0], g[1]), P(g[2], g[3]))
                else:
                    crv = Arc.Create(P(g[0], g[1]), P(g[4], g[5]), P(g[2], g[3]))
                if crv.Length < 300 * MM:
                    continue
                w = Wall.Create(doc, crv, cw.Id, lvl.Id, h, 0.0, False, False)
                if nxt is not None:
                    w.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(nxt.Id)
                w.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(TAG)
                made += 1
            except Exception as ex:
                log.append('%s층 커튼월 실패: %s' % (fl, ex))
        total += made
        log.append('%s층 커튼월 %d개 (직선 %d, 곡선 %d)' % (fl, made, len(DATA[fl]['lines']), len(DATA[fl]['curves'])))
    log.insert(0, '총 커튼월 %d개 생성' % total)

TransactionManager.Instance.TransactionTaskDone()
OUT = log
