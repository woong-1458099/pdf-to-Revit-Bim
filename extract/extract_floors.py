# -*- coding: utf-8 -*-
"""
[2단계] 바닥 외곽 추출
- 입력 : out/walls.json
- 출력 : out/floors.json  (층별 바닥 외곽 폴리곤 + 구멍)
- 원리 : 벽 띠(중심선을 두께만큼 buffer)를 합쳐 건물 외곽 폴리곤을 만들고 단순화
- 실행 : python extract_floors.py [단순화 허용오차 pt, 기본 0.1]
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_walls as W, math, json
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import unary_union
D = json.load(open('out/walls.json'))
out = {}
CL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1
for k, f in enumerate(W.files):
    fl = str(k+1)
    p = W.fitz.open(W.base+f)[0]
    geoms = []
    for x1, y1, x2, y2, t in D[fl]['walls'] + D[fl].get('jambs', []):   # 바닥 외곽에는 돌출부도 포함
        geoms.append(LineString([(x1, y1), (x2, y2)]).buffer(t/2, cap_style=2, join_style=2))
    for a in D[fl]['arcs']:
        geoms.append(LineString([(a[0], a[1]), (a[2], a[3]), (a[4], a[5])]).buffer(a[6]/2))
    for a, b, w in W.get_lines(p, {1.438}):
        geoms.append(LineString([a, b]).buffer(0.8))
    thin = W.get_lines(p, {0.24})
    darcs = W.find_door_arcs(thin)
    keyp = [d['c'] for d in darcs]
    for a, b, w in thin:
        if math.dist(a, b) < 6:
            continue   # arc pieces
        if any(math.dist(a, k) < 2 or math.dist(b, k) < 2 for k in keyp):
            continue   # open door leaves
        geoms.append(LineString([a, b]).buffer(0.8))
    U = unary_union(geoms)
    import shapely
    from shapely.geometry import MultiPoint
    pts = []
    for g in (U.geoms if hasattr(U, 'geoms') else [U]):
        ext = g.exterior
        n = max(4, int(ext.length / 2))
        pts += [ext.interpolate(i * ext.length / n).coords[0] for i in range(n)]
    hull = shapely.concave_hull(MultiPoint(pts), ratio=CL)
    R = 25
    closed = U.buffer(R, join_style=2).buffer(-R, join_style=2)
    cps = list(closed.geoms) if hasattr(closed, 'geoms') else [closed]
    filled = unary_union([Polygon(g.exterior) for g in cps])
    tight = hull.intersection(filled)
    if hasattr(tight, 'geoms'):
        tight = max(tight.geoms, key=lambda g: g.area)
    print('  hull-tight diff m2', round((hull.area - tight.area)*(29669/840/1000)**2, 2))
    use = tight if (hull.area - tight.area) * (29669/840/1000)**2 < 3 else hull
    shell = Polygon(use.exterior).simplify(0.8, preserve_topology=True)
    # vertical circulation openings (1.079 lines: elevator box + stair treads)
    L = [LineString([a, b]) for a, b, w in W.get_lines(p, {1.079})]
    holes = []
    if L:
        from shapely.ops import polygonize
        cl = unary_union([l.buffer(0.8) for l in L])
        parts = list(cl.geoms) if hasattr(cl, 'geoms') else [cl]
        for g in parts:
            sub = [l for l in L if l.intersects(g)]
            faces = unary_union(list(polygonize(unary_union(sub))))
            r = faces.minimum_rotated_rectangle if (not faces.is_empty and faces.area > 800) else unary_union(sub).minimum_rotated_rectangle
            if r.area > 800 and fl != '1':
                holes.append(r)
    out[fl] = {'shell': [list(map(lambda v: round(v, 3), c)) for c in list(shell.exterior.coords)[:-1]],
               'holes': [[list(map(lambda v: round(v, 3), c)) for c in list(h.exterior.coords)[:-1]] for h in holes]}
    print(fl, 'shell pts', len(out[fl]['shell']), 'area m2', round(shell.area*(29669/840/1000)**2, 1), 'holes', [round(h.area*(29669/840/1000)**2, 1) for h in holes])
json.dump(out, open('out/floors.json', 'w'))
