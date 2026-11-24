# -*- coding: utf-8 -*-
"""
[3단계-b] 커튼월 정리
- 입력 : out/cw_keep.json
- 출력 : out/cw.json  (층별 커튼월 직선·곡선 경로)
- 원리 : 같은 방향으로 이어지는 조각을 병합하고, 곡면 유리는 3점 원호로 근사
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_walls as W, json, math
K = json.load(open('out/cw_keep.json'))
ANG = math.radians(1.5)


def unitv(a, b):
    L = math.dist(a, b)
    return ((b[0]-a[0])/L, (b[1]-a[1])/L), L


out = {}
for fl, segs in K.items():
    segs = [(tuple(s[0]), tuple(s[1])) for s in segs]
    # ---- curved chains over all segments (gradual consistent turning)
    def cross(d1, d2): return d1[0]*d2[1]-d1[1]*d2[0]
    usedc = set(); chains = []
    def nbr(pt, ids):
        for k2, s in enumerate(segs):
            if k2 in usedc or k2 in ids: continue
            if math.dist(s[0], pt) < 0.3: return k2, s[1]
            if math.dist(s[1], pt) < 0.3: return k2, s[0]
    for k2 in range(len(segs)):
        if k2 in usedc: continue
        pts = [segs[k2][0], segs[k2][1]]; ids = [k2]; sign = 0
        for side in (0, 1):
            while True:
                end = pts[-1] if side == 0 else pts[0]; prev = pts[-2] if side == 0 else pts[1]
                r = nbr(end, set(ids))
                if not r: break
                d1 = (end[0]-prev[0], end[1]-prev[1]); d2 = (r[1][0]-end[0], r[1][1]-end[1])
                cs = cross(d1, d2)/(math.hypot(*d1)*math.hypot(*d2)+1e-9)
                ang = math.degrees(math.asin(max(-1, min(1, cs))))
                if side == 1: ang = -ang
                if not (0.3 < abs(ang) < 20) or (sign and (ang > 0) != (sign > 0)): break
                sign = sign or (1 if ang > 0 else -1)
                ids.append(r[0])
                if side == 0: pts.append(r[1])
                else: pts.insert(0, r[1])
        if len(ids) >= 4:
            c, R = W.fit_circle(pts)
            if R < 500 and max(abs(math.dist(q, c)-R) for q in pts) < 1.0:
                chains.append({'pts': pts, 'c': c, 'r': R})
                usedc |= set(ids)
    straight = [s for i, s in enumerate(segs) if i not in usedc and math.dist(*s) >= 6]
    short = []
    # ---- straight groups (union-find)
    n = len(straight)
    par = list(range(n))
    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    for i in range(n):
        u, L = unitv(*straight[i]); nn = (-u[1], u[0]); a = straight[i][0]
        for j in range(i+1, n):
            v, L2 = unitv(*straight[j])
            if abs(u[0]*v[1]-u[1]*v[0]) > math.sin(ANG):
                continue
            c, d = straight[j]
            offs = [(P[0]-a[0])*nn[0]+(P[1]-a[1])*nn[1] for P in (c, d)]
            if max(abs(o) for o in offs) > 8:
                continue
            ts = sorted((P[0]-a[0])*u[0]+(P[1]-a[1])*u[1] for P in (c, d))
            if ts[0] > L+3 or ts[1] < -3:
                continue
            par[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(straight[i])
    lines = []
    for g in groups.values():
        lead = max(g, key=lambda s: math.dist(*s))
        u, _ = unitv(*lead); nn = (-u[1], u[0]); a = lead[0]
        ts, os_ = [], []
        for s in g:
            for P in s:
                ts.append((P[0]-a[0])*u[0]+(P[1]-a[1])*u[1])
                os_.append((P[0]-a[0])*nn[0]+(P[1]-a[1])*nn[1])
        t0, t1 = min(ts), max(ts)
        if t1-t0 < 20:
            continue
        oc = (min(os_)+max(os_))/2
        P = lambda t: (a[0]+u[0]*t+nn[0]*oc, a[1]+u[1]*t+nn[1]*oc)
        lines.append([round(v, 3) for v in (*P(t0), *P(t1))])
    # ---- arcs (chains computed above)
    used = set()
    def nb(pt, ids):
        for k2, s in enumerate(short):
            if k2 in used or k2 in ids: continue
            if math.dist(s[0], pt) < 0.3: return k2, s[1]
            if math.dist(s[1], pt) < 0.3: return k2, s[0]
    for k2 in range(len(short)):
        if k2 in used: continue
        used.add(k2); pts = [short[k2][0], short[k2][1]]; ids = [k2]
        for side in (0, 1):
            while True:
                end = pts[-1] if side == 0 else pts[0]
                r = nb(end, set(ids))
                if not r: break
                used.add(r[0]); ids.append(r[0])
                if side == 0: pts.append(r[1])
                else: pts.insert(0, r[1])
        if len(ids) >= 6:
            c, R = W.fit_circle(pts)
            if R < 500 and max(abs(math.dist(q, c)-R) for q in pts) < 0.6:
                chains.append({'pts': pts, 'c': c, 'r': R})
    # group concentric chains
    curves = []
    taken = set()
    for i, A in enumerate(chains):
        if i in taken: continue
        grp = [A]; taken.add(i)
        for j, B in enumerate(chains):
            if j in taken: continue
            dB = [math.dist(q, A['c']) for q in B['pts']]
            if max(dB)-min(dB) < 1.5 and abs(sum(dB)/len(dB)-A['r']) < 8:
                grp.append(B); taken.add(j)
        c = A['c']
        allp = [q for g in grp for q in g['pts']]
        Rm = (min(math.dist(q, c) for q in allp)+max(math.dist(q, c) for q in allp))/2
        mp = A['pts'][len(A['pts'])//2]
        ref = math.atan2(mp[1]-c[1], mp[0]-c[0])
        rel = [((math.atan2(q[1]-c[1], q[0]-c[0])-ref+math.pi) % (2*math.pi))-math.pi for q in allp]
        lo, hi = min(rel), max(rel)
        if (hi-lo)*Rm < 20: continue
        P = lambda t: (c[0]+Rm*math.cos(t+ref), c[1]+Rm*math.sin(t+ref))
        curves.append([round(v, 3) for v in (*P(lo), *P((lo+hi)/2), *P(hi))])
    out[fl] = {'lines': lines, 'curves': curves}
    print(fl, 'straight', len(lines), 'curved', len(curves))
json.dump(out, open('out/cw.json', 'w'))

# ---- merge collinear straight pieces separated by small gaps (mullion marks)
for fl, v in out.items():
    L = [list(l) for l in v['lines']]
    changed = True
    while changed:
        changed = False
        for i in range(len(L)):
            for j in range(i+1, len(L)):
                a, b = (L[i][0], L[i][1]), (L[i][2], L[i][3])
                c, d = (L[j][0], L[j][1]), (L[j][2], L[j][3])
                u, la = unitv(a, b); w_, _ = unitv(c, d)
                if abs(u[0]*w_[1]-u[1]*w_[0]) > math.sin(math.radians(2)): continue
                nn = (-u[1], u[0])
                if max(abs((P[0]-a[0])*nn[0]+(P[1]-a[1])*nn[1]) for P in (c, d)) > 2.5: continue
                ts = sorted((P[0]-a[0])*u[0]+(P[1]-a[1])*u[1] for P in (c, d))
                if ts[0] > la+8 or ts[1] < -8: continue
                t0, t1 = min(0, ts[0]), max(la, ts[1])
                L[i] = [a[0]+u[0]*t0, a[1]+u[1]*t0, a[0]+u[0]*t1, a[1]+u[1]*t1]
                del L[j]; changed = True; break
            if changed: break
    v['lines'] = [[round(x, 3) for x in l] for l in L]
    print(fl, 'merged straight', len(L), [round(math.dist(l[:2], l[2:])*29669/840) for l in L])
json.dump(out, open('out/cw.json', 'w'))
