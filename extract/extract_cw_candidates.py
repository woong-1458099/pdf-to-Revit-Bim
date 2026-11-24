# -*- coding: utf-8 -*-
"""
[3단계-a] 커튼월(유리면) 후보 추출
- 입력 : pdf/*.pdf, out/walls.json
- 출력 : out/cw.json, out/cw_keep.json  (유리면 후보 선과 채택 목록)
- 원리 : 0.24pt 가는 선 중 벽 개구부에 속하지 않는 긴 직선/곡선을 유리면 후보로 분류
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_walls as W, json, math
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
c = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dynamo', '01_모델생성_벽바닥창문.py'), encoding='utf-8').read()
D = json.loads(c.split("r'''")[1].split("'''")[0])
out = {}
KEEP = {}
for k, f in enumerate(W.files):
    fl = str(k+1)
    p = W.fitz.open(W.base+f)[0]
    thin = W.get_lines(p, {0.24})
    darcs = W.find_door_arcs(thin)
    hinges = [d['c'] for d in darcs]
    bands = unary_union([LineString([(w[0], w[1]), (w[2], w[3])]).buffer(w[4]/2+1.2, cap_style=2) for w in D[fl]['walls']]
                        + [LineString([(a[0], a[1]), (a[2], a[3]), (a[4], a[5])]).buffer(a[6]/2+1.2) for a in D[fl]['arcs']])
    keep = []
    for a, b, w in thin:
        L = math.dist(a, b)
        seg = LineString([a, b])
        if any(math.dist(a, h) < 2.5 or math.dist(b, h) < 2.5 for h in hinges):
            continue   # door leaf
        if L < 6:
            # arc pieces: keep only if not part of a door arc
            mid = ((a[0]+b[0])/2, (a[1]+b[1])/2)
            if any(abs(math.dist(mid, d['c']) - d['r']) < 1.0 for d in darcs):
                continue
        if bands.buffer(0).contains(seg.interpolate(0.5, normalized=True)) and seg.length < 200:
            if bands.intersection(seg).length > 0.8*seg.length:
                continue   # window frame inside wall band
        keep.append(seg)
    KEEP[fl] = [list(l.coords) for l in keep]
    strips = unary_union([s.buffer(2.0, cap_style=2) for s in keep])
    polys = list(strips.geoms) if hasattr(strips, 'geoms') else [strips]
    lines, curves = [], []
    for g in polys:
        r = g.minimum_rotated_rectangle
        xs = list(r.exterior.coords)[:4]
        e = sorted([(math.dist(xs[i], xs[(i+1) % 4]), i) for i in range(4)])
        wdt, ln = e[0][0], e[-1][0]
        if ln < 25:
            continue
        if wdt < 9 and g.area > 0.6*r.area:
            i = e[0][1]
            m1 = ((xs[i][0]+xs[(i+1) % 4][0])/2, (xs[i][1]+xs[(i+1) % 4][1])/2)
            j = (i+2) % 4
            m2 = ((xs[j][0]+xs[(j+1) % 4][0])/2, (xs[j][1]+xs[(j+1) % 4][1])/2)
            # trim 2pt buffer at both ends
            ux, uy = (m2[0]-m1[0])/ln, (m2[1]-m1[1])/ln
            m1 = (m1[0]+ux*2, m1[1]+uy*2); m2 = (m2[0]-ux*2, m2[1]-uy*2)
            lines.append([round(v, 3) for v in (*m1, *m2)])
        else:
            # curved strip: fit circle to centerline samples
            import numpy as np
            sk = g.exterior
            pts = [sk.interpolate(t*sk.length/200).coords[0] for t in range(200)]
            cc, R = W.fit_circle(pts)
            err = np.std([math.dist(q, cc) for q in pts])
            if R < 400 and err < 4.0:
                angs = sorted((math.atan2(q[1]-cc[1], q[0]-cc[0]) for q in pts))
                # largest gap in angles → arc span is the complement
                gaps = [(angs[(i+1) % len(angs)]-angs[i]) % (2*math.pi) for i in range(len(angs))]
                gi = max(range(len(gaps)), key=lambda i: gaps[i])
                a0, a1 = angs[(gi+1) % len(angs)], angs[gi]
                span = (a1-a0) % (2*math.pi)
                Rm = sum(math.dist(q, cc) for q in pts)/len(pts)
                P = lambda t: (cc[0]+Rm*math.cos(t), cc[1]+Rm*math.sin(t))
                curves.append([round(v, 3) for v in (*P(a0+0.01), *P(a0+span/2), *P(a0+span-0.01))])
            else:
                print(fl, 'skip shape', round(ln), round(wdt), round(err, 1))
    out[fl] = {'lines': lines, 'curves': curves}
    print(fl, 'straight', len(lines), 'curved', len(curves))
json.dump(out, open('out/cw.json', 'w'))
json.dump(KEEP, open('out/cw_keep.json', 'w'))
