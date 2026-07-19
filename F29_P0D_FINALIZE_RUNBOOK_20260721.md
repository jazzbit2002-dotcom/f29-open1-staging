# F29 P0-D FINALIZE 런북 r3 (2026-07-21 화 실행용)

> 정본: `F29_US_BRIEFING_RULING_20260719_P0D.md` §9-4 / **PREBUILD r3.1 번들**.
> **명령은 한 줄씩 실행한다.** 여러 줄 붙여넣기는 터미널 출력 겹침 사고 이력이 있다.
> 각 STEP의 판정 조건을 통과하지 못하면 다음 STEP으로 넘어가지 않는다.

## 서버 배치 (평면 구조)

전부 `/root/moneyflow/` 에 둔다. `brief_contract.py`는 `us_macro_delivery.py`·`build_review_v2.py`와
같은 디렉터리에 있어야 import가 성립한다. fixtures는 서버에서 생성한다(업로드하지 않는다).

## 반입 대상 SHA-256 (r3.1 — r2·r3 값은 폐기)

```
brief_contract.py          6cf81aeb11760e2b58c9512b7dd60d797be76388ede2690fa5139200b520abb6
build_review_v2.py         59e994fba8cc72546694751b648887d3aa3a2c404c9a80871dc8c61e191487cb
apply_p0d_delivery.py      cbe7a8a271530d508e2e7528c6e6fe47c0c6278736f70d89dbc6b6f63dfac4df
macro_prompt_v7.txt        5f4d65cb6366bf7616a00e6a7c8207269adf92ea165ac00c397efca14db4b2f3
test_brief_contract.py     bb1e3fa3982cf9b5c32b9ec6be43928eaf0b4760b273e7ddf90c35713aecfde2
test_review_integrity.py   1f9f5cf867292818071fb8190d096e71143064d02a52ddbbabe5f25cf08bc904
make_fixtures.py           7916a94a7d738a9400bb381b9993307d3749230dd27489c8dd3bdfb866b5f134
us_macro_brief_v1.schema.json fe8706c264b9548dfc02de6edb457400628282bbb13f98bac4de6adf178c9677
```

404 텍스트 해시 `d5558cd419c8…` — 하나라도 이 값이면 즉시 중단하고 GitHub 업로드부터 다시 한다.

---

## STEP 0 — 세션 정렬 게이트 (15:00 KST 이후, 읽기 전용)

```
curl -fsS http://127.0.0.1:3001/api/briefing-context | python3 -c 'import json,sys; d=json.load(sys.stdin); mi=d.get("market_internals",{}); print({"top": d.get("as_of"), "daily": mi.get("daily",{}).get("as_of"), "close": mi.get("market_close_snapshot",{}).get("as_of"), "daily_state": mi.get("daily",{}).get("freshness"), "close_state": mi.get("market_close_snapshot",{}).get("freshness")})'
```

**통과 조건**: as_of 세 값이 모두 `2026-07-20` + daily·close 둘 다 `fresh`.
하나라도 어긋나면 **여기서 중단**하고 시간을 두고 재확인한다. 05:00 즉시 실행 금지 사유가 이것이다.

---

## STEP 1 — bridge run 1회 (v6 그대로, 배선 전)

```
cd /root/moneyflow && python3 us_macro_delivery.py && python3 build_review.py
```

**판정**: comparison `ready (2026-07-17 -> 2026-07-20)` / 검사FAIL 0건 / latest자격 O.
이 run은 **canary 0회차**다. 정본 canary로 세지 않는다.

**실패하면 원인을 기록하고 FINALIZE를 중단한다. STEP 3 이후로 진행하지 않는다.**
bridge run의 목적이 comparison-ready 실데이터 fixture 확보와 v7 최종 보정이므로,
실패한 상태로 진행하면 PREBUILD를 검증 없이 운영에 넣는 셈이 된다.

---

## STEP 2 — bridge fixture 보존 (run_id는 STEP 1 출력에서 복사)

```
ls /root/moneyflow/briefing_delivery/evidence/ | tail -3
```

```
cp -r /root/moneyflow/briefing_delivery/evidence/<RUN_ID> /root/f29-backups/bridge-fixture-20260721/
```

이 폴더가 v7 회귀 기준이다. 이후 어떤 단계에서도 덮어쓰지 않는다.

---

## STEP 3 — r3.1 반입 (GitHub 경유, CJK 포함이라 SSH 붙여넣기 금지)

먼저 8개 파일을 `jazzbit2002-dotcom/f29-open1-staging` 에 업로드하고 **브라우저에서 raw URL을 열어
실제 코드가 보이는지 눈으로 확인**한다. 그 다음:

```
cd /root/moneyflow && for f in brief_contract.py build_review_v2.py apply_p0d_delivery.py macro_prompt_v7.txt test_brief_contract.py test_review_integrity.py make_fixtures.py us_macro_brief_v1.schema.json; do curl -s -o $f https://raw.githubusercontent.com/jazzbit2002-dotcom/f29-open1-staging/main/$f; done && sha256sum brief_contract.py build_review_v2.py apply_p0d_delivery.py macro_prompt_v7.txt test_brief_contract.py test_review_integrity.py make_fixtures.py us_macro_brief_v1.schema.json
```

**판정**: 8개 SHA 전건 위 표와 일치. 하나라도 다르면 중단.

---

## STEP 4 — 서버에서 자체 검증 (배선 전 필수)

```
cd /root/moneyflow && python3 make_fixtures.py | tail -2
```

```
cd /root/moneyflow && python3 test_brief_contract.py 2>&1 | tail -3
```

**판정**: `Ran 36 tests ... OK`

```
cd /root/moneyflow && python3 test_review_integrity.py 2>&1 | tail -3
```

**판정**: `Ran 7 tests ... OK`

여기서 실패하면 배선하지 않는다. 서버 python 버전 차이 등 환경 문제일 수 있으므로 출력을 그대로 회신한다.

---

## STEP 5 — D-3 배선 (프롬프트 전환보다 **먼저**)

```
cd /root/moneyflow && python3 apply_p0d_delivery.py
```

**판정**: `anchor gate: import count==1` / `tail count==1` / `py_compile: PASS` /
`pre_sha256: 5457ebd809be1539d221217346ec6e5bf688702bb5b905ac33ace3184d83f1a7` / marker count 2.
pre_sha가 다르면 대상 파일이 정본이 아니므로 중단.

**ROLLBACK**: 출력에 찍힌 `cp /root/f29-backups/p0d-d3-<TS>/us_macro_delivery.py /root/moneyflow/us_macro_delivery.py`

> 순서 주의: 이 단계를 STEP 6보다 먼저 하는 이유는, 반대로 하면 v7이 뱉은 JSON이
> 검증 없이 저장되기 때문이다.

---

## STEP 6 — PROMPT_FILE v7 전환

```
sed -i 's#macro_prompt_v[0-9]*\.txt#macro_prompt_v7.txt#' /root/moneyflow/us_macro_delivery.py && grep -n "PROMPT_FILE =" /root/moneyflow/us_macro_delivery.py
```

**판정**: `PROMPT_FILE = "/root/moneyflow/macro_prompt_v7.txt"`
(07-18에 `v[45]` 패턴이 no-op으로 빠진 사고가 있었으므로 `v[0-9]*`를 쓴다.)

---

## STEP 7 — 검수기 호출 전환 (파일 수정 없음)

기존 `build_review.py`는 그대로 두고, 구조화 run부터 `build_review_v2.py`를 호출한다.
파일을 수정하지 않으므로 백업도 롤백도 필요 없다. 구조화 이전 run은 v2가 legacy로 렌더한다.

실행할 명령은 없다.

---

## STEP 8 — 정본 canary 1회차

```
cd /root/moneyflow && python3 us_macro_delivery.py && python3 build_review_v2.py
```

**판정 (전건 필요)**:
- `CONTRACT: PASS | <N> chars | sections ...` + `brief_sha256` 출력
- **sections 목록에 `rotation` 과 `value_chain_radar` 가 반드시 들어 있어야 한다.**
  없으면 검증기가 `required section id(s) missing` 으로 차단한다 (F29 차별 데이터 누락 방지)
- 검사FAIL 0건 / latest자격 O
- 정본 brief.json 존재·SHA 일치·원시 응답 대조 PASS

**실패 시**: `CONTRACT: FAIL`이면 exit 3으로 멈추고 `violations.json`이 남는다.
brief.json은 생성되지 않고 latest도 갱신되지 않는다 — 그대로 위반 목록을 회신한다.
이때 **STEP 5·6을 되돌릴 필요는 없다.** v7 문체 보정 후 재실행이 정상 경로다.

검수 확인:

```
cat /root/moneyflow/briefing_delivery/evidence/<RUN_ID>/brief.json | head -40
```

---

## 비용 예상 (실측 아님, PREBUILD 추정)

| 항목 | v6 실측 | v7 추정 |
|---|---|---|
| 프롬프트 템플릿 | 14,059 B | 14,728 B (+669) |
| input 토큰 | 14,785 | 약 15,100 (+317) |
| output 토큰 | 2,037 | 약 2,870 (JSON 오버헤드 산문 대비 약 86%) |
| run 당 비용 | $0.1249 | **약 $0.147** |

canary 3회 기준 약 $0.44. 실측은 STEP 8 evidence에서 확정한다.

---

## 되돌리기 전체 경로

| 단계 | 롤백 |
|---|---|
| STEP 5 배선 | `cp /root/f29-backups/p0d-d3-<TS>/us_macro_delivery.py /root/moneyflow/` |
| STEP 6 프롬프트 | 위 롤백에 포함(같은 파일). 단독으로는 sed로 v6 복귀 |
| STEP 7 검수기 | 파일 수정 없음 — 롤백 불필요. `build_review.py` 계속 사용 가능 |
| 전체 | 백업 복원 → `grep -n "PROMPT_FILE =" /root/moneyflow/us_macro_delivery.py` 로 v6 확인 → `python3 -m py_compile /root/moneyflow/us_macro_delivery.py` |

pm2 재시작은 필요 없다 — `mf_server.js`를 건드리지 않는다.

---

## 이번 차수에서 하지 않는 것

cron 등록 / 공개 페이지 / 이메일 / SNS / DB / 신규 수집기 / `mf_server.js` 수정 /
`/moneyflow/briefing/` 연결. 전부 P1 이후이며 현재 HOLD.
