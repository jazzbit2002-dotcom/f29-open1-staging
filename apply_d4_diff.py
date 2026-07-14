#!/usr/bin/env python3
# apply_d4_diff.py — D4-3 '어제와 달라진 3가지' 제목·행명·단위 정정 (F29-D4-DIFF v1)
# 데이터 논리(어제 계산값 vs 오늘 계산값, 동일 기간)는 그대로. 오해를 부르는 라벨만 정정한다.
# 단위: 변화율(prev/curr) = % / 그 차이(delta) = %p  ← 변화율의 차이는 %가 아니라 %p.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-DIFF v1'
REQUIRE = 'F29-D4-FMT v2'

PATCHES = []

# ── ① 행명: 수준이 아니라 '변화율/변화'임을 라벨에 박는다
PATCHES.append((
"""FIELD_KO = {'share': '거래대금 점유율', 'price': '주가', 'state': '상태'}""",
"""FIELD_KO = {'share': '거래대금 점유율 변화', 'price': '주가 변화율', 'state': '상태'}   # F29-D4-DIFF v1"""
))

# ── ② 제목·부제·delta 단위(%p)·괄호 표기
PATCHES.append((
"""def card_diff(retro):
    \"\"\"② 어제와 달라진 3가지 — 상태 변화 우선, 없으면 지표 변화.\"\"\"
    ch = (retro or {}).get('diff') or []
    if not ch:
        return ('<section class="card"><h2>어제와 달라진 3가지</h2>'
                '<p class="hint">전일 데이터가 없어 변화 추적은 다음 거래일부터 시작됩니다.</p></section>')
    items = ''
    for c in ch[:3]:
        w = c['window']
        if c['kind'] == 'state':
            items += (f'<li><span class="dk">{w}일 상태</span>'
                      f'<span class="dv"><s>{esc(c["prev"])}</s> → <b>{esc(c["curr"])}</b></span></li>')
        else:
            f = fmt_pp if c['field'] == 'share' else fmt_pct   # F29-D4-FMT v1
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{f(c["prev"])}</s> → '
                      f'<b class="{cls}">{f(c["curr"])}</b>'
                      f'<em class="dd">{f(c["delta"])}</em></span></li>')
    return (f'<section class="card"><h2>어제와 달라진 3가지</h2>'
            f'<ul class="difflist">{items}</ul>'
            f'<p class="hint">직전 거래일과 같은 기준으로 다시 계산한 결과입니다.</p></section>')""",
"""def card_diff(retro):
    \"\"\"② 전일 대비 달라진 핵심 3가지 — 상태 변화 우선, 없으면 지표 변화.  # F29-D4-DIFF v1
    비교 대상은 '같은 기간(15/30/60/90일) 지표를 어제 계산한 값 vs 오늘 계산한 값'이다.
    1일·7일 지표가 아니다. 단위: 변화율 = % / 변화율의 차이 = %p.\"\"\"
    ch = (retro or {}).get('diff') or []
    if not ch:
        return ('<section class="card"><h2>전일 대비 달라진 핵심 3가지</h2>'
                '<p class="hint">전일 데이터가 없어 변화 추적은 다음 거래일부터 시작됩니다.</p></section>')
    items = ''
    for c in ch[:3]:
        w = c['window']
        if c['kind'] == 'state':
            items += (f'<li><span class="dk">{w}일 상태</span>'
                      f'<span class="dv"><s>{esc(c["prev"])}</s> → <b>{esc(c["curr"])}</b></span></li>')
        else:
            f = fmt_pp if c['field'] == 'share' else fmt_pct
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{f(c["prev"])}</s> → '
                      f'<b class="{cls}">{f(c["curr"])}</b>'
                      f'<em class="dd">({fmt_pp(c["delta"])})</em></span></li>')
    return (f'<section class="card"><h2>전일 대비 달라진 핵심 3가지</h2>'
            f'<ul class="difflist">{items}</ul>'
            f'<p class="hint">직전 거래일에 계산된 <b>동일 기간</b> 지표와 비교합니다. '
            f'1일·7일 변화가 아니라, 같은 15·30·60·90일 지표를 어제와 오늘 각각 계산해 그 차이를 봅니다. '
            f'괄호 안은 그 차이(%p)입니다.</p></section>')"""
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
    if '<h2>어제와 달라진 3가지</h2>' in out:
        sys.exit('ABORT: 구 제목 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4diff-{ts}')
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
