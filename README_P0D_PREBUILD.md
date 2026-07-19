# F29 P0-D PREBUILD 번들 r3.1 (2026-07-19)

> 정본: `F29_US_BRIEFING_RULING_20260719_P0D.md` §9.
> **비배포 로컬 번들이다.** 운영 반영·PROMPT_FILE 전환·cron·공개 페이지·이메일·SNS·DB/신규 수집기 전부 금지.
> 화요일 bridge run 이후 P0-D FINALIZE에서 실데이터 fixture를 넣고 보정한 뒤에만 배포한다.

## 1. 산출물

| 파일 | 역할 | 비고 |
|---|---|---|
| `us_macro_brief_v1.schema.json` | D-1 정본 스키마 | JSON Schema draft-07. 문서·계약용 |
| `brief_contract.py` | D-3 fail-closed 검증 모듈 | 표준 라이브러리만 사용(jsonschema 불필요) |
| `macro_prompt_v7.txt` | D-2 v7 프롬프트 초안 | 구조화 JSON만 출력 |
| `build_review_v2.py` | D-4 구조화 검수기 | legacy 산문 run 병행 렌더 |
| `apply_p0d_delivery.py` | D-3 배선 앵커 패치 | **순수 ASCII, PREBUILD에서 미실행** |
| `test_brief_contract.py` | 계약 단위 테스트 36건 | `python3 test_brief_contract.py` |
| `test_review_integrity.py` | 정본 무결성 통합 테스트 7건 | `python3 test_review_integrity.py` |
| `make_fixtures.py` | fixture 생성기 | 합성 fixture — 시장 판단에 미사용 |
| `fixtures/` | fixture 23종 + context·comparison 4종 | |

## 1-1. r2 보정 — 감리 재판정 차단 결함 3건 해소

| # | 결함 | 보정 |
|---|---|---|
| L1-1 | brief.json 정본 무결성 미보장 (변조본이 latest 획득 가능) | D-3: tmp→flush→fsync→`os.replace` 원자 저장 후 **디스크 바이트를 재해시**해 `evidence.brief_sha256` 기록. 불일치 시 exit 4. D-4: latest 자격에 `brief.json 존재` + `status==brief_saved` + `brief_sha256` 기록 + **SHA 실측 일치** + **response.txt 파싱 객체 == brief.json** 전건 요구. brief.json 없으면 복구 렌더만 하고 반드시 부적격 |
| L1-2 | 스키마와 검증기 불일치 | tickers 최대 4·중복 금지 / themes 최대 6·중복 금지 / **theme 정확 문자열 일치**(`_norm` 비교 폐기 — `금 융` 통과 차단) / `comparison_status`는 `ready`·`baseline_only` 외 전부 FAIL |
| L1-3 | 숫자 충돌 검사가 단위 미인식 | `number_tokens()`로 (숫자, 단위) 토큰화. 단위 7종(`%p %` `bp` `포인트` `억 주` `개` `일` 등). 단위가 붙은 토큰은 숫자+단위 정확 일치 요구 → `1bp ≠ 1%`, `1.3%p ≠ 1.3%`, `7일 ≠ 7%`. key_points도 section body가 뒷받침해야 함 |

비차단 정정 3건도 반영: 검수 화면 하단 문구를 `brief.json과 evidence.json이 정본이며 response.txt는 모델 원시 응답 증거` 로 교정 / 파일 수 표기를 `entries / files` 로 구분 / 테스트 `with open()` 전환으로 ResourceWarning 제거.

## 1-2. r3 보정 — 프롬프트 재감리 + r2 잔여 지적

**v7 프롬프트 차단 3건 (프롬프트와 검증기 양쪽 반영)**

| # | 지적 | 보정 |
|---|---|---|
| L1-1 | JSON 출력과 "따옴표 금지"가 상충 | JSON 문법의 큰따옴표는 필수로 명시, 금지는 **자연어 문자열 내용 안의 인용 따옴표·가운뎃점**으로 한정 |
| L1-2 | digest 활용이 필수라면서 절 구성은 선택 | **digest 사용 가능 시 `rotation`·`value_chain_radar` 필수**로 잠금. 프롬프트 계약 + 검증기 `_digest_is_usable()` 양쪽 구현. rotation body는 d7/d90 대비 필수, value_chain_radar body는 산업 내부 격차 1건 + 종목 양축 사례 1건 필수. ready 구성은 필수 4 + 선택 2~4 = 6~8절 |
| L1-3 | 상위 필드 근거 부재 | 프롬프트 `[7-1] 상위 필드 근거 계약` + 검증기 `_check_watchpoints_derived()`. watchpoints는 next_session에 없는 새 숫자를 넣을 수 없다. **메타 강제 연결은 r3.1에서 철회** — §1-3 참조 |

**보강 3건**: freshness·as_of를 전체 경로(`market_internals.…`)로 표기하고 ready에서도 daily가 fresh가
아니면 breadth 생략 명시 / 좋은 예의 `좁혀졌습니다`(변화 암시)를 `일부 업종에 집중된 상태`로 교체하고
경고 추가 / 표시 정밀도 7종 표로 고정하고 `억 주 변환과 표시용 반올림은 새 파생 계산이 아니다` 한 줄 추가.

**r2 잔여 비차단 3건**: `test_malformed_json`의 `open()` → `with` 전환(ResourceWarning **0건 실측**) /
README·런북의 서버 검증 숫자를 38/38로 정정 / theme 비교에서 `strip()` 제거 — `" 금융 "`도 차단.

## 1-3. r3.1 — 과잉 검증 1건 철회 (감리 판정)

`_check_cross_field()`(sections 밖 문자열의 종목·테마를 section 메타에 강제 연결)를 **제거**했다.

- **P0-D 범위 밖**: 링크 렌더는 P1, SNS는 P3. section body ↔ section 메타 정합만으로 현 목적에 충분하다
- **실제 오탐 확인**: `section.themes`에 `반도체장비`만 선언하고 상위 요약에 `반도체장비`만 써도,
  부분 문자열 매칭 때문에 `theme '반도체' absent from every section.themes` 4건이 발생하는 것을 재현했다.
  `에너지`/`클린에너지`, `인프라건설`/`전력인프라`에서도 같은 유형이 생긴다
- **단어 경계 알고리즘을 새로 만들지 않는다.** 그것이 다시 과잉 엔지니어링이다

함께 제거: fixture `cross_field_ticker_orphan`·`cross_field_theme_orphan`, 테스트 2건.
프롬프트 `[7-1]`도 근거 계약 수준으로 축소했다.

**이후 추가 의미 검증 개발은 금지다.** d7/d90 해설의 충실도, 산업 격차 설명의 위치,
social_summary의 의미 동일성, headline의 대표성은 v7 canary에서 사람이 판독한다.

## 2. PREBUILD 검증 결과 (이 번들에서 실측)

- **계약 단위 테스트 36/36 PASS** (`test_brief_contract.py` — fixture 23종 + 경계·단위 케이스)
- **정본 무결성 통합 테스트 7/7 PASS** (`test_review_integrity.py` — 회귀 28~31·33)
  - 감리 재현 시나리오 고정: **변조된 brief.json run이 최신이어도 latest는 정상 run으로 간다**
  - brief.json 없음 / SHA 불일치 / 원시 응답 불일치 / status≠brief_saved / comparison.json 상태 불일치 → 전건 부적격
- **D-4 렌더 테스트**: 유효 baseline·유효 ready·금칙어 위반·legacy 산문 4 run → 유효 2건만 자격 O
- **앵커 패치 dry-run**: 업로드된 `us_macro_delivery.py` 사본에 적용 PASS
  - pre_sha256 `5457ebd809be1539d221217346ec6e5bf688702bb5b905ac33ace3184d83f1a7` — 핸드오프 기록값과 일치(정본 확인)
  - anchor import 1/1, tail 1/1, `py_compile` PASS, 중복 적용 가드 동작 확인
  - 패치 스크립트 non-ASCII 바이트 **0**
- **배선 로직 오프라인 실증**: valid → `CONTRACT: PASS | 1474 chars` + 원자 저장·tmp 잔여 0·SHA 일치,
  단위 불일치/비정확 theme → `exit 3` + violations 기록, **brief.json 미생성 확인**

## 3. 계약 요지

### D-1 스키마
최상위 11키 고정(추가 키 거부). `key_points` 정확히 3개 / `sections` 4~8개 /
`watchpoints` 1~3개 / `disclaimer` 완전 일치 / `as_of`는 마감 스냅샷 as_of와 동일.
section id 허용 9종: `conclusion` `breadth` `size_style` `rates_vol` `commodities`
`semis_sectors` `rotation` `value_chain_radar` `next_session`.
`conclusion`·`next_session` 필수, 중복 금지.
**baseline_only에서는 `size_style` `rates_vol` `commodities` `semis_sectors` 금지**(비교 기준 부재).

렌더 계층 필드(링크·UTM·URL·구독·SNS 상태·SEO·OG)는 스키마에 없으며,
넣으면 `unexpected top-level field`로 차단된다.

### D-3 검증 (전건 fail-closed, 위반 시 exit 3)
JSON parse / schema_version / 필수키·타입 / 추가키 거부 / 빈 문자열·빈 배열 /
길이 범위 / section id 허용·중복·필수 / baseline 금지 절 / 금칙어 12종 /
내부 명칭 18종 / 금지 표현 / **자금 이동 은유(정규식)** / ticker 허용목록 ·
body↔tickers 양방향 정합 · 총 8개 상한 / theme 허용목록 / social·email 신규 주장 방지 /
as_of 일치 / disclaimer 완전 일치 / 산문 분량.

**허용목록은 하드코딩하지 않고 실제 briefing-context에서 파생한다**
(`build_allowlists`): stock_radar·leaders·exits·watching의 ticker/name,
theme_ranking·horizon_leaders·value_chains·strength_quality의 theme.
필드명 추정 없음 — 07-18 실노출 스키마 기준.

### D-2 v7 반영 (§9-3)
1. 거래량 억 주 단위 (`705백만 주` → `약 7억 주`)
2. 자금 이동 은유 금지 확장 — v6 [6]의 좋은 예에 남아 있던 `돈이 전체로 퍼지기보다`를 제거,
   대체 표현 5종 명시. 검증기가 정규식으로 삽입어 형태까지 차단
3. `밸류체인` → `산업 계열 안의 격차`/`산업 안의 강약`. **내부 JSON 키 `value_chains`는 유지**
   (추가로 `로테이션` → `시장의 선택이 옮겨가는 흐름`도 평이화)

### D-4 검수기
차단 검사: 스키마 / schema_version / as_of / 섹션 id 중복 / ticker 정합 /
본문↔요약 숫자 충돌 / 핵심 3줄 / watchpoints / 분량 / stop_reason / SHA 대조.
**latest 자격 = 구조화 run + 차단 검사 전건 PASS.** legacy 산문 run은 렌더는 되지만 자격 없음.

## 4. FINALIZE 절차 (화요일 bridge run 이후)

1. bridge run evidence로 실데이터 회귀 fixture 추가 (`fixtures/bridge_*.json`)
2. v7 문체 보정 — bridge 본문에서 확인된 잔여 표현만
3. GitHub 업로드 → raw 확인 → curl → SHA 대조로 서버 반입:
   `brief_contract.py` `macro_prompt_v7.txt` `build_review_v2.py` `apply_p0d_delivery.py`
4. 서버에서 `python3 make_fixtures.py` → `test_brief_contract.py` (36/36) → `test_review_integrity.py` (7/7) 재실행 = 총 43/43
5. `python3 apply_p0d_delivery.py` — 백업·앵커·py_compile·롤백 경로 확인
6. PROMPT_FILE을 `macro_prompt_v7.txt`로 전환
7. `build_review.py`는 그대로 두고 구조화 run부터 `build_review_v2.py`를 호출 (파일 수정 없음)
8. 정본 canary 1회차 실행

**순서 주의**: 5번(배선)이 6번(프롬프트 전환)보다 먼저다. 반대로 하면 v7 JSON 출력이
검증 없이 저장된다.

## 5. 미결 — 감리 판정 반영

- **`sections` 8개 상한: 유지 확정.** 허용 ID 9종은 선택지가 9개라는 뜻이지 매일 9절을 쓰라는 뜻이 아니다.
  bridge run에서 특정 절이 계속 누락돼 정보 손실이 확인될 때만 재검토한다. (미결 아님 — 8개 유지 / 실물 관찰)
- **`social_summary` 서술적 신규 주장**: 숫자·단위·티커는 자동 차단되지만 서술적 주장은 휴리스틱 밖이다.
  P0-D canary까지는 사람 판독 병행으로 충분. **P3 SNS 자동 게시 전에는 headline·key_points에서
  결정론적으로 조립하거나 더 강한 의미 정합 검증이 필요하다.**
- **분량 계약**: bridge fixture에서 실측. 현재 baseline 1,474자로 정상 범위
