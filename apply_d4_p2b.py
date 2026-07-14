#!/usr/bin/env python3
# apply_d4_p2b.py — F29 D4 P2-B
#   (a) D4-5 엣지: 조건명 '점유율 고점 회복' → '점유율 20일 최고 수준' (수식 무변경)
#   (b) D4-11: 차트 형태 비교 = 한 줄형 축소
#   (c) D4-10: ⑤ 테마 수치 행 클릭 → 카드 내부 단일 미니차트 (점유율 / 전일 대비 2행만)
# 대상: /root/krx-moneyflow/build_stock_pages.py (P2-A 적용본)
# 계약: 표시층만. 신규 컴퓨트 0 · 새 색 토큰 0 · 판정 수치 출처 불변.
#   - 점유율 미니차트 = tradingSharePctSeries 실측값 그대로
#   - 전일 대비 미니차트 = theme_rank5의 prevDelta와 동일 산식(s[i]-s[i-1])의 시계열 → 표시값과 정합
#   - 15일 점유 변화(엔진 값·시계열 없음) · 테마 내 순위(일별 전 멤버 재계산 = 신규 컴퓨트) → 비클릭

import os, sys, shutil, hashlib, py_compile, datetime, tempfile

TARGET    = '/root/krx-moneyflow/build_stock_pages.py'
EXPECT    = '55218a6a0d1ed3b8b8ab838761f8a044f3918e3302be5e6cba9ac2cfa6245fc0'
BKROOT    = '/root/f29-backups'
NEW_MARKS = ['F29-D4-MINI v1', 'F29-D4-PAT v1']
PRE_MARKS = ['F29-D4-ARROW v1', 'F29-D4-PCGRID v1', 'F29-D4-SCEN v1', 'F29-D3-THEME v1']
FORBIDDEN = ['PRICE_EPS', 'AVG_N', 'nextDayReturn', 'nextDayRet']

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

PATCHES = []

# ---------------------------------------------------------------- (a) 조건명
PATCHES.append(('A1-조건명', """        ('점유율 고점 회복', fmt_pp(peak),           fmt_delta_pp(sd),  sd >= peak, _imp(sd, p_sd, peak)),""",
"""        ('점유율 20일 최고 수준', fmt_pp(peak),      fmt_delta_pp(sd),  sd >= peak, _imp(sd, p_sd, peak)),"""))

PATCHES.append(('A2-조건명 고지', """            f'<p class="hint">기준값은 관측 가능한 값입니다 — 0%p·0% 교차, 최근 20거래일 점유율 고점. '""",
"""            f'<p class="hint">기준값은 관측 가능한 값입니다 — 0%p·0% 교차, 최근 20거래일 점유율 최고 수준. '"""))

PATCHES.append(('A3-조건명 주석', """#      기준은 관측 가능한 값만: 0%p 교차 / 0% 교차 / 최근 20거래일 점유율 고점.""",
"""#      기준은 관측 가능한 값만: 0%p 교차 / 0% 교차 / 최근 20거래일 점유율 최고 수준."""))

# ---------------------------------------------------------------- (c) D4-10: 미니차트 + theme_card5 재구성
PATCHES.append(('C1-theme_card5', '''def theme_card5(theme_info, tstage):
    r = (theme_info or {}).get('r5') or {}
    theme = esc(theme_info.get('theme', ''))
    sub = esc(theme_info.get('subtheme', ''))
    head = f'{theme} · {sub}' if sub else theme
    rows = []
    if isinstance(r.get('share'), (int, float)):
        rows.append(('거래대금 점유율', f'{r["share"]:.2f}%'))
    if r.get('rank') and r.get('total'):
        rows.append(('테마 내 순위', f'{r["rank"]}위 / {r["total"]}개'))
    if isinstance(r.get('prevDelta'), (int, float)):                       # F29-D4-ARROW v1
        rows.append(('전일 대비 점유', fmt_delta_pp(r["prevDelta"])))
    if isinstance(r.get('sd15'), (int, float)):
        rows.append(('15일 점유 변화', fmt_delta_pp(r["sd15"])))
    if r.get('pressSide') and r.get('pressRank'):
        rows.append(('시장 자금 압력', f'{esc(r["pressSide"])} {r["pressRank"]}위'))
    li = ''.join(f'<li><span class="rk">{esc(k)}</span><b class="rv">{esc(v)}</b></li>'
                 for k, v in rows)
    role_html = f'<p class="trole">역할: <b>{esc(r["role"])}</b></p>' if r.get('role') else ''
    stage_html = f'<p class="tline">테마 단계: <b>{esc(tstage)}</b></p>' if tstage else ''
    body = (f'<ul class="rank5">{li}</ul>{role_html}' if li else '')
    return (f'<section class="card"><h2>테마 내 실제 위치</h2>'
            f'<p class="tsub">{head}</p>{body}{stage_html}'
            f'<a class="golink" data-ev="card_more" data-card="kr" href="/kr-moneyflow">'
            f'{theme} 테마 전체 보기 <span class="goar">&rarr;</span></a></section>')''',
'''# F29-D4-MINI v1
# ---- D4-10: ⑤ 테마 수치 행 클릭 → 카드 내부 단일 미니차트(최근 20거래일). 팝업 없음·fetch 0.
#      신규 컴퓨트 없음. 클릭 가능 행은 시계열이 실재하는 2개뿐:
#        점유율     = tradingSharePctSeries 실측값 그대로(절대 수준 → 화살표 미적용)
#        전일 대비  = theme_rank5의 prevDelta와 동일 산식 s[i]-s[i-1]의 시계열(변화값 → 화살표 적용)
#      비클릭: 15일 점유 변화(값 출처=엔진 summary, 시계열 부재) / 테마 내 순위(일별 전 멤버 재계산 필요)
MINI_N = 20
_MVB = (440, 120, 8, 46, 10, 18)      # W,H,PL,PR,PT,PB

def mini_svg(pts, unit, zero=False):
    """최근 N거래일 단일 지표 추이. 축 = 실측 최고/최저. 역산·예측 수치 없음."""
    W, H, PL, PR, PT, PB = _MVB
    x0, x1, y0, y1 = PL, W - PR, PT, H - PB
    pw, ph = x1 - x0, y1 - y0
    n = len(pts)
    if n < 2:
        return ''
    vs = [v for _, v in pts]
    lo, hi = min(vs), max(vs)
    if zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    rng = (hi - lo) or 1.0
    def xi(i): return x0 + i * pw / (n - 1)
    def yi(v): return y0 + (hi - v) * ph / rng
    poly = ' '.join(f'{xi(i):.1f},{yi(v):.1f}' for i, v in enumerate(vs))
    grid = ''.join(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="#1F2A3D" '
                   f'stroke-width="1" stroke-dasharray="2,4"/>' for y in (y0, y1))
    zl = (f'<line x1="{x0}" y1="{yi(0):.1f}" x2="{x1}" y2="{yi(0):.1f}" stroke="#5A6B84" stroke-width="1"/>'
          if zero and lo <= 0 <= hi else '')
    ax = ''.join(f'<text x="{x1+4}" y="{y+3:.1f}" font-size="9" fill="#f0c674" '
                 f'text-anchor="start" opacity=".85">{val:.2f}{unit}</text>'
                 for val, y in ((hi, y0), (lo, y1)))
    def md(dd): return f'{dd[4:6]}.{dd[6:8]}' if len(dd) == 8 else dd
    xax = (f'<text x="{x0}" y="{y1+13}" font-size="9" fill="#8FA0B8">{md(pts[0][0])}</text>'
           f'<text x="{x1}" y="{y1+13}" font-size="9" fill="#8FA0B8" text-anchor="end">{md(pts[-1][0])}</text>')
    bw = pw / max(n - 1, 1)
    hover = ''.join(f'<rect x="{max(x0, xi(i)-bw/2):.1f}" y="{y0}" width="{bw:.1f}" height="{ph}" '
                    f'fill="transparent"><title>{md(dd)} · {v:.2f}{unit}</title></rect>'
                    for i, (dd, v) in enumerate(pts))
    dot = f'<circle cx="{xi(n-1):.1f}" cy="{yi(vs[-1]):.1f}" r="2.6" fill="#f0c674"/>'
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" role="img" '
            f'aria-label="최근 {n}거래일 추이">{grid}{zl}'
            f'<polyline fill="none" stroke="#f0c674" stroke-width="2" points="{poly}"/>'
            f'{dot}{ax}{xax}{hover}</svg>')

_MINI_JS = ('<script>(function(){var r=document.currentScript.parentNode;'
            'var b=r.querySelectorAll(".rrow"),p=r.querySelectorAll(".mcpane");'
            'b.forEach(function(x){x.addEventListener("click",function(){'
            'var m=x.getAttribute("data-mc");var op=x.getAttribute("aria-expanded")==="true";'
            'b.forEach(function(y){y.setAttribute("aria-expanded","false");y.classList.remove("on");});'
            'p.forEach(function(q){q.hidden=true;});'
            'if(!op){x.setAttribute("aria-expanded","true");x.classList.add("on");'
            'p.forEach(function(q){if(q.getAttribute("data-mc")===m)q.hidden=false;});}'
            '});});})();</script>')

def theme_card5(theme_info, tstage, share_s=None):
    r = (theme_info or {}).get('r5') or {}
    theme = esc(theme_info.get('theme', ''))
    sub = esc(theme_info.get('subtheme', ''))
    head = f'{theme} · {sub}' if sub else theme

    sp = _cser(share_s, MINI_N)                     # 점유율 실측 시계열
    full = _cser(share_s, MINI_N + 1)
    dp = [(full[i][0], round(full[i][1] - full[i - 1][1], 3)) for i in range(1, len(full))]
    has_sp, has_dp = len(sp) >= 2, len(dp) >= 2

    rows = []                                       # (라벨, 표시값, 미니차트 키 or None)
    if isinstance(r.get('share'), (int, float)):
        rows.append(('거래대금 점유율', f'{r["share"]:.2f}%', 'share' if has_sp else None))
    if r.get('rank') and r.get('total'):
        rows.append(('테마 내 순위', f'{r["rank"]}위 / {r["total"]}개', None))
    if isinstance(r.get('prevDelta'), (int, float)):                       # F29-D4-ARROW v1
        rows.append(('전일 대비 점유', fmt_delta_pp(r["prevDelta"]), 'delta' if has_dp else None))
    if isinstance(r.get('sd15'), (int, float)):
        rows.append(('15일 점유 변화', fmt_delta_pp(r["sd15"]), None))
    if r.get('pressSide') and r.get('pressRank'):
        rows.append(('시장 자금 압력', f'{esc(r["pressSide"])} {r["pressRank"]}위', None))

    li = ''
    for k, v, mc in rows:
        if mc:
            li += (f'<li class="rli"><button type="button" class="rrow" data-mc="{mc}" '
                   f'data-ev="theme_mini" data-card="theme" aria-expanded="false">'
                   f'<span class="rk">{esc(k)}</span><b class="rv">{esc(v)}</b>'
                   f'<span class="rgo" aria-hidden="true">&#9662;</span></button></li>')
        else:
            li += f'<li><span class="rk">{esc(k)}</span><b class="rv">{esc(v)}</b></li>'

    panes = ''
    if has_sp:
        vs = [v for _, v in sp]
        panes += (f'<div class="mcpane" data-mc="share" hidden>'
                  f'<p class="mctitle">거래대금 점유율 · 최근 {len(sp)}거래일</p>'
                  f'{mini_svg(sp, "%")}'
                  f'<p class="mcmeta">현재 {vs[-1]:.2f}% · 최고 {max(vs):.2f}% · 최저 {min(vs):.2f}%</p></div>')
    if has_dp:
        dv = [v for _, v in dp]
        panes += (f'<div class="mcpane" data-mc="delta" hidden>'
                  f'<p class="mctitle">전일 대비 점유율 변화 · 최근 {len(dp)}거래일</p>'
                  f'{mini_svg(dp, "%p", zero=True)}'
                  f'<p class="mcmeta">현재 {fmt_delta_pp(dv[-1])} · 최고 {fmt_delta_pp(max(dv))} '
                  f'· 최저 {fmt_delta_pp(min(dv))}</p></div>')

    mhint = ('<p class="hint">밑줄 친 행을 누르면 최근 20거래일 추이가 열립니다. '
             '점유율은 실측 시계열, 전일 대비는 그 시계열의 하루 차이입니다. '
             '차트는 흐름이고 판정 수치는 3일 평균 비교라 정확히 일치하지 않습니다.</p>') if panes else ''
    js = _MINI_JS if panes else ''
    role_html = f'<p class="trole">역할: <b>{esc(r["role"])}</b></p>' if r.get('role') else ''
    stage_html = f'<p class="tline">테마 단계: <b>{esc(tstage)}</b></p>' if tstage else ''
    body = (f'<ul class="rank5">{li}</ul>{panes}{role_html}' if li else '')
    return (f'<section class="card"><h2>테마 내 실제 위치</h2>'
            f'<p class="tsub">{head}</p>{body}{stage_html}{mhint}'
            f'<a class="golink" data-ev="card_more" data-card="kr" href="/kr-moneyflow">'
            f'{theme} 테마 전체 보기 <span class="goar">&rarr;</span></a>{js}</section>')'''))

PATCHES.append(('C2-호출부', '''        card2 = theme_card5(theme_info, tstage)   # F29-D3-THEME v1''',
'''        card2 = theme_card5(theme_info, tstage, d.get('tradingSharePctSeries'))   # F29-D3-THEME v1 / F29-D4-MINI v1'''))

# ---------------------------------------------------------------- (b) D4-11 한 줄형
PATCHES.append(('B1-card4', '''    card4 = ''
    if pj and isinstance(pj.get('top1'), dict):
        t1 = pj['top1']
        st = pj.get('structure')
        st_txt = f' · 구조: {STRUCT_LABEL.get(st, "")}' if st in STRUCT_LABEL else ''
        card4 = f\'\'\'<section class="card">
<h2>차트 형태 비교</h2>
<p>최근 흐름과 가장 닮은 패턴: <b>{esc(t1.get("pattern_title",""))}</b>
(형태 유사도 {t1.get("score","")}){st_txt}</p>
<p class="hint">유사도는 형태의 닮음이며 신뢰도나 예측이 아닙니다.</p>
<a class="golink" data-ev="card_more" data-card="lab" href="/lab/match.html">차트분석 연구소에서 직접 비교 <span class="goar">&rarr;</span></a>
</section>\'\'\'''',
'''    card4 = ''                                            # F29-D4-PAT v1: 대형 빈 카드 → 한 줄형 축소
    if pj and isinstance(pj.get('top1'), dict):
        t1 = pj['top1']
        st = pj.get('structure')
        st_txt = f' · 구조: {STRUCT_LABEL.get(st, "")}' if st in STRUCT_LABEL else ''
        _sim = t1.get('score')
        sim_txt = f' · 형태 유사도 {_sim}/100' if isinstance(_sim, (int, float)) else ''
        card4 = f\'\'\'<section class="card patline">
<h2>차트 형태 비교</h2>
<p class="pl1">가장 닮은 패턴 <b>{esc(t1.get("pattern_title",""))}</b>{sim_txt}{st_txt}</p>
<a class="golink" data-ev="card_more" data-card="lab" href="/lab/match.html">차트분석 연구소에서 직접 비교 <span class="goar">&rarr;</span></a>
<p class="hint">유사도는 형태의 닮음이며 신뢰도나 예측이 아닙니다.</p>
</section>\'\'\''''))

# ---------------------------------------------------------------- CSS
PATCHES.append(('S1-css', '''.trole{{margin:6px 0 0;color:var(--teal);font-size:.9rem}}''',
'''.trole{{margin:6px 0 0;color:var(--teal);font-size:.9rem}}
/* F29-D4-MINI v1: 수치 행 클릭 → 카드 내부 미니차트. <button> UA 스타일 리셋 필수(appearance:none) */
.rank5 li.rli{{padding:0;display:block}}
.rrow{{appearance:none;-webkit-appearance:none;background:none;border:0;margin:0;padding:8px 4px;width:100%;min-height:44px;box-sizing:border-box;display:flex;align-items:center;gap:12px;color:var(--tx);font:inherit;text-align:left;cursor:pointer;border-radius:6px}}
.rrow .rv{{margin-left:auto}}
.rrow .rk{{text-decoration:underline;text-decoration-color:#334155;text-underline-offset:3px}}
.rrow:hover{{background:#0d1523}}
.rrow.on{{background:#0d1523}}
.rrow.on .rk{{text-decoration-color:var(--gold)}}
.rgo{{flex:0 0 auto;color:var(--sub);font-size:.78rem;line-height:1;transition:transform .15s}}
.rrow.on .rgo{{transform:rotate(180deg);color:var(--gold)}}
.mcpane{{margin:8px 0 4px;padding:10px;background:#0d1523;border-radius:8px}}
.mcpane svg{{display:block;width:100%;height:auto}}
.mctitle{{margin:0 0 6px;color:var(--sub);font-size:.8rem}}
.mcmeta{{margin:6px 0 0;color:var(--sub);font-size:.78rem;font-family:"JetBrains Mono",monospace}}
/* F29-D4-PAT v1: 형태 비교 한 줄형 */
.patline{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.patline h2{{margin:0;flex:0 0 auto}}
.pl1{{margin:0;flex:1 1 240px;font-size:.95rem}}
.patline .golink{{margin-top:0;flex:0 0 auto}}
.patline .hint{{flex:1 1 100%;margin:0}}'''))

# ---------------------------------------------------------------- 실행
def main():
    if not os.path.isfile(TARGET):
        sys.exit(f'FAIL: 대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()

    for m in NEW_MARKS:
        if m in src:
            sys.exit(f'SKIP: 이미 적용됨 [{m}] — 변경 없음')

    cur = sha(TARGET)
    if cur != EXPECT:
        sys.exit(f'FAIL: 기준 SHA 불일치 (P2-A 적용본이어야 함)\n  기대 {EXPECT}\n  실제 {cur}\n  → 원인 규명 전 패치 금지.')

    for m in PRE_MARKS:
        if m not in src:
            sys.exit(f'FAIL: 선행 마커 부재 [{m}]')

    fails = []
    for name, old, new in PATCHES:
        n = src.count(old)
        if n != 1:
            fails.append(f'  [{name}] 앵커 {n}회 (기대 1)')
    if fails:
        sys.exit('FAIL: 앵커 게이트\n' + '\n'.join(fails))

    out = src
    for name, old, new in PATCHES:
        out = out.replace(old, new, 1)

    for tok in FORBIDDEN:
        if out.count(tok) != src.count(tok):
            sys.exit(f'FAIL: 금지 토큰 유입 [{tok}]')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bk = os.path.join(BKROOT, f'd4p2b-{ts}')
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(TARGET), suffix='.tmp')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)
    os.chmod(tmp, os.stat(TARGET).st_mode & 0o777)
    try:
        py_compile.compile(tmp, doraise=True)
    except Exception as e:
        os.unlink(tmp)
        sys.exit(f'FAIL: py_compile\n{e}')
    os.replace(tmp, TARGET)

    print('OK: D4 P2-B 적용 완료')
    print(f'  백업   {bk}/build_stock_pages.py')
    print(f'  before {EXPECT} ({len(src.encode())} B)')
    print(f'  after  {sha(TARGET)} ({len(out.encode())} B)')
    print(f'  패치   {len(PATCHES)}건 / 마커 ' + ' · '.join(NEW_MARKS))
    print(f'  롤백   cp {bk}/build_stock_pages.py {TARGET}')

if __name__ == '__main__':
    main()
