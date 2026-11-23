# -*- coding: utf-8 -*-
"""
[1단계] 벽·창·문 추출  (PC에서 실행, Revit 불필요)
- 입력 : pdf/1.pdf ~ pdf/7.pdf  (1층 ~ 옥상 벡터 평면도)
- 출력 : out/walls2.json  (층별 벽 중심선·두께, 원호 벽, 창/문 개구부)
- 원리 : PDF 선 두께로 요소를 구분
         1.438pt = 벽 이중선, 0.24pt = 창·문·유리, 1.079pt = 계단·승강기, 0.12pt = 글자 외곽
         평행한 이중선 쌍(간격 3~10pt)을 찾아 벽 중심선과 두께로 바꾸고,
         벽 사이의 빈틈은 문 호(arc) 유무로 문/창/개구부를 판단
- 실행 : PDF_DIR=pdf python walls2.py
"""
import os
import pymupdf as fitz, math, json, sys
base = os.environ.get('PDF_DIR', 'pdf') + '/'   # 평면도 PDF 폴더
files = ['%d.pdf' % i for i in range(1, 8)]   # 1층 ~ 옥상
WALL_W = 1.438
DMIN, DMAX = 3.0, 10.0      # wall thickness range in pt
ANG_TOL = 0.015            # rad


def unit(a, b):
    L = math.hypot(b[0]-a[0], b[1]-a[1])
    return ((b[0]-a[0])/L, (b[1]-a[1])/L), L


def get_lines(p, widths):
    out = []
    for x in p.get_drawings():
        w = round(x.get('width') or 0, 3)
        if w not in widths:
            continue
        for it in x['items']:
            if it[0] == 'l':
                a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
                if math.dist(a, b) > 0.3:
                    out.append((a, b, w))
    return out


def angdiff(u, v):
    c = abs(u[0]*v[1]-u[1]*v[0])
    return math.asin(min(1, c)) if u[0]*v[0]+u[1]*v[1] != 0 or c else 0


def merge_collinear(segs, gap=0.6):
    """merge thick segments lying on same line and touching"""
    segs = [list(s[:2]) for s in segs]
    changed = True
    while changed:
        changed = False
        for i in range(len(segs)):
            for j in range(i+1, len(segs)):
                a, b = segs[i]; c, d = segs[j]
                u, L = unit(a, b)
                v, _ = unit(c, d)
                if abs(u[0]*v[1]-u[1]*v[0]) > ANG_TOL:
                    continue
                n = (-u[1], u[0])
                if abs((c[0]-a[0])*n[0]+(c[1]-a[1])*n[1]) > 0.3 or abs((d[0]-a[0])*n[0]+(d[1]-a[1])*n[1]) > 0.3:
                    continue
                ts = [0, L, (c[0]-a[0])*u[0]+(c[1]-a[1])*u[1], (d[0]-a[0])*u[0]+(d[1]-a[1])*u[1]]
                if min(ts[2:]) > L+gap or max(ts[2:]) < -gap:
                    continue
                t0, t1 = min(ts), max(ts)
                segs[i] = [(a[0]+u[0]*t0, a[1]+u[1]*t0), (a[0]+u[0]*t1, a[1]+u[1]*t1)]
                del segs[j]
                changed = True
                break
            if changed:
                break
    return [tuple(s) for s in segs]


def pair_walls(S):
    cands = []
    for i in range(len(S)):
        a, b = S[i]
        u, L = unit(a, b)
        n = (-u[1], u[0])
        for j in range(i+1, len(S)):
            c, d = S[j]
            v, L2 = unit(c, d)
            if abs(u[0]*v[1]-u[1]*v[0]) > ANG_TOL:
                continue
            dc = (c[0]-a[0])*n[0]+(c[1]-a[1])*n[1]
            dd = (d[0]-a[0])*n[0]+(d[1]-a[1])*n[1]
            dist = (dc+dd)/2
            if abs(dc-dd) > 0.8 or not (DMIN <= abs(dist) <= DMAX):
                continue
            tc = (c[0]-a[0])*u[0]+(c[1]-a[1])*u[1]
            td = (d[0]-a[0])*u[0]+(d[1]-a[1])*u[1]
            t0, t1 = max(0, min(tc, td)), min(L, max(tc, td))
            if t1-t0 < 1.0:
                continue
            cands.append((dist, i, j, t0, t1, a, u, n))
    cands.sort(key=lambda c: abs(c[0]))
    cover = {k: [] for k in range(len(S))}

    def covered(k, lo, hi):
        tot = 0
        for (x, y) in cover[k]:
            tot += max(0, min(hi, y)-max(lo, x))
        return tot / (hi-lo)

    def proj(k, pt):
        a, b = S[k]; u, _ = unit(a, b)
        return (pt[0]-a[0])*u[0]+(pt[1]-a[1])*u[1]

    walls = []
    for dist, i, j, t0, t1, a, u, n in cands:
        p0 = (a[0]+u[0]*t0, a[1]+u[1]*t0)
        p1 = (a[0]+u[0]*t1, a[1]+u[1]*t1)
        q0 = (p0[0]+n[0]*dist, p0[1]+n[1]*dist)
        q1 = (p1[0]+n[0]*dist, p1[1]+n[1]*dist)
        ji = sorted([proj(j, q0), proj(j, q1)])
        if covered(i, t0, t1) > 0.5 or covered(j, *ji) > 0.5:
            continue
        cover[i].append((t0, t1)); cover[j].append(tuple(ji))
        h = dist/2
        walls.append({'a': (p0[0]+n[0]*h, p0[1]+n[1]*h), 'b': (p1[0]+n[0]*h, p1[1]+n[1]*h), 't': abs(dist)})
    return walls


def line_inter(p, u, q, v):
    den = u[0]*v[1]-u[1]*v[0]
    if abs(den) < 1e-6:
        return None
    s = ((q[0]-p[0])*v[1]-(q[1]-p[1])*v[0])/den
    return s


def merge_walls(W, thin, door_arcs=(), max_gap=150):
    """merge collinear walls of same thickness; bridge gaps that contain window lines"""
    openings = []
    doors = []
    changed = True
    while changed:
        changed = False
        for i in range(len(W)):
            for j in range(i+1, len(W)):
                A, B = W[i], W[j]
                if abs(A['t']-B['t']) > 0.6:
                    continue
                u, L = unit(A['a'], A['b'])
                v, _ = unit(B['a'], B['b'])
                if abs(u[0]*v[1]-u[1]*v[0]) > ANG_TOL:
                    continue
                n = (-u[1], u[0])
                off = [(P[0]-A['a'][0])*n[0]+(P[1]-A['a'][1])*n[1] for P in (B['a'], B['b'])]
                if max(abs(o) for o in off) > 0.8:
                    continue
                tb = sorted((P[0]-A['a'][0])*u[0]+(P[1]-A['a'][1])*u[1] for P in (B['a'], B['b']))
                if tb[0] > L:
                    gap = (L, tb[0])
                elif tb[1] < 0:
                    gap = (tb[1], 0)
                else:
                    gap = None
                if gap and gap[1]-gap[0] > 0.8:
                    g0, g1 = gap
                    if g1-g0 > max_gap:
                        continue
                    # door check: arc hinge inside gap
                    hit = []
                    for da in door_arcs:
                        oc = (da['c'][0]-A['a'][0])*n[0]+(da['c'][1]-A['a'][1])*n[1]
                        tc = (da['c'][0]-A['a'][0])*u[0]+(da['c'][1]-A['a'][1])*u[1]
                        if abs(oc) <= A['t']/2+2.0 and g0-3 <= tc <= g1+3:
                            om = (da['mid'][0]-A['a'][0])*n[0]+(da['mid'][1]-A['a'][1])*n[1]
                            hit.append((tc, 1 if om > 0 else -1, da))
                    if hit:
                        side = hit[0][1]
                        hinge = None
                        P_ = lambda tt: (A['a'][0]+u[0]*tt, A['a'][1]+u[1]*tt)
                        if len(hit) >= 2:
                            hs = sorted(h[0] for h in hit)
                            pa, pb = P_(hs[0]), P_(hs[-1])
                        else:
                            da = hit[0][2]
                            offs = [abs((E[0]-A['a'][0])*n[0]+(E[1]-A['a'][1])*n[1]) for E in da['ends']]
                            E = da['ends'][0] if offs[0] < offs[1] else da['ends'][1]
                            te = (E[0]-A['a'][0])*u[0]+(E[1]-A['a'][1])*u[1]
                            pa, pb = P_(hit[0][0]), P_(te)
                            hinge = 'a'
                        doors.append({'a': pa, 'b': pb, 't': A['t'], 'n': (n[0]*side, n[1]*side),
                                      'leaves': len(hit), 'hinge': hinge, 'arcs': [h[2] for h in hit]})
                        for h in hit:
                            h[2]['used'] = True
                        t0, t1 = min(0, tb[0]), max(L, tb[1])
                        W[i] = {'a': (A['a'][0]+u[0]*t0, A['a'][1]+u[1]*t0),
                                'b': (A['a'][0]+u[0]*t1, A['a'][1]+u[1]*t1), 't': A['t']}
                        del W[j]
                        changed = True
                        break
                    # window check: thin lines parallel inside band covering gap
                    cov = []
                    for (c, d, w) in thin:
                        vv, LL = unit(c, d)
                        if abs(u[0]*vv[1]-u[1]*vv[0]) > ANG_TOL:
                            continue
                        oc = (c[0]-A['a'][0])*n[0]+(c[1]-A['a'][1])*n[1]
                        if abs(oc) > A['t']/2+0.3:
                            continue
                        t = sorted([(c[0]-A['a'][0])*u[0]+(c[1]-A['a'][1])*u[1], (d[0]-A['a'][0])*u[0]+(d[1]-A['a'][1])*u[1]])
                        cov.append((max(g0, t[0]), min(g1, t[1])))
                    # union length
                    cov = sorted(c for c in cov if c[1] > c[0])
                    tot, cur = 0, None
                    for c in cov:
                        if cur is None or c[0] > cur[1]:
                            if cur: tot += cur[1]-cur[0]
                            cur = list(c)
                        else:
                            cur[1] = max(cur[1], c[1])
                    if cur: tot += cur[1]-cur[0]
                    if tot < 0.7*(g1-g0):
                        continue
                    pa = (A['a'][0]+u[0]*g0, A['a'][1]+u[1]*g0)
                    pb = (A['a'][0]+u[0]*g1, A['a'][1]+u[1]*g1)
                    openings.append({'a': pa, 'b': pb, 't': A['t']})
                t0, t1 = min(0, tb[0]), max(L, tb[1])
                W[i] = {'a': (A['a'][0]+u[0]*t0, A['a'][1]+u[1]*t0),
                        'b': (A['a'][0]+u[0]*t1, A['a'][1]+u[1]*t1), 't': (A['t']*L+B['t']*(tb[1]-tb[0]))/(L+tb[1]-tb[0])}
                del W[j]
                changed = True
                break
            if changed:
                break
    return W, openings, doors


def extend_corners(W):
    """extend wall ends to meet centerlines of nearby walls (L and T joints)"""
    for _ in range(2):
        for i, A in enumerate(W):
            for end in ('a', 'b'):
                P = A[end]; O = A['b' if end == 'a' else 'a']
                u, L = unit(O, P)            # direction pointing out of this end
                best = None
                for j, B in enumerate(W):
                    if j == i:
                        continue
                    v, LB = unit(B['a'], B['b'])
                    if abs(u[0]*v[1]-u[1]*v[0]) < 0.2:
                        continue
                    s = line_inter(P, u, B['a'], v)
                    if s is None:
                        continue
                    lim = max(A['t'], B['t'])*1.1 + 0.5
                    if not (-0.5 <= s <= lim):
                        continue
                    X = (P[0]+u[0]*s, P[1]+u[1]*s)
                    tb = (X[0]-B['a'][0])*v[0]+(X[1]-B['a'][1])*v[1]
                    if -lim <= tb <= LB+lim:
                        if best is None or s < best[0]:
                            best = (s, X)
                if best and best[0] > 0.05:
                    A[end] = best[1]
    return W


def fit_circle(pts):
    import numpy as np
    P = np.array(pts); A = np.c_[2*P[:, 0], 2*P[:, 1], np.ones(len(P))]
    b = (P**2).sum(1); cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    return (cx, cy), math.sqrt(c+cx*cx+cy*cy)


def find_arcs(thick):
    short = [s for s in thick if math.dist(*s) < 14]
    used = set(); chains = []
    def nb(pt, excl):
        for k, s in enumerate(short):
            if k in used or k in excl: continue
            if math.dist(s[0], pt) < 0.3: return k, s[1]
            if math.dist(s[1], pt) < 0.3: return k, s[0]
        return None
    for k in range(len(short)):
        if k in used: continue
        used.add(k); pts = [short[k][0], short[k][1]]; ids = [k]
        for side in (0, 1):
            while True:
                end = pts[-1] if side == 0 else pts[0]
                r = nb(end, set(ids))
                if not r: break
                prev = pts[-2] if side == 0 else pts[1]
                d1 = (end[0]-prev[0], end[1]-prev[1]); d2 = (r[1][0]-end[0], r[1][1]-end[1])
                cosang = (d1[0]*d2[0]+d1[1]*d2[1])/(math.hypot(*d1)*math.hypot(*d2)+1e-9)
                if cosang < math.cos(math.radians(25)): break
                used.add(r[0]); ids.append(r[0])
                if side == 0: pts.append(r[1])
                else: pts.insert(0, r[1])
        if len(ids) >= 5:
            c, R = fit_circle(pts)
            err = max(abs(math.dist(p, c)-R) for p in pts)
            if err < 0.4 and R < 400:
                chains.append({'pts': pts, 'c': c, 'r': R, 'segs': [short[i] for i in ids]})
    arcs, removed = [], []
    for i in range(len(chains)):
        for j in range(i+1, len(chains)):
            A, B = chains[i], chains[j]
            dB = [math.dist(p, A['c']) for p in B['pts']]
            if max(dB)-min(dB) < 1.0 and DMIN <= abs(sum(dB)/len(dB)-A['r']) <= DMAX:
                B = dict(B, c=A['c'], r=sum(dB)/len(dB))
                mp = A['pts'][len(A['pts'])//2]
                ref = math.atan2(mp[1]-A['c'][1], mp[0]-A['c'][0])
                def rel(ch, p):
                    t = math.atan2(p[1]-ch['c'][1], p[0]-ch['c'][0]) - ref
                    return (t + math.pi) % (2*math.pi) - math.pi
                a1 = sorted(rel(A, p) for p in (A['pts'][0], A['pts'][-1]))
                a2 = sorted(rel(B, p) for p in (B['pts'][0], B['pts'][-1]))
                lo, hi = max(a1[0], a2[0]), min(a1[1], a2[1])
                if hi <= lo: continue
                c = ((A['c'][0]+B['c'][0])/2, (A['c'][1]+B['c'][1])/2); R = (A['r']+B['r'])/2
                P = lambda t: (c[0]+R*math.cos(t+ref), c[1]+R*math.sin(t+ref))
                arcs.append({'a': P(lo), 'm': P((lo+hi)/2), 'b': P(hi), 't': abs(A['r']-B['r'])})
                removed += A['segs'] + B['segs']
    rest = [s for s in thick if s not in removed]
    return arcs, rest


def find_door_arcs(thin_lines):
    short = [(a, b) for a, b, w in thin_lines if w == 0.24 and math.dist(a, b) < 6]
    used = set(); out = []
    def nb(pt, ids):
        for k, s in enumerate(short):
            if k in used or k in ids: continue
            if math.dist(s[0], pt) < 0.15: return k, s[1]
            if math.dist(s[1], pt) < 0.15: return k, s[0]
    for k in range(len(short)):
        if k in used: continue
        used.add(k); pts = [short[k][0], short[k][1]]; ids = [k]
        for side in (0, 1):
            while True:
                end = pts[-1] if side == 0 else pts[0]; prev = pts[-2] if side == 0 else pts[1]
                r = nb(end, set(ids))
                if not r: break
                d1 = (end[0]-prev[0], end[1]-prev[1]); d2 = (r[1][0]-end[0], r[1][1]-end[1])
                if (d1[0]*d2[0]+d1[1]*d2[1])/(math.hypot(*d1)*math.hypot(*d2)+1e-9) < math.cos(math.radians(30)): break
                used.add(r[0]); ids.append(r[0])
                if side == 0: pts.append(r[1])
                else: pts.insert(0, r[1])
        if len(ids) >= 4:
            c, R = fit_circle(pts)
            err = max(abs(math.dist(q, c)-R) for q in pts)
            a0 = math.atan2(pts[0][1]-c[1], pts[0][0]-c[0]); a1 = math.atan2(pts[-1][1]-c[1], pts[-1][0]-c[0])
            sw = abs((a1-a0+math.pi) % (2*math.pi)-math.pi)
            if err < 0.5 and 12 < R < 45 and 1.2 < sw < 1.9:
                mid = pts[len(pts)//2]
                out.append({'c': (float(c[0]), float(c[1])), 'r': float(R), 'mid': mid, 'ends': (pts[0], pts[-1])})
    return out


def end_doors(W, loose):
    """doors whose opening is next to a wall end: extend the wall over the opening"""
    # build spans: single arcs, or pairs (double doors)
    spans = []
    used = set()
    for i in range(len(loose)):
        for j in range(i+1, len(loose)):
            A, B = loose[i], loose[j]
            if abs(A['r']-B['r']) < 3 and abs(math.dist(A['c'], B['c'])-(A['r']+B['r'])) < 4:
                spans.append({'h1': A['c'], 'h2': B['c'], 'arcs': [A, B], 'mid': A['mid']})
                used |= {i, j}
    for i, A in enumerate(loose):
        if i in used:
            continue
        # closed-position end: the arc end farther from the leaf (pick both, test later)
        spans.append({'h1': A['c'], 'cands': A['ends'], 'r': A['r'], 'arcs': [A], 'mid': A['mid']})
    out = []
    for sp in spans:
        best = None
        for wi, w in enumerate(W):
            if 'c' in w: continue
            u, L = unit(w['a'], w['b']); n = (-u[1], u[0]); t = w['t']
            off = lambda P: (P[0]-w['a'][0])*n[0]+(P[1]-w['a'][1])*n[1]
            par = lambda P: (P[0]-w['a'][0])*u[0]+(P[1]-w['a'][1])*u[1]
            if abs(off(sp['h1'])) > t/2+2.5:
                continue
            if 'h2' in sp:
                if abs(off(sp['h2'])) > t/2+2.5: continue
                e = sp['h2']
            else:
                ok = [E for E in sp['cands'] if abs(off(E)) <= t/2+2.5 and abs(abs(par(E)-par(sp['h1']))-sp['r']) < 3]
                if not ok: continue
                e = ok[0]
            lo, hi = sorted([par(sp['h1']), par(e)])
            inside = max(0, min(hi, L)-max(lo, 0))
            if inside > 0.3*(hi-lo):
                continue
            gapd = lo-L if lo >= L-0.5 else (0-hi if hi <= 0.5 else 0)
            if gapd > 6 or gapd < -1:
                continue
            if best is None or abs(off(sp['h1'])) < best[0]:
                best = (abs(off(sp['h1'])), wi, lo, hi, u, n, e)
        if best is None:
            continue
        _, wi, lo, hi, u, n, e = best
        w = W[wi]; _, L = unit(w['a'], w['b'])
        # extend wall to cover the opening, up to a crossing wall if close
        if lo >= L-0.5:
            target = hi
            for v in W:
                if v is w: continue
                vu, vL = unit(v['a'], v['b'])
                if abs(u[0]*vu[1]-u[1]*vu[0]) < 0.2: continue
                s_ = line_inter(w['a'], u, v['a'], vu)
                if s_ is not None and hi-0.5 <= s_ <= hi+v['t']+3:
                    X = (w['a'][0]+u[0]*s_, w['a'][1]+u[1]*s_)
                    tb = (X[0]-v['a'][0])*vu[0]+(X[1]-v['a'][1])*vu[1]
                    if -v['t'] <= tb <= vL+v['t']:
                        target = min(target, s_) if target != hi else s_
            w['b'] = (w['a'][0]+u[0]*max(target, hi), w['a'][1]+u[1]*max(target, hi))
        else:
            target = lo
            for v in W:
                if v is w: continue
                vu, vL = unit(v['a'], v['b'])
                if abs(u[0]*vu[1]-u[1]*vu[0]) < 0.2: continue
                s_ = line_inter(w['a'], u, v['a'], vu)
                if s_ is not None and lo-v['t']-3 <= s_ <= lo+0.5:
                    X = (w['a'][0]+u[0]*s_, w['a'][1]+u[1]*s_)
                    tb = (X[0]-v['a'][0])*vu[0]+(X[1]-v['a'][1])*vu[1]
                    if -v['t'] <= tb <= vL+v['t']:
                        target = s_
            na = (w['a'][0]+u[0]*min(target, lo), w['a'][1]+u[1]*min(target, lo))
            w['a'] = na
            # re-base params (a moved)
        u2, _ = unit(w['a'], w['b']); n2 = (-u2[1], u2[0])
        P = lambda tt: None
        h1 = sp['h1']
        pa = h1; pb = e
        # project onto centerline
        def proj(Pt):
            tt = (Pt[0]-w['a'][0])*u2[0]+(Pt[1]-w['a'][1])*u2[1]
            return (w['a'][0]+u2[0]*tt, w['a'][1]+u2[1]*tt)
        om = (sp['mid'][0]-w['a'][0])*n2[0]+(sp['mid'][1]-w['a'][1])*n2[1]
        side = 1 if om > 0 else -1
        out.append({'a': proj(pa), 'b': proj(pb), 't': w['t'], 'n': (n2[0]*side, n2[1]*side),
                    'leaves': len(sp['arcs']), 'hinge': 'a' if len(sp['arcs']) == 1 else None, 'arcs': sp['arcs']})
        for a_ in sp['arcs']:
            a_['used'] = True
    return out


def process(path):
    p = fitz.open(path)[0]
    thick = [(a, b) for a, b, w in get_lines(p, {WALL_W})]
    thin = get_lines(p, {0.24, 0.719, 0.12})
    arcs, thick = find_arcs(thick)
    S = merge_collinear(thick)
    W = pair_walls(S)
    darcs = find_door_arcs(thin)
    W, ops, doors = merge_walls(W, thin, darcs)
    W = extend_corners(W)
    W = [w for w in W if math.dist(w['a'], w['b']) > 1.5]
    loose = [d for d in darcs if not d.get('used')]
    doors += end_doors(W, loose)
    return W, ops, p.rect, arcs, doors, [d for d in darcs if not d.get('used')]


if __name__ == '__main__':
    out = {}
    for k, f in enumerate(files):
        W, ops, r, arcs, doors, loose = process(base+f)
        out[str(k+1)] = {'walls': [[round(w['a'][0], 3), round(w['a'][1], 3), round(w['b'][0], 3), round(w['b'][1], 3), round(w['t'], 3)] for w in W],
                         'openings': [[round(o['a'][0], 2), round(o['a'][1], 2), round(o['b'][0], 2), round(o['b'][1], 2)] for o in ops],
                         'arcs': [[round(v, 3) for v in (*a['a'], *a['m'], *a['b'], a['t'])] for a in arcs],
                         'doors': [[round(d['a'][0], 3), round(d['a'][1], 3), round(d['b'][0], 3), round(d['b'][1], 3), round(d['t'], 3), round(d['n'][0], 4), round(d['n'][1], 4), d['leaves'], d['hinge'] or ''] for d in doors],
                         'loose_doors': [[round(d['c'][0], 2), round(d['c'][1], 2), round(d['r'], 2)] for d in loose],
                         'page': [r.width, r.height]}
        print(k+1, 'walls', len(W), 'arcs', len(arcs), 'windows', len(ops), 'doors', len(doors), [d['leaves'] for d in doors], 'loose arcs', len(loose))
    json.dump(out, open('out/walls2.json', 'w'))
