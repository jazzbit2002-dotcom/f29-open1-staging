#!/usr/bin/env python3
# apply_d4_verdict.py — D4-2 오늘 판정의 기준 기간 명시 (F29-D4-VERDICT v1)
# 대표 = 15거래일 / 배경 = 90거래일 로 분리하고, 90일은 주가뿐 아니라 점유율도 병기한다.
# 값은 전부 summary[w]에서만. 라벨은 build_weight SSOT(flowLabel) 원문.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-VERDICT v1'
REQUIRE = 'F29-D4-FMT v2'

PATCHES = []

# ── ① verdict() 재구성: (head, base, sub, long_line, axes)
PATCHES.append((
"""def verdict(summ, quote):
    \"\"\"결론 1줄 + 근거 축. (headline, sub, axes[])\"\"\"
    s15 = (summ or {}).get('15') or {}
    s90 = (summ or {}).get('90') or {}
    s60 = (summ or {}).get('60') or {}
    st15, lb15 = s15.get('flowState', ''), s15.get('flowLabel', '')
    long_st = s90.get('flowState') or s60.get('flowState') or ''
    long_pc = s90.get('priceChangePct', 0) or 0
    head = lb15 or '판정 데이터 부족'
    sub = ''
    if long_st and st15:
        lrank = RETRO.STATE_RANK.get(long_st, 0)
        srank = RETRO.STATE_RANK.get(st15, 0)
        ltxt = TREND_LONG.get(long_st, '')
        if lrank > 0 and srank < 0:
            sub = f'{ltxt}는 유지되나, 최근 15일 관심이 꺾이는 국면입니다.'
        elif lrank < 0 and srank > 0:
            sub = f'{ltxt} 속에서 최근 15일 자금이 다시 들어오는 국면입니다.'
        elif lrank > 0 and srank > 0:
            sub = f'{ltxt}와 단기 흐름이 같은 방향입니다.'
        elif lrank < 0 and srank < 0:
            sub = f'{ltxt}가 단기에도 이어지고 있습니다.'
        else:
            sub = f'{ltxt} 대비 단기 방향은 뚜렷하지 않습니다.'
    axes = []
    if s15:
        axes.append(('15일 주가', fmt_pct(s15.get('priceChangePct')), pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율', fmt_pp(s15.get('shareDeltaPp')), ''))   # F29-D4-FMT v1
    if s90:
        axes.append(('90일 주가', fmt_pct(long_pc), pcls(long_pc)))
    return head, sub, axes""",
"""def verdict(summ, quote):
    \"\"\"대표 판정 = 15거래일 / 배경 = 90거래일. 기준 기간을 화면에 드러낸다.  # F29-D4-VERDICT v1
    (head, base, sub, long_line, axes[]) — 값은 summary[w]에서만, 라벨은 flowLabel 원문.\"\"\"
    s15 = (summ or {}).get('15') or {}
    s90 = (summ or {}).get('90') or {}
    s60 = (summ or {}).get('60') or {}
    st15, lb15 = s15.get('flowState', ''), s15.get('flowLabel', '')
    long_st = s90.get('flowState') or s60.get('flowState') or ''
    long_pc = s90.get('priceChangePct', 0) or 0
    head = lb15 or '판정 데이터 부족'
    base = '최근 15거래일 기준' if lb15 else ''
    sub = ''
    if long_st and st15:
        lrank = RETRO.STATE_RANK.get(long_st, 0)
        srank = RETRO.STATE_RANK.get(st15, 0)
        ltxt = TREND_LONG.get(long_st, '')
        if lrank > 0 and srank < 0:
            sub = f'{ltxt}는 유지되나, 최근 15거래일 가격·관심이 함께 저하된 국면입니다.'
        elif lrank < 0 and srank > 0:
            sub = f'{ltxt} 속에서 최근 15거래일 거래대금이 다시 들어오는 국면입니다.'
        elif lrank > 0 and srank > 0:
            sub = f'{ltxt}와 최근 15거래일 흐름이 같은 방향입니다.'
        elif lrank < 0 and srank < 0:
            sub = f'{ltxt}가 최근 15거래일에도 이어지고 있습니다.'
        else:
            sub = f'{ltxt} 대비 최근 15거래일 방향은 뚜렷하지 않습니다.'
    # 배경(중기 90거래일): 주가만이 아니라 점유율도 병기해 판정 기준을 드러낸다.
    long_line = ''
    lb90 = s90.get('flowLabel', '')
    if lb90:
        long_line = (f'중기 90거래일 기준: {lb90} · 주가 {fmt_pct(long_pc)} · '
                     f'거래대금 점유율 {fmt_pp(s90.get("shareDeltaPp"))}')
    axes = []
    if s15:
        axes.append(('15일 주가 변화율', fmt_pct(s15.get('priceChangePct')), pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율 변화', fmt_pp(s15.get('shareDeltaPp')), ''))
    if s90:
        axes.append(('90일 주가 변화율', fmt_pct(long_pc), pcls(long_pc)))
        axes.append(('90일 거래대금 점유율 변화', fmt_pp(s90.get('shareDeltaPp')), ''))
    return head, base, sub, long_line, axes"""
))

# ── ② 호출부 언패킹
PATCHES.append((
"""    v_head, v_sub, v_axes = verdict(summ, q)""",
"""    v_head, v_base, v_sub, v_long, v_axes = verdict(summ, q)   # F29-D4-VERDICT v1"""
))

# ── ③ card0: 기준 기간 칩 + 중기 배경 줄
PATCHES.append((
"""    card0 = f'''<section class="card verdict">
<h2>F29 오늘 판정</h2>
<p class="vhead">{esc(v_head)}</p>
<p class="vsub">{esc(v_sub)}</p>
<ul class="axes">{axes_html}</ul>
{theme_line}""",
"""    v_base_html = f'<span class="vbase">{esc(v_base)}</span>' if v_base else ''
    v_long_html = f'<p class="vlong">{esc(v_long)}</p>' if v_long else ''
    card0 = f'''<section class="card verdict">
<h2>F29 오늘 판정</h2>
<p class="vhead">{esc(v_head)} {v_base_html}</p>
<p class="vsub">{esc(v_sub)}</p>
{v_long_html}
<ul class="axes">{axes_html}</ul>
{theme_line}"""
))

# ── ④ CSS
PATCHES.append((
""".vsub{{margin:0 0 12px;color:var(--tx);font-size:1rem}}""",
""".vsub{{margin:0 0 6px;color:var(--tx);font-size:1rem}}
.vbase{{display:inline-block;vertical-align:middle;background:#1f2937;color:var(--sub);font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:10px;margin-left:6px}}
.vlong{{margin:0 0 12px;padding:8px 10px;background:#0d1523;border-radius:8px;color:var(--sub);font-size:.86rem}}"""
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
    if 'v_head, v_sub, v_axes' in out:
        sys.exit('ABORT: 구 언패킹 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4verdict-{ts}')
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
