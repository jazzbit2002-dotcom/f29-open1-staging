#!/usr/bin/env python3
# apply_d4_sync.py — D4-9 같은 테마·같은 상태 종목 수 (F29-D4-SYNC v1)
# 1단계: 현재 동조 카운트만. 각 멤버 repState(stocks_public, 이미 로드) 집계 — 신규 데이터·컴퓨트 없음.
# 2단계(전일 대비 확산 "어제 1 → 오늘 3")는 스냅샷 배선 후 별건.
# 라벨은 build_weight SSOT(repLabel) 원문, 색은 state_tone() 3단.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-SYNC v1'
REQUIRE = 'F29-D4-DEF15 v1'

PATCHES = []

# ── ① 집계 + 카드 (theme_card5 정의 직전에 삽입)
PATCHES.append((
"""def theme_card5(theme_info, tstage):""",
"""# F29-D4-SYNC v1
# ---- D4-9 같은 테마·같은 상태: 테마 멤버의 repState를 집계한다. 판정 엔진 호출 없음(표시층 집계).
SYNC_LOW, SYNC_WIDE = 1 / 3, 2 / 3      # 동조도 구간(표시 규칙. 엔진 내부 임계값 아님)

def theme_sync9(code, d, members, stocks):
    st = d.get('repState', '')
    if not st or not members:
        return {}
    same = [(c, stocks[c].get('name', ''), stocks[c].get('repLabel', ''))
            for c in members
            if c != code and stocks[c].get('repState', '') == st]
    total = len(members)
    incl = len(same) + 1                 # 이 종목 포함
    ratio = incl / total if total else 0
    sync = '낮음' if ratio < SYNC_LOW else ('확산 중' if ratio < SYNC_WIDE else '광범위')
    return {'state': st, 'label': d.get('repLabel', ''), 'same': same,
            'incl': incl, 'total': total, 'ratio': ratio, 'sync': sync}

def theme_sync_card9(theme_info, name):
    s = (theme_info or {}).get('sync9') or {}
    if not s.get('total'):
        return ''
    theme = esc((theme_info or {}).get('theme', ''))
    tone = state_tone(s['state'])
    pct = round(s['ratio'] * 100)
    lst = ''.join(
        f'<li><a href="/stock/{c}/">{esc(nm)}</a>'
        f'<span class="sl {state_tone(s["state"])}">{esc(lb)}</span></li>'
        for c, nm, lb in s['same'][:8]) if s['same'] else ''
    lst_html = (f'<p class="slbl">같은 상태인 다른 종목</p><ul class="synclist">{lst}</ul>'
                if lst else '<p class="hint">현재 이 테마에서 같은 상태인 다른 종목은 없습니다.</p>')
    return (f'<section class="card"><h2>테마 동조 현황</h2>'
            f'<p class="tsub">{theme} · {s["total"]}종목</p>'
            f'<p class="syncbig"><b class="syncn {tone}">{s["incl"]}</b>'
            f'<span class="syncd"> / {s["total"]}종목이 '
            f'<span class="fbadge {tone}">{esc(s["label"])}</span> 상태</span></p>'
            f'<p class="syncrate">테마 동조도 <b class="{tone}">{esc(s["sync"])}</b> '
            f'<span class="syncsub">(같은 상태 비중 {pct}% · 이 종목 포함)</span></p>'
            f'{lst_html}'
            f'<p class="hint">같은 테마 안에서 지금 같은 상태로 판정된 종목 수입니다. '
            f'비중 33% 미만이면 낮음, 67% 미만이면 확산 중, 그 이상이면 광범위로 표시합니다. '
            f'개별 종목의 움직임인지 테마 전체의 움직임인지 구분하는 참고지표입니다.</p></section>')

def theme_card5(theme_info, tstage):"""
))

# ── ② page_html: 카드 생성 + 레이아웃(peers 바로 위)
PATCHES.append((
"""    # 카드3: 같은 테마 종목
    card3 = ''""",
"""    card9 = theme_sync_card9(theme_info, name) if theme_info else ''   # F29-D4-SYNC v1

    # 카드3: 같은 테마 종목
    card3 = ''"""
))
PATCHES.append((
"""<div class="grid">{card_d}{card_s}{card1}{card_chart}{card2}{card3}{card_h}{card4}</div>""",
"""<div class="grid">{card_d}{card_s}{card1}{card_chart}{card2}{card9}{card3}{card_h}{card4}</div>"""
))

# ── ③ main(): sync9 집계 주입
PATCHES.append((
"""            ti = {**ti, 'r5': theme_rank5(code, d, members, stocks, press_rank)}""",
"""            ti = {**ti, 'r5': theme_rank5(code, d, members, stocks, press_rank),
                  'sync9': theme_sync9(code, d, members, stocks)}      # F29-D4-SYNC v1"""
))

# ── ④ CSS
PATCHES.append((
""".rank5{{list-style:none;margin:0 0 8px;padding:0}}""",
""".syncbig{{margin:0 0 6px;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}}
.syncn{{font-size:1.9rem;font-weight:800;font-family:"JetBrains Mono",monospace;line-height:1.1}}
.syncn.up-c{{color:var(--teal)}}
.syncn.wt-c{{color:var(--gold)}}
.syncn.dn-c{{color:var(--up)}}
.syncd{{font-size:.92rem}}
.syncrate{{margin:0 0 10px;font-size:.9rem;color:var(--tx)}}
.syncrate .up-c{{color:var(--teal)}}
.syncrate .wt-c{{color:var(--gold)}}
.syncrate .dn-c{{color:var(--up)}}
.syncsub{{color:var(--sub);font-size:.78rem}}
.slbl{{color:var(--sub);font-size:.78rem;margin:0 0 4px}}
.synclist{{list-style:none;margin:0;padding:0}}
.synclist li{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:6px 0;border-bottom:1px solid #1f2937}}
.synclist li:last-child{{border-bottom:0}}
.synclist a{{color:var(--tx);text-decoration:none}}
.sl{{font-size:.8rem}}
.sl.up-c{{color:var(--teal)}}
.sl.wt-c{{color:var(--gold)}}
.sl.dn-c{{color:var(--up)}}
.rank5{{list-style:none;margin:0 0 8px;padding:0}}"""
))


def main():
    if not os.path.isfile(TARGET):
        sys.exit(f'ABORT: target not found: {TARGET}')
    src = open(TARGET, encoding='utf-8').read()
    if REQUIRE not in src:
        sys.exit(f'ABORT: 선행 패치 미적용 ({REQUIRE})')
    if MARKER in src:
        sys.exit(f'ABORT: marker already present ({MARKER}) — 이미 적용됨.')
    for i, (old, _) in enumerate(PATCHES, 1):
        c = src.count(old)
        if c != 1:
            sys.exit(f'ABORT: anchor #{i} count={c} (expected 1)\n---\n{old[:120]}\n---')
    print(f'anchor gate OK: {len(PATCHES)}/{len(PATCHES)} × 1')

    out = src
    for old, new in PATCHES:
        out = out.replace(old, new, 1)
    if MARKER not in out:
        sys.exit('ABORT: marker missing after patch')
    if '{card2}{card3}' in out:
        sys.exit('ABORT: 레이아웃에 card9 미삽입')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4sync-{ts}')
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bdir, 'build_stock_pages.py'))
    print(f'backup: {bdir}/build_stock_pages.py')

    d = os.path.dirname(TARGET)
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(out)
    try:
        py_compile.compile(tmp, doraise=True, cfile=tmp + '.pyc')
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        sys.exit(f'ABORT: py_compile failed\n{e}')
    os.unlink(tmp + '.pyc')
    os.chmod(tmp, 0o644)
    os.replace(tmp, TARGET)
    print(f'OK: {MARKER} applied  {len(src.encode())} B → {len(out.encode())} B')


if __name__ == '__main__':
    main()
