#!/usr/bin/env python3
# F29 D4 P1-1: D4-7(peers 행 전체 클릭) + D4-6(이동 링크 버튼화)
# 마커: F29-D4-ROW v1 / F29-D4-GOLINK v1
# 규칙: 리터럴 앵커 + count 게이트(정확히 1회) + 자동 백업 + py_compile + 원자 쓰기
#       + 마커 중복 방지 + 선행 마커 요구(F29-D4-SYNC v2). 추정 패치 없음.
# 사용: python3 patch_d4_row_golink.py            → /root/krx-moneyflow/build_stock_pages.py
#       python3 patch_d4_row_golink.py <경로>     → 로컬 검증용
#       --dry-run                                  → 쓰기 없이 앵커 검사만

import sys, os, shutil, py_compile, datetime, tempfile

TARGET      = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
TAG         = 'd4row'

MARKERS_NEW  = ['F29-D4-ROW v1', 'F29-D4-GOLINK v1']
MARKER_PREREQ = 'F29-D4-SYNC v2'

# ---------------------------------------------------------------- D4-7 peers
A1_OLD = """        items = ''.join(
            f'<li><a href="/stock/{p["code"]}/">{esc(p["name"])}</a>'
            f'<span class="pl">{esc(p["repLabel"])}</span></li>' for p in peers)"""

A1_NEW = """        items = ''.join(                                        # F29-D4-ROW v1
            f'<li><a class="prow" data-ev="peer_click" data-card="peers" '
            f'href="/stock/{p["code"]}/">'
            f'<span class="pn">{esc(p["name"])}</span>'
            f'<span class="pl">{esc(p["repLabel"])}</span>'
            f'<span class="pgo" aria-hidden="true">&rsaquo;</span></a></li>' for p in peers)"""

A2_OLD = """.peers{{list-style:none;margin:0;padding:0}}
.peers li{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1f2937}}
.peers a{{color:var(--tx);text-decoration:none}}
.pl{{color:var(--sub);font-size:.85rem}}"""

A2_NEW = """.peers{{list-style:none;margin:0;padding:0}}
/* F29-D4-ROW v1: 행 전체가 링크. 터치 타깃 44px */
.peers li{{border-bottom:1px solid #1f2937}}
.peers li:last-child{{border-bottom:0}}
.prow{{display:flex;align-items:center;gap:12px;padding:9px 6px;min-height:44px;box-sizing:border-box;color:var(--tx);text-decoration:none;border-radius:6px}}
.prow:hover{{background:#0d1523}}
.pn{{flex:1 1 auto;font-weight:600}}
.pl{{color:var(--sub);font-size:.85rem}}
.pgo{{flex:0 0 auto;color:var(--sub);font-size:1.1rem;line-height:1}}
.prow:hover .pgo{{color:var(--teal)}}"""

# --------------------------------------------------------------- D4-6 golink
A3_OLD = """.more{{display:inline-block;margin-top:10px;color:var(--teal);text-decoration:none;font-size:.88rem}}"""

A3_NEW = """/* F29-D4-GOLINK v1: 카드 밖으로 나가는 이동 링크. 카드 내부 확장(.ctab 등)과 시각 분리 */
.golink{{display:inline-flex;align-items:center;gap:7px;margin-top:12px;padding:9px 14px;min-height:44px;box-sizing:border-box;background:#0d1523;border:1px solid #1f2937;border-radius:8px;color:var(--teal);text-decoration:none;font-size:.88rem;font-weight:600}}
.golink:hover{{border-color:var(--teal);background:#101c2e}}
.goar{{font-family:"JetBrains Mono",monospace;font-weight:700}}"""

A4_OLD = """<a class="more" data-ev="card_more" data-card="weight" href="/weight">돈의 무게에서 더 보기</a>"""
A4_NEW = """<a class="golink" data-ev="card_more" data-card="weight" href="/weight">돈의 무게 전체 보기 <span class="goar">&rarr;</span></a>"""

A5_OLD = """<a class="more" data-ev="card_more" data-card="kr" href="/kr-moneyflow">시장 전체 자금 흐름 보기</a>"""
A5_NEW = """<a class="golink" data-ev="card_more" data-card="kr" href="/kr-moneyflow">시장 전체 자금 흐름 보기 <span class="goar">&rarr;</span></a>"""

A6_OLD = """            f'<a class="more" data-ev="card_more" data-card="kr" href="/kr-moneyflow">'
            f'한국주식 돈의 흐름에서 테마 보기</a></section>')"""
A6_NEW = """            f'<a class="golink" data-ev="card_more" data-card="kr" href="/kr-moneyflow">'
            f'{theme} 테마 전체 보기 <span class="goar">&rarr;</span></a></section>')"""

A7_OLD = """<a class="more" data-ev="card_more" data-card="lab" href="/lab/match.html">차트분석 연구소에서 직접 비교</a>"""
A7_NEW = """<a class="golink" data-ev="card_more" data-card="lab" href="/lab/match.html">차트분석 연구소에서 직접 비교 <span class="goar">&rarr;</span></a>"""

PATCHES = [
    ('D4-7 peers 렌더', A1_OLD, A1_NEW),
    ('D4-7 peers CSS',  A2_OLD, A2_NEW),
    ('D4-6 .more CSS → .golink', A3_OLD, A3_NEW),
    ('D4-6 링크1 weight', A4_OLD, A4_NEW),
    ('D4-6 링크2 kr(테마 미분류)', A5_OLD, A5_NEW),
    ('D4-6 링크3 kr(테마 카드)', A6_OLD, A6_NEW),
    ('D4-6 링크4 lab', A7_OLD, A7_NEW),
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry-run' in sys.argv
    target = args[0] if args else TARGET

    src = open(target, encoding='utf-8').read()
    print(f'target : {target}  ({len(src.encode()):,} B)')

    # 선행 마커
    if MARKER_PREREQ not in src:
        sys.exit(f'STOP: 선행 마커 없음 — {MARKER_PREREQ}. D4 P0 미반영 파일로 보임.')

    # 마커 중복 방지
    for m in MARKERS_NEW:
        if m in src:
            sys.exit(f'STOP: 마커 이미 존재 — {m}. 재적용 금지.')

    # 앵커 count 게이트 (정확히 1회)
    for name, old, _ in PATCHES:
        n = src.count(old)
        if n != 1:
            sys.exit(f'STOP: 앵커 {n}회 — [{name}]. 정확히 1회여야 함.')
        print(f'  anchor OK (1) : {name}')

    if '.more' in src.replace(A3_OLD, ''):
        # class="more" 잔존 여부는 아래 치환 후 재검사
        pass

    out = src
    for name, old, new in PATCHES:
        out = out.replace(old, new, 1)

    # 사후 검사: .more 잔존 금지
    if 'class="more"' in out:
        sys.exit('STOP: class="more" 잔존. 링크 4곳 중 누락 있음.')
    for m in MARKERS_NEW:
        if m not in out:
            sys.exit(f'STOP: 마커 미주입 — {m}')

    # 문법 검사 (임시 파일)
    tmpf = tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8')
    tmpf.write(out); tmpf.close()
    try:
        py_compile.compile(tmpf.name, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmpf.name)
        sys.exit(f'STOP: py_compile 실패\n{e}')
    os.unlink(tmpf.name)
    print('  py_compile OK')

    if dry:
        print(f'DRY-RUN 종료. 결과 크기 {len(out.encode()):,} B (기존 대비 {len(out.encode())-len(src.encode()):+,} B)')
        return

    # 백업
    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'{TAG}-{ts}')
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(target, os.path.join(bdir, os.path.basename(target)))
    print(f'  backup : {bdir}')

    # 원자 쓰기
    tmp = target + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)
    print(f'DONE. {len(out.encode()):,} B')


if __name__ == '__main__':
    main()
