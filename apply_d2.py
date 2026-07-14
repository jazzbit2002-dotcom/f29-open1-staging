#!/usr/bin/env python3
# apply_d2.py — build_stock_pages.py D2 패치 (2026-07-13)
# 추가: ② 어제와 달라진 3가지 / ③ 다음 거래일 시나리오 / ⑥ 최근 20거래일 판정 이력
# 규율: 앵커 게이트 전건 통과 시에만 write. 백업 필수. 마커 F29-D2-DASHBOARD v1.
# 계약: 내부 임계값(SHARE_RATIO_UP/DN, PRICE_EPS, pressure_score) 화면 비노출.
#       시나리오 조건은 관측 가능한 값(점유율 pp, 가격 %)으로만 표현.

import os, shutil, sys, datetime, hashlib, ast

TGT = '/root/krx-moneyflow/build_stock_pages.py'
MARK = '# F29-D2-DASHBOARD v1'
BK_DIR = '/root/f29-backups/d2-' + datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')

src = open(TGT, encoding='utf-8').read()
if MARK in src:
    print('SKIP — 이미 적용됨')
    sys.exit(0)
if '# F29-D1-DASHBOARD v1' not in src:
    print('FAIL — D1 미적용 상태. D2는 D1 위에만 적용 가능.')
    sys.exit(1)

edits = []

# [1] 마커 + 카드 빌더 함수군 (verdict 함수 앞에 삽입)
edits.append((
    "# ---- F29 오늘 판정: 열거형 라벨 조합만 사용. 자유 생성 금지. 행동 지시 5종 금지.\n",
    MARK + "\n"
    "# ---- 변화/시나리오/이력 카드 (retro 엔진 산출물 소비. 내부 임계값 비노출)\n"
    "FIELD_KO = {'share': '거래대금 점유율', 'price': '가격', 'state': '상태'}\n\n"
    "def card_diff(retro):\n"
    "    \"\"\"② 어제와 달라진 3가지 — 상태 변화 우선, 없으면 지표 변화.\"\"\"\n"
    "    ch = (retro or {}).get('diff') or []\n"
    "    if not ch:\n"
    "        return ('<section class=\"card\"><h2>어제와 달라진 3가지</h2>'\n"
    "                '<p class=\"hint\">전일 데이터가 없어 변화 추적은 다음 거래일부터 시작됩니다.</p></section>')\n"
    "    items = ''\n"
    "    for c in ch[:3]:\n"
    "        w = c['window']\n"
    "        if c['kind'] == 'state':\n"
    "            items += (f'<li><span class=\"dk\">{w}일 상태</span>'\n"
    "                      f'<span class=\"dv\"><s>{esc(c[\"prev\"])}</s> → <b>{esc(c[\"curr\"])}</b></span></li>')\n"
    "        else:\n"
    "            unit = 'p' if c['field'] == 'share' else '%'\n"
    "            cls = pcls(c['delta']) if c['field'] == 'price' else ''\n"
    "            items += (f'<li><span class=\"dk\">{w}일 {esc(FIELD_KO.get(c[\"field\"],\"\"))}</span>'\n"
    "                      f'<span class=\"dv\"><s>{c[\"prev\"]}{unit}</s> → '\n"
    "                      f'<b class=\"{cls}\">{c[\"curr\"]}{unit}</b>'\n"
    "                      f'<em class=\"dd\">{c[\"delta\"]:+g}{unit}</em></span></li>')\n"
    "    return (f'<section class=\"card\"><h2>어제와 달라진 3가지</h2>'\n"
    "            f'<ul class=\"difflist\">{items}</ul>'\n"
    "            f'<p class=\"hint\">직전 거래일과 같은 기준으로 다시 계산한 결과입니다.</p></section>')\n\n"
    "def card_scenario(retro, summ):\n"
    "    \"\"\"③ 다음 거래일 시나리오 — 관측값 기준 조건. 내부 스코어 비노출.\"\"\"\n"
    "    s15 = (summ or {}).get('15') or {}\n"
    "    if not s15:\n"
    "        return ''\n"
    "    st = s15.get('flowState', '')\n"
    "    pc = s15.get('priceChangePct', 0) or 0\n"
    "    sd = s15.get('shareDeltaPp', 0) or 0\n"
    "    hist = (retro or {}).get('history') or []\n"
    "    # 최근 20일 점유율 최고치 = 관심 회복의 관측 기준\n"
    "    peak = max([h.get('shareDeltaPp', 0) or 0 for h in hist], default=sd)\n"
    "    rank = RETRO.STATE_RANK.get(st, 0)\n"
    "    if rank > 0:\n"
    "        keep = f'거래대금 점유율 변화가 {sd:+g}p 수준을 유지'\n"
    "        turn = '점유율 증가폭이 줄고 가격이 하락으로 돌아서는 경우'\n"
    "        kept = '현재 자금 유입 흐름 유지'\n"
    "    elif rank < 0:\n"
    "        keep = f'거래대금 점유율 변화가 최근 고점 {peak:+g}p 방향으로 회복'\n"
    "        turn = f'점유율이 {sd:+g}p 아래로 더 밀리고 가격 약세가 이어지는 경우'\n"
    "        kept = '현재 관심 이탈 흐름 지속'\n"
    "    else:\n"
    "        keep = '점유율과 가격이 함께 위로 방향을 잡는 경우'\n"
    "        turn = '점유율과 가격이 함께 아래로 밀리는 경우'\n"
    "        kept = '현재 방향성 부재 지속'\n"
    "    return (f'<section class=\"card scen\"><h2>다음 거래일 시나리오</h2>'\n"
    "            f'<div class=\"sc up-c\"><span class=\"sk\">흐름 반전 조건</span>'\n"
    "            f'<span class=\"sv\">{esc(keep)}</span></div>'\n"
    "            f'<div class=\"sc dn-c\"><span class=\"sk\">흐름 악화 조건</span>'\n"
    "            f'<span class=\"sv\">{esc(turn)}</span></div>'\n"
    "            f'<div class=\"sc now\"><span class=\"sk\">변화 없을 경우</span>'\n"
    "            f'<span class=\"sv\">{esc(kept)}</span></div>'\n"
    "            f'<p class=\"promise\">다음 거래일 장 마감 후 F29가 자동으로 결과를 다시 판정합니다.</p>'\n"
    "            f'</section>')\n\n"
    "def card_history(retro):\n"
    "    \"\"\"⑥ 최근 20거래일 판정 이력 (소급 산출). 배포 전 구간은 소급 표기.\"\"\"\n"
    "    hist = (retro or {}).get('history') or []\n"
    "    if len(hist) < 3:\n"
    "        return ''\n"
    "    rows = ''\n"
    "    for h in reversed(hist[-10:]):\n"
    "        d8 = h.get('date', '')\n"
    "        dk = f'{d8[4:6]}/{d8[6:8]}' if len(d8) == 8 else d8\n"
    "        nd = h.get('nextDayReturn')\n"
    "        ndc = pcls(nd) if nd is not None else 'flat'\n"
    "        ndt = f'{nd:+.2f}%' if nd is not None else '—'\n"
    "        rows += (f'<tr><td>{esc(dk)}</td><td>{esc(h.get(\"flowLabel\",\"\"))}</td>'\n"
    "                 f'<td class=\"num {ndc}\">{ndt}</td></tr>')\n"
    "    return (f'<section class=\"card\"><h2>최근 판정 이력</h2>'\n"
    "            f'<table><thead><tr><th>날짜</th><th>그날의 F29 판정</th>'\n"
    "            f'<th>다음 거래일 종가</th></tr></thead><tbody>{rows}</tbody></table>'\n"
    "            f'<p class=\"hint\">데이터 기준 소급 판정 — 각 날짜까지의 데이터만으로 같은 기준을 적용해 재산출했습니다. '\n"
    "            f'당시 실제로 게시된 문구가 아닙니다.</p></section>')\n\n"
    "# ---- F29 오늘 판정: 열거형 라벨 조합만 사용. 자유 생성 금지. 행동 지시 5종 금지.\n"
))

# [2] 카드 조립 — card0 뒤에 추가
edits.append((
    "    return f'''<!doctype html>\n",
    "    card_d = card_diff(retro)\n"
    "    card_s = card_scenario(retro, summ)\n"
    "    card_h = card_history(retro)\n\n"
    "    return f'''<!doctype html>\n"
))

# [3] body 배치 — 그리드 순서: diff / scenario / 돈의무게 / 차트 / 테마 / peers / 이력 / 패턴
edits.append((
    "<div class=\"grid\">{card1}{card_chart}{card2}{card3}{card4}</div>\n",
    "<div class=\"grid\">{card_d}{card_s}{card1}{card_chart}{card2}{card3}{card_h}{card4}</div>\n"
))

# [4] CSS
edits.append((
    ".grid{{display:grid;grid-template-columns:1fr;gap:14px}}\n",
    ".difflist{{list-style:none;margin:0;padding:0}}\n"
    ".difflist li{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:9px 0;border-bottom:1px solid #1f2937}}\n"
    ".difflist li:last-child{{border-bottom:0}}\n"
    ".dk{{color:var(--sub);font-size:.86rem}}\n"
    ".dv{{font-family:\"JetBrains Mono\",monospace;font-size:.95rem;text-align:right}}\n"
    ".dv s{{color:#6b7280;text-decoration:line-through;font-size:.85rem}}\n"
    ".dd{{display:block;font-style:normal;color:var(--sub);font-size:.76rem;margin-top:2px}}\n"
    ".scen .sc{{display:flex;flex-direction:column;gap:3px;padding:10px 12px;border-radius:8px;margin-bottom:8px;background:#0d1523}}\n"
    ".scen .up-c{{border-left:3px solid var(--teal)}}\n"
    ".scen .dn-c{{border-left:3px solid var(--up)}}\n"
    ".scen .now{{border-left:3px solid var(--sub)}}\n"
    ".sk{{color:var(--sub);font-size:.76rem}}\n"
    ".sv{{font-size:.92rem;line-height:1.45}}\n"
    ".promise{{margin:12px 0 0;padding-top:10px;border-top:1px solid #1f2937;color:var(--teal);font-size:.84rem;font-weight:600}}\n"
    ".grid{{display:grid;grid-template-columns:1fr;gap:14px}}\n"
))

fails = [(i, src.count(o), o.strip().splitlines()[0][:60])
         for i, (o, n) in enumerate(edits, 1) if src.count(o) != 1]
if fails:
    print('ANCHOR FAIL — 파일 무변경')
    for f in fails:
        print(f'  [{f[0]}] count={f[1]}  {f[2]}')
    sys.exit(1)

out = src
for o, n in edits:
    out = out.replace(o, n)

try:
    ast.parse(out)
except SyntaxError as e:
    print(f'SYNTAX FAIL — 미적용: {e}')
    sys.exit(1)

os.makedirs(BK_DIR, exist_ok=True)
shutil.copy2(TGT, os.path.join(BK_DIR, 'build_stock_pages.py'))
tmp = TGT + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(out)
os.chmod(tmp, 0o755)
os.replace(tmp, TGT)

print(f'APPLIED  edits={len(edits)}')
print(f'  backup : {BK_DIR}/build_stock_pages.py')
print(f'  before : {hashlib.sha256(src.encode()).hexdigest()[:16]}…  {len(src.encode())} B')
print(f'  after  : {hashlib.sha256(out.encode()).hexdigest()[:16]}…  {len(out.encode())} B')
print(f'  rollback: cp {BK_DIR}/build_stock_pages.py {TGT}')
