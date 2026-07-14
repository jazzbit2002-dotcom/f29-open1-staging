#!/usr/bin/env python3
# apply_d4_fmt2.py — D4-4 보정 (F29-D4-FMT v2)
# 누락 지점: page_html 카드1 '15·30·60·90일 돈의 무게' 표.
#   :+g 가 아니라 포맷 자체가 없는 raw f-string이라 D4-4 1차 스캔에서 누락됨.
#   {_pc}% → fmt_pct / {shareDeltaPp}p → fmt_pp (%p). 값 출처는 summary 그대로.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-FMT v2'
REQUIRE = 'F29-D4-FMT v1'

PATCHES = [(
"""        rows += (f'<tr><td>{w}일</td><td><b>{esc(s.get("flowLabel",""))}</b></td>'
                 f'<td class="num {pcls(_pc)}">{_pc}%</td>'
                 f'<td class="num">{s.get("shareDeltaPp","")}p</td></tr>')""",
"""        rows += (f'<tr><td>{w}일</td><td><b>{esc(s.get("flowLabel",""))}</b></td>'   # F29-D4-FMT v2
                 f'<td class="num {pcls(_pc)}">{fmt_pct(_pc)}</td>'
                 f'<td class="num">{fmt_pp(s.get("shareDeltaPp"))}</td></tr>')"""
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
    if '}p</td>' in out or '{_pc}%' in out:
        sys.exit('ABORT: 미포맷 단위 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4fmt2-{ts}')
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
