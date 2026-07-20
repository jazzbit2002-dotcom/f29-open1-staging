# F29-US-P0 v1
#!/usr/bin/env python3
# build_us_stock_pages.py — F29 미국 종목 상태판정 페이지 공장 (Phase 0)
# 입력: /root/moneyflow/positions_output.json (.positions[], read-only)
# 출력: /var/www/f29-stock-us/{SLUG}/index.html + us-slug-map.json + sitemap-us.xml
# 원칙(Phase 0, Sky 비준 2026-07-16):
#   - 상태판정 중심. 종목별 시계열 차트 없음 / 가격·거래금액 카드 없음.
#   - 자금 비중을 RS·테마로 대체·추정하지 않음. 없는 데이터는 렌더하지 않는다.
#   - KR 6카드 내용 동형 복제가 아니라 레이아웃·형태표기·색·반응형 골격만 재사용.
#   - lifecycle/axis 라벨 = 미국장 엔진 SSOT 원문. 색은 표시층 매핑(라벨 불변).
#   - 컴플라이언스: 매수/매도/보유 행동 문구 0, confidence 등급 직접 노출 금지.
#   - build_stock_pages.py(KR, fc7a6db5…)는 수정하지 않는다 — 유틸 자기완결 복제.

import json, os, re, html, datetime

os.umask(0o022)

SRC      = '/root/moneyflow/positions_output.json'
OUT_DIR  = '/var/www/f29-stock-us'
SLUG_MAP = '/var/www/f29-stock-us/us-slug-map.json'
SITEMAP  = '/var/www/f29-stock-us/sitemap-us.xml'
SITE     = 'https://f29.io'

# ── 재사용 유틸 (bsp_canon_ref.py fc7a6db5… 에서 순수함수만 복제, 전역 의존 0) ──
def esc(s): return html.escape(str(s), quote=True)

def fmt_pct(v, plus=True):
    try: v = float(v)
    except (TypeError, ValueError): return '-'
    return (f'{v:+.2f}%' if plus else f'{v:.2f}%')

def fmt_delta_pct(v):
    """관측값 형태표기: ▲ +0.00% / ▼ -0.00% / ─ 0.00% (색만으로 의미 전달 금지)"""
    try: v = round(float(v), 2)
    except (TypeError, ValueError): return '-'
    if v > 0: return f'\u25b2 +{v:.2f}%'
    if v < 0: return f'\u25bc {v:.2f}%'
    return '\u2500 0.00%'

def load_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except Exception:
        return default

def write_atomic(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)

# ── US 색 매핑 (lifecycle 9상태 → teal/gold/red 표시층. 라벨 SSOT는 엔진) ──
#   teal = 유입·강세 / gold = 관찰·전환·중립 / red = 이탈
#   관심도성숙=gold (주도 다음·둔화 전 = 전환 초입). 미국장 검토 통보 대상.
US_STATE_TONE = {
    '신규부상': 'up-c', '강화': 'up-c', '주도': 'up-c',
    '관심도성숙': 'wt-c', '관찰시작': 'wt-c', '둔화관찰': 'wt-c',
    '이탈관찰': 'wt-c', '중립': 'wt-c',
    '이탈': 'dn-c',
}
def us_tone(state): return US_STATE_TONE.get(state or '', 'wt-c')

# axis_state 표시(라벨 원문 그대로)
AXIS_SET = {'혼조', '양축우위', '양축열위', '중립'}

# RS 신호 방향 한글(원문 유지 축) — signals 값 up/down/neutral/null
SIG_KO = {'up': '우위', 'down': '열위', 'neutral': '중립'}
# 신호 키 한글 라벨 (화면 노출 — 영문 키 제거)
SIGKEY_KO = {'sector_20': '섹터 20일', 'market_20': '시장 20일',
             'sector_60': '섹터 60일', 'market_60': '시장 60일'}


def slugify(ticker):
    """raw ticker(대문자 보존) → URL slug. '.'→'-'. 대문자화."""
    return str(ticker).replace('.', '-').upper()


def is_partial(rec):
    """부분 데이터 판정: status≠normal 또는 RS 60창 결측 → noindex 대상."""
    return rec.get('status') != 'normal' or rec.get('RS_sector_60') is None or rec.get('RS_market_60') is None


def is_excluded(rec):
    """진짜 판정제외(방어): lifecycle 또는 axis 부재. 현 유니버스 0건, 방어 코드."""
    return not rec.get('lifecycle') or not rec.get('axis_state')


# ── 카드 렌더 ──
def card_verdict(rec):
    """① 오늘 판정: lifecycle + axis_state + status. 라벨 엔진 SSOT."""
    lc = rec.get('lifecycle', '')
    ax = rec.get('axis_state', '')
    tone = us_tone(lc)
    lcd = rec.get('lifecycle_detail', '')
    axd = rec.get('axis_detail', '')
    return (f'<section class="card verdict {tone}">'
            f'<h2>오늘 판정</h2>'
            f'<p class="vhead">{esc(lc)}<span class="vaxis"> · {esc(ax)}</span></p>'
            f'<p class="vsub">{esc(lcd)}</p>'
            f'<p class="vsub">{esc(axd)}</p>'
            f'<p class="hint">상대강도 기반 상태 분류입니다. 거래 지시가 아닌 위치 참고 지표입니다.</p>'
            f'</section>')


def resolve_lifecycle_transition(rec, hist, updated):
    """P05-6/② 공용 헬퍼(단일 SSOT): lifecycle final 전환 해석. card_diff와 상단 요약행이 공유(로직 복제 금지).
    규칙(스펙 §2): history 마지막 date==updated → 마지막 두 final 비교([-2]→[-1]);
    마지막 date<updated → 마지막 final vs 현재 lifecycle. 미래 date는 방어적 None(main HARD_FAIL 선차단). 유효<2 → None.
    반환: None 또는 {prev_date, prev_final, cur_date, cur_final, changed}. candidate·axis·RS 미사용."""
    if not isinstance(hist, list) or len(hist) < 2:
        return None
    last = hist[-1]
    last_date = last.get('date', '')
    last_final = last.get('final')
    if not last_final or last_date > updated:
        return None
    if last_date == updated:
        prev_date = hist[-2].get('date', '')
        prev_final = hist[-2].get('final')
        cur_date = last_date
        cur_final = last_final
    else:
        prev_date = last_date
        prev_final = last_final
        cur_date = updated
        cur_final = rec.get('lifecycle')
    if not prev_final or not cur_final:
        return None
    return {'prev_date': prev_date, 'prev_final': prev_final,
            'cur_date': cur_date, 'cur_final': cur_final,
            'changed': prev_final != cur_final}


def card_diff(rec, hist, updated):
    """② 직전 판정 대비: resolve_lifecycle_transition() 공유(로직 복제 금지). axis 추론 금지, candidate 미사용."""
    tr = resolve_lifecycle_transition(rec, hist, updated)
    if tr is None:
        return ''  # 이력 부족(SPCX 등) → 숨김(빈 카드 금지)
    prev_date, prev_final = tr['prev_date'], tr['prev_final']
    cur_date, cur_final = tr['cur_date'], tr['cur_final']
    if not tr['changed']:
        return (f'<section class="card"><h2>직전 판정 대비</h2>'
                f'<p class="hint">직전 판정({esc(prev_date)} · {esc(prev_final)})과 '
                f'현재 판정에 변화가 없습니다.</p></section>')
    return (f'<section class="card"><h2>직전 판정 대비</h2>'
            f'<ul class="difflist"><li>'
            f'<span class="dk">상태</span>'
            f'<span class="dv"><s>{esc(prev_final)}</s> &rarr; <b>{esc(cur_final)}</b></span>'
            f'</li></ul>'
            f'<p class="hint">직전 판정일({esc(prev_date)}) 대비 현재 기준일({esc(cur_date)})의 '
            f'상태 전환입니다. 생애주기 판정만 비교하며, 축(axis) 전환은 이력이 없어 표시하지 않습니다.</p>'
            f'</section>')


def card_rs(rec):
    """③ 기간 상대강도: RS_sector/market 20·60. 60 결측 시 보류 명시. 시계열 차트 금지.
    P05-2: 표→0 기준선 가로 막대. 방향=RS 숫자 부호, 색·라벨=signals(부호로 재판정 금지). 카드별 축 스케일."""
    import math
    def _rs(v):
        if v is None: return None
        try: return round(float(v), 2)
        except (TypeError, ValueError): return None
    r_s20, r_m20 = _rs(rec.get('RS_sector_20')), _rs(rec.get('RS_market_20'))
    r_s60, r_m60 = _rs(rec.get('RS_sector_60')), _rs(rec.get('RS_market_60'))
    sig = rec.get('signals', {}) or {}
    _vals = [v for v in (r_s20, r_m20, r_s60, r_m60) if v is not None]
    _maxabs = max((abs(v) for v in _vals), default=0.0)
    scale = max(10.0, math.ceil(_maxabs / 10.0) * 10.0)
    TONE = {'up': 'up', 'down': 'dn', 'neutral': 'flat'}

    def _bar(label, val, sigkey):
        s = sig.get(sigkey)
        if val is None:
            return (f'<div class="rsrow"><span class="rslab">{esc(label)}</span>'
                    f'<span class="rstrack"><i class="rzero"></i></span>'
                    f'<span class="rsval">-</span>'
                    f'<span class="rsdir hold">이력 부족 · 보류</span></div>')
        tone = TONE.get(s, 'flat') if s else 'flat'
        sk = SIG_KO.get(s, '') if s else ''
        w = abs(val) / scale * 50.0
        if val >= 0:
            fill = f'<i class="rsfill {tone}" style="left:50%;width:{w:.2f}%"></i>'
        else:
            fill = f'<i class="rsfill {tone}" style="left:{(50.0 - w):.2f}%;width:{w:.2f}%"></i>'
        return (f'<div class="rsrow"><span class="rslab">{esc(label)}</span>'
                f'<span class="rstrack"><i class="rzero"></i>{fill}</span>'
                f'<span class="rsval">{fmt_pct(val)}</span>'
                f'<span class="rsdir {tone}">{esc(sk)}</span></div>')

    bars = (_bar('섹터 대비 · 20거래일', r_s20, 'sector_20')
            + _bar('시장 대비 · 20거래일', r_m20, 'market_20')
            + _bar('섹터 대비 · 60거래일', r_s60, 'sector_60')
            + _bar('시장 대비 · 60거래일', r_m60, 'market_60'))
    partial_note = ''
    if r_s60 is None or r_m60 is None:
        partial_note = ('<p class="hint">상장 후 데이터가 짧아 60거래일 상대강도는 아직 보류 중입니다. '
                        '20거래일 값만 참고하세요.</p>')
    return (f'<section class="card scen"><h2>기간 상대강도</h2>'
            f'<div class="rsprofile">{bars}</div>'
            f'<p class="hint">막대 길이는 이 종목의 4개 상대강도 값을 같은 축에서 비교한 것입니다. '
            f'종목 간 비교는 숫자를 기준으로 확인하세요. 벤치마크 대비 상대강도이며 가격이나 자금 흐름 수치가 아닙니다.</p>'
            f'{partial_note}</section>')


def card_theme_sync(rec, all_recs):
    """④ 테마 동조 (P05-4): 같은 theme_group 유효 종목(self 포함) 중 동일 lifecycle 수. peer 목록은 self 제외."""
    tg = rec.get('theme_group')
    lc = rec.get('lifecycle')
    if not tg or not lc:
        return ''  # 결측 시 숨김
    members = [r for r in all_recs if r.get('theme_group') == tg and r.get('lifecycle')]
    peers = [r for r in members if r.get('ticker') != rec.get('ticker')]
    if not peers:
        return ('<section class="card"><h2>테마 동조</h2>'
                f'<p>소속 테마 <b>{esc(tg)}</b>에서 비교 가능한 다른 종목이 없습니다.</p></section>')
    total = len(members)
    n_same = sum(1 for r in members if r.get('lifecycle') == lc)
    if n_same >= total:  sync_txt = '광범위'
    elif n_same <= 1:    sync_txt = '단독'
    else:                sync_txt = '부분 확산'
    listed = ''.join(
        f'<li><a class="prow" data-ev="us_peer_click" href="/stock/us/{slugify(r["ticker"])}/">'
        f'<span class="pn">{esc(r.get("name_ko") or r["ticker"])}</span>'
        f'<span class="pl">{esc(r.get("lifecycle",""))}</span>'
        f'<span class="pgo" aria-hidden="true">&rsaquo;</span></a></li>'
        for r in peers)
    return (f'<section class="card"><h2>테마 동조</h2>'
            f'<p class="synchead">소속 테마 <b>{esc(tg)}</b> · 유효 {total}종 중 '
            f'같은 상태(<b>{esc(lc)}</b>) <b>{n_same}</b>종 <span class="synctag">{esc(sync_txt)}</span></p>'
            f'<ul class="peers">{listed}</ul>'
            f'<p class="hint">소속 테마의 유효 분류 종목(자기 포함) 중 동일 상태 수입니다. 방향을 전망하지 않습니다.</p>'
            f'</section>')


def card_bench(rec):
    """⑤ 벤치마크 참조: primary/secondary ETF. confidence 등급 직접 노출 금지."""
    pri = rec.get('primary', '')
    sec = rec.get('secondary', '')
    if not pri and not sec:
        return ''
    conf = rec.get('confidence', '')
    note = rec.get('confidence_note', '') or ''
    # confidence 등급(high/low) 직접 노출 금지 → 안정도 문구로 치환, note 있으면 정면 표기
    conf_line = ''
    if note:
        conf_line = f'<p class="confnote">판정 참고: {esc(note)}</p>'
    elif conf == 'low':
        conf_line = '<p class="confnote">제한적 데이터 기반 판정입니다.</p>'
    bench = ' · '.join(x for x in (pri, sec) if x)
    return (f'<section class="card"><h2>비교 기준</h2>'
            f'<p>상대강도 비교 벤치마크: <b>{esc(bench)}</b></p>'
            f'{conf_line}'
            f'</section>')


def card_meta(rec, updated):
    """⑥ 판정 근거·데이터 상태: signals 2×2 매트릭스 + status·n_data·updated. 행동 문구 금지, stale 숨김 금지.
    P05-5: 신호 한 줄 나열 → sector/market × 20/60 2×2(값=signals 직접, up=우위/neutral=중립/down=열위/null=축적 중)."""
    sig = rec.get('signals', {}) or {}
    n = rec.get('n_data', '-')
    status = rec.get('status', '-')
    status_ko = {'normal': '정상', 'short_history': '이력 짧음', 'extreme_initial_move': '초기 변동 과대'}.get(status, status)
    TONE = {'up': 'up', 'down': 'dn', 'neutral': 'flat'}

    def _cell(key):
        v = sig.get(key)
        if not v:
            return '<span class="sc hold">축적 중</span>'
        return f'<span class="sc {TONE.get(v, "flat")}">{esc(SIG_KO.get(v, v))}</span>'

    matrix = (f'<div class="sigmx">'
              f'<span class="sh"></span><span class="sh">20거래일</span><span class="sh">60거래일</span>'
              f'<span class="sr">섹터</span>{_cell("sector_20")}{_cell("sector_60")}'
              f'<span class="sr">시장</span>{_cell("market_20")}{_cell("market_60")}'
              f'</div>')
    return (f'<section class="card meta"><h2>판정 근거 · 데이터 상태</h2>'
            f'{matrix}'
            f'<ul class="metalist">'
            f'<li><span class="mk">데이터 상태</span><span class="mv">{esc(status_ko)}</span></li>'
            f'<li><span class="mk">사용 데이터 수</span><span class="mv">{esc(n)}개</span></li>'
            f'<li><span class="mk">데이터 기준일</span><span class="mv">{esc(updated)}</span></li>'
            f'</ul>'
            f'<p class="hint">신호는 섹터·시장 대비 20·60거래일 상대강도 방향입니다. '
            f'미국 시장 종가(ET) 기준 데이터입니다. 거래 지시가 아닌 상태 참고 자료입니다.</p>'
            f'</section>')


CSS = '''*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0A0E17;--card:#111827;--tx:#e5e7eb;--sub:#9ca3af;--teal:#3DD8B0;--gold:#f0c674;--up:#F45B69;--down:#4C8DFF;--flat:#9ca3af}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',sans-serif;line-height:1.5;font-size:15px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
@media(min-width:1024px){.wrap{padding:28px 24px 80px}}
h1{font-size:1.5rem;margin-bottom:4px}
.tick{color:var(--sub);font-size:.9rem;margin-bottom:18px}
.subdate{color:var(--sub);font-size:.82rem;margin-top:-14px;margin-bottom:18px}
.line1{font-size:1.02rem;margin-bottom:18px;padding:12px 14px;background:var(--card);border-left:3px solid var(--teal);border-radius:8px}
.grid{display:grid;gap:14px}
@media(min-width:1024px){.grid{grid-template-columns:1fr 1fr}.grid .full{grid-column:1/-1}}
.card{background:var(--card);border:1px solid #1f2937;border-radius:10px;padding:16px}
.card h2{font-size:1.02rem;margin-bottom:10px;color:var(--teal)}
.verdict{border-left:3px solid var(--teal)}
.verdict.up-c{border-left-color:var(--teal)}.verdict.up-c h2{color:var(--teal)}
.verdict.wt-c{border-left-color:var(--gold)}.verdict.wt-c h2{color:var(--gold)}
.verdict.dn-c{border-left-color:var(--up)}.verdict.dn-c h2{color:var(--up)}
.vhead{font-size:1.4rem;font-weight:700;margin-bottom:8px}
.vaxis{font-size:1rem;font-weight:500;color:var(--sub)}
.vsub{color:var(--tx);margin-bottom:4px;font-size:.94rem}
.scen{border-left:3px solid var(--gold)}.scen h2{color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid #1f2937}
th{color:var(--sub);font-weight:600}
td.num{font-variant-numeric:tabular-nums}
td.hold{color:var(--gold);font-size:.84rem}
.hint{color:var(--sub);font-size:.82rem;margin-top:10px}
.difflist,.peers,.metalist{list-style:none}
.difflist li,.metalist li{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1f2937;gap:10px}
.dk,.mk{color:var(--sub)}.dv s{color:var(--sub)}
.synchead{margin-bottom:8px}.synctag{background:#1f2937;color:var(--gold);font-size:.75rem;padding:2px 8px;border-radius:10px;margin-left:4px}
.peers li{border-bottom:1px solid #1f2937}
.prow{display:flex;align-items:center;gap:10px;padding:9px 4px;text-decoration:none;color:var(--tx)}
.prow:hover{background:#0d1420}
.pn{flex:1}.pl{color:var(--sub);font-size:.85rem}.pgo{color:var(--sub)}
.confnote{color:var(--gold);font-size:.86rem;margin-top:6px}
.mv{font-variant-numeric:tabular-nums;text-align:right}
.rsprofile{display:flex;flex-direction:column;gap:9px;margin:2px 0 4px}
.rsrow{display:grid;grid-template-columns:118px 1fr 66px 42px;align-items:center;gap:8px;font-size:.86rem}
.rslab{color:var(--sub);word-break:keep-all;line-height:1.2}
.rstrack{position:relative;height:10px}
.rzero{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#374151}
.rsfill{position:absolute;top:3px;height:4px;border-radius:2px}
.rsfill.up{background:var(--teal)}.rsfill.dn{background:var(--up)}.rsfill.flat{background:var(--flat)}
.rsval{font-variant-numeric:tabular-nums;text-align:right}
.rsdir{text-align:right;font-size:.82rem}
.rsdir.up{color:var(--teal)}.rsdir.dn{color:var(--up)}.rsdir.flat{color:var(--sub)}
.rsdir.hold{color:var(--gold);grid-column:3/5;font-size:.78rem}
.sigmx{display:grid;grid-template-columns:auto 1fr 1fr;gap:6px 8px;margin:2px 0 12px;align-items:center;font-size:.88rem}
.sigmx .sh{color:var(--sub);text-align:center;font-size:.76rem}
.sigmx .sr{color:var(--sub)}
.sc{text-align:center;padding:5px 4px;font-weight:600}
.sc.up{color:var(--teal)}.sc.dn{color:var(--up)}.sc.flat{color:var(--sub)}.sc.hold{color:var(--gold);font-weight:400;font-size:.82rem}
@media(max-width:420px){.rsrow{grid-template-columns:104px 1fr 52px 34px;gap:5px;font-size:.8rem}.sigmx{font-size:.82rem}}
.tl{list-style:none}
.tlrow{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #1f2937}
.tlrow:last-child{border-bottom:0}
.tldot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:var(--flat)}
.tldot.up-c{background:var(--teal)}.tldot.wt-c{background:var(--gold)}.tldot.dn-c{background:var(--up)}
.tldate{color:var(--sub);font-variant-numeric:tabular-nums;font-size:.84rem;flex:0 0 auto}
.tlstate{font-weight:600}
.tlbadge{margin-left:auto;background:#1f2937;color:var(--gold);font-size:.72rem;padding:2px 8px;border-radius:10px}
.tlaccum{color:var(--gold);padding:8px 0;font-size:.95rem}
.topchange{color:var(--sub);font-size:.86rem;margin:-6px 0 18px;white-space:normal;word-break:keep-all}
.pat{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:2px 0 10px}
.patname{font-size:1.15rem;font-weight:700;color:var(--tx)}
.patscore{font-size:1.05rem;font-weight:700;color:var(--gold);white-space:nowrap}
.patmax{font-size:.8rem;font-weight:400;color:var(--sub);margin-left:1px}
.patlink{margin-top:10px}
.patlink a{color:var(--teal);text-decoration:none;font-size:.9rem}
.patlink a:hover{text-decoration:underline}
'''


def load_pattern_judgments():
    """US-P05-PATTERN: Pattern Lab 판정 최신 가용분 로드 -> {TICKER: row}.
    빌더(07:00 UTC)가 pattern cron(07:30/07:40)보다 먼저 돌아 당일 파일이 없을 수 있다.
    가장 최근 존재 파일을 쓰고, 화면에 그 기준일을 명시한다(보정/추정 금지)."""
    import glob
    d = '/root/f29-pattern-lab/history/pattern_judgments'
    try:
        files = sorted(glob.glob(os.path.join(d, '*.jsonl')))
    except Exception:
        return {}
    if not files:
        return {}
    out = {}
    try:
        with open(files[-1], encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                t = r.get('ticker')
                if t and isinstance(r.get('top1'), dict):
                    out[t] = r
    except Exception:
        return {}
    return out


def card_pattern(rec, pj, updated):
    """차트 형태 (US-P05-PATTERN). Pattern Lab top1 표시, 미보유 -> None(카드 생략)."""
    r = (pj or {}).get(rec.get('ticker'))
    if not r:
        return None
    t1 = r.get('top1') or {}
    title = t1.get('pattern_title')
    score = t1.get('score')
    if not title or score is None:
        return None
    base = r.get('data_last_date') or r.get('date') or ''
    bars = r.get('bars', 60)
    note = ''
    if base and updated and base != updated:
        note = (f'<p class="hint">형태 비교 기준일 {esc(base)} — 이 페이지 기준일'
                f'({esc(updated)})과 다릅니다.</p>')
    return (f'<section class="card"><h2>차트 형태</h2>'
            f'<p class="pat"><span class="patname">{esc(title)}</span>'
            f'<span class="patscore">닮음 {esc(score)}<span class="patmax">/100</span></span></p>'
            f'<p class="hint">최근 {esc(bars)}거래일 종가 흐름을 학습용 형태와 비교한 닮음 '
            f'점수입니다. 상승·하락 확률이 아니며 방향을 전망하지 않습니다.</p>'
            f'{note}'
            f'<p class="patlink"><a href="/lab/match.html?ticker={esc(rec["ticker"])}">차트분석 연구소에서 직접 비교 &rsaquo;</a></p>'
            f'</section>')


def card_history(rec, hist, updated):
    """판정 이력 타임라인 (P05-1): positions_history final 전환점 + candidate≠final 강제포함(최근 창).
    이력<2 → '축적 중 · N일째'. candidate 값 병렬노출 금지(배지만). 방향예측·성과해석 금지. 라벨=엔진 final SSOT."""
    seq = [e for e in (hist or []) if e.get('date') and e.get('final')]
    seq.sort(key=lambda e: e['date'])
    if len(seq) < 2:
        return (f'<section class="card"><h2>최근 판정 이력</h2>'
                f'<p class="tlaccum">이력 축적 중 · {len(seq)}일째</p>'
                f'<p class="hint">판정 이력이 쌓이면 상태 변화 흐름을 표시합니다. 방향을 전망하지 않습니다.</p>'
                f'</section>')
    n = len(seq)
    keep = []
    for i, e in enumerate(seq):
        changed = (i > 0 and e['final'] != seq[i - 1]['final'])
        mismatch = (e.get('candidate') is not None and e.get('candidate') != e.get('final'))
        if i == 0 or i == n - 1 or changed or mismatch:
            keep.append((e, mismatch))
    if len(keep) > 8:
        keep = [keep[0]] + keep[-7:]

    def _row(e, mm):
        badge = '<span class="tlbadge">당일 후보 판정 상이</span>' if mm else ''
        return (f'<li class="tlrow"><span class="tldot {us_tone(e["final"])}"></span>'
                f'<span class="tldate">{esc(e["date"])}</span>'
                f'<span class="tlstate">{esc(e["final"])}</span>{badge}</li>')

    rows = ''.join(_row(e, mm) for e, mm in keep)
    return (f'<section class="card"><h2>최근 판정 이력</h2>'
            f'<ul class="tl">{rows}</ul>'
            f'<p class="hint">생애주기 판정(final)의 변화 흐름입니다. 반복 구간은 생략하고 전환일과 '
            f'당일 후보 판정이 다른 날을 표시합니다. 방향을 전망하지 않습니다.</p>'
            f'</section>')


def page_html(rec, all_recs, hist, updated, pj=None):
    ticker = rec['ticker']
    slug = slugify(ticker)
    name = rec.get('name_ko') or ticker
    lc = rec.get('lifecycle', '')
    ax = rec.get('axis_state', '')
    partial = is_partial(rec)
    excluded = is_excluded(rec)

    canonical = f'{SITE}/stock/us/{slug}/'
    robots = 'noindex,follow' if (partial or excluded) else 'index,follow'

    title = f'{name}({ticker}) 상대강도·상태 분석 | F29'
    if excluded:
        desc = f'{name}({ticker})는 현재 판정 가능한 데이터가 부족합니다. F29 미국 종목 상태 분석.'
    else:
        desc = (f'{name}({ticker})의 오늘 상태는 {lc}({ax})입니다. '
                f'섹터·시장 대비 상대강도와 소속 테마 위치를 F29 데이터로 분석합니다.')

    # ── 본문 ──
    if excluded:
        # 진짜 판정제외(방어) — 현 유니버스 0건. ①만, 나머지 숨김.
        body = (f'<section class="card verdict wt-c"><h2>판정 보류</h2>'
                f'<p class="vhead">판정 제외</p>'
                f'<p class="vsub">데이터 상태({esc(rec.get("status","-"))})로 인해 현재 상태 분류를 '
                f'제공하지 않습니다. 데이터가 충분히 쌓이면 판정이 시작됩니다.</p></section>'
                f'{card_meta(rec, updated)}')
        cards = body
    else:
        c1 = card_verdict(rec)
        c2 = card_diff(rec, hist, updated)
        c3 = card_rs(rec)
        ch = card_history(rec, hist, updated)
        c4 = card_theme_sync(rec, all_recs)
        cp = card_pattern(rec, pj, updated)   # US-P05-PATTERN: 미보유 시 None -> 생략
        c5 = card_bench(rec)
        c6 = card_meta(rec, updated)
        parts = [p for p in (c1, c2, c3, ch, c4, cp, c5, c6) if p]
        # 홀수 카드면 마지막 카드 full (PC 2단 하단 공백 흡수) — nth-child 미사용, 문자열 주입
        if len(parts) % 2 == 1:
            parts[-1] = parts[-1].replace('<section class="card', '<section class="card full', 1)
        cards = ''.join(parts)

    line1 = f'{esc(name)}의 오늘 상태는 <b>{esc(lc)}</b> · {esc(ax)}입니다.' if not excluded \
        else f'{esc(name)}는 현재 판정 보류 상태입니다.'
    _tr = resolve_lifecycle_transition(rec, hist, updated)
    if _tr and not excluded:
        if _tr['changed']:
            toprow = (f'<p class="topchange">직전 판정({esc(_tr["prev_date"])}): '
                      f'{esc(_tr["prev_final"])} &rarr; {esc(_tr["cur_final"])}</p>')
        else:
            toprow = (f'<p class="topchange">직전 판정({esc(_tr["prev_date"])}) 대비 변화 없음 · '
                      f'{esc(_tr["cur_final"])}</p>')
    else:
        toprow = ''

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<script src="/shared/f29-chrome.js?v=20260709b" data-active="" defer></script>
<style>{CSS}</style>
</head>
<body>
<div id="f29-header"></div>
<div class="wrap">
<h1>{esc(name)}</h1>
<p class="tick">{esc(ticker)} · 미국주식</p>
<p class="subdate">{esc(updated)} 미국장 마감 기준 · 매 영업일 갱신</p>
<p class="line1">{line1}</p>{toprow}
<div class="grid">
{cards}
</div>
</div>
<div id="f29-footer"></div>
</body>
</html>'''


def main():
    data = load_json(SRC)
    if not data or 'positions' not in data:
        raise SystemExit(f'FATAL: 소스 없음 또는 positions 키 부재: {SRC}')
    positions = data['positions']
    updated = data.get('updated', '')
    # positions_history.json = {TICKER: [{date, candidate, final}, ...]} (날짜 오름차순)
    hist_raw = load_json('/root/moneyflow/positions_history.json') or {}
    hist_map = hist_raw if isinstance(hist_raw, dict) else {}
    # 미래 이력 방어(스펙 §2): history 마지막 date > updated 이면 HARD_FAIL
    if updated:
        future = [t for t, arr in hist_map.items()
                  if isinstance(arr, list) and arr
                  and isinstance(arr[-1], dict) and arr[-1].get('date', '') > updated]
        if future:
            raise SystemExit(f'HARD_FAIL: history 날짜가 기준일({updated})보다 미래: {sorted(future)[:10]}')

    # ── slug 충돌 전수 검사 (빌드 전, 충돌 1건이라도 HARD_FAIL) ──
    slug_map = {}
    collisions = []
    for r in positions:
        t = r.get('ticker')
        if not t: continue
        s = slugify(t)
        if s in slug_map and slug_map[s] != t:
            collisions.append((s, slug_map[s], t))
        slug_map[s] = t
    if collisions:
        raise SystemExit(f'HARD_FAIL: slug 충돌 {len(collisions)}건: {collisions}')

    # ── 빌드 ──
    built, indexed = [], []
    pj = load_pattern_judgments()   # US-P05-PATTERN: 루프 밖 1회 로드
    print('[us-build] pattern_judgments=%d' % len(pj))
    for r in positions:
        t = r.get('ticker')
        if not t: continue
        slug = slugify(t)
        html_out = page_html(r, positions, hist_map.get(t), updated, pj)
        write_atomic(os.path.join(OUT_DIR, slug, 'index.html'), html_out)
        built.append(slug)
        if not (is_partial(r) or is_excluded(r)):
            indexed.append(slug)  # sitemap = index 대상만

    # raw↔slug 매핑 (canonical·검색 인덱스용)
    write_atomic(SLUG_MAP, json.dumps(
        {slugify(r['ticker']): r['ticker'] for r in positions if r.get('ticker')},
        ensure_ascii=False, indent=2))

    # sitemap-us (index 대상만, noindex 제외)
    urls = ''.join(f'  <url><loc>{SITE}/stock/us/{s}/</loc></url>\n' for s in sorted(indexed))
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               f'{urls}</urlset>\n')
    write_atomic(SITEMAP, sitemap)

    print(f'[us-build] built={len(built)} indexed={len(indexed)} '
          f'noindex={len(built)-len(indexed)} collisions=0')
    print(f'[us-build] slugs={built}')


if __name__ == '__main__':
    main()
