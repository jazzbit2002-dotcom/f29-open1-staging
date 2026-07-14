#!/usr/bin/env python3
# apply_d3_hist.py — F29 D3 ⑥ 판정 이력 결함 수정
#   예측 프레임(익일 종가 칼럼) 제거 → 상태 전환 타임라인으로 재구성.
#   방식(CHROME_CONTRACT §8): 리터럴 앵커 str.replace, 앵커 count 게이트,
#   자동 백업, py_compile(AST) 검증, 원자적 쓰기, 내부 버전마커.
#   대상 파일 외 변경 0. 데이터/라우팅 무변경(L2).
import os, sys, shutil, py_compile, datetime

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
MARK   = 'F29-D3-HIST v1'

# ── 앵커 1: card_history 함수 전문 (현재 소스와 바이트 일치 필수) ──────────────
OLD_FUNC = '''def card_history(retro):
    """⑥ 최근 20거래일 판정 이력 (소급 산출). 배포 전 구간은 소급 표기."""
    hist = (retro or {}).get('history') or []
    if len(hist) < 3:
        return ''
    rows = ''
    for h in reversed(hist[-10:]):
        d8 = h.get('date', '')
        dk = f'{d8[4:6]}/{d8[6:8]}' if len(d8) == 8 else d8
        nd = h.get('nextDayReturn')
        ndc = pcls(nd) if nd is not None else 'flat'
        ndt = f'{nd:+.2f}%' if nd is not None else '—'
        rows += (f'<tr><td>{esc(dk)}</td><td>{esc(h.get("flowLabel",""))}</td>'
                 f'<td class="num {ndc}">{ndt}</td></tr>')
    return (f'<section class="card"><h2>최근 판정 이력</h2>'
            f'<table><thead><tr><th>날짜</th><th>그날의 F29 판정</th>'
            f'<th>다음 거래일 종가</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<p class="hint">데이터 기준 소급 판정 — 각 날짜까지의 데이터만으로 같은 기준을 적용해 재산출했습니다. '
            f'당시 실제로 게시된 문구가 아닙니다.</p></section>')'''

NEW_FUNC = '''def card_history(retro):
    """⑥ 최근 판정 흐름 — 상태 전환 타임라인 (소급 산출). %s
    익일 등락 예측 칼럼 제거: 15일 상태는 익일 종가 예측 계약이 아니므로,
    상태가 어떤 궤적을 거쳐 현재에 왔는지만 보여준다. 수치는 판정 엔진(judge_at)에서만."""
    hist = (retro or {}).get('history') or []
    if len(hist) < 3:
        return ''
    recent = hist[-10:]                       # 최근 10거래일 (오래된→최신)
    segs = []                                 # 연속 동일 상태 구간으로 압축
    for h in recent:
        st = h.get('flowState', '')
        if segs and segs[-1]['state'] == st:
            segs[-1]['end'] = h.get('date', '')
            segs[-1]['days'] += 1
            segs[-1]['share'] = h.get('shareDeltaPp')
        else:
            segs.append({'state': st, 'label': h.get('flowLabel', ''),
                         'start': h.get('date', ''), 'end': h.get('date', ''),
                         'days': 1, 'share': h.get('shareDeltaPp')})

    def _md(d8):
        d8 = str(d8)
        return f'{d8[4:6]}/{d8[6:8]}' if len(d8) == 8 else d8

    def _acc(state):
        r = RETRO.STATE_RANK.get(state, 0)
        return 'up-c' if r > 0 else ('dn-c' if r < 0 else 'nu-c')

    path = ' → '.join(esc(s['label']) for s in segs)   # 궤적 요약(오래된→최신)

    rows = ''
    for i, s in enumerate(reversed(segs)):                  # 타임라인: 최신 구간 먼저
        span = _md(s['start']) if s['start'] == s['end'] else f'{_md(s["start"])}~{_md(s["end"])}'
        sd = s.get('share')
        sd_txt = f'{sd:+g}p' if isinstance(sd, (int, float)) else '—'
        cur = ' cur' if i == 0 else ''
        rows += (f'<li class="tl {_acc(s["state"])}{cur}"><span class="tl-dot"></span>'
                 f'<div class="tl-body"><span class="tl-label">{esc(s["label"])}</span>'
                 f'<span class="tl-meta">{span} · {s["days"]}거래일 · 점유율 {sd_txt}</span>'
                 f'</div></li>')
    return (f'<section class="card"><h2>최근 판정 이력</h2>'
            f'<p class="tl-path">{path}</p>'
            f'<ul class="timeline">{rows}</ul>'
            f'<p class="hint">각 날짜까지의 데이터만으로 같은 기준을 소급 적용해, 상태가 어떻게 바뀌어 왔는지 보여줍니다. '
            f'다음 거래일 등락 예측이 아니며, 당시 실제 게시된 문구도 아닙니다. '
            f'점유율은 15일 판정 기준 거래대금 점유율 변화입니다.</p></section>')''' % ('# ' + MARK)

# ── 앵커 2: 타임라인 CSS 삽입 (page_html f-string 내부 → 중괄호 이중) ──────────
OLD_CSS = '.hint{{color:var(--sub);font-size:.8rem;margin:8px 0 0}}\n'
NEW_CSS = OLD_CSS + (
    '.timeline{{list-style:none;margin:0;padding:0}}\n'
    '.tl{{display:flex;gap:10px;padding:8px 0;align-items:flex-start}}\n'
    '.tl-dot{{flex:0 0 auto;width:9px;height:9px;border-radius:50%;margin-top:6px;background:var(--sub)}}\n'
    '.tl.up-c .tl-dot{{background:var(--teal)}}\n'
    '.tl.dn-c .tl-dot{{background:var(--up)}}\n'
    '.tl.cur .tl-dot{{width:11px;height:11px;margin-top:5px}}\n'
    '.tl-body{{display:flex;flex-direction:column;gap:1px}}\n'
    '.tl-label{{font-size:.95rem;font-weight:600}}\n'
    '.tl.cur .tl-label{{color:#fff}}\n'
    '.tl-meta{{color:var(--sub);font-size:.78rem;font-family:"JetBrains Mono",monospace}}\n'
    '.tl-path{{color:var(--sub);font-size:.82rem;margin:0 0 10px;line-height:1.5}}\n'
)

def die(msg):
    print(f'FAIL: {msg}')
    sys.exit(1)

def main():
    if not os.path.exists(TARGET):
        die(f'대상 없음 {TARGET}')
    src = open(TARGET, encoding='utf-8').read()

    if MARK in src:
        die(f'이미 적용됨(마커 {MARK} 존재) — 중복 적용 방지, 중단')

    # 앵커 count 게이트 (정확히 1회여야 함)
    n_func = src.count(OLD_FUNC)
    n_css  = src.count(OLD_CSS)
    print(f'anchor card_history: {n_func} / anchor .hint CSS: {n_css}')
    if n_func != 1:
        die(f'card_history 앵커 {n_func}회 (1 기대) — 소스 불일치, 중단')
    if n_css != 1:
        die(f'.hint CSS 앵커 {n_css}회 (1 기대) — 소스 불일치, 중단')

    # 백업
    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    bkroot = '/root/f29-backups'
    os.makedirs(bkroot, exist_ok=True)
    bk = os.path.join(bkroot, f'd3hist-{ts}')
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(TARGET, os.path.join(bk, 'build_stock_pages.py'))
    print(f'backup: {bk}/build_stock_pages.py')

    out = src.replace(OLD_FUNC, NEW_FUNC).replace(OLD_CSS, NEW_CSS)
    if out == src:
        die('치환 결과 무변경 — 중단')
    if MARK not in out:
        die('치환 후 마커 부재 — 중단')

    # 원자적 쓰기
    tmp = TARGET + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(out)

    # py_compile (AST/구문 검증) — 실패 시 원복
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp)
        die(f'py_compile 실패, 미적용: {e}')

    os.replace(tmp, TARGET)
    print('OK_APPLIED')
    print(f'bytes: {len(out.encode("utf-8"))}')
    print(f'marker present: {MARK in open(TARGET, encoding="utf-8").read()}')

if __name__ == '__main__':
    main()
