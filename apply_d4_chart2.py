#!/usr/bin/env python3
# apply_d4_chart2.py — D4-1 차트 범례·축·문장 + 툴팁 + 상태→색 3단 매핑 (F29-D4-CHART2 v1)
# 선행 필수: apply_d4_fmt.py (F29-D4-FMT v1) — fmt_pct/fmt_pp 사용
# 계약: 툴팁 = 날짜 + 가격지수 값 + 점유율 값만. 실제 종가·기간 등락률 없음(역산 금지).
#       해설 수치 = summary[w]에서만. flowLabel 라벨은 build_weight SSOT, 색만 표시층.
import os, shutil, sys, tempfile, datetime, py_compile

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_ROOT = '/root/f29-backups'
MARKER = 'F29-D4-CHART2 v1'
REQUIRE = 'F29-D4-FMT v1'

PATCHES = []

# ── ① 상태→표시색 3단 SSOT 주입
PATCHES.append((
"""FIELD_KO = {'share': '거래대금 점유율', 'price': '주가', 'state': '상태'}""",
"""FIELD_KO = {'share': '거래대금 점유율', 'price': '주가', 'state': '상태'}

# F29-D4-CHART2 v1
# ---- 상태 → 표시색 3단. 라벨 자체는 build_weight SSOT, 여기서 바꾸는 것은 색뿐이다.
#      teal = 유입/강세 · gold = 관찰/전환 · red = 이탈. (위축 ≠ 이탈: fade_down을 red로 칠하지 않는다)
STATE_TONE = {'up_concentration': 'up-c', 'attention_up': 'up-c', 'fade_up': 'up-c',
              'neutral': 'wt-c', 'fade_down': 'wt-c',
              'down_concentration': 'dn-c'}

def state_tone(state):
    return STATE_TONE.get(state or '', 'wt-c')"""
))

# ── ② card_history _acc: STATE_RANK<0 일괄 red → 3단 매핑
PATCHES.append((
"""    def _acc(state):
        r = RETRO.STATE_RANK.get(state, 0)
        return 'up-c' if r > 0 else ('dn-c' if r < 0 else 'nu-c')""",
"""    def _acc(state):
        return state_tone(state)          # F29-D4-CHART2 v1: 위축(gold) / 이탈(red) 분리"""
))

# ── ③ chart_dual_svg: 툴팁 밴드(날짜·가격지수·점유율만, 무JS <title>)
PATCHES.append((
"""    lines = f'<polyline fill="none" stroke="#3DD8B0" stroke-width="2.2" points="{cpoly}"/>'
    if spoly:
        lines += (f'<polyline fill="none" stroke="#f0c674" stroke-width="2.2" '
                  f'stroke-dasharray="4 3" points="{spoly}"/>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" role="img" '
            f'aria-label="가격 지수와 거래대금 점유율 {w}일 겹쳐보기">{grid}{lax}{rax}{lines}{xax}</svg>')""",
"""    lines = f'<polyline fill="none" stroke="#3DD8B0" stroke-width="2.2" points="{cpoly}"/>'
    if spoly:
        lines += (f'<polyline fill="none" stroke="#f0c674" stroke-width="2.2" '
                  f'stroke-dasharray="4 3" points="{spoly}"/>')
    # F29-D4-CHART2 v1 — 툴팁: 날짜 + 가격지수 + 점유율 값만.
    # 실제 종가는 페이지에 없고(rawClose 미임베드), 기간 등락률을 hover 지점에서 역산하면
    # 판정 엔진(3일 평균)과 갈라진다 → 계약상 둘 다 넣지 않는다.
    smap = dict(sp) if spoly else {}
    bw = pw / max(n - 1, 1)
    hover = ''.join(
        f'<rect x="{max(cx0, xi(i) - bw / 2):.1f}" y="{cy0:.1f}" '
        f'width="{bw:.1f}" height="{ph:.1f}" fill="transparent">'
        f'<title>{md(dd)} · 가격지수 {v:.2f}'
        + (f' · 점유율 {smap[dd]:.2f}%' if dd in smap else '')
        + '</title></rect>'
        for i, (dd, v) in enumerate(cp))
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" role="img" '
            f'aria-label="가격지수와 거래대금 점유율 {w}일 겹쳐보기">'
            f'{grid}{lax}{rax}{lines}{xax}{hover}</svg>')"""
))

# ── ④ chart_relation 전면 재작성: 매수/매도 서사 삭제(사실오류), 2자리·%p, 라벨은 배지로 분리
PATCHES.append((
"""def chart_relation(summ, w):
    \"\"\"선택 기간 관계 해설. 수치는 summary[w]에서만(차트 v값 역산 금지).\"\"\"
    s = (summ or {}).get(str(w)) or {}
    pc, sd, lb = s.get('priceChangePct'), s.get('shareDeltaPp'), s.get('flowLabel', '')
    if pc is None or sd is None:
        return ''
    EP, ES = 0.5, 0.1
    pu, pdn, su, sdn = pc > EP, pc < -EP, sd > ES, sd < -ES
    if pdn and sdn:
        head, tail = '두 선이 함께 내려갔습니다', '사는 쪽도 파는 쪽도 줄어든 구간입니다'
    elif pu and su:
        head, tail = '주가와 점유율이 함께 올랐습니다', '시장의 돈이 이 종목으로 몰린 구간입니다'
    elif pu and sdn:
        head, tail = '주가는 올랐지만 점유율은 줄었습니다', '상승폭 대비 시장 관심은 옅어진 구간입니다'
    elif pdn and su:
        head, tail = '주가는 내렸지만 점유율은 늘었습니다', '하락 속에도 거래대금이 이 종목에 몰린 구간입니다'
    elif su:
        head, tail = '주가 방향은 뚜렷하지 않고 점유율만 늘었습니다', '관심이 먼저 붙는 구간입니다'
    elif sdn:
        head, tail = '주가 방향은 뚜렷하지 않고 점유율은 줄었습니다', '관심이 먼저 식는 구간입니다'
    else:
        head, tail = '주가도 점유율도 큰 방향이 없습니다', '뚜렷한 쏠림이 없는 구간입니다'
    lbl = f' ({esc(lb)})' if lb else ''
    return f'{head}. 주가 {pc:+.1f}%, 점유율 {sd:+.1f}p — {tail}.{lbl}'""",
"""def chart_relation(summ, w):
    \"\"\"선택 기간 관계 해설. 수치는 summary[w]에서만(차트 v값 역산 금지).  # F29-D4-CHART2 v1
    금지: 점유율 하락을 '사는 쪽/파는 쪽 감소'로 해석. 모든 체결에는 매수·매도가 동시에 존재하므로
    거래대금 점유율은 매수/매도 세력이 아니라 '시장 관심도(거래대금 비중)'로만 서술한다.
    flowLabel은 문장에 괄호로 붙이지 않고 별도 배지로 분리(chart_dual_card).\"\"\"
    s = (summ or {}).get(str(w)) or {}
    pc, sd = s.get('priceChangePct'), s.get('shareDeltaPp')
    if pc is None or sd is None:
        return ''
    EP, ES = 0.5, 0.1
    pu, pdn, su, sdn = pc > EP, pc < -EP, sd > ES, sd < -ES
    if pdn and sdn:
        head, tail = '두 선이 함께 내려갔습니다', '가격과 시장 관심도가 함께 낮아진 구간입니다'
    elif pu and su:
        head, tail = '두 선이 함께 올라갔습니다', '시장 거래대금이 이 종목에 집중된 구간입니다'
    elif pu and sdn:
        head, tail = '가격은 올랐지만 점유율은 줄었습니다', '상승폭 대비 시장 관심도는 옅어진 구간입니다'
    elif pdn and su:
        head, tail = '가격은 내렸지만 점유율은 늘었습니다', '하락 속에도 거래대금이 이 종목에 집중된 구간입니다'
    elif su:
        head, tail = '가격 방향은 뚜렷하지 않고 점유율만 늘었습니다', '관심이 먼저 붙는 구간입니다'
    elif sdn:
        head, tail = '가격 방향은 뚜렷하지 않고 점유율은 줄었습니다', '관심이 먼저 식는 구간입니다'
    else:
        head, tail = '가격도 점유율도 큰 방향이 없습니다', '뚜렷한 쏠림이 없는 구간입니다'
    return f'{head}. 주가 {fmt_pct(pc)}, 점유율 {fmt_pp(sd)} — {tail}.'"""
))

# ── ⑤ chart_dual_card: 고정 범례 + 탭별 제목 + 라벨 배지 + 축 문구 정정
PATCHES.append((
"""    panes = ''
    for w in wins:
        svg = chart_dual_svg(close_s, share_s, w)
        if not svg:
            continue
        hid = '' if w == default else ' hidden'
        panes += (f'<div class="cpane" data-w="{w}"{hid}>{svg}'
                  f'<p class="crel">{chart_relation(summ, w)}</p></div>')
    if not panes:
        return ''
    return (f'<section class="card chart">'
            f'<h2>가격·점유율 겹쳐보기</h2>'
            f'<div class="ctabs">{tabs}</div>{panes}'
            f'<p class="caxis">왼쪽 축 = 가격 지수(기간 시작=100) · 오른쪽 축 = 거래대금 점유율(%)</p>'
            f'<p class="chint">점유율 = 이날 시장 전체 거래대금 중 이 종목이 차지한 비중. '
            f'차트는 흐름(추이)이고 판정 수치는 3일 평균 비교라 정확히 일치하지 않습니다.</p>'
            f'{_CHART_JS}</section>')""",
"""    panes = ''
    for w in wins:
        svg = chart_dual_svg(close_s, share_s, w)
        if not svg:
            continue
        hid = '' if w == default else ' hidden'
        s = (summ or {}).get(str(w)) or {}          # F29-D4-CHART2 v1
        lb = s.get('flowLabel', '')
        badge = (f'<p class="fbwrap"><span class="fbadge {state_tone(s.get("flowState", ""))}">'
                 f'{esc(lb)}</span></p>') if lb else ''
        panes += (f'<div class="cpane" data-w="{w}"{hid}>'
                  f'<p class="ctitle">{w}일 가격지수 · 거래대금 점유율</p>{svg}'
                  f'<p class="crel">{chart_relation(summ, w)}</p>{badge}</div>')
    if not panes:
        return ''
    # 고정 범례: 색 + 선형(실선/점선) 병기 → 색만으로 의미를 전달하지 않는다.
    leg = ('<div class="cleg">'
           '<span class="cl"><i class="cln p"></i>가격지수 <em>(기간 시작 = 100)</em></span>'
           '<span class="cl"><i class="cln s"></i>시장 거래대금 점유율 <em>(%)</em></span>'
           '</div>')
    return (f'<section class="card chart">'
            f'<h2>가격·점유율 겹쳐보기</h2>'
            f'{leg}<div class="ctabs">{tabs}</div>{panes}'
            f'<p class="caxis">왼쪽 축 = 가격지수(기간 시작을 100으로 맞춘 지수 · 종가가 아닙니다) · '
            f'오른쪽 축 = 거래대금 점유율(%)</p>'
            f'<p class="chint">거래대금 점유율 = 이날 시장 전체 거래대금 중 이 종목이 차지한 비중(시장 관심도). '
            f'차트는 흐름(추이)이고 판정 수치는 3일 평균 비교라 정확히 일치하지 않습니다. '
            f'차트 위에 마우스를 올리면 그날의 가격지수·점유율 값이 표시됩니다.</p>'
            f'{_CHART_JS}</section>')"""
))

# ── ⑥ CSS: 범례·탭 제목·배지·타임라인 gold 톤
PATCHES.append((
""".cpane svg{{display:block;width:100%;height:auto}}
.crel{{font-size:.88rem;line-height:1.5;margin:8px 0 0}}""",
""".cpane svg{{display:block;width:100%;height:auto}}
.cleg{{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 10px;font-size:.8rem;color:var(--tx)}}
.cl{{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}}
.cl em{{color:var(--sub);font-style:normal;font-size:.74rem}}
.cln{{display:inline-block;width:22px;height:0;border-top:2.2px solid var(--sub)}}
.cln.p{{border-color:var(--teal)}}
.cln.s{{border-top-style:dashed;border-color:var(--gold)}}
.ctitle{{margin:0 0 6px;color:var(--sub);font-size:.82rem}}
.fbwrap{{margin:8px 0 0}}
.fbadge{{display:inline-block;background:#1f2937;font-size:.78rem;padding:2px 9px;border-radius:10px;font-weight:600}}
.fbadge.up-c{{color:var(--teal)}}
.fbadge.wt-c{{color:var(--gold)}}
.fbadge.dn-c{{color:var(--up)}}
.crel{{font-size:.88rem;line-height:1.5;margin:8px 0 0}}"""
))
PATCHES.append((
""".tl.up-c .tl-dot{{background:var(--teal)}}
.tl.dn-c .tl-dot{{background:var(--up)}}""",
""".tl.up-c .tl-dot{{background:var(--teal)}}
.tl.wt-c .tl-dot{{background:var(--gold)}}
.tl.dn-c .tl-dot{{background:var(--up)}}"""
))

# ── ⑦ 모바일: 탭 터치영역 ≥44px, 범례 접힘 (D4-15 게이트 선반영)
PATCHES.append((
""".ctab{{padding:4px 9px}}.crel{{font-size:.85rem}}""",
""".ctab{{padding:11px 14px;min-height:44px}}.cleg{{gap:8px 14px;font-size:.76rem}}.crel{{font-size:.85rem}}"""
))


def main():
    if not os.path.isfile(TARGET):
        sys.exit(f'ABORT: target not found: {TARGET}')
    src = open(TARGET, encoding='utf-8').read()

    if REQUIRE not in src:
        sys.exit(f'ABORT: 선행 패치 미적용 ({REQUIRE}) — apply_d4_fmt.py 를 먼저 실행하세요.')
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
    if '사는 쪽도 파는 쪽도' in out:
        sys.exit('ABORT: 사실오류 문장 잔존')
    if 'nu-c' in out:
        sys.exit('ABORT: 구 색분기(nu-c) 잔존')

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_ROOT, f'd4chart2-{ts}')
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
