#!/usr/bin/env python3
# apply_d3_mobile.py — F29 D3 모바일 390px 폴리시 (경량)
#   실측: 카드 순서 ①→②→③→④→차트→⑤→⑥→CTA 준수, 가로 overflow 0(검증됨).
#   보강: ≤480px 카드 여백·타이포·표/차트/타임라인 가독성만 소폭 조정. 레이아웃/DOM 무변경.
#   방식: 리터럴 앵커 str.replace(1개, 1회 게이트), 백업, py_compile, 원자 쓰기, 버전마커.
import os, sys, shutil, py_compile, datetime

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
MARK   = 'F29-D3-MOBILE v1'

OLD = '@media(max-width:480px){{.wrap{{padding:12px}}.quote{{gap:16px}}.vhead{{font-size:1.25rem}}.axes{{gap:14px}}}}'
NEW = ('@media(max-width:480px){{.wrap{{padding:12px}}.quote{{gap:16px}}.vhead{{font-size:1.25rem}}.axes{{gap:14px}}'
       '.card{{padding:13px}}h1{{font-size:1.16rem}}table{{font-size:.83rem}}th,td{{padding:5px 3px}}'
       '.ctab{{padding:4px 9px}}.crel{{font-size:.85rem}}.tl-label{{font-size:.9rem}}.dv{{font-size:.88rem}}'
       '/* F29-D3-MOBILE v1 */}}')

def die(m):
    print(f'FAIL: {m}'); sys.exit(1)

def main():
    if not os.path.exists(TARGET):
        die(f'대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()
    if MARK in src:
        die(f'이미 적용됨(마커 {MARK}) — 중단')
    n = src.count(OLD)
    print(f'anchor @media480: {n}')
    if n != 1:
        die(f'앵커 {n}회(1 기대) — 소스 불일치, 중단')
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bk = f'/root/f29-backups/d3mobile-{ts}'
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))
    print(f'backup: {bk}/build_stock_pages.py')
    out = src.replace(OLD, NEW)
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
