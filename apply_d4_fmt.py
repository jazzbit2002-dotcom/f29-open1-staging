#!/usr/bin/env python3
# apply_d4_fmt.py — D4-4 숫자 정밀도·단위 전면 통일 (F29-D4-FMT v1)
# 원칙: 표시 형식만 변경. 값 출처는 summary/retro 그대로. 새 수치 생성 없음.
# 규칙: 주가 변화율 = +0.00% / 점유율 변화 = +0.00%p / 점유율 수준 = 0.00%
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-FMT v1'

PATCHES = []

# ── ① 중앙 포매터 주입 (pcls 정의 직전)
PATCHES.append((
"""def pcls(v):
    \"\"\"가격색: 상승 빨강 / 하락 파랑 / 보합 회색 (판정색과 분리)\"\"\"""",
"""# F29-D4-FMT v1
# ---- 중앙 포매터: 표시 정밀도·단위 SSOT. 값은 summary/retro 원본, 여기서 만들지 않는다.
#      주가 변화율 = +0.00% · 점유율 변화 = +0.00%p · 점유율 수준 = 0.00%
def fmt_pct(v, plus=True):
    \"\"\"변화율(%) 2자리\"\"\"
    try: v = float(v)
    except (TypeError, ValueError): return '-'
    return (f'{v:+.2f}%' if plus else f'{v:.2f}%')

def fmt_pp(v, plus=True):
    \"\"\"점유율 변화(%p) 2자리. 단위는 p가 아니라 %p.\"\"\"
    try: v = float(v)
    except (TypeError, ValueError): return '-'
    return (f'{v:+.2f}%p' if plus else f'{v:.2f}%p')

def pcls(v):
    \"\"\"가격색: 상승 빨강 / 하락 파랑 / 보합 회색 (판정색과 분리)\"\"\""""
))

# ── ② card_diff (182행 :+g)
PATCHES.append((
"""        else:
            unit = 'p' if c['field'] == 'share' else '%'
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{c["prev"]}{unit}</s> → '
                      f'<b class="{cls}">{c["curr"]}{unit}</b>'
                      f'<em class="dd">{c["delta"]:+g}{unit}</em></span></li>')""",
"""        else:
            f = fmt_pp if c['field'] == 'share' else fmt_pct   # F29-D4-FMT v1
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{f(c["prev"])}</s> → '
                      f'<b class="{cls}">{f(c["curr"])}</b>'
                      f'<em class="dd">{f(c["delta"])}</em></span></li>')"""
))

# ── ③ card_scenario (200·204·205행 :+g) — D4-5에서 카드 자체 재구성 예정, 단위만 선행 교정
PATCHES.append((
"""        keep = f'거래대금 점유율 변화가 {sd:+g}p 수준을 유지'""",
"""        keep = f'거래대금 점유율 변화가 {fmt_pp(sd)} 수준을 유지'"""
))
PATCHES.append((
"""        keep = f'거래대금 점유율 변화가 최근 고점 {peak:+g}p 방향으로 회복'
        turn = f'점유율이 {sd:+g}p 아래로 더 밀리고 주가 약세가 이어지는 경우'""",
"""        keep = f'거래대금 점유율 변화가 최근 고점 {fmt_pp(peak)} 방향으로 회복'
        turn = f'점유율이 {fmt_pp(sd)} 아래로 더 밀리고 주가 약세가 이어지는 경우'"""
))

# ── ④ card_history (255행 :+g)
PATCHES.append((
"""        sd_txt = f'{sd:+g}p' if isinstance(sd, (int, float)) else '—'""",
"""        sd_txt = fmt_pp(sd) if isinstance(sd, (int, float)) else '—'"""
))

# ── ⑤ theme_card5 (476·478행 :+g)
PATCHES.append((
"""        rows.append(('전일 대비 점유', f'{r["prevDelta"]:+g}p'))""",
"""        rows.append(('전일 대비 점유', fmt_pp(r["prevDelta"])))"""
))
PATCHES.append((
"""        rows.append(('15일 점유 변화', f'{r["sd15"]:+g}p'))""",
"""        rows.append(('15일 점유 변화', fmt_pp(r["sd15"])))"""
))

# ── ⑥ verdict 축 (299·300·302행: 포맷 부재 = raw float 노출. D4-4 진원지)
PATCHES.append((
"""        axes.append(('15일 주가', f"{s15.get('priceChangePct','-')}%", pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율', f"{s15.get('shareDeltaPp','-')}p", ''))
    if s90:
        axes.append(('90일 주가', f"{long_pc}%", pcls(long_pc)))""",
"""        axes.append(('15일 주가', fmt_pct(s15.get('priceChangePct')), pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율', fmt_pp(s15.get('shareDeltaPp')), ''))   # F29-D4-FMT v1
    if s90:
        axes.append(('90일 주가', fmt_pct(long_pc), pcls(long_pc)))"""
))


def main():
    if not os.path.isfile(TARGET):
        sys.exit(f'ABORT: target not found: {TARGET}')
    src = open(TARGET, encoding='utf-8').read()

    if MARKER in src:
        sys.exit(f'ABORT: marker already present ({MARKER}) — 이미 적용됨. 중복 적용 방지.')

    # 앵커 count 게이트: 모든 앵커가 정확히 1회
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
    if ':+g' in out:
        sys.exit('ABORT: :+g 잔존 — 통일 실패')

    # 백업
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4fmt-{ts}')
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bdir, 'build_stock_pages.py'))
    print(f'backup: {bdir}/build_stock_pages.py')

    # 원자 쓰기 (py_compile 선통과 후 교체)
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
