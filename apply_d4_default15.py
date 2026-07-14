#!/usr/bin/env python3
# apply_d4_default15.py — 차트 기본창 90일 → 15일 (F29-D4-DEF15 v1)
# 이유: 최장창(90일) 기본은 후행성이 커서 첫 화면이 현재 국면을 늦게 반영한다.
# 규칙: 기간 토글이 있는 모든 차트는 '최단 창'을 기본으로 연다.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-DEF15 v1'
REQUIRE = 'F29-D4-CHART2 v1'

PATCHES = [(
"""    wins = [w for w in CHART_WINS if str(w) in (summ or {})] or [min(CHART_WINS)]
    default = max(wins)""",
"""    wins = [w for w in CHART_WINS if str(w) in (summ or {})] or [min(CHART_WINS)]
    default = min(wins)          # F29-D4-DEF15 v1: 기간 토글 차트는 최단 창을 기본으로 연다(후행성 축소)"""
)]


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
    if 'default = max(wins)' in out:
        sys.exit('ABORT: 구 기본창(max) 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4def15-{ts}')
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
