# F29-US-P0 v1
#!/usr/bin/env python3
# build_us_stock_pages.py — F29 미국 종목 상태판정 페이지 공장 (Phase 0)
# 입력: /root/moneyflow/positions_output.json (.positions[], read-only)
# 출력: /var/www/f29-stock-us/{SLUG}/index.html + us-slug-map.json + sitemap-us.xml
# 원칙(Phase 0, Sky 비준 2026-07-16):
#   - 상태판정 중심. 종목별 시계열 차트 없음 / 가격·거래금액 카드 없음.
#   - 자금 비중을 RS·테마로 대체·추정하지 않음. 없는 데이터는 렌더하지 않는다.
#   - KR 6카드 내용 동형 복제가 아니라 레이아웃·형태표기·색·반응형 골격만 재사용.
#   - lifecycle/axis 라벨 = 미국장 엔진 SSOT 원문. 색은 표시층 매핑(라벨 불변).
#   - 컴플라이언스: 매수/매도/보유 행동 문구 0, confidence 등급 직접 노출 금지.
#   - build_stock_pages.py(KR, fc7a6db5…)는 수정하지 않는다 — 유틸 자기완결 복제.

import json, os, re, html, datetime

os.umask(0o022)

SRC      = '/root/moneyflow/positions_output.json'
OUT_DIR  = '/var/www/f29-stock-us'
SLUG_MAP = '/var/www/f29-stock-us/us-slug-map.json'
SITEMAP  = '/var/www/f29-stock-us/sitemap-us.xml'
SITE     = 'https://f29.io'

# ── 재사용 유틸 (bsp_canon_ref.py fc7a6db5… 에서 순수함수만 복제, 전역 의존 0) ──
def esc(s): return html.escape(str(s), quote=True)

def fmt_pct(v, plus=True):
    try: v = float(v)
    except (TypeError, ValueError): return '-'
    return (f'{v:+.2f}%' if plus else f'{v:.2f}%')

def fmt_delta_pct(v):
    """관측값 형태표기: ▲ +0.00% / ▼ -0.00% / ─ 0.00% (색만으로 의미 전달 금지)"""
    try: v = round(float(v), 2)
    except (TypeError, ValueError): return '-'
    if v > 0: return f'\u25b2 +{v:.2f}%'
    if v < 0: return f'\u25bc {v:.2f}%'
    return '\u2500 0.00%'

def load_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except Exception:
        return default

def write_atomic(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)

# ── US 색 매핑 (lifecycle 9상태 → teal/gold/red 표시층. 라벨 SSOT는 엔진) ──
#   teal = 유입·강세 / gold = 관찰·전환·중립 / red = 이탈
#   관심도성숙=gold (주도 다음·둔화 전 = 전환 초입). 미국장 검토 통보 대상.
US_STATE_TONE = {
    '신규부상': 'up-c', '강화': 'up-c', '주도': 'up-c',
    '관심도성숙': 'wt-c', '관찰시작': 'wt-c', '둔화관찰': 'wt-c',
    '이탈관찰': 'wt-c', '중립': 'wt-c',
    '이탈': 'dn-c',
}
def us_tone(state): return US_STATE_TONE.get(state or '', 'wt-c')

# axis_state 표시(라벨 원문 그대로)
AXIS_SET = {'혼조', '양축우위', '양축열위', '중립'}

# RS 신호 방향 한글(원문 유지 축) — signals 값 up/down/neutral/null
SIG_KO = {'up': '우위', 'down': '열위', 'neutral': '중립'}


def slugify(ticker):
    """raw ticker(대문자 보존) → URL slug. '.'→'-'. 대문자화."""
    return str(ticker).replace('.', '-').upper()


def is_partial(rec):
    """부분 데이터 판정: status≠normal 또는 RS 60창 결측 → noindex 대상."""
    return rec.get('status') != 'normal' or rec.get('RS_sector_60') is None or rec.get('RS_market_60') is None


def is_excluded(rec):
    """진짜 판정제외(방어): lifecycle 또는 axis 부재. 현 유니버스 0건, 방어 코드."""
    return not rec.get('lifecycle') or not rec.get('axis_state')


# ── 카드 렌더 ──
def card_verdict(rec):
    """① 오늘 판정: lifecycle + axis_state + status. 라벨 엔진 SSOT."""
    lc = rec.get('lifecycle', '')
    ax = rec.get('axis_state', '')
    tone = us_tone(lc)
    lcd = rec.get('lifecycle_detail', '')
    axd = rec.get('axis_detail', '')
    return (f'<section class="card verdict {tone}">'
            f'<h2>오늘 판정</h2>'
            f'<p class="vhead">{esc(lc)}<span class="vaxis"> · {esc(ax)}</span></p>'
            f'<p class="vsub">{esc(lcd)}</p>'
            f'<p class="vsub">{esc(axd)}</p>'
            f'<p class="hint">상대강도 기반 상태 분류입니다. 거래 지시가 아닌 위치 참고 지표입니다.</p>'
            f'</section>')


def card_diff(rec, prev_rec):
    """② 전일 대비: 직전 스냅샷과 lifecycle/axis 전환만. 없으면 숨김. 수치 diff 생성 금지."""
    if not prev_rec:
        return ''  # 이전 스냅샷 없음 → 카드 숨김(빈 카드 금지)
    changes = []
    if prev_rec.get('lifecycle') != rec.get('lifecycle'):
        changes.append(('상태', prev_rec.get('lifecycle', ''), rec.get('lifecycle', '')))
    if prev_rec.get('axis_state') != rec.get('axis_state'):
        changes.append(('축 판정', prev_rec.get('axis_state', ''), rec.get('axis_state', '')))
    if not changes:
        return ('<section class="card"><h2>전일 대비</h2>'
                '<p class="hint">직전 거래일과 판정 변화가 없습니다.</p></section>')
    items = ''.join(
        f'<li><span class="dk">{esc(k)}</span>'
        f'<span class="dv"><s>{esc(p)}</s> &rarr; <b>{esc(c)}</b></span></li>'
        for k, p, c in changes)
    return (f'<section class="card"><h2>전일 대비</h2>'
            f'<ul class="difflist">{items}</ul>'
            f'<p class="hint">직전 거래일 판정과 비교한 상태 전환입니다.</p></section>')


def card_rs(rec):
    """③ 기간 상대강도: RS_sector/market 20·60. 60 결측 시 보류 명시. 시계열 차트 금지."""
    def _rs(v):
        if v is None: return None
        try: return round(float(v), 2)
        except (TypeError, ValueError): return None
    r_s20, r_m20 = _rs(rec.get('RS_sector_20')), _rs(rec.get('RS_market_20'))
    r_s60, r_m60 = _rs(rec.get('RS_sector_60')), _rs(rec.get('RS_market_60'))
    sig = rec.get('signals', {}) or {}

    def _row(label, val, sigkey):
        if val is None:
            return (f'<tr><td>{esc(label)}</td><td class="num">-</td>'
                    f'<td class="hold">이력 부족 · 보류</td></tr>')
        s = sig.get(sigkey)
        sk = SIG_KO.get(s, '-') if s else '-'
        return (f'<tr><td>{esc(label)}</td><td class="num">{fmt_pct(val)}</td>'
                f'<td>{esc(sk)}</td></tr>')

    rows = (_row('섹터 대비 · 20거래일', r_s20, 'sector_20')
            + _row('시장 대비 · 20거래일', r_m20, 'market_20')
            + _row('섹터 대비 · 60거래일', r_s60, 'sector_60')
            + _row('시장 대비 · 60거래일', r_m60, 'market_60'))
    partial_note = ''
    if r_s60 is None or r_m60 is None:
        partial_note = ('<p class="hint">상장 후 데이터가 짧아 60거래일 상대강도는 아직 보류 중입니다. '
                        '20거래일 값만 참고하세요.</p>')
    return (f'<section class="card scen"><h2>기간 상대강도</h2>'
            f'<table><thead><tr><th>기준</th><th>상대강도</th><th>방향</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'<p class="hint">벤치마크 대비 상대강도입니다. 가격이나 자금 흐름 수치가 아닙니다. '
            f'양수 = 벤치 대비 우위, 음수 = 열위.</p>{partial_note}</section>')


def card_theme_sync(rec, all_recs):
    """④ 테마 동조: 같은 theme_group 안 동일 lifecycle 종목 수. self 제외 + 유효 peer 수."""
    tg = rec.get('theme_group')
    lc = rec.get('lifecycle')
    if not tg or not lc:
        return ''  # 결측 시 숨김
    peers = [r for r in all_recs
             if r.get('theme_group') == tg and r.get('ticker') != rec.get('ticker')
             and r.get('lifecycle')]
    total = len(peers)
    if total == 0:
        return ('<section class="card"><h2>테마 동조</h2>'
                f'<p>소속 테마 <b>{esc(tg)}</b>에서 비교 가능한 다른 종목이 없습니다.</p></section>')
    same = [r for r in peers if r.get('lifecycle') == lc]
    n_same = len(same)
    ratio = n_same / total if total else 0
    if ratio >= 0.5:   sync_txt = '광범위'
    elif ratio > 0:    sync_txt = '부분 확산'
    else:              sync_txt = '단독'
    listed = ''.join(
        f'<li><a class="prow" data-ev="us_peer_click" href="/stock/us/{slugify(r["ticker"])}/">'
        f'<span class="pn">{esc(r.get("name_ko") or r["ticker"])}</span>'
        f'<span class="pl">{esc(r.get("lifecycle",""))}</span>'
        f'<span class="pgo" aria-hidden="true">&rsaquo;</span></a></li>'
        for r in peers)
    return (f'<section class="card"><h2>테마 동조</h2>'
            f'<p class="synchead">소속 테마 <b>{esc(tg)}</b> · 유효 비교 종목 {total}개 중 '
            f'같은 상태 <b>{n_same}</b>개 <span class="synctag">{sync_txt}</span></p>'
            f'<ul class="peers">{listed}</ul>'
            f'<p class="hint">같은 테마에서 동일 상태로 분류된 종목 수입니다. 방향을 전망하지 않습니다.</p>'
            f'</section>')


def card_bench(rec):
    """⑤ 벤치마크 참조: primary/secondary ETF. confidence 등급 직접 노출 금지."""
    pri = rec.get('primary', '')
    sec = rec.get('secondary', '')
    if not pri and not sec:
        return ''
    conf = rec.get('confidence', '')
    note = rec.get('confidence_note', '') or ''
    # confidence 등급(high/low) 직접 노출 금지 → 안정도 문구로 치환, note 있으면 정면 표기
    conf_line = ''
    if note:
        conf_line = f'<p class="confnote">판정 참고: {esc(note)}</p>'
    elif conf == 'low':
        conf_line = '<p class="confnote">제한적 데이터 기반 판정입니다.</p>'
    bench = ' · '.join(x for x in (pri, sec) if x)
    return (f'<section class="card"><h2>비교 기준</h2>'
            f'<p>상대강도 비교 벤치마크: <b>{esc(bench)}</b></p>'
            f'{conf_line}'
            f'<p class="hint">이 종목의 상대강도를 계산할 때 기준으로 삼은 ETF입니다.</p>'
            f'</section>')


def card_meta(rec, updated):
    """⑥ 판정 근거·데이터 상태: signals·status·n_data·updated. 행동 문구 금지, stale 숨김 금지."""
    sig = rec.get('signals', {}) or {}
    n = rec.get('n_data', '-')
    status = rec.get('status', '-')
    status_ko = {'normal': '정상', 'short_history': '이력 짧음', 'extreme_initial_move': '초기 변동 과대'}.get(status, status)
    sig_txt = ' / '.join(f'{k}: {SIG_KO.get(v, v) if v else "보류"}' for k, v in sig.items())
    return (f'<section class="card meta"><h2>판정 근거 · 데이터 상태</h2>'
            f'<ul class="metalist">'
            f'<li><span class="mk">데이터 상태</span><span class="mv">{esc(status_ko)}</span></li>'
            f'<li><span class="mk">사용 데이터 수</span><span class="mv">{esc(n)}개</span></li>'
            f'<li><span class="mk">신호 요약</span><span class="mv">{esc(sig_txt)}</span></li>'
            f'<li><span class="mk">데이터 기준일</span><span class="mv">{esc(updated)}</span></li>'
            f'</ul>'
            f'<p class="hint">미국 시장 종가(ET) 기준 데이터입니다. 거래 지시가 아닌 상태 참고 자료입니다.</p>'
            f'</section>')


CSS = '''*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0A0E17;--card:#111827;--tx:#e5e7eb;--sub:#9ca3af;--teal:#3DD8B0;--gold:#f0c674;--up:#F45B69;--down:#4C8DFF;--flat:#9ca3af}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',sans-serif;line-height:1.5;font-size:15px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
@media(min-width:1024px){.wrap{padding:28px 24px 80px}}
h1{font-size:1.5rem;margin-bottom:4px}
.tick{color:var(--sub);font-size:.9rem;margin-bottom:18px}
.line1{font-size:1.02rem;margin-bottom:18px;padding:12px 14px;background:var(--card);border-left:3px solid var(--teal);border-radius:8px}
.grid{display:grid;gap:14px}
@media(min-width:1024px){.grid{grid-template-columns:1fr 1fr}.grid .full{grid-column:1/-1}}
.card{background:var(--card);border:1px solid #1f2937;border-radius:10px;padding:16px}
.card h2{font-size:1.02rem;margin-bottom:10px;color:var(--teal)}
.verdict{border-left:3px solid var(--teal)}
.verdict.up-c{border-left-color:var(--teal)}.verdict.up-c h2{color:var(--teal)}
.verdict.wt-c{border-left-color:var(--gold)}.verdict.wt-c h2{color:var(--gold)}
.verdict.dn-c{border-left-color:var(--up)}.verdict.dn-c h2{color:var(--up)}
.vhead{font-size:1.4rem;font-weight:700;margin-bottom:8px}
.vaxis{font-size:1rem;font-weight:500;color:var(--sub)}
.vsub{color:var(--tx);margin-bottom:4px;font-size:.94rem}
.scen{border-left:3px solid var(--gold)}.scen h2{color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid #1f2937}
th{color:var(--sub);font-weight:600}
td.num{font-variant-numeric:tabular-nums}
td.hold{color:var(--gold);font-size:.84rem}
.hint{color:var(--sub);font-size:.82rem;margin-top:10px}
.difflist,.peers,.metalist{list-style:none}
.difflist li,.metalist li{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1f2937;gap:10px}
.dk,.mk{color:var(--sub)}.dv s{color:var(--sub)}
.synchead{margin-bottom:8px}.synctag{background:#1f2937;color:var(--gold);font-size:.75rem;padding:2px 8px;border-radius:10px;margin-left:4px}
.peers li{border-bottom:1px solid #1f2937}
.prow{display:flex;align-items:center;gap:10px;padding:9px 4px;text-decoration:none;color:var(--tx)}
.prow:hover{background:#0d1420}
.pn{flex:1}.pl{color:var(--sub);font-size:.85rem}.pgo{color:var(--sub)}
.confnote{color:var(--gold);font-size:.86rem;margin-top:6px}
.mv{font-variant-numeric:tabular-nums;text-align:right}
.foot{margin-top:28px;color:var(--sub);font-size:.8rem;text-align:center}
'''


def page_html(rec, all_recs, prev_rec, updated):
    ticker = rec['ticker']
    slug = slugify(ticker)
    name = rec.get('name_ko') or ticker
    lc = rec.get('lifecycle', '')
    ax = rec.get('axis_state', '')
    partial = is_partial(rec)
    excluded = is_excluded(rec)

    canonical = f'{SITE}/stock/us/{slug}/'
    robots = 'noindex,follow' if (partial or excluded) else 'index,follow'

    title = f'{name}({ticker}) 상대강도·상태 분석 | F29'
    if excluded:
        desc = f'{name}({ticker})는 현재 판정 가능한 데이터가 부족합니다. F29 미국 종목 상태 분석.'
    else:
        desc = (f'{name}({ticker})의 오늘 상태는 {lc}({ax})입니다. '
                f'섹터·시장 대비 상대강도와 소속 테마 위치를 F29 데이터로 분석합니다.')

    # ── 본문 ──
    if excluded:
        # 진짜 판정제외(방어) — 현 유니버스 0건. ①만, 나머지 숨김.
        body = (f'<section class="card verdict wt-c"><h2>판정 보류</h2>'
                f'<p class="vhead">판정 제외</p>'
                f'<p class="vsub">데이터 상태({esc(rec.get("status","-"))})로 인해 현재 상태 분류를 '
                f'제공하지 않습니다. 데이터가 충분히 쌓이면 판정이 시작됩니다.</p></section>'
                f'{card_meta(rec, updated)}')
        cards = body
    else:
        c1 = card_verdict(rec)
        c2 = card_diff(rec, prev_rec)
        c3 = card_rs(rec)
        c4 = card_theme_sync(rec, all_recs)
        c5 = card_bench(rec)
        c6 = card_meta(rec, updated)
        parts = [p for p in (c1, c2, c3, c4, c5, c6) if p]
        # 홀수 카드면 마지막 카드 full (PC 2단 하단 공백 흡수) — nth-child 미사용, 문자열 주입
        if len(parts) % 2 == 1:
            parts[-1] = parts[-1].replace('<section class="card', '<section class="card full', 1)
        cards = ''.join(parts)

    line1 = f'{esc(name)}의 오늘 상태는 <b>{esc(lc)}</b> · {esc(ax)}입니다.' if not excluded \
        else f'{esc(name)}는 현재 판정 보류 상태입니다.'

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>{esc(name)}</h1>
<p class="tick">{esc(ticker)} · 미국주식</p>
<p class="line1">{line1}</p>
<div class="grid">
{cards}
</div>
<p class="foot">F29 · 미국 종목 상태 분석 (Phase 0) · 데이터 기준일 {esc(updated)}</p>
</div>
</body>
</html>'''


def main():
    data = load_json(SRC)
    if not data or 'positions' not in data:
        raise SystemExit(f'FATAL: 소스 없음 또는 positions 키 부재: {SRC}')
    positions = data['positions']
    updated = data.get('updated', '')
    prev = load_json('/root/moneyflow/positions_history.json') or {}
    prev_map = {}
    if isinstance(prev, dict) and 'positions' in prev:
        prev_map = {r['ticker']: r for r in prev['positions'] if 'ticker' in r}

    # ── slug 충돌 전수 검사 (빌드 전, 충돌 1건이라도 HARD_FAIL) ──
    slug_map = {}
    collisions = []
    for r in positions:
        t = r.get('ticker')
        if not t: continue
        s = slugify(t)
        if s in slug_map and slug_map[s] != t:
            collisions.append((s, slug_map[s], t))
        slug_map[s] = t
    if collisions:
        raise SystemExit(f'HARD_FAIL: slug 충돌 {len(collisions)}건: {collisions}')

    # ── 빌드 ──
    built, indexed = [], []
    for r in positions:
        t = r.get('ticker')
        if not t: continue
        slug = slugify(t)
        html_out = page_html(r, positions, prev_map.get(t), updated)
        write_atomic(os.path.join(OUT_DIR, slug, 'index.html'), html_out)
        built.append(slug)
        if not (is_partial(r) or is_excluded(r)):
            indexed.append(slug)  # sitemap = index 대상만

    # raw↔slug 매핑 (canonical·검색 인덱스용)
    write_atomic(SLUG_MAP, json.dumps(
        {slugify(r['ticker']): r['ticker'] for r in positions if r.get('ticker')},
        ensure_ascii=False, indent=2))

    # sitemap-us (index 대상만, noindex 제외)
    urls = ''.join(f'  <url><loc>{SITE}/stock/us/{s}/</loc></url>\n' for s in sorted(indexed))
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               f'{urls}</urlset>\n')
    write_atomic(SITEMAP, sitemap)

    print(f'[us-build] built={len(built)} indexed={len(indexed)} '
          f'noindex={len(built)-len(indexed)} collisions=0')
    print(f'[us-build] slugs={built}')


if __name__ == '__main__':
    main()
