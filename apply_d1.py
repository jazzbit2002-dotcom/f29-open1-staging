#!/usr/bin/env python3
# apply_d1.py — build_stock_pages.py D1 패치 (2026-07-13)
# 적용: ① 헤더 시세(종가·등락률·거래대금) ② F29 오늘 판정 카드 ③ 기간별 압력 재표현
#      ④ PC 1440px 2단 레이아웃 ⑤ SEO title/H1 전망 키워드
# 규율: 앵커 count 게이트(전건 1회) → 전부 통과해야 write. 백업 필수. 버전 마커 v1.9.1-D1.

import os, shutil, sys, datetime, hashlib

TGT = '/root/krx-moneyflow/build_stock_pages.py'
MARK = '# F29-D1-DASHBOARD v1'

BK_DIR = '/root/f29-backups/d1-' + datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

src = open(TGT, encoding='utf-8').read()

if MARK in src:
    print('SKIP — 이미 적용됨 (마커 발견)')
    sys.exit(0)

# ---------------------------------------------------------------- 패치 정의
edits = []

# [1] import + 마커
edits.append((
    "import json, os, re, glob, html, datetime\n",
    "import json, os, re, glob, html, datetime\n"
    "import f29_retro as RETRO   " + MARK + "\n"
))

# [2] 숫자 포맷 유틸 (esc 다음)
edits.append((
    "def esc(s): return html.escape(str(s), quote=True)\n",
    "def esc(s): return html.escape(str(s), quote=True)\n\n"
    "def won(v):\n"
    "    \"\"\"거래대금 → 조/억 한글 표기\"\"\"\n"
    "    try: v = float(v)\n"
    "    except (TypeError, ValueError): return '-'\n"
    "    if v >= 1e12: return f'{v/1e12:.2f}조원'\n"
    "    if v >= 1e8:  return f'{v/1e8:,.0f}억원'\n"
    "    return f'{v:,.0f}원'\n\n"
    "def num(v, suffix='', plus=False):\n"
    "    try: v = float(v)\n"
    "    except (TypeError, ValueError): return '-'\n"
    "    s = f'{v:+.2f}' if plus else f'{v:,.0f}'\n"
    "    return s + suffix\n\n"
    "def pcls(v):\n"
    "    \"\"\"가격색: 상승 빨강 / 하락 파랑 / 보합 회색 (판정색과 분리)\"\"\"\n"
    "    try: v = float(v)\n"
    "    except (TypeError, ValueError): return 'flat'\n"
    "    return 'up' if v > 0 else ('down' if v < 0 else 'flat')\n"
))

# [3] 오늘 판정 문장 조립기 (page_html 앞)
edits.append((
    "def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell):\n",
    "# ---- F29 오늘 판정: 열거형 라벨 조합만 사용. 자유 생성 금지. 행동 지시 5종 금지.\n"
    "TREND_LONG = {'up_concentration': '장기 상승 추세', 'down_concentration': '장기 하락 압력',\n"
    "              'attention_up': '장기 관심 증가', 'fade_up': '장기 완만한 상승',\n"
    "              'fade_down': '장기 위축', 'neutral': '장기 뚜렷한 방향 없음'}\n\n"
    "def verdict(summ, quote):\n"
    "    \"\"\"결론 1줄 + 근거 축. (headline, sub, axes[])\"\"\"\n"
    "    s15 = (summ or {}).get('15') or {}\n"
    "    s90 = (summ or {}).get('90') or {}\n"
    "    s60 = (summ or {}).get('60') or {}\n"
    "    st15, lb15 = s15.get('flowState', ''), s15.get('flowLabel', '')\n"
    "    long_st = s90.get('flowState') or s60.get('flowState') or ''\n"
    "    long_pc = s90.get('priceChangePct', 0) or 0\n"
    "    head = lb15 or '판정 데이터 부족'\n"
    "    sub = ''\n"
    "    if long_st and st15:\n"
    "        lrank = RETRO.STATE_RANK.get(long_st, 0)\n"
    "        srank = RETRO.STATE_RANK.get(st15, 0)\n"
    "        ltxt = TREND_LONG.get(long_st, '')\n"
    "        if lrank > 0 and srank < 0:\n"
    "            sub = f'{ltxt}는 유지되나, 최근 15일 관심이 꺾이는 국면입니다.'\n"
    "        elif lrank < 0 and srank > 0:\n"
    "            sub = f'{ltxt} 속에서 최근 15일 자금이 다시 들어오는 국면입니다.'\n"
    "        elif lrank > 0 and srank > 0:\n"
    "            sub = f'{ltxt}와 단기 흐름이 같은 방향입니다.'\n"
    "        elif lrank < 0 and srank < 0:\n"
    "            sub = f'{ltxt}가 단기에도 이어지고 있습니다.'\n"
    "        else:\n"
    "            sub = f'{ltxt} 대비 단기 방향은 뚜렷하지 않습니다.'\n"
    "    axes = []\n"
    "    if s15:\n"
    "        axes.append(('15일 가격', f\"{s15.get('priceChangePct','-')}%\", pcls(s15.get('priceChangePct'))))\n"
    "        axes.append(('15일 거래대금 점유율', f\"{s15.get('shareDeltaPp','-')}p\", ''))\n"
    "    if s90:\n"
    "        axes.append(('90일 가격', f\"{long_pc}%\", pcls(long_pc)))\n"
    "    return head, sub, axes\n\n"
    "def page_html(d, theme_info, peers, tstage, pj, in_buy, in_sell, retro=None):\n"
))

# [4] SEO title/desc — 전망 키워드
edits.append((
    "    title = f'{name}({code}) 거래대금·자금 압력 | F29'\n"
    "    desc  = (f'{name}({code})의 거래대금 압력, 가격 흐름, 테마 위치를 '\n"
    "             f'F29 기준으로 정리합니다. 최근 15일 기준 {rep_label} 상태.')\n",
    "    q = (retro or {}).get('quote') or {}\n"
    "    v_head, v_sub, v_axes = verdict(summ, q)\n"
    "    tname = (theme_info or {}).get('theme', '')\n\n"
    "    title = f'{name}({code}) 전망·수급·자금 흐름 분석 | F29'\n"
    "    desc  = (f'{name}({code})의 오늘 수급과 거래대금, '\n"
    "             + (f'{tname} 테마 내 위치, ' if tname else '')\n"
    "             + f'15·30·60·90일 자금 압력을 F29 데이터로 분석합니다. 최근 15일 {rep_label}.')\n"
))

# [5] 카드1 표 — 상태 강조 + 가격색
edits.append((
    "        rows += (f'<tr><td>{w}일</td><td>{esc(s.get(\"flowLabel\",\"\"))}</td>'\n"
    "                 f'<td class=\"num\">{s.get(\"priceChangePct\",\"\")}%</td>'\n"
    "                 f'<td class=\"num\">{s.get(\"shareDeltaPp\",\"\")}p</td></tr>')\n",
    "        _pc = s.get('priceChangePct', 0)\n"
    "        rows += (f'<tr><td>{w}일</td><td><b>{esc(s.get(\"flowLabel\",\"\"))}</b></td>'\n"
    "                 f'<td class=\"num {pcls(_pc)}\">{_pc}%</td>'\n"
    "                 f'<td class=\"num\">{s.get(\"shareDeltaPp\",\"\")}p</td></tr>')\n"
))

# [6] 카드1 제목·힌트 — 돈의 무게 서사
edits.append((
    "<h2>기간별 자금 압력</h2>{badge}\n",
    "<h2>15·30·60·90일 돈의 무게</h2>{badge}\n"
))

# [7] 헤더 시세 + 오늘 판정 카드 블록 (본문 렌더 직전 조립)
edits.append((
    "    return f'''<!doctype html>\n",
    "    # 헤더 시세 (data/stocks bars[-1])\n"
    "    quote_html = ''\n"
    "    if q.get('close'):\n"
    "        _cr = q.get('changeRate', 0)\n"
    "        quote_html = f'''<div class=\"quote\">\n"
    "<div class=\"q\"><span class=\"qk\">종가</span><span class=\"qv\">{num(q.get(\"close\"))}</span></div>\n"
    "<div class=\"q\"><span class=\"qk\">전일 대비</span><span class=\"qv {pcls(_cr)}\">{num(_cr, \"%\", plus=True)}</span></div>\n"
    "<div class=\"q\"><span class=\"qk\">거래대금</span><span class=\"qv\">{won(q.get(\"tradingValue\"))}</span></div>\n"
    "</div>'''\n\n"
    "    # 카드 0: F29 오늘 판정\n"
    "    axes_html = ''.join(\n"
    "        f'<li><span class=\"ak\">{esc(k)}</span><span class=\"av {c}\">{esc(val)}</span></li>'\n"
    "        for k, val, c in v_axes)\n"
    "    theme_line = (f'<p class=\"tline\">소속 테마 <b>{esc(tname)}</b> · 현재 <b>{esc(tstage)}</b> 단계</p>'\n"
    "                  if tname and tstage else '')\n"
    "    card0 = f'''<section class=\"card verdict\">\n"
    "<h2>F29 오늘 판정</h2>\n"
    "<p class=\"vhead\">{esc(v_head)}</p>\n"
    "<p class=\"vsub\">{esc(v_sub)}</p>\n"
    "<ul class=\"axes\">{axes_html}</ul>\n"
    "{theme_line}\n"
    "<span class=\"judg-disc\">데이터 기반 상태 판정이며, 특정 종목의 매수·매도 추천이 아닙니다.</span>\n"
    "</section>'''\n\n"
    "    return f'''<!doctype html>\n"
))

# [8] CSS — PC 1240px 2단 + 가격색 토큰 + 신규 카드 스타일
edits.append((
    ":root{{--bg:#0A0E17;--card:#111827;--tx:#e5e7eb;--sub:#9ca3af;--teal:#3DD8B0;--gold:#f0c674}}\n",
    ":root{{--bg:#0A0E17;--card:#111827;--tx:#e5e7eb;--sub:#9ca3af;--teal:#3DD8B0;--gold:#f0c674;"
    "--up:#F45B69;--down:#4C8DFF;--flat:#9ca3af}}\n"
))

edits.append((
    ".wrap{{max-width:680px;margin:0 auto;padding:16px}}\n",
    ".wrap{{max-width:1240px;margin:0 auto;padding:16px 24px}}\n"
    ".up{{color:var(--up)}}.down{{color:var(--down)}}.flat{{color:var(--flat)}}\n"
    ".quote{{display:flex;gap:28px;flex-wrap:wrap;background:var(--card);padding:14px 18px;border-radius:10px;margin-bottom:16px}}\n"
    ".quote .q{{display:flex;flex-direction:column;gap:2px}}\n"
    ".qk{{color:var(--sub);font-size:.78rem}}\n"
    ".qv{{font-size:1.25rem;font-weight:700;font-family:\"JetBrains Mono\",monospace}}\n"
    ".verdict{{border-left:3px solid var(--teal)}}\n"
    ".vhead{{font-size:1.5rem;font-weight:800;margin:0 0 6px;color:#fff}}\n"
    ".vsub{{margin:0 0 12px;color:var(--tx);font-size:1rem}}\n"
    ".axes{{list-style:none;display:flex;gap:24px;flex-wrap:wrap;margin:0;padding:0}}\n"
    ".axes li{{display:flex;flex-direction:column;gap:2px}}\n"
    ".ak{{color:var(--sub);font-size:.76rem}}\n"
    ".av{{font-size:1.05rem;font-weight:700;font-family:\"JetBrains Mono\",monospace}}\n"
    ".tline{{margin:12px 0 0;color:var(--sub);font-size:.88rem}}\n"
    ".grid{{display:grid;grid-template-columns:1fr;gap:14px}}\n"
    "@media(min-width:1024px){{.grid{{grid-template-columns:1fr 1fr}}.grid .full{{grid-column:1/-1}}}}\n"
    "@media(max-width:480px){{.wrap{{padding:12px}}.quote{{gap:16px}}.vhead{{font-size:1.25rem}}.axes{{gap:14px}}}}\n"
))

# [9] body — 헤더 시세 + card0 + 2단 그리드 배치
edits.append((
    "<h1>{esc(name)}({code}) 거래대금·자금 압력</h1>\n"
    "<p class=\"asof\">{end_k} 집계 기준 · 매 영업일 오후 갱신</p>\n"
    "<div class=\"judg\">{line1}<span class=\"judg-disc\">특정 종목의 매수·매도 추천이 아닙니다.</span></div>\n"
    "{card1}{card_chart}{card2}{card3}{card4}{card5}\n",
    "<h1>{esc(name)}({code}) 전망과 오늘 자금 흐름</h1>\n"
    "<p class=\"asof\">{end_k} 장 마감 기준 · 매 영업일 오후 갱신</p>\n"
    "{quote_html}\n"
    "{card0}\n"
    "<div class=\"grid\">{card1}{card_chart}{card2}{card3}{card4}</div>\n"
    "{card5}\n"
))

# [10] main() — retro 산출 후 page_html에 전달
edits.append((
    "        html_out = page_html(d, ti, peers[:6], tstage,\n"
    "                             patterns.get(code), code in buy_codes, code in sell_codes)\n",
    "        try:\n"
    "            retro = RETRO.analyze(code)\n"
    "        except Exception as e:\n"
    "            print(f'  retro 실패 {code}: {e}')\n"
    "            retro = None\n"
    "        html_out = page_html(d, ti, peers[:6], tstage,\n"
    "                             patterns.get(code), code in buy_codes, code in sell_codes,\n"
    "                             retro=retro)\n"
))

# ---------------------------------------------------------------- 앵커 게이트
fails = []
for i, (old, new) in enumerate(edits, 1):
    c = src.count(old)
    if c != 1:
        fails.append((i, c, old.strip().splitlines()[0][:70]))

if fails:
    print('ANCHOR FAIL — 미적용, 파일 무변경')
    for i, c, t in fails:
        print(f'  [{i}] count={c}  {t}')
    sys.exit(1)

out = src
for old, new in edits:
    out = out.replace(old, new)

# ---------------------------------------------------------------- 구문 검증
import ast
try:
    ast.parse(out)
except SyntaxError as e:
    print(f'SYNTAX FAIL — 미적용: {e}')
    sys.exit(1)

# ---------------------------------------------------------------- 백업 후 기록
os.makedirs(BK_DIR, exist_ok=True)
shutil.copy2(TGT, os.path.join(BK_DIR, 'build_stock_pages.py'))
before = hashlib.sha256(src.encode()).hexdigest()

tmp = TGT + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(out)
os.chmod(tmp, 0o755)
os.replace(tmp, TGT)

after = hashlib.sha256(out.encode()).hexdigest()
print(f'APPLIED  edits={len(edits)}')
print(f'  backup : {BK_DIR}/build_stock_pages.py')
print(f'  before : {before[:16]}…  {len(src.encode())} B')
print(f'  after  : {after[:16]}…  {len(out.encode())} B')
print(f'  rollback: cp {BK_DIR}/build_stock_pages.py {TGT}')
