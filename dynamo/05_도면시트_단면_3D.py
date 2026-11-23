# -*- coding: utf-8 -*-
# [Revit 5] A1 도면 시트 11장 + 단면도 + 3D 뷰 + PDF/PNG 내보내기
# - 평면도 1:50 (7장), 입면도 1:100 (2장), 단면도 1:100 (1장), 표지 3D (1장)
# - 도면틀 범위를 읽어 표제란을 뺀 영역 중앙에 뷰 배치
# - 재실행 : 시트 번호 A-xxx 와 'S_' 로 시작하는 뷰를 지우고 새로 만듦
# - 알려진 한계 : 이 버전에서 시트 작성자·언더레이 끄기·단면 표식 숨김이 적용되지 않아
#                RevitClaudeConnector(MCP)로 후보정함 → README 참고
# 실행 : Dynamo > Python Script 노드(엔진 PythonNet3)에 붙여 넣거나 같은 이름의 .dyn 을 열어 실행
#
# 도면 시트 + 단면도 + 3D 이미지 + PDF 도면집 자동 생성
# 다시 실행하면 이 스크립트가 만든 시트(A-xxx)와 뷰(이름이 'S_'로 시작)를 지우고 새로 만듭니다.
import clr, json, math, os
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List
from System import Environment
import System.IO

# ───────── 설정 ─────────
AUTHOR = '작성자 이름'                 # 표제란 작성자
OUT_DIR = os.path.join(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), 'BIM포트폴리오')   # 결과 저장 폴더
PLAN_LEVELS = [('1F', '1층 평면도'), ('2F', '2층 평면도'), ('3F', '3층 평면도'), ('4F', '4층 평면도'),
               ('5F', '5층 평면도'), ('6F', '6층 평면도'), ('옥상', '옥상 평면도')]
PLAN_SCALE = 50                 # A1 도면틀 기준
ELEV_SCALE = 100
SECTION_SCALE = 100
TAG_ROOMS = True
TAG_DOORS_WINDOWS = True
EXPORT_PDF = True
EXPORT_IMAGES = True
PX_W = 840.0
# ────────────────────────

DATA = json.loads(r'''{"sheet_numbers": ["A-001", "A-101", "A-102", "A-103", "A-104", "A-105", "A-106", "A-107", "A-201", "A-202", "A-301"], "sections": [["단면도 A-A (계단 방향)", [305.67, 504.25], [0.9755607592287645, 0.21972984561273537]], ["단면도 B-B (계단 직각 방향)", [301.62, 522.2], [-0.21972984561273537, 0.9755607592287645]]]}''')
doc = DocumentManager.Instance.CurrentDBDocument
MM = 1.0 / 304.8
log = []


def ename(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)


def short(ex):
    return str(ex).splitlines()[0]


levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
lv_by_name = dict((ename(l), l) for l in levels)

TransactionManager.Instance.EnsureInTransaction(doc)

# ── 0. 이전 결과 삭제 ──
try:
    nums = set(DATA['sheet_numbers'])
    for sh in list(FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()):
        if sh.SheetNumber in nums:
            doc.Delete(sh.Id)
    for v in list(FilteredElementCollector(doc).OfClass(View).ToElements()):
        try:
            if not v.IsTemplate and ename(v).startswith('S_'):
                doc.Delete(v.Id)
        except Exception:
            pass
except Exception as ex:
    log.append('이전 결과 삭제 오류: %s' % short(ex))

# ── 공통 도구 ──
def bbox_of(elems):
    mn = [1e9, 1e9, 1e9]; mx = [-1e9, -1e9, -1e9]
    for e in elems:
        b = e.get_BoundingBox(None)
        if b is None: continue
        for i, a in enumerate((b.Min.X, b.Min.Y, b.Min.Z)): mn[i] = min(mn[i], a)
        for i, a in enumerate((b.Max.X, b.Max.Y, b.Max.Z)): mx[i] = max(mx[i], a)
    return XYZ(*mn), XYZ(*mx)


all_walls = list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType().ToElements())
all_floors = list(FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType().ToElements())
BMIN, BMAX = bbox_of(all_walls)


def fit_crop(view, pmin, pmax, margin_mm=1500):
    """모델 상자(pmin~pmax)를 뷰 좌표로 바꿔 자르기 영역을 맞춤"""
    cb = view.CropBox
    inv = cb.Transform.Inverse
    xs, ys = [], []
    for x in (pmin.X, pmax.X):
        for y in (pmin.Y, pmax.Y):
            for z in (pmin.Z, pmax.Z):
                q = inv.OfPoint(XYZ(x, y, z)); xs.append(q.X); ys.append(q.Y)
    m = margin_mm * MM
    nb = BoundingBoxXYZ()
    nb.Transform = cb.Transform
    nb.Min = XYZ(min(xs) - m, min(ys) - m, cb.Min.Z)
    nb.Max = XYZ(max(xs) + m, max(ys) + m, cb.Max.Z)
    view.CropBox = nb
    view.CropBoxActive = True
    view.CropBoxVisible = False


def hide_cat(view, bic):
    try:
        view.SetCategoryHidden(ElementId(bic), True)
    except Exception:
        pass


def dup(view, name):
    nid = view.Duplicate(ViewDuplicateOption.Duplicate)
    v = doc.GetElement(nid)
    v.Name = name
    return v


# 도면틀 (A3 우선)
tbs = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType().ToElements())
tb = next((t for t in tbs if 'A3' in ename(t) or 'A3' in (t.FamilyName or '')), tbs[0] if tbs else None)
TB_ID = tb.Id if tb else ElementId.InvalidElementId
log.append('도면틀: %s' % (('%s : %s' % (tb.FamilyName, ename(tb))) if tb else '없음(빈 시트)'))

sheets = []


def sheet(num, name):
    s = ViewSheet.Create(doc, TB_ID)
    s.SheetNumber = num
    s.Name = name
    for bip in (BuiltInParameter.SHEET_DRAWN_BY, BuiltInParameter.SHEET_DESIGNED_BY,
                BuiltInParameter.SHEET_CHECKED_BY, BuiltInParameter.SHEET_APPROVED_BY):
        try:
            s.get_Parameter(bip).Set(AUTHOR)
        except Exception:
            pass
    sheets.append(s)
    return s


def tb_box(s):
    """시트 위 도면틀의 범위 (오른쪽 표제란을 뺀 그림 영역)"""
    doc.Regenerate()
    tbi = list(FilteredElementCollector(doc, s.Id).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType().ToElements())
    if tbi:
        b = tbi[0].get_BoundingBox(s)
        x0, y0, x1, y1 = b.Min.X, b.Min.Y, b.Max.X, b.Max.Y
    else:
        x0, y0, x1, y1 = 0.0, 0.0, 841 * MM, 594 * MM
    strip = (x1 - x0) * 0.14                      # 오른쪽 표제란 폭
    return x0, y0, x1 - strip, y1


def sheet_center(s):
    x0, y0, x1, y1 = tb_box(s)
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def sheet_width(s):
    x0, y0, x1, y1 = tb_box(s)
    return (x1 - x0), (y1 - y0)


def place(s, v, u, vv):
    return Viewport.Create(doc, s.Id, v.Id, XYZ(u, vv, 0))


# ── 1. 평면도 시트 ──
plan_views = [v for v in FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
              if not v.IsTemplate and v.ViewType == ViewType.FloorPlan]
rooms = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements())
doors = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().ToElements())
wins = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements())
n_plan = n_rt = n_dt = 0
for i, (lvname, vname) in enumerate(PLAN_LEVELS):
    try:
        lvl = lv_by_name.get(lvname)
        src = next((v for v in plan_views if v.GenLevel is not None and lvl is not None and v.GenLevel.Id == lvl.Id), None)
        if src is None:
            log.append('%s: 평면 뷰 없음' % vname); continue
        v = dup(src, 'S_' + vname)
        v.Scale = PLAN_SCALE
        hide_cat(v, BuiltInCategory.OST_RasterImages)     # PDF 밑그림 숨김
        for bic in (BuiltInCategory.OST_Elev, BuiltInCategory.OST_Sections, BuiltInCategory.OST_RoomSeparationLines):
            hide_cat(v, bic)
        for bip in (BuiltInParameter.VIEW_UNDERLAY_BOTTOM_ID, BuiltInParameter.VIEW_UNDERLAY_TOP_ID):
            try:                                          # 아래층 언더레이 끄기
                prm = v.get_Parameter(bip)
                if prm is not None and not prm.IsReadOnly:
                    prm.Set(ElementId.InvalidElementId)
            except Exception:
                pass
        lw = [w for w in all_walls if w.LevelId == lvl.Id] + [f for f in all_floors if f.LevelId == lvl.Id]
        mn, mx = bbox_of(lw if lw else all_walls)
        fit_crop(v, XYZ(mn.X, mn.Y, 0), XYZ(mx.X, mx.Y, 0), 2000)
        if TAG_ROOMS:
            for rm in rooms:
                if rm.LevelId == lvl.Id and rm.Area > 0 and rm.Location is not None:
                    try:
                        p = rm.Location.Point
                        doc.Create.NewRoomTag(LinkElementId(rm.Id), UV(p.X, p.Y), v.Id); n_rt += 1
                    except Exception:
                        pass
        if TAG_DOORS_WINDOWS:
            for e in doors + wins:
                if e.LevelId == lvl.Id:
                    try:
                        p = e.Location.Point
                        IndependentTag.Create(doc, v.Id, Reference(e), False, TagMode.TM_ADDBY_CATEGORY,
                                              TagOrientation.Horizontal, p); n_dt += 1
                    except Exception:
                        pass
        s = sheet('A-1%02d' % (i + 1), vname)
        cu, cv = sheet_center(s)
        place(s, v, cu, cv)
        n_plan += 1
    except Exception as ex:
        log.append('%s 시트 실패: %s' % (vname, short(ex)))
log.append('평면도 시트 %d장 (실 태그 %d, 문·창 태그 %d)' % (n_plan, n_rt, n_dt))

# ── 2. 입면도 시트 (2면씩 2장) ──
try:
    elevs = [v for v in FilteredElementCollector(doc).OfClass(ViewSection).ToElements()
             if not v.IsTemplate and v.ViewType == ViewType.Elevation]
    order = ['남측', '동측', '북측', '서측']
    picked = []
    for key in order:
        ev = next((v for v in elevs if key in ename(v) and not ename(v).startswith('S_')), None)
        if ev is not None:
            picked.append((key, ev))
    groups = [picked[0:2], picked[2:4]]
    for gi, grp in enumerate(groups):
        if not grp: continue
        s = sheet('A-20%d' % (gi + 1), '입면도 (%s)' % ', '.join(k for k, _ in grp))
        W, H = sheet_width(s)
        cu, cv = sheet_center(s)
        for j, (key, ev) in enumerate(grp):
            v = dup(ev, 'S_%s 입면도' % key)
            v.Scale = ELEV_SCALE
            for bic in (BuiltInCategory.OST_Sections, BuiltInCategory.OST_Elev, BuiltInCategory.OST_RasterImages):
                hide_cat(v, bic)
            fit_crop(v, BMIN, BMAX, 2000)
            place(s, v, cu + (j - 0.5) * W * 0.48, cv)
    log.append('입면도 시트 %d장 (%d면)' % (len([g for g in groups if g]), len(picked)))
except Exception as ex:
    log.append('입면도 단계 오류: %s' % short(ex))

# ── 3. 단면도 (계단 축 방향 A-A, 직각 방향 B-B) ──
try:
    img = next((i for i in FilteredElementCollector(doc).OfClass(ImageInstance).ToElements()
                if ename(doc.GetElement(i.GetTypeId())).strip().lower() == '1.pdf'), None)
    c = img.GetLocation(BoxPlacement.Center)
    k = img.Width / PX_W
    left, top = c.X - img.Width / 2.0, c.Y + img.Height / 2.0
    P = lambda x, y: XYZ(left + x * k, top - y * k, 0)
    vft = next(t for t in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
               if t.ViewFamily == ViewFamily.Section)
    zmin = levels[0].Elevation - 1500 * MM
    zmax = levels[-1].Elevation + 4000 * MM
    ctr = XYZ((BMIN.X + BMAX.X) / 2, (BMIN.Y + BMAX.Y) / 2, 0)
    span = max(BMAX.X - BMIN.X, BMAX.Y - BMIN.Y) / 2 + 3000 * MM
    secs = []
    for name, (x0, y0), (dx, dy) in DATA['sections']:
        o = P(x0, y0)
        d = XYZ(dx, -dy, 0).Normalize()            # PDF y축 반전
        up = XYZ.BasisZ
        vd = d.CrossProduct(up)                     # 보는 방향
        t = Transform.Identity
        t.Origin = XYZ(o.X, o.Y, 0)
        t.BasisX = d; t.BasisY = up; t.BasisZ = vd
        bb = BoundingBoxXYZ()
        bb.Transform = t
        bb.Min = XYZ(-span, zmin, -span)              # 단면은 -BasisZ 방향을 바라봄 (깊이는 음수 쪽)
        bb.Max = XYZ(span, zmax, 0)
        sv = ViewSection.CreateSection(doc, vft.Id, bb)
        sv.Name = 'S_' + name
        sv.Scale = SECTION_SCALE
        for bic in (BuiltInCategory.OST_Sections, BuiltInCategory.OST_Elev, BuiltInCategory.OST_RasterImages):
            hide_cat(sv, bic)                       # 다른 단면·입면 표식 숨김
        secs.append(sv)
    s = sheet('A-301', '단면도')
    W, H = sheet_width(s)
    cu, cv = sheet_center(s)
    for j, sv in enumerate(secs):
        place(s, sv, cu + (j - 0.5) * W * 0.48, cv)
    log.append('단면도 %d개 + 시트 1장' % len(secs))
except Exception as ex:
    log.append('단면도 단계 오류: %s' % short(ex))

# ── 4. 3D 뷰 (표지용 전경, 2층에서 자른 내부) ──
views3d = []
try:
    v3t = next(t for t in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
               if t.ViewFamily == ViewFamily.ThreeDimensional)
    v1 = View3D.CreateIsometric(doc, v3t.Id)
    v1.Name = 'S_3D 전경'
    v1.DisplayStyle = DisplayStyle.ShadingWithEdges
    views3d.append(v1)
    lv2 = lv_by_name.get('2F')
    v2 = View3D.CreateIsometric(doc, v3t.Id)
    v2.Name = 'S_3D 1층 내부(단면)'
    v2.DisplayStyle = DisplayStyle.ShadingWithEdges
    cut = (lv2.Elevation - 300 * MM) if lv2 else 3000 * MM
    bb = BoundingBoxXYZ()
    bb.Min = XYZ(BMIN.X - 1, BMIN.Y - 1, BMIN.Z - 1)
    bb.Max = XYZ(BMAX.X + 1, BMAX.Y + 1, cut)
    v2.SetSectionBox(bb)
    views3d.append(v2)
    for v in views3d:
        for bic in (BuiltInCategory.OST_RasterImages, BuiltInCategory.OST_Levels, BuiltInCategory.OST_RoomSeparationLines,
                    BuiltInCategory.OST_Rooms):
            hide_cat(v, bic)
        try:                                            # 흰 배경
            wc = Color(255, 255, 255)
            v.SetBackground(ViewDisplayBackground.CreateGradient(wc, wc, wc))
        except Exception as ex:
            log.append('3D 흰 배경 설정 실패(Revit 화면 배경색 사용): %s' % short(ex))
    s = sheet('A-001', '표지 - 3D 전경')
    cu, cv = sheet_center(s)
    v1.Scale = 100
    place(s, v1, cu, cv)
    log.append('3D 뷰 %d개 + 표지 시트' % len(views3d))
except Exception as ex:
    log.append('3D 단계 오류: %s' % short(ex))

TransactionManager.Instance.ForceCloseTransaction()     # 여기까지 확정 (내보내기는 트랜잭션 밖에서)

# ── 5. 내보내기 ──
try:
    System.IO.Directory.CreateDirectory(OUT_DIR)
except Exception:
    pass
if EXPORT_PDF and sheets:
    try:
        ids = List[ElementId]()
        for s in sorted(sheets, key=lambda x: x.SheetNumber):
            ids.Add(s.Id)
        o = PDFExportOptions()
        o.Combine = True
        o.FileName = '도면집'
        try:
            o.HideCropBoundaries = True
            o.HideScopeBoxes = True
        except Exception:
            pass
        doc.Export(OUT_DIR, ids, o)
        log.append('PDF 도면집 저장: %s\\도면집.pdf (%d장)' % (OUT_DIR, ids.Count))
    except Exception as ex:
        log.append('PDF 내보내기 실패: %s' % short(ex))
if EXPORT_IMAGES and views3d:
    for v in views3d:
        try:
            o = ImageExportOptions()
            o.ExportRange = ExportRange.SetOfViews
            vids = List[ElementId](); vids.Add(v.Id)
            o.SetViewsAndSheets(vids)
            o.FilePath = os.path.join(OUT_DIR, ename(v).replace('S_', ''))
            o.ZoomType = ZoomFitType.FitToPage
            o.PixelSize = 3000
            o.ImageResolution = ImageResolution.DPI_300
            o.HLRandWFViewsFileType = ImageFileType.PNG
            o.ShadowViewsFileType = ImageFileType.PNG
            doc.ExportImage(o)
        except Exception as ex:
            log.append('%s 이미지 실패: %s' % (ename(v), short(ex)))
    log.append('3D 이미지 저장 위치: %s' % OUT_DIR)

log.insert(0, '시트 %d장 생성' % len(sheets))
OUT = log
