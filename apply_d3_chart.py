#!/usr/bin/env python3
# apply_d3_chart.py — F29 D3 차트 재구현 (§3-1 계약)
#   "최근 흐름"(위아래 2분리, 각 독립 정규화) → "가격·점유율 겹쳐보기"
#   한 축 이중선 · 이중 Y스케일(좌=가격지수, 우=점유율%) · 축 실수치 · 15/30/60/90 토글
#   해설 수치는 summary[w]에서만(역산 금지) · 서버 렌더 SVG + JS 토글(PE)
#   방식: 리터럴 앵커 str.replace(3개, 각 1회 게이트), 백업, py_compile, 원자 쓰기, 버전마커.
import os, sys, shutil, py_compile, datetime

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
MARK   = 'F29-D3-CHART v1'

# ── 앵커 A: 신규 함수 삽입 지점 (verdict 종료 직후, page_html 직전) ──────────────
A_OLD = '''    return head, sub, axes

def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell, retro=None):'''

A_NEW = '''    return head, sub, axes

# F29-D3-CHART v1
# ---- 차트: 가격·점유율 한 축 이중선 (§3-1 계약).
#      축 눈금 = 시계열 실측 표시값(가격 지수/점유율 %). 해설 수치 = summary[w]에서만(역산 금지).
#      기간 토글은 서버가 15/30/60/90 SVG를 미리 렌더 → JS는 표시 전환만(fetch 0). 무JS 시 기본창 유지.
CHART_WINS = (15, 30, 60, 90)
_CVB = (480, 168, 34, 36, 12, 22)   # W,H,PL,PR,PT,PB

def _cser(series, w):
    out = [(str(p.get('date', '')), float(p['v']))
           for p in (series or []) if isinstance(p.get('v'), (int, float))]
    return out[-w:] if w else out

def chart_dual_svg(close_s, share_s, w):
    """가격 지수(실선 teal) + 점유율(점선 gold)을 한 축에 겹쳐 렌더. 두 선은 각자 축으로 독립 스케일."""
    W, H, PL, PR, PT, PB = _CVB
    cx0, cx1, cy0, cy1 = PL, W - PR, PT, H - PB
    pw, ph = cx1 - cx0, cy1 - cy0
    cp = _cser(close_s, w)
    if len(cp) < 2:
        return ''
    n = len(cp)
    def xi(i): return cx0 + i * pw / (n - 1)
    def sc(vals):
        lo, hi = min(vals), max(vals)
        return lo, hi, ((hi - lo) or 1.0)
    cv = [v for _, v in cp]
    clo, chi, crng = sc(cv)
    def cy(v): return cy0 + (chi - v) * ph / crng
    cpoly = ' '.join(f'{xi(i):.1f},{cy(v):.1f}' for i, v in enumerate(cv))
    sp = _cser(share_s, w)
    spoly = slo = shi = None
    if len(sp) == n and n >= 2:
        sv = [v for _, v in sp]
        slo, shi, srng = sc(sv)
        def sy(v): return cy0 + (shi - v) * ph / srng
        spoly = ' '.join(f'{xi(i):.1f},{sy(v):.1f}' for i, v in enumerate(sv))
    grid = ''.join(
        f'<line x1="{cx0:.1f}" y1="{y:.1f}" x2="{cx1:.1f}" y2="{y:.1f}" '
        f'stroke="#1F2A3D" stroke-width="1" stroke-dasharray="2,4"/>'
        for y in (cy0, (cy0 + cy1) / 2, cy1))
    lax = ''.join(
        f'<text x="{cx0-4:.1f}" y="{y+3:.1f}" font-size="9" fill="#3DD8B0" '
        f'text-anchor="end" opacity=".75">{val:.0f}</text>'
        for val, y in ((chi, cy0), ((chi + clo) / 2, (cy0 + cy1) / 2), (clo, cy1)))
    rax = ''
    if spoly:
        rax = ''.join(
            f'<text x="{cx1+4:.1f}" y="{y+3:.1f}" font-size="9" fill="#f0c674" '
            f'text-anchor="start" opacity=".85">{val:.1f}%</text>'
            for val, y in ((shi, cy0), ((shi + slo) / 2, (cy0 + cy1) / 2), (slo, cy1)))
    def md(dd): return f'{dd[4:6]}.{dd[6:8]}' if len(dd) == 8 else dd
    idxs = sorted(set([0, n // 2, n - 1]))
    xax = ''.join(
        f'<text x="{xi(i):.1f}" y="{cy1+13:.1f}" font-size="9" fill="#8FA0B8" '
        f'text-anchor="{"end" if i==n-1 else ("start" if i==0 else "middle")}">{md(cp[i][0])}</text>'
        for i in idxs)
    lines = f'<polyline fill="none" stroke="#3DD8B0" stroke-width="2.2" points="{cpoly}"/>'
    if spoly:
        lines += (f'<polyline fill="none" stroke="#f0c674" stroke-width="2.2" '
                  f'stroke-dasharray="4 3" points="{spoly}"/>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" role="img" '
            f'aria-label="가격 지수와 거래대금 점유율 {w}일 겹쳐보기">{grid}{lax}{rax}{lines}{xax}</svg>')

def chart_relation(summ, w):
    """선택 기간 관계 해설. 수치는 summary[w]에서만(차트 v값 역산 금지)."""
    s = (summ or {}).get(str(w)) or {}
    pc, sd, lb = s.get('priceChangePct'), s.get('shareDeltaPp'), s.get('flowLabel', '')
    if pc is None or sd is None:
        return ''
    EP, ES = 0.5, 0.1
    pu, pdn, su, sdn = pc > EP, pc < -EP, sd > ES, sd < -ES
    if pdn and sdn:
        head, tail = '두 선이 함께 내려갔습니다', '사는 쪽도 파는 쪽도 줄어든 구간입니다'
    elif pu and su:
        head, tail = '주가와 점유율이 함께 올랐습니다', '시장의 돈이 이 종목으로 몰린 구간입니다'
    elif pu and sdn:
        head, tail = '주가는 올랐지만 점유율은 줄었습니다', '상승폭 대비 시장 관심은 옅어진 구간입니다'
    elif pdn and su:
        head, tail = '주가는 내렸지만 점유율은 늘었습니다', '하락 속에도 거래대금이 이 종목에 몰린 구간입니다'
    elif su:
        head, tail = '주가 방향은 뚜렷하지 않고 점유율만 늘었습니다', '관심이 먼저 붙는 구간입니다'
    elif sdn:
        head, tail = '주가 방향은 뚜렷하지 않고 점유율은 줄었습니다', '관심이 먼저 식는 구간입니다'
    else:
        head, tail = '주가도 점유율도 큰 방향이 없습니다', '뚜렷한 쏠림이 없는 구간입니다'
    lbl = f' ({esc(lb)})' if lb else ''
    return f'{head}. 주가 {pc:+.1f}%, 점유율 {sd:+.1f}p — {tail}.{lbl}'

_CHART_JS = ('<script>(function(){var r=document.currentScript.parentNode;'
             'var t=r.querySelectorAll(".ctab"),p=r.querySelectorAll(".cpane");'
             't.forEach(function(b){b.addEventListener("click",function(){'
             'var w=b.getAttribute("data-w");'
             't.forEach(function(x){x.classList.toggle("on",x===b);});'
             'p.forEach(function(q){q.hidden=(q.getAttribute("data-w")!==w);});'
             '});});})();</script>')

def chart_dual_card(d, summ):
    close_s = d.get('closeIndexSeries', []) or []
    share_s = d.get('tradingSharePctSeries', []) or []
    if len([1 for x in close_s if isinstance(x.get('v'), (int, float))]) < 2:
        return ''
    wins = [w for w in CHART_WINS if str(w) in (summ or {})] or [min(CHART_WINS)]
    default = max(wins)
    tabs = ''.join(
        f'<button type="button" class="ctab{" on" if w==default else ""}" data-w="{w}" '
        f'data-ev="chart_win" data-card="chart">{w}일</button>' for w in wins)
    panes = ''
    for w in wins:
        svg = chart_dual_svg(close_s, share_s, w)
        if not svg:
            continue
        hid = '' if w == default else ' hidden'
        panes += (f'<div class="cpane" data-w="{w}"{hid}>{svg}'
                  f'<p class="crel">{chart_relation(summ, w)}</p></div>')
    if not panes:
        return ''
    return (f'<section class="card chart">'
            f'<h2>가격·점유율 겹쳐보기</h2>'
            f'<div class="ctabs">{tabs}</div>{panes}'
            f'<p class="caxis">왼쪽 축 = 가격 지수(기간 시작=100) · 오른쪽 축 = 거래대금 점유율(%)</p>'
            f'<p class="chint">점유율 = 이날 시장 전체 거래대금 중 이 종목이 차지한 비중. '
            f'차트는 흐름(추이)이고 판정 수치는 3일 평균 비교라 정확히 일치하지 않습니다.</p>'
            f'{_CHART_JS}</section>')

def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell, retro=None):'''

# ── 앵커 B: 기존 card_chart 조립부(2분리 sparkline) → 신규 이중선 호출로 교체 ─────
B_OLD = '''    # 카드: 가격/점유율 흐름 (서버 렌더 SVG)
    svg1 = sparkline(d.get('closeIndexSeries', []), '#3DD8B0')
    svg2 = sparkline(d.get('tradingSharePctSeries', []), '#f0c674', unit='%')
    card_chart = ''
    if svg1 or svg2:
        card_chart = f\'\'\'<section class="card">
<h2>최근 흐름</h2>
{'<p class="lbl">주가 흐름 (기간 시작=100)</p>' + svg1 if svg1 else ''}
{'<p class="lbl">시장 거래대금 점유율</p>' + svg2 if svg2 else ''}
</section>\'\'\''''

B_NEW = '''    # 카드: 가격·점유율 한 축 이중선 (§3-1 계약: 이중 스케일·기간 토글·축 실수치)  # F29-D3-CHART v1
    card_chart = chart_dual_card(d, summ)'''

# ── 앵커 C: 차트 CSS 삽입 (page_html f-string 내부 → 중괄호 이중) ─────────────────
C_OLD = '.lbl{{color:var(--sub);font-size:.8rem;margin:8px 0 2px}}\n'
C_NEW = C_OLD + (
    '.chart .ctabs{{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}}\n'
    '.ctab{{background:#0d1523;color:var(--sub);border:1px solid #1f2937;border-radius:7px;'
    'padding:4px 11px;font-size:.8rem;cursor:pointer;font-family:inherit}}\n'
    '.ctab.on{{background:var(--teal);color:#0A0E17;border-color:var(--teal);font-weight:700}}\n'
    '.cpane svg{{display:block;width:100%;height:auto}}\n'
    '.crel{{font-size:.88rem;line-height:1.5;margin:8px 0 0}}\n'
    '.caxis{{color:var(--sub);font-size:.76rem;margin:10px 0 0}}\n'
    '.chint{{color:var(--sub);font-size:.76rem;margin:4px 0 0}}\n'
)

def die(m):
    print(f'FAIL: {m}'); sys.exit(1)

def main():
    if not os.path.exists(TARGET):
        die(f'대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()
    if MARK in src:
        die(f'이미 적용됨(마커 {MARK}) — 중단')
    na, nb, nc = src.count(A_OLD), src.count(B_OLD), src.count(C_OLD)
    print(f'anchor A(page_html前): {na} / B(card_chart): {nb} / C(.lbl CSS): {nc}')
    if na != 1: die(f'앵커 A {na}회(1 기대) — 소스 불일치, 중단')
    if nb != 1: die(f'앵커 B {nb}회(1 기대) — 소스 불일치, 중단')
    if nc != 1: die(f'앵커 C {nc}회(1 기대) — 소스 불일치, 중단')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bk = f'/root/f29-backups/d3chart-{ts}'
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))
    print(f'backup: {bk}/build_stock_pages.py')

    out = src.replace(A_OLD, A_NEW).replace(B_OLD, B_NEW).replace(C_OLD, C_NEW)
    if out == src or MARK not in out:
        die('치환 무효 — 중단')

    tmp = TARGET + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp); die(f'py_compile 실패, 미적용: {e}')
    os.replace(tmp, TARGET)
    print('OK_APPLIED')
    print(f'bytes: {len(out.encode("utf-8"))}')
    print(f'marker present: {MARK in open(TARGET, encoding="utf-8").read()}')

if __name__ == '__main__':
    main()
