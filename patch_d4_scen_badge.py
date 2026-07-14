#!/usr/bin/env python3
# F29 D4 P1-2: D4-5(시나리오 조건 체크리스트) + D4-8(⑥ 소급 판정 배지)
# 마커: F29-D4-SCEN v1 / F29-D4-RETROBADGE v1
# 선행: F29-D4-ROW v1 (P1 1라운드 반영본 = 51,593 B / 8f4ce770…6a4f)
# 규칙: 리터럴 앵커 + count 게이트(정확히 1회) + 자동 백업 + py_compile + 원자 쓰기
#       + 마커 중복 방지 + 선행 마커 요구. 추정 패치 없음.
# 사용: python3 patch_d4_scen_badge.py [경로] [--dry-run]

import sys, os, shutil, py_compile, datetime, tempfile

TARGET      = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
TAG         = 'd4scen'

MARKERS_NEW   = ['F29-D4-SCEN v1', 'F29-D4-RETROBADGE v1']
MARKER_PREREQ = 'F29-D4-ROW v1'

# ------------------------------------------------------------ D4-5 card_scenario
A1_OLD = '''def card_scenario(retro, summ):
    """③ 다음 거래일 시나리오 — 관측값 기준 조건. 내부 스코어 비노출."""
    s15 = (summ or {}).get('15') or {}
    if not s15:
        return ''
    st = s15.get('flowState', '')
    pc = s15.get('priceChangePct', 0) or 0
    sd = s15.get('shareDeltaPp', 0) or 0
    hist = (retro or {}).get('history') or []
    # 최근 20일 점유율 최고치 = 관심 회복의 관측 기준
    peak = max([h.get('shareDeltaPp', 0) or 0 for h in hist], default=sd)
    rank = RETRO.STATE_RANK.get(st, 0)
    if rank > 0:
        keep = f'거래대금 점유율 변화가 {fmt_pp(sd)} 수준을 유지'
        turn = '점유율 증가폭이 줄고 주가가 하락으로 돌아서는 경우'
        kept = '현재 자금 유입 흐름 유지'
    elif rank < 0:
        keep = f'거래대금 점유율 변화가 최근 고점 {fmt_pp(peak)} 방향으로 회복'
        turn = f'점유율이 {fmt_pp(sd)} 아래로 더 밀리고 주가 약세가 이어지는 경우'
        kept = '현재 관심 이탈 흐름 지속'
    else:
        keep = '점유율과 주가가 함께 위로 방향을 잡는 경우'
        turn = '점유율과 주가가 함께 아래로 밀리는 경우'
        kept = '현재 방향성 부재 지속'
    return (f'<section class="card scen"><h2>다음 거래일 시나리오</h2>'
            f'<div class="sc up-c"><span class="sk">흐름 반전 조건</span>'
            f'<span class="sv">{esc(keep)}</span></div>'
            f'<div class="sc dn-c"><span class="sk">흐름 악화 조건</span>'
            f'<span class="sv">{esc(turn)}</span></div>'
            f'<div class="sc now"><span class="sk">변화 없을 경우</span>'
            f'<span class="sv">{esc(kept)}</span></div>'
            f'<p class="promise">다음 거래일 장 마감 후 F29가 자동으로 결과를 다시 판정합니다.</p>'
            f'</section>')'''

A1_NEW = '''# F29-D4-SCEN v1
# ---- D4-5: 시나리오 = 관측 조건 체크리스트. 기준값·현재값·충족 여부만 제시.
#      기준은 관측 가능한 값만: 0%p 교차 / 0% 교차 / 최근 20거래일 점유율 고점.
#      엔진 내부 임계값(가격 엡실론·평균 구간·스코어) 비노출. 익일 실등락 필드 미사용(예측 칼럼 부활 금지).
#      '개선 중' = 미충족이나 |기준-오늘| < |기준-전일| (방향 판정. 새 임계값 없음).
#      칩 색은 ok/imp/no 전용 — 상태색 SSOT(teal/gold/red)와 의미축이 다르므로 red를 쓰지 않는다.
SCEN_HEAD = {1: '유지 조건', 0: '전환 조건', -1: '회복 조건'}

def _scen_row(name, base_txt, cur_txt, met, improving):
    if met:
        chip, cls = '충족', 'ok'
    elif improving:
        chip, cls = '개선 중', 'imp'
    else:
        chip, cls = '미충족', 'no'
    return (f'<li class="cd"><span class="cdn">{esc(name)}</span>'
            f'<span class="cdv"><b>{esc(cur_txt)}</b>'
            f'<em class="cdb">기준 {esc(base_txt)}</em></span>'
            f'<span class="cdc {cls}">{chip}</span></li>')

def card_scenario(retro, summ):
    """③ 다음 거래일 시나리오 — 관측 조건 체크리스트. 내부 스코어 비노출.  # F29-D4-SCEN v1"""
    s15 = (summ or {}).get('15') or {}
    if not s15:
        return ''
    st    = s15.get('flowState', '')
    label = s15.get('flowLabel', '')          # 상태 문구는 SSOT(build_weight 라벨)에서만
    pc    = s15.get('priceChangePct', 0) or 0
    sd    = s15.get('shareDeltaPp', 0) or 0
    hist  = (retro or {}).get('history') or []
    peak  = max([h.get('shareDeltaPp', 0) or 0 for h in hist], default=sd)
    prev  = hist[-2] if len(hist) >= 2 else {}     # 전일의 동일 창(15일) 판정 완전값
    p_pc  = prev.get('priceChangePct')
    p_sd  = prev.get('shareDeltaPp')

    def _imp(cur, prv, base):
        """미충족 조건이 전일보다 기준에 가까워졌는가. 방향만 본다(임계값 없음)."""
        if not isinstance(prv, (int, float)):
            return False
        return abs(base - cur) < abs(base - prv)

    conds = [
        ('점유율 방향 전환', fmt_pp(0, plus=False),  fmt_pp(sd),  sd >= 0,    _imp(sd, p_sd, 0)),
        ('주가 방향 전환',   fmt_pct(0, plus=False), fmt_pct(pc), pc >= 0,    _imp(pc, p_pc, 0)),
        ('점유율 고점 회복', fmt_pp(peak),           fmt_pp(sd),  sd >= peak, _imp(sd, p_sd, peak)),
    ]
    met_n = sum(1 for c in conds if c[3])
    rank  = RETRO.STATE_RANK.get(st, 0)
    head  = SCEN_HEAD[1 if rank > 0 else (0 if rank == 0 else -1)]
    tone  = 'ok' if met_n == len(conds) else ('imp' if met_n else 'no')
    rows  = ''.join(_scen_row(*c) for c in conds)

    if rank > 0:
        worse = '점유율 증가폭이 줄고 주가가 하락으로 돌아서는 경우'
    elif rank < 0:
        worse = f'점유율이 {fmt_pp(sd)} 아래로 더 밀리고 주가 약세가 이어지는 경우'
    else:
        worse = '점유율과 주가가 함께 아래로 밀리는 경우'

    return (f'<section class="card scen"><h2>다음 거래일 시나리오</h2>'
            f'<p class="scnt"><b class="{tone}">{head} {len(conds)}개 중 {met_n}개 충족</b></p>'
            f'<ul class="cdlist">{rows}</ul>'
            f'<div class="sc dn-c"><span class="sk">흐름 악화 조건</span>'
            f'<span class="sv">{esc(worse)}</span></div>'
            f'<div class="sc now"><span class="sk">변화 없을 경우</span>'
            f'<span class="sv">현재 {esc(label)} 상태 지속</span></div>'
            f'<p class="hint">기준값은 관측 가능한 값입니다 — 0%p·0% 교차, 최근 20거래일 점유율 고점. '
            f'<b>조건을 충족해도 상태 판정이 반드시 바뀌지는 않습니다.</b> 상태는 별도 산식으로 결정됩니다. '
            f'개선 중 = 아직 미충족이지만 직전 거래일보다 기준에 가까워진 경우.</p>'
            f'<p class="promise">다음 거래일 장 마감 후 F29가 자동으로 결과를 다시 판정합니다.</p>'
            f'</section>')'''

# ------------------------------------------------------------- D4-5 CSS
A2_OLD = """.scen .sc{{display:flex;flex-direction:column;gap:3px;padding:10px 12px;border-radius:8px;margin-bottom:8px;background:#0d1523}}"""

A2_NEW = """/* F29-D4-SCEN v1: 조건 체크리스트. ok/imp/no = 충족축 전용 색(상태색 SSOT와 분리) */
.scnt{{margin:0 0 10px;font-size:1.02rem}}
.scnt .ok{{color:var(--teal)}}
.scnt .imp{{color:var(--gold)}}
.scnt .no{{color:var(--sub)}}
.cdlist{{list-style:none;margin:0 0 12px;padding:0}}
.cd{{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid #1f2937}}
.cd:last-child{{border-bottom:0}}
.cdn{{flex:1 1 auto;font-size:.9rem}}
.cdv{{display:flex;flex-direction:column;align-items:flex-end;gap:1px;font-family:"JetBrains Mono",monospace}}
.cdv b{{font-size:.95rem}}
.cdb{{font-style:normal;color:var(--sub);font-size:.74rem}}
.cdc{{flex:0 0 auto;min-width:52px;text-align:center;font-size:.76rem;font-weight:700;padding:3px 8px;border-radius:10px;background:#1f2937}}
.cdc.ok{{color:var(--teal)}}
.cdc.imp{{color:var(--gold)}}
.cdc.no{{color:var(--sub)}}
.rbadge{{display:inline-block;margin-left:6px;background:#1f2937;color:var(--gold);font-size:.7rem;font-weight:600;padding:2px 8px;border-radius:10px;cursor:help;vertical-align:middle}}
.scen .sc{{display:flex;flex-direction:column;gap:3px;padding:10px 12px;border-radius:8px;margin-bottom:8px;background:#0d1523}}"""

# --------------------------------------------------------- D4-8 소급 배지
A3_OLD = """    return (f'<section class="card"><h2>최근 판정 이력</h2>'
            f'<p class="tl-path">{path}</p>'"""

A3_NEW = """    return (f'<section class="card"><h2>최근 판정 이력'          # F29-D4-RETROBADGE v1
            f'<span class="rbadge" title="각 날짜까지의 데이터만으로 같은 기준을 소급 적용해 재계산한 결과입니다. '
            f'당시 실제로 게시된 문구가 아니며, 다음 거래일 등락 예측도 아닙니다.">데이터 기준 소급 판정</span></h2>'
            f'<p class="tl-path">{path}</p>'"""

PATCHES = [
    ('D4-5 card_scenario 재구성', A1_OLD, A1_NEW),
    ('D4-5 CSS(+ .rbadge)',       A2_OLD, A2_NEW),
    ('D4-8 ⑥ 소급 판정 배지',      A3_OLD, A3_NEW),
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry-run' in sys.argv
    target = args[0] if args else TARGET

    src = open(target, encoding='utf-8').read()
    print(f'target : {target}  ({len(src.encode()):,} B)')

    if MARKER_PREREQ not in src:
        sys.exit(f'STOP: 선행 마커 없음 — {MARKER_PREREQ}. P1 1라운드 미반영 파일.')
    for m in MARKERS_NEW:
        if m in src:
            sys.exit(f'STOP: 마커 이미 존재 — {m}. 재적용 금지.')

    for name, old, _ in PATCHES:
        n = src.count(old)
        if n != 1:
            sys.exit(f'STOP: 앵커 {n}회 — [{name}]. 정확히 1회여야 함.')
        print(f'  anchor OK (1) : {name}')

    out = src
    for name, old, new in PATCHES:
        out = out.replace(old, new, 1)

    # 사후 검사
    for m in MARKERS_NEW:
        if m not in out:
            sys.exit(f'STOP: 마커 미주입 — {m}')
    if '관심 이탈 흐름 지속' in out:
        sys.exit('STOP: 하드코딩 이탈 문구 잔존.')
    for banned in ('PRICE_EPS', 'AVG_N', 'nextDayReturn'):
        if banned in out:
            sys.exit(f'STOP: 비노출 대상이 빌더에 유입 — {banned}')

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
        print(f'DRY-RUN 종료. 결과 크기 {len(out.encode()):,} B '
              f'(기존 대비 {len(out.encode())-len(src.encode()):+,} B)')
        return

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'{TAG}-{ts}')
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(target, os.path.join(bdir, os.path.basename(target)))
    print(f'  backup : {bdir}')

    tmp = target + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)
    print(f'DONE. {len(out.encode()):,} B')


if __name__ == '__main__':
    main()
