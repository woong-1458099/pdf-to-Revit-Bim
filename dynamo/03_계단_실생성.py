# -*- coding: utf-8 -*-
# [Revit 3] 계단(StairsEditScope) + 난간 + 실(Room) 생성
# - 계단 : 1층 22단(디딤판 270mm), 2~6층 20단(300mm), 계단참 자동 생성
# - 실   : PDF 글자 위치에 NewRoom + 실 이름 입력
# - 재실행 : 주석 = 'PDF자동생성_계단실' 요소만 교체
# 실행 : Dynamo > Python Script 노드(엔진 PythonNet3)에 붙여 넣거나 같은 이름의 .dyn 을 열어 실행
#
# PDF 평면도 → Revit 계단 + 실(Room) 자동 생성
# 벽·바닥·창·문·커튼월은 건드리지 않습니다. 다시 실행하면 이 스크립트가 만든 계단·실만 지우고 새로 만듭니다.
import clr, json, math
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Architecture import *
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ───────── 설정 ─────────
RUN_STAIRS = True
RUN_ROOMS = True
FLOOR_LEVEL = {'1': '1F', '2': '2F', '3': '3F', '4': '4F', '5': '5F', '6': '6F', '7': '옥상'}
STAIR_FLOORS = ['1', '2', '3', '4', '5', '6']      # 이 층에서 위층으로 올라가는 계단
MAX_RISER_MM = 180.0
RUN_GAP_MM = 50.0              # 두 계단 사이 칸막이 여유
ADD_RAILINGS = True
TAG = 'PDF자동생성_계단실'
PX_W = 840.0
# ────────────────────────

DATA = json.loads(r'''{"stair":{"a":[264.5509948730469,513.85498046875],"u":[0.9755607592287645,0.21972984561273537],"n":[0.21972984561273537,-0.9755607592287645],"t_east":76.41261925027248,"t_west":-0.045227308317507445,"off":-0.002276454150349863,"width":73.6,"tread":8.495316284287776},"rooms":{"1":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["카페",331.1,624.0],["서점",562.4,473.2],["HALL",425.4,515.6],["계단실",249.87,510.55]],"2":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["카페",434.6,542.8],["독서실",482.1,391.8],["계단실",249.87,510.55]],"3":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["식당",491.6,378.4],["뷔페",489.4,582.9],["계단실",249.87,510.55]],"4":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["PC방",478.3,480.7],["계단실",249.87,510.55]],"5":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["바버샵",524.1,375.0],["계단실",249.87,510.55]],"6":[["화장실(남)",290.5,346.4],["화장실(여)",340.8,264.6],["계단실",249.87,510.55]],"7":[["계단실",249.87,510.55]]}}''')
doc = DocumentManager.Instance.CurrentDBDocument
MM = 1.0 / 304.8
log = []


def ename(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)


class WarnSwallower(IFailuresPreprocessor):
    __namespace__ = 'PDFStairsRooms'

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return FailureProcessingResult.Continue


def tx(name):
    t = Transaction(doc, name)
    t.Start()
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(WarnSwallower())
    t.SetFailureHandlingOptions(o)
    return t


def tagged(cat):
    out = []
    for e in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType().ToElements():
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None and p.AsString() == TAG:
            out.append(e.Id)
    return out


def set_tag(e):
    p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(TAG)


levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
lv_by_name = dict((ename(l), l) for l in levels)
images = {}
for img in FilteredElementCollector(doc).OfClass(ImageInstance).ToElements():
    images[ename(doc.GetElement(img.GetTypeId())).strip().lower()] = img


def frame(fl):
    img = images.get('%s.pdf' % fl)
    lvl = lv_by_name.get(FLOOR_LEVEL[fl])
    if img is None or lvl is None:
        return None
    c = img.GetLocation(BoxPlacement.Center)
    k = img.Width / PX_W
    left, top = c.X - img.Width / 2.0, c.Y + img.Height / 2.0
    idx = levels.index(lvl)
    nxt = levels[idx + 1] if idx + 1 < len(levels) else None
    return {'k': k, 'left': left, 'top': top, 'lvl': lvl, 'nxt': nxt}


def XY(F, x, y, z):
    return XYZ(F['left'] + x * F['k'], F['top'] - y * F['k'], z)


# ── 0. 이전 결과 삭제 (Dynamo 트랜잭션 사용) ──
TransactionManager.Instance.EnsureInTransaction(doc)
n_st = n_rm = 0
if RUN_STAIRS:
    for cat in (BuiltInCategory.OST_StairsRailing, BuiltInCategory.OST_Stairs):
        for i in tagged(cat):
            try:
                doc.Delete(i); n_st += cat == BuiltInCategory.OST_Stairs
            except Exception:
                pass
if RUN_ROOMS:
    for i in tagged(BuiltInCategory.OST_Rooms):
        try:
            doc.Delete(i); n_rm += 1
        except Exception:
            pass
if n_st or n_rm:
    log.append('이전 자동생성 계단 %d개, 실 %d개 삭제' % (n_st, n_rm))

# ── 1. 실 ──
if RUN_ROOMS:
    made = 0
    for fl, rooms in sorted(DATA['rooms'].items()):
        F = frame(fl)
        if F is None:
            continue
        for name, x, y in rooms:
            try:
                p = XY(F, x, y, 0)
                rm = doc.Create.NewRoom(F['lvl'], UV(p.X, p.Y))
                rm.get_Parameter(BuiltInParameter.ROOM_NAME).Set(name)
                if F['nxt'] is not None:
                    rm.UpperLimit = F['nxt']
                    rm.LimitOffset = 0.0
                set_tag(rm)
                made += 1
            except Exception as ex:
                log.append('%s층 실(%s) 실패: %s' % (fl, name, ex))
    log.append('실 %d개 생성' % made)

# 여기까지(삭제 + 실)를 확정하고, 계단은 별도 트랜잭션으로 처리
TransactionManager.Instance.ForceCloseTransaction()

# ── 2. 계단 ──
if RUN_STAIRS:
    S = DATA['stair']
    ax, ay = S['a']; ux, uy = S['u']; nx, ny = S['n']

    def SP(t_, o_):   # 계단 축(t) / 북쪽 오프셋(o) → PDF 좌표
        return (ax + ux * t_ + nx * o_, ay + uy * t_ + ny * o_)

    rail_type = None
    if ADD_RAILINGS:
        rts = FilteredElementCollector(doc).OfClass(RailingType).ToElements()
        rail_type = rts[0] if rts else None

    made = 0
    for fl in STAIR_FLOORS:
        F = frame(fl)
        if F is None or F['nxt'] is None:
            log.append('%s층 계단: 레벨/PDF 없음' % fl); continue
        scope = None; t = None
        try:
            H = (F['nxt'].Elevation - F['lvl'].Elevation) / MM
            R = 2 * int(round(H / 2.0 / MAX_RISER_MM))
            per = R // 2
            run_pt = S['t_east'] - S['t_west']                 # 도면상 계단 길이 (pt)
            tread_mm = run_pt * F['k'] / MM / (per - 1)
            half_w_pt = S['width'] / 2.0
            run_w_mm = half_w_pt * F['k'] / MM - RUN_GAP_MM
            q = half_w_pt / 2.0                                  # 각 계단 중심선 오프셋
            z0 = F['lvl'].Elevation                              # 계단 경로는 실제 레벨 높이에 둠
            scope = StairsEditScope(doc, 'PDF 계단 %s층' % fl)
            sid = scope.Start(F['lvl'].Id, F['nxt'].Id)
            t = tx('PDF 계단 %s층' % fl)
            st = doc.GetElement(sid)
            try:
                st.DesiredRisersNumber = R
            except Exception:
                pass
            try:
                st.ActualTreadDepth = tread_mm * MM
            except Exception:
                pass
            # 1단: 북쪽 절반, 동쪽 끝(UP)에서 서쪽으로
            x1, y1 = SP(S['t_east'], q); x2, y2 = SP(S['t_west'], q)
            r1 = StairsRun.CreateStraightRun(doc, sid, Line.CreateBound(XY(F, x1, y1, z0), XY(F, x2, y2, z0)), StairsRunJustification.Center)
            r1.ActualRunWidth = run_w_mm * MM
            # 2단: 남쪽 절반, 서쪽에서 동쪽으로
            z1 = r1.TopElevation if r1.TopElevation > z0 + 1e-6 else z0 + r1.TopElevation   # 상대/절대 높이 모두 대응
            x3, y3 = SP(S['t_west'], -q); x4, y4 = SP(S['t_east'], -q)
            r2 = StairsRun.CreateStraightRun(doc, sid, Line.CreateBound(XY(F, x3, y3, z1), XY(F, x4, y4, z1)), StairsRunJustification.Center)
            r2.ActualRunWidth = run_w_mm * MM
            try:
                StairsLanding.CreateAutomaticLanding(doc, r1.Id, r2.Id)
            except Exception as ex:
                log.append('%s층 계단참 자동생성 실패: %s' % (fl, ex))
            set_tag(st)
            t.Commit()
            scope.Commit(WarnSwallower())
            t = None; scope = None
            # 난간은 Revit이 계단 생성 시 자동으로 붙임 → 태그만 달아 둠 (재실행 시 함께 삭제)
            t = tx('PDF 난간 태그 %s층' % fl)
            try:
                st = doc.GetElement(sid)
                rids = list(st.GetAssociatedRailings())
                for rid in rids:
                    set_tag(doc.GetElement(rid))
                if not rids and rail_type is not None:
                    for rid in Railing.Create(doc, sid, rail_type.Id, RailingPlacementPosition.Treads):
                        set_tag(doc.GetElement(rid))
            except Exception as ex:
                log.append('%s층 난간 처리 실패: %s' % (fl, str(ex).splitlines()[0]))
            t.Commit(); t = None
            made += 1
            log.append('%s층 계단: 챌면 %d개(%.0fmm), 디딤판 %.0fmm, 폭 %.0fmm' % (fl, R, H / R, tread_mm, run_w_mm))
        except Exception as ex:
            import traceback
            log.append('%s층 계단 실패: %s' % (fl, str(ex).splitlines()[0]))
            try:
                if t is not None and t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
            except Exception:
                pass
            try:
                if scope is not None and scope.IsActive:
                    scope.Cancel()
            except Exception:
                pass
    log.insert(0, '계단 %d개 생성' % made)

OUT = log
