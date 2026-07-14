#!/usr/bin/env python3
# apply_d4_sync2.py — D4-9 보정 (F29-D4-SYNC v2)
# 문제: 비중이 경계값(5/15 = 33.3%)일 때 화면에 '비중 33%' + '33% 미만이면 낮음' + '확산 중'이
#       동시에 뜬다 → 반올림 때문에 모순처럼 읽힌다.
# 수정: 비중은 소수 1자리 표시, 임계는 % 대신 분수(3분의 1 / 3분의 2)로 서술. 집계 로직 불변.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-SYNC v2'
REQUIRE = 'F29-D4-SYNC v1'

PATCHES = []

PATCHES.append((
"""    pct = round(s['ratio'] * 100)""",
"""    pct = f"{s['ratio'] * 100:.1f}"       # F29-D4-SYNC v2: 경계값 반올림 모순 방지"""
))
PATCHES.append((
"""            f'<span class="syncsub">(같은 상태 비중 {pct}% · 이 종목 포함)</span></p>'""",
"""            f'<span class="syncsub">(같은 상태 비중 {pct}% · 이 종목 포함)</span></p>'   # F29-D4-SYNC v2"""
))
PATCHES.append((
"""            f'<p class="hint">같은 테마 안에서 지금 같은 상태로 판정된 종목 수입니다. '
            f'비중 33% 미만이면 낮음, 67% 미만이면 확산 중, 그 이상이면 광범위로 표시합니다. '
            f'개별 종목의 움직임인지 테마 전체의 움직임인지 구분하는 참고지표입니다.</p></section>')""",
"""            f'<p class="hint">같은 테마 안에서 지금 같은 상태로 판정된 종목 수입니다. '
            f'같은 상태 비중이 3분의 1 미만이면 낮음, 3분의 2 미만이면 확산 중, '
            f'그 이상이면 광범위로 표시합니다. '
            f'개별 종목의 움직임인지 테마 전체의 움직임인지 구분하는 참고지표입니다.</p></section>')"""
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
    if '비중 33% 미만이면' in out:
        sys.exit('ABORT: 구 임계 문구 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4sync2-{ts}')
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
