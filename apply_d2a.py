#!/usr/bin/env python3
# apply_d2a.py — 어휘 통일: "가격" → "주가" (2026-07-13)
# 범위: build_stock_pages.py가 생성하는 표 헤더·축 라벨·항목명만.
# 불변: build_weight.py의 flowLabel("관심·가격 동반 위축" 등)은 서비스 공용 SSOT — 미변경.
#       (돈의 무게/한국주식 흐름과 어휘가 갈라지는 것을 방지)

import os, shutil, sys, datetime, hashlib, ast

TGT = '/root/krx-moneyflow/build_stock_pages.py'
MARK = '# F29-D2A-VOCAB v1'
BK_DIR = '/root/f29-backups/d2a-' + datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')

src = open(TGT, encoding='utf-8').read()
if MARK in src:
    print('SKIP — 이미 적용됨')
    sys.exit(0)
if '# F29-D2-DASHBOARD v1' not in src:
    print('FAIL — D2 미적용 상태')
    sys.exit(1)

edits = [
    # 마커
    ("# F29-D2-DASHBOARD v1\n",
     "# F29-D2-DASHBOARD v1\n" + MARK + "\n"),

    # ② diff 카드 항목명
    ("FIELD_KO = {'share': '거래대금 점유율', 'price': '가격', 'state': '상태'}\n",
     "FIELD_KO = {'share': '거래대금 점유율', 'price': '주가', 'state': '상태'}\n"),

    # ① 오늘 판정 근거 축
    ("        axes.append(('15일 가격', f\"{s15.get('priceChangePct','-')}%\", pcls(s15.get('priceChangePct'))))\n",
     "        axes.append(('15일 주가', f\"{s15.get('priceChangePct','-')}%\", pcls(s15.get('priceChangePct'))))\n"),
    ("        axes.append(('90일 가격', f\"{long_pc}%\", pcls(long_pc)))\n",
     "        axes.append(('90일 주가', f\"{long_pc}%\", pcls(long_pc)))\n"),

    # ④ 돈의 무게 표 헤더
    ("<table><thead><tr><th>기간</th><th>상태</th><th>가격 변화</th><th>점유율 변화</th></tr></thead>\n",
     "<table><thead><tr><th>기간</th><th>상태</th><th>주가 변화</th><th>점유율 변화</th></tr></thead>\n"),

    # ④ 하단 힌트
    ("<p class=\"hint\">거래대금 점유율 변화와 가격 방향을 함께 본 참고지표입니다.</p>\n",
     "<p class=\"hint\">거래대금 점유율 변화와 주가 방향을 함께 본 참고지표입니다.</p>\n"),

    # 최근 흐름 차트 라벨
    ("'<p class=\"lbl\">가격 (기간 시작=100)</p>' + svg1 if svg1 else ''",
     "'<p class=\"lbl\">주가 흐름 (기간 시작=100)</p>' + svg1 if svg1 else ''"),

    # ③ 시나리오 문구
    ("        turn = '점유율 증가폭이 줄고 가격이 하락으로 돌아서는 경우'\n",
     "        turn = '점유율 증가폭이 줄고 주가가 하락으로 돌아서는 경우'\n"),
    ("        turn = f'점유율이 {sd:+g}p 아래로 더 밀리고 가격 약세가 이어지는 경우'\n",
     "        turn = f'점유율이 {sd:+g}p 아래로 더 밀리고 주가 약세가 이어지는 경우'\n"),
    ("        keep = '점유율과 가격이 함께 위로 방향을 잡는 경우'\n",
     "        keep = '점유율과 주가가 함께 위로 방향을 잡는 경우'\n"),
    ("        turn = '점유율과 가격이 함께 아래로 밀리는 경우'\n",
     "        turn = '점유율과 주가가 함께 아래로 밀리는 경우'\n"),
]

fails = [(i, src.count(o), o.strip().splitlines()[0][:55])
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
