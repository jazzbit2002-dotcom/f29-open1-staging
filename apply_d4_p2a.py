#!/usr/bin/env python3
# apply_d4_p2a.py — F29 D4 P2-A: D4-13(형태 표기 ▲▼─) + D4-12(PC 레이아웃·위계)
# 대상: /root/krx-moneyflow/build_stock_pages.py
# 방식: 리터럴 앵커 str.replace(count 게이트=정확히 1) + 백업 + py_compile + 원자 쓰기
#       + 마커 중복 방지 + 선행 마커 요구 + 사후 가드(금지 토큰 유입 0)
# 계약: 표시층만 변경. 판정 문구·계산값·색 토큰값·데이터 출처 변경 0건.

import os, re, sys, shutil, hashlib, py_compile, datetime, tempfile

TARGET   = '/root/krx-moneyflow/build_stock_pages.py'
EXPECT   = '922dfe41f5838fbbd3262cbc6c5c0b4c265456325ccd850df8898097620a7e7e'
BKROOT   = '/root/f29-backups'
NEW_MARK = 'F29-D4-ARROW v1'
NEW_MARK2 = 'F29-D4-PCGRID v1'
PRE_MARKS = ['F29-D4-FMT v1', 'F29-D4-SCEN v1', 'F29-D4-ROW v1', 'F29-D4-GOLINK v1']
FORBIDDEN = ['PRICE_EPS', 'AVG_N', 'nextDayReturn', "get('score'", 'nextDayRet']

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

# ---------------------------------------------------------------- 앵커 정의
PATCHES = []

# [1] 변화값 전용 포매터 신설 (기존 fmt_pct/fmt_pp 무변경 — 기준값·절대값·산문 계속 사용)
PATCHES.append(('P1-포매터 신설', '''def pcls(v):
    """가격색: 상승 빨강 / 하락 파랑 / 보합 회색 (판정색과 분리)"""''',
'''# F29-D4-ARROW v1
# ---- 변화값 전용 포매터: 형태(▲▼─)+부호+2자리. 색만으로 의미 전달 금지(접근성).
#      적용: 전일 대비 변화 · 기간 변화 · 점유율 증감 · 가격 증감
#      비적용(fmt_pct/fmt_pp 유지): 기준값 · 절대 수준 · 순위/개수 · 문장 내부 서술 수치
#      값 출처 불변 — 여기서 새 수치를 만들지 않는다(표시 형식만).
def fmt_delta_pct(v):
    """변화율 관측값: ▲ +0.00% / ▼ -0.00% / ─ 0.00%"""
    try: v = round(float(v), 2)
    except (TypeError, ValueError): return '-'
    if v > 0: return f'\\u25b2 +{v:.2f}%'
    if v < 0: return f'\\u25bc {v:.2f}%'
    return '\\u2500 0.00%'

def fmt_delta_pp(v):
    """점유율 변화 관측값: ▲ +0.00%p / ▼ -0.00%p / ─ 0.00%p"""
    try: v = round(float(v), 2)
    except (TypeError, ValueError): return '-'
    if v > 0: return f'\\u25b2 +{v:.2f}%p'
    if v < 0: return f'\\u25bc {v:.2f}%p'
    return '\\u2500 0.00%p'

def pcls(v):
    """가격색: 상승 빨강 / 하락 파랑 / 보합 회색 (판정색과 분리)"""'''))

# [2] ② 전일 대비 — 오늘값(관측)·차이에 형태 적용. 전일값(취소선 참조)은 평문 유지.
PATCHES.append(('P2-card_diff', '''            f = fmt_pp if c['field'] == 'share' else fmt_pct
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{f(c["prev"])}</s> → '
                      f'<b class="{cls}">{f(c["curr"])}</b>'
                      f'<em class="dd">({fmt_pp(c["delta"])})</em></span></li>')''',
'''            f = fmt_pp if c['field'] == 'share' else fmt_pct              # 전일값 = 취소선 참조(형태 미적용)
            g = fmt_delta_pp if c['field'] == 'share' else fmt_delta_pct   # 오늘값 = 관측 변화(형태 적용)  # F29-D4-ARROW v1
            cls = pcls(c['delta']) if c['field'] == 'price' else ''
            items += (f'<li><span class="dk">{w}일 {esc(FIELD_KO.get(c["field"],""))}</span>'
                      f'<span class="dv"><s>{f(c["prev"])}</s> → '
                      f'<b class="{cls}">{g(c["curr"])}</b>'
                      f'<em class="dd">({fmt_delta_pp(c["delta"])})</em></span></li>')'''))

# [3] ③ 시나리오 — 현재값만 형태 적용. 기준값(0 교차·20일 고점)은 평문 유지(계약: 기준값 화살표 금지).
PATCHES.append(('P3-scenario', '''        ('점유율 방향 전환', fmt_pp(0, plus=False),  fmt_pp(sd),  sd >= 0,    _imp(sd, p_sd, 0)),
        ('주가 방향 전환',   fmt_pct(0, plus=False), fmt_pct(pc), pc >= 0,    _imp(pc, p_pc, 0)),
        ('점유율 고점 회복', fmt_pp(peak),           fmt_pp(sd),  sd >= peak, _imp(sd, p_sd, peak)),''',
'''        # F29-D4-ARROW v1: 현재값 = 관측 변화(형태 적용) / 기준값 = 관측 기준(형태 미적용)
        ('점유율 방향 전환', fmt_pp(0, plus=False),  fmt_delta_pp(sd),  sd >= 0,    _imp(sd, p_sd, 0)),
        ('주가 방향 전환',   fmt_pct(0, plus=False), fmt_delta_pct(pc), pc >= 0,    _imp(pc, p_pc, 0)),
        ('점유율 고점 회복', fmt_pp(peak),           fmt_delta_pp(sd),  sd >= peak, _imp(sd, p_sd, peak)),'''))

# [4] ⑥ 판정 이력 — 구간 점유율 변화
PATCHES.append(('P4-history', '''        sd_txt = fmt_pp(sd) if isinstance(sd, (int, float)) else '—\'''',
'''        sd_txt = fmt_delta_pp(sd) if isinstance(sd, (int, float)) else '—'   # F29-D4-ARROW v1'''))

# [5] ① 오늘 판정 4축 — 전부 변화값
PATCHES.append(('P5-axes', '''    axes = []
    if s15:
        axes.append(('15일 주가 변화율', fmt_pct(s15.get('priceChangePct')), pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율 변화', fmt_pp(s15.get('shareDeltaPp')), ''))
    if s90:
        axes.append(('90일 주가 변화율', fmt_pct(long_pc), pcls(long_pc)))
        axes.append(('90일 거래대금 점유율 변화', fmt_pp(s90.get('shareDeltaPp')), ''))''',
'''    axes = []                                                    # F29-D4-ARROW v1: 4축 전부 변화값
    if s15:
        axes.append(('15일 주가 변화율', fmt_delta_pct(s15.get('priceChangePct')), pcls(s15.get('priceChangePct'))))
        axes.append(('15일 거래대금 점유율 변화', fmt_delta_pp(s15.get('shareDeltaPp')), ''))
    if s90:
        axes.append(('90일 주가 변화율', fmt_delta_pct(long_pc), pcls(long_pc)))
        axes.append(('90일 거래대금 점유율 변화', fmt_delta_pp(s90.get('shareDeltaPp')), ''))'''))

# [6] ⑤ 테마 내 실제 위치 — 변화 2행만. 절대 점유율(%)·순위(위/개)는 무변경.
PATCHES.append(('P6-theme5', '''    if isinstance(r.get('prevDelta'), (int, float)):
        rows.append(('전일 대비 점유', fmt_pp(r["prevDelta"])))
    if isinstance(r.get('sd15'), (int, float)):
        rows.append(('15일 점유 변화', fmt_pp(r["sd15"])))''',
'''    if isinstance(r.get('prevDelta'), (int, float)):                       # F29-D4-ARROW v1
        rows.append(('전일 대비 점유', fmt_delta_pp(r["prevDelta"])))
    if isinstance(r.get('sd15'), (int, float)):
        rows.append(('15일 점유 변화', fmt_delta_pp(r["sd15"])))'''))

# [7] 돈의 무게 표 — 주가 변화 / 점유율 변화
PATCHES.append(('P7-weight-table', '''                 f'<td class="num {pcls(_pc)}">{fmt_pct(_pc)}</td>'
                 f'<td class="num">{fmt_pp(s.get("shareDeltaPp"))}</td></tr>')''',
'''                 f'<td class="num {pcls(_pc)}">{fmt_delta_pct(_pc)}</td>'      # F29-D4-ARROW v1
                 f'<td class="num">{fmt_delta_pp(s.get("shareDeltaPp"))}</td></tr>')'''))

# ---------------- D4-12 ----------------
# [8] 폭 1240 → 1180
PATCHES.append(('P8-wrap-width', '''.wrap{{max-width:1240px;margin:0 auto;padding:16px 24px}}''',
'''.wrap{{max-width:1180px;margin:0 auto;padding:16px 24px}}   /* F29-D4-PCGRID v1 */'''))

# [9] PC 2단: 카드 높이 강제 확장 제거(align-items:start) + PC 전용 타이포·여백. 모바일 무회귀(≤1023 무변경).
PATCHES.append(('P9-pc-media', '''@media(min-width:1024px){{.grid{{grid-template-columns:1fr 1fr}}.grid .full{{grid-column:1/-1}}}}''',
'''/* F29-D4-PCGRID v1: align-items:start = 좌우 카드 높이 강제 정렬 제거(하단 공백 소멸). 타이포는 PC 전용 — 390px 무회귀 */
@media(min-width:1024px){{.grid{{grid-template-columns:1fr 1fr;align-items:start}}.grid .full{{grid-column:1/-1}}.card{{padding:18px}}.verdict{{padding:22px}}.vhead{{font-size:1.62rem}}.av{{font-size:1.12rem}}.rv{{font-size:1.02rem}}.dv{{font-size:1rem}}.card h2{{font-size:1.06rem}}}}'''))

# [10] ①③ 시각 위계: 판정=teal 구조 / 시나리오=gold 구조(조건·관찰 축). 색 토큰값 신설 0건 — 기존 --teal/--gold 재사용.
PATCHES.append(('P10-hierarchy', '''.verdict{{border-left:3px solid var(--teal)}}''',
'''/* F29-D4-PCGRID v1: ①=판정(teal 구조) / ③=조건·관찰(gold 구조). 새 색 토큰 없음 — 기존 --teal/--gold 재사용 */
.verdict{{border:1px solid #24344e;border-left:3px solid var(--teal);background:#131d2f;padding:18px}}
.scen{{border:1px solid #3a3524;border-left:3px solid var(--gold)}}
.scen h2{{color:var(--gold)}}'''))

# [11] 홀수 카드 → 마지막 카드만 명시 클래스 .full (nth-child 미사용)
PATCHES.append(('P11-grid-assembly', '''    card_d = card_diff(retro)
    card_s = card_scenario(retro, summ)
    card_h = card_history(retro)''',
'''    card_d = card_diff(retro)
    card_s = card_scenario(retro, summ)
    card_h = card_history(retro)

    # F29-D4-PCGRID v1: 2단 그리드에서 카드 수가 홀수면 마지막 카드에 .full(전체 폭).
    # nth-child 미사용 — 명시 클래스만. align-items:start이므로 전체 폭이어도 높이는 내용만큼만 커진다.
    _cards = [c for c in (card_d, card_s, card1, card_chart, card2, card9, card3, card_h, card4) if c]
    if len(_cards) % 2 == 1:
        _cards[-1] = _cards[-1].replace('<section class="card', '<section class="card full', 1)
    grid_html = ''.join(_cards)'''))

# [12] 템플릿 그리드 라인 교체
PATCHES.append(('P12-grid-line', '''<div class="grid">{card_d}{card_s}{card1}{card_chart}{card2}{card9}{card3}{card_h}{card4}</div>''',
'''<div class="grid">{grid_html}</div>'''))

# ---------------------------------------------------------------- 실행
def main():
    if not os.path.isfile(TARGET):
        sys.exit(f'FAIL: 대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()

    for m in (NEW_MARK, NEW_MARK2):           # 중복 적용 방지 (SHA 게이트보다 선행 — 재실행 시 오경보 방지)
        if m in src:
            sys.exit(f'SKIP: 이미 적용됨 [{m}] — 변경 없음')

    cur = sha(TARGET)
    if cur != EXPECT:
        sys.exit(f'FAIL: 기준 SHA 불일치\n  기대 {EXPECT}\n  실제 {cur}\n  → 다른 경로 변경 의심. 원인 규명 전 패치 금지.')

    for m in PRE_MARKS:                       # 선행 마커 요구
        if m not in src:
            sys.exit(f'FAIL: 선행 마커 부재 [{m}] — 대상 판본 불일치')

    fails = []                                # Phase 1: 전 앵커 검증(쓰기 없음)
    for name, old, new in PATCHES:
        n = src.count(old)
        if n != 1:
            fails.append(f'  [{name}] 앵커 {n}회 (기대 1)')
    if fails:
        sys.exit('FAIL: 앵커 게이트\n' + '\n'.join(fails))

    out = src                                 # Phase 2: 전건 통과 시에만 치환
    for name, old, new in PATCHES:
        out = out.replace(old, new, 1)

    for tok in FORBIDDEN:                     # 사후 가드: 금지 토큰 유입 0
        if out.count(tok) != src.count(tok):
            sys.exit(f'FAIL: 금지 토큰 유입 [{tok}]')

    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    bk = os.path.join(BKROOT, f'd4p2a-{ts}')
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(TARGET), suffix='.tmp')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)
    os.chmod(tmp, os.stat(TARGET).st_mode & 0o777)
    try:
        py_compile.compile(tmp, doraise=True)
    except Exception as e:
        os.unlink(tmp)
        sys.exit(f'FAIL: py_compile\n{e}')
    os.replace(tmp, TARGET)

    print('OK: D4 P2-A 적용 완료')
    print(f'  백업   {bk}/build_stock_pages.py')
    print(f'  before {EXPECT} ({len(src.encode())} B)')
    print(f'  after  {sha(TARGET)} ({len(out.encode())} B)')
    print(f'  패치   {len(PATCHES)}건 / 마커 {NEW_MARK} · {NEW_MARK2}')
    print(f'  롤백   cp {bk}/build_stock_pages.py {TARGET}')

if __name__ == '__main__':
    main()
