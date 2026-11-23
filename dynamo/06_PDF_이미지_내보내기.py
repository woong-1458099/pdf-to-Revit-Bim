# -*- coding: utf-8 -*-
# [Revit 6] 시트는 그대로 두고 도면집 PDF + 3D PNG 만 다시 내보내기
# 실행 : Dynamo > Python Script 노드(엔진 PythonNet3)에 붙여 넣거나 같은 이름의 .dyn 을 열어 실행
#
# 도면집 PDF + 3D 이미지만 다시 내보내기 (시트는 건드리지 않음)
import clr, os
from System import Environment
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List
import System.IO

OUT_DIR = os.path.join(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), 'BIM포트폴리오')
doc = DocumentManager.Instance.CurrentDBDocument
TransactionManager.Instance.ForceCloseTransaction()
log = ['[내보내기 전용 v1]']
System.IO.Directory.CreateDirectory(OUT_DIR)

sheets = sorted([s for s in FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
                 if not s.IsPlaceholder and s.SheetNumber.startswith('A-')], key=lambda s: s.SheetNumber)
try:
    ids = List[ElementId]()
    for s in sheets: ids.Add(s.Id)
    o = PDFExportOptions()
    o.Combine = True
    o.FileName = '도면집'
    try:
        o.HideCropBoundaries = True; o.HideScopeBoxes = True
    except Exception:
        pass
    doc.Export(OUT_DIR, ids, o)
    log.append('PDF 도면집 %d장 저장: %s' % (ids.Count, OUT_DIR))
except Exception as ex:
    log.append('PDF 실패: %s' % ex)

for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
    if v.IsTemplate or not v.Name.startswith('S_'): continue
    try:
        o = ImageExportOptions()
        o.ExportRange = ExportRange.SetOfViews
        vids = List[ElementId](); vids.Add(v.Id)
        o.SetViewsAndSheets(vids)
        o.FilePath = os.path.join(OUT_DIR, v.Name.replace('S_', ''))
        o.ZoomType = ZoomFitType.FitToPage
        o.PixelSize = 3000
        o.ImageResolution = ImageResolution.DPI_300
        o.HLRandWFViewsFileType = ImageFileType.PNG
        o.ShadowViewsFileType = ImageFileType.PNG
        doc.ExportImage(o)
        log.append('3D 이미지: %s' % v.Name)
    except Exception as ex:
        log.append('%s 실패: %s' % (v.Name, ex))
OUT = log
