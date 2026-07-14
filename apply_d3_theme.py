#!/usr/bin/env python3
# apply_d3_theme.py — F29 D3 ⑤ 테마 내 실제 위치 (실측)
#   기존 "테마 위치"(테마명·단계만) → 테마 내 거래대금 점유율 순위 / 전일 대비 점유 /
#   15일 점유 변화 / 시장 자금 압력 순위 / 역할. 전부 실측 필드에서(추정 없음):
#     점유율·순위·전일대비 = stocks_public.tradingSharePctSeries
#     15일 점유 변화       = summary['15'].shareDeltaPp
#     자금 압력 순위       = weight_output.buyPressure/sellPressure 정렬 위치
#   방식: 리터럴 앵커 str.replace(5개, 각 1회 게이트), 백업, py_compile, 원자 쓰기, 버전마커.
import os, sys, shutil, py_compile, datetime

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
MARK   = 'F29-D3-THEME v1'

# ── 앵커 1: weight 로딩 뒤 압력 순위 맵 추가 ──────────────────────────────────
A1_OLD = '''    weight = load_json(F_WEIGHT, {}) or {}
    buy_codes  = {r.get('code') for r in weight.get('buyPressure', [])}
    sell_codes = {r.get('code') for r in weight.get('sellPressure', [])}'''
A1_NEW = A1_OLD + '''
    # F29-D3-THEME v1: 시장 자금 압력 순위 맵 (code → (측, 순위))
    press_rank = {}
    for _side, _key in (('매수', 'buyPressure'), ('매도', 'sellPressure')):
        for _i, _r in enumerate(weight.get(_key, [])):
            _c = _r.get('code')
            if _c and _c not in press_rank:
                press_rank[_c] = (_side, _i + 1)'''

# ── 앵커 2: theme_rank5 / theme_card5 함수 삽입 (page_html 직전) ───────────────
A2_OLD = 'def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell, retro=None):'
A2_NEW = '''# F29-D3-THEME v1
# ---- ⑤ 테마 내 실제 위치: 실측 순위/점유/압력/역할. 배지가 아니라 수치.
def theme_rank5(code, d, members, stocks, press_rank):
    def _cur(x):
        for p in reversed(x.get('tradingSharePctSeries') or []):
            if isinstance(p.get('v'), (int, float)):
                return p['v']
        return None
    def _prev(x):
        s = [p['v'] for p in (x.get('tradingSharePctSeries') or [])
             if isinstance(p.get('v'), (int, float))]
        return round(s[-1] - s[-2], 3) if len(s) >= 2 else None
    ranked = sorted(
        [(c, _cur(stocks[c])) for c in members if _cur(stocks[c]) is not None],
        key=lambda t: t[1], reverse=True)
    total = len(ranked)
    rank = next((i + 1 for i, (c, _) in enumerate(ranked) if c == code), None)
    sd15 = ((d.get('summary') or {}).get('15') or {}).get('shareDeltaPp')
    pr = press_rank.get(code)
    if rank == 1:
        role = '테마 주도'
    elif rank and rank <= max(3, total // 3):
        role = '주력'
    elif rank:
        role = '후발'
    else:
        role = ''
    if role and isinstance(sd15, (int, float)):
        if sd15 <= -0.1:
            role += ' · 점유 축소'
        elif sd15 >= 0.1:
            role += ' · 점유 확대'
    return {'share': _cur(d), 'rank': rank, 'total': total, 'prevDelta': _prev(d),
            'sd15': sd15, 'pressSide': pr[0] if pr else None,
            'pressRank': pr[1] if pr else None, 'role': role}

def theme_card5(theme_info, tstage):
    r = (theme_info or {}).get('r5') or {}
    theme = esc(theme_info.get('theme', ''))
    sub = esc(theme_info.get('subtheme', ''))
    head = f'{theme} · {sub}' if sub else theme
    rows = []
    if isinstance(r.get('share'), (int, float)):
        rows.append(('거래대금 점유율', f'{r["share"]:.2f}%'))
    if r.get('rank') and r.get('total'):
        rows.append(('테마 내 순위', f'{r["rank"]}위 / {r["total"]}개'))
    if isinstance(r.get('prevDelta'), (int, float)):
        rows.append(('전일 대비 점유', f'{r["prevDelta"]:+g}p'))
    if isinstance(r.get('sd15'), (int, float)):
        rows.append(('15일 점유 변화', f'{r["sd15"]:+g}p'))
    if r.get('pressSide') and r.get('pressRank'):
        rows.append(('시장 자금 압력', f'{esc(r["pressSide"])} {r["pressRank"]}위'))
    li = ''.join(f'<li><span class="rk">{esc(k)}</span><b class="rv">{esc(v)}</b></li>'
                 for k, v in rows)
    role_html = f'<p class="trole">역할: <b>{esc(r["role"])}</b></p>' if r.get('role') else ''
    stage_html = f'<p class="tline">테마 단계: <b>{esc(tstage)}</b></p>' if tstage else ''
    body = (f'<ul class="rank5">{li}</ul>{role_html}' if li else '')
    return (f'<section class="card"><h2>테마 내 실제 위치</h2>'
            f'<p class="tsub">{head}</p>{body}{stage_html}'
            f'<a class="more" data-ev="card_more" data-card="kr" href="/kr-moneyflow">'
            f'한국주식 돈의 흐름에서 테마 보기</a></section>')

def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell, retro=None):'''

# ── 앵커 3: main 루프에서 r5 계산 + theme_info 확장 ───────────────────────────
A3_OLD = '''        ti = code2theme.get(code)
        tstage = theme_stage(tflow, ti['theme']) if ti else ''
        peers = []
        if ti:
            for pc in theme2codes.get(ti['theme'], []):
                if pc == code or pc not in stocks: continue
                pd = stocks[pc]
                peers.append({'code': pc, 'name': pd['name'],
                              'repLabel': pd.get('repLabel', '')})'''
A3_NEW = '''        ti = code2theme.get(code)
        tstage = theme_stage(tflow, ti['theme']) if ti else ''
        peers = []
        if ti:                                        # F29-D3-THEME v1
            members = [c for c in theme2codes.get(ti['theme'], []) if c in stocks]
            for pc in members:
                if pc == code: continue
                pd = stocks[pc]
                peers.append({'code': pc, 'name': pd['name'],
                              'repLabel': pd.get('repLabel', '')})
            ti = {**ti, 'r5': theme_rank5(code, d, members, stocks, press_rank)}'''

# ── 앵커 4: card2(테마 위치) → theme_card5 호출 ──────────────────────────────
A4_OLD = '''    if theme_info:
        stage_txt = f'<p>현재 단계: <b>{esc(tstage)}</b></p>' if tstage else ''
        card2 = f\'\'\'<section class="card">
<h2>테마 위치</h2>
<p>{esc(theme_info["theme"])} · {esc(theme_info.get("subtheme",""))}</p>
{stage_txt}
<a class="more" data-ev="card_more" data-card="kr" href="/kr-moneyflow">한국주식 돈의 흐름에서 테마 보기</a>
</section>\'\'\''''
A4_NEW = '''    if theme_info:
        card2 = theme_card5(theme_info, tstage)   # F29-D3-THEME v1'''

# ── 앵커 5: ⑤ CSS (page_html f-string 내부 → 중괄호 이중) ────────────────────
A5_OLD = '.pl{{color:var(--sub);font-size:.85rem}}\n'
A5_NEW = A5_OLD + (
    '.rank5{{list-style:none;margin:0 0 8px;padding:0}}\n'
    '.rank5 li{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;'
    'padding:6px 0;border-bottom:1px solid #1f2937}}\n'
    '.rank5 li:last-child{{border-bottom:0}}\n'
    '.rk{{color:var(--sub);font-size:.84rem}}\n'
    '.rv{{font-family:"JetBrains Mono",monospace;font-size:.95rem}}\n'
    '.tsub{{margin:0 0 8px;font-weight:600}}\n'
    '.trole{{margin:6px 0 0;color:var(--teal);font-size:.9rem}}\n'
)

STEPS = [('A1 press_rank', A1_OLD, A1_NEW), ('A2 함수삽입', A2_OLD, A2_NEW),
         ('A3 r5계산', A3_OLD, A3_NEW), ('A4 card2', A4_OLD, A4_NEW),
         ('A5 CSS', A5_OLD, A5_NEW)]

def die(m):
    print(f'FAIL: {m}'); sys.exit(1)

def main():
    if not os.path.exists(TARGET):
        die(f'대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()
    if MARK in src:
        die(f'이미 적용됨(마커 {MARK}) — 중단')
    for name, old, _ in STEPS:
        c = src.count(old)
        print(f'anchor {name}: {c}')
        if c != 1:
            die(f'앵커 {name} {c}회(1 기대) — 소스 불일치, 중단')
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bk = f'/root/f29-backups/d3theme-{ts}'
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))
    print(f'backup: {bk}/build_stock_pages.py')
    out = src
    for _, old, new in STEPS:
        out = out.replace(old, new)
    if out == src or MARK not in out:
        die('치환 무효 — 중단')
    tmp = TARGET + '.tmp'
    open(tmp, 'w', encoding='utf-8').write(out)
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
