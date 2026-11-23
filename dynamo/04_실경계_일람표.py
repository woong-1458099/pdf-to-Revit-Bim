# -*- coding: utf-8 -*-
# [Revit 4] 실 구분선 + 일람표 4종
# - 실 구분선 : 계단을 가로지르면 Revit이 무시하므로 계단 옆 L자 선으로 실 경계 분리
# - 일람표    : 실 면적표, 문 일람표, 창 일람표, 벽 물량표 (필드는 이름으로 매칭)
# 실행 : Dynamo > Python Script 노드(엔진 PythonNet3)에 붙여 넣거나 같은 이름의 .dyn 을 열어 실행
#
# 실 구분선 + 일람표(실 면적표, 문 일람표, 창 일람표, 벽 물량표) 자동 생성
# 다시 실행하면 이 스크립트가 만든 실 구분선과 같은 이름의 일람표를 지우고 새로 만듭니다.
import clr, json
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ───────── 설정 ─────────
RUN_SEPARATION = True
RUN_SCHEDULES = True
FLOOR_LEVEL = {'1': '1F', '2': '2F', '3': '3F', '4': '4F', '5': '5F', '6': '6F', '7': '옥상'}
TAG = 'PDF자동생성_실구분선'
PX_W = 840.0
# 일람표: 이름, 카테고리, 필드(순서대로, 한글/영문 이름 후보), 정렬·그룹 필드 수, 항목별 표시 여부
SCHEDULES = [
    ('PDF_실 면적표', BuiltInCategory.OST_Rooms,
     [['레벨', 'Level'], ['이름', 'Name'], ['면적', 'Area']], 1, True, ['면적', 'Area']),
    ('PDF_문 일람표', BuiltInCategory.OST_Doors,
     [['레벨', 'Level'], ['패밀리 및 유형', 'Family and Type'], ['폭', 'Width'], ['높이', 'Height'], ['개수', 'Count']], 2, False, ['개수', 'Count']),
    ('PDF_창 일람표', BuiltInCategory.OST_Windows,
     [['레벨', 'Level'], ['패밀리 및 유형', 'Family and Type'], ['폭', 'Width'], ['높이', 'Height'], ['개수', 'Count']], 2, False, ['개수', 'Count']),
    ('PDF_벽 물량표', BuiltInCategory.OST_Walls,
     [['베이스 구속', 'Base Constraint'], ['패밀리 및 유형', 'Family and Type'], ['개수', 'Count'], ['길이', 'Length'], ['면적', 'Area'], ['체적', 'Volume']], 2, False, ['개수', 'Count', '길이', 'Length', '면적', 'Area', '체적', 'Volume']),
]
# ────────────────────────

DATA = json.loads(r'''{"seps": {"1": [[[390.4, 677.5], [368.2, 776.6]], [[196.3, 637.5], [198.2, 641.0]], [[224.1, 665.1], [230.4, 670.8]], [[363.6, 793.7], [365.3, 789.3]], [[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]], "2": [[[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]], "3": [[[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]], "4": [[[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]], "5": [[[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]], "6": [[[350.32, 492.58], [331.51, 576.09]], [[350.32, 492.58], [344.47, 491.26]]]}}''')
doc = DocumentManager.Instance.CurrentDBDocument
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

# ── 1. 실 구분선 ──
if RUN_SEPARATION:
    try:
        # 이전에 만든 실 구분선 삭제 (구분선에는 주석을 달 수 없어 전체 실 구분선을 지우고 다시 그림)
        old = [e.Id for e in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RoomSeparationLines).WhereElementIsNotElementType().ToElements()]
        for i in old:
            doc.Delete(i)
        if old:
            log.append('기존 실 구분선 %d개 삭제' % len(old))
        plans = [v for v in FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
                 if not v.IsTemplate and v.GenLevel is not None and v.ViewType == ViewType.FloorPlan]
        made = 0
        for fl, segs in sorted(DATA['seps'].items()):
            img = images.get('%s.pdf' % fl)
            lvl = lv_by_name.get(FLOOR_LEVEL[fl])
            view = next((v for v in plans if v.GenLevel.Id == lvl.Id), None) if lvl else None
            if img is None or lvl is None or view is None:
                log.append('%s층 실 구분선: PDF/레벨/평면뷰 없음' % fl); continue
            c = img.GetLocation(BoxPlacement.Center)
            k = img.Width / PX_W
            left, top = c.X - img.Width / 2.0, c.Y + img.Height / 2.0
            P = lambda x, y: XYZ(left + x * k, top - y * k, lvl.Elevation)
            sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, lvl.Elevation)))
            arr = CurveArray()
            for a, b in segs:
                arr.Append(Line.CreateBound(P(a[0], a[1]), P(b[0], b[1])))
            for e in doc.Create.NewRoomBoundaryLines(sp, arr, view):
                p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if p is not None and not p.IsReadOnly:
                    p.Set(TAG)
                made += 1
        log.append('실 구분선 %d개 생성' % made)
    except Exception as ex:
        log.append('실 구분선 단계 오류: %s' % str(ex).splitlines()[0])

doc.Regenerate()

# ── 1-2. 계단실 실 다시 배치 (구분선이 생긴 뒤 경계를 새로 계산하도록) ──
if RUN_SEPARATION:
    try:
        n = 0
        for rm in list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()):
            nm = rm.get_Parameter(BuiltInParameter.ROOM_NAME)
            if nm is None or nm.AsString() != '계단실' or rm.Location is None:
                continue
            pt = rm.Location.Point
            lvl = doc.GetElement(rm.LevelId)
            upper = rm.UpperLimit
            cm = rm.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
            doc.Delete(rm.Id)
            doc.Regenerate()
            new = doc.Create.NewRoom(lvl, UV(pt.X, pt.Y))
            new.get_Parameter(BuiltInParameter.ROOM_NAME).Set('계단실')
            if upper is not None:
                new.UpperLimit = upper
                new.LimitOffset = 0.0
            if cm:
                new.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(cm)
            n += 1
        log.append('계단실 %d개 다시 배치' % n)
    except Exception as ex:
        log.append('계단실 재배치 오류: %s' % str(ex).splitlines()[0])
    doc.Regenerate()

# ── 2. 일람표 ──
if RUN_SCHEDULES:
    existing = dict((ename(v), v) for v in FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements())
    for name, cat, fields, n_sort, itemized, total_names in SCHEDULES:
        try:
            if name in existing:
                doc.Delete(existing[name].Id)
            vs = ViewSchedule.CreateSchedule(doc, ElementId(cat))
            vs.Name = name
            d = vs.Definition
            avail = list(d.GetSchedulableFields())
            fids, missing = [], []
            for cands in fields:
                sf = next((f for f in avail if f.GetName(doc) in cands), None)
                if sf is None:
                    missing.append(cands[0]); continue
                fld = d.AddField(sf)
                fids.append(fld)
                if fld.GetName() in total_names or cands[0] in total_names:
                    try:
                        fld.DisplayType = ScheduleFieldDisplayType.Totals
                    except Exception:
                        pass
            for fld in fids[:n_sort]:
                g = ScheduleSortGroupField(fld.FieldId)
                g.ShowHeader = False
                d.AddSortGroupField(g)
            d.IsItemized = itemized
            d.ShowGrandTotal = True
            try:
                d.ShowGrandTotalCount = False
            except Exception:
                pass
            log.append('%s 생성%s' % (name, (' (없는 필드: %s)' % ', '.join(missing)) if missing else ''))
        except Exception as ex:
            log.append('%s 실패: %s' % (name, str(ex).splitlines()[0]))

TransactionManager.Instance.TransactionTaskDone()
OUT = log
