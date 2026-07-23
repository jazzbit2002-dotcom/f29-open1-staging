# F29 D5b 서버 반입 런북 — Sonnet 반입 차수용 (2026-07-23)

> 감리 3차 PASS·서버 스테이징 반입 승인. 승인 ZIP `D5b(2).zip` SHA `4e1bec84524195b5e4bd1f18e4b4fce05c45bcbe7cc17f886aac300712e88f8e`.
> **구현 7파일은 감리 승인 지문에서 동결 — 코드 재수정 금지.** 이 창은 반입·회귀·문서만.
> 운영 규칙: `claude/F29_HANDOFF_20260713_OPEN45.md` §1(릴레이·L등급·GitHub raw·한 줄 명령·evidence-only) 그대로 적용.

## 0. 릴레이 원칙 (매 명령 준수)

- **직접 서버 접근 없음.** 모든 서버 명령은 운영자(Sky)가 실행하고 출력을 붙여넣는다. "독립 직접 실측" 주장 금지 — 전부 운영자 실행 증거로 인용.
- 명령은 **한 줄씩** "이것만 실행" 형태로. 여러 줄 블록 동시 실행 금지(출력 겹침 실패 사례).
- 서버 반입은 **GitHub raw(`jazzbit2002-dotcom`) → curl → 서버**. `/raw/` 또는 `raw.githubusercontent.com` 확인(`/blob/` 아님).
- 바이트는 `wc -c`, SHA는 `sha256sum`. Python `len()` 금지(CJK 불일치).
- 실패 시 부분 롤백 금지 — 백업 묶음 전체 복원.

## 1. 승인 산출물 지문 (SHA-256 · bytes)

| 파일 | 역할 | SHA-256 | bytes |
|---|---|---|---|
| `scripts/collect_etf_ibit.py` | **검증 대상**(적용 후 기대 바이트) | `a48e592d2ee7d04b263fc399d2a9c15d9f193585afac191e7118aa280b3f21fa` | 17,139 |
| `scripts/validate_registry.py` | **검증 대상**(적용 후 기대 바이트) | `fb3798474522f46c832a5c11bc342e7d7e8d5c3e8c8021a927a68d782ab314cc` | 17,201 |
| `tests/test_d3_target_lag.py` | 배치(기존 덮어쓰기) | `9d8f8b30052158f6ae33b79db434760746053d321a3bf419fca6e59776c31ba6` | 20,517 |
| `tests/test_registry_v4.py` | 배치(기존 덮어쓰기) | `d28f102762a8479cff5576d1ddf37df9c18db92a996135f51c2c85a3e1a3f77e` | 24,336 |
| `tests/test_d5b_strict_lag.py` | 배치(신규) | `2a2abbcef307bb3c7b697b35cb2feb78106c19c298a02509b0b31b43f2a7a76f` | 3,935 |
| `tests/test_d5b_apply_contract.py` | 배치(신규) | `6156e1cc6aa459c540256e6fba79eebbecc22be3f3225d26cf32a761b31816ba` | 10,057 |
| `d5b_apply.py` | 반입 도구(repo root) | `90508f27cdc53650dc9711681877887c35231e9487bb1b73d724abd6d2989921` | 8,978 |

**반입 방식 주의:**
- 드라이버·검증자(`scripts/*.py`)는 **직접 push 하지 않는다.** `d5b_apply.py`가 서버의 라이브 파일을 in-place로 패치한다. 승인 패치본 SHA는 **적용 후 라이브 SHA 비교용 검증 대상**이다. (드라이버 패치본은 CJK 주석 포함이나, 적용은 라이브 파일 위에서 일어나므로 CJK-paste 없음.)
- push 대상 = `d5b_apply.py` + 테스트 4파일(전부 ASCII-safe). GitHub raw 표준 경로.

## 2. 반입 전 게이트 (전건 확인 후에만 착수)

운영자 실행·출력 인용:
1. 라이브 registry SHA = `fe42a4a456d97eef73dc9d715b3d939ebd7f3bd401c9d087797b887925baf264` (v4)
2. 전 issuer에 `target_lag_us_business_days` 키 존재
3. IBIT raw lag 키 존재 · `type is int` · 값 `0` · helper 반환 `0`
4. 기준선 전체 pytest = **265 passed, 0 skipped**
5. `cron_ibit.sh` 항목 정확히 2개 / `cron_etf.sh` 0개 / GBTC·FBTC·ARKB cron 0개
6. GBTC DB·ledger 산출물 0
7. ledger `*.d5b.tmp` 0

게이트 실패 시 착수 중단·재통보.

## 3. 반입 절차

1. **백업**: driver·validator·관련 테스트를 비공개 묶음으로. `/root/f29-backups/d5b-intake-<UTC타임스탬프>/` + manifest(원본 절대경로·소유자·권한·크기·변경전 SHA). 공개 디렉터리 `.bak` 금지.
2. **도구·테스트 배치**: `d5b_apply.py`(repo root) + 테스트 4파일을 GitHub raw → curl. 배치 후 각 파일 `sha256sum`·`wc -c`가 §1 표와 일치 확인.
3. **applier SHA 확인**: `sha256sum d5b_apply.py` == `90508f27…`.
4. **dry-run**: `python3 d5b_apply.py --check` → 판정 `apply`·`--check: would apply cleanly; no write`·라이브 driver/validator SHA 불변.
5. **적용**: `python3 d5b_apply.py` → `applied`.
6. **적용 후 검증**:
   - `sha256sum scripts/collect_etf_ibit.py` == `a48e592d…` (17,139B)
   - `sha256sum scripts/validate_registry.py` == `fb379847…` (17,201B)
   - `grep -c "expected = prev_us_business_day" scripts/collect_etf_ibit.py` == `0` (H2)
   - `ls scripts/*.d5b.tmp 2>/dev/null | wc -l` == `0`
7. **컴파일**: 7파일 `python3 -m py_compile …` 전건 PASS.
8. **전체 pytest**: 아래 §4 수용 기준.

## 4. 수용 기준

- **293 passed, 0 skipped, pytest_rc=0**
- 기존 `test_etf_issuer.py` 33건 전건 유지
- `test_d4_ticker_isolation.py`(D4 격리) 전건 유지
- `test_registry_v4_live.py` 유지
- registry·collector·cron·DB·ledger 무변경
- 실행 후 `*.d5b.tmp` 0
- GBTC 산출물 0

## 5. 행동 뮤테이션 (판별력 재검증, 서버)

일시 변형→테스트 FAIL 확인 후 즉시 원복(변형본 반입 금지):
- **D2** missing-key → `None` 복원 → missing-key 테스트 FAIL
- **D4** 명시 null 차단(→ValueError) → observation-only 테스트 FAIL
- **D7** lag 검사를 fetch 이후로 이동 → fetch-0 테스트 FAIL

(D1 폴백 복원·D3 `_LEGACY_TICKER` 제거는 Opus 차수에서 로컬 선증명 완료 — strict_lag 4 FAIL / `_paths_for` 경로격리.)

## 6. 롤백 규율

- 실패 시 **부분 롤백 금지** — driver·validator·관련 테스트를 백업 묶음으로 **전량 복원**.
- v3 registry 롤백이 필요하면 **반드시 D5b를 먼저 롤백**한다. strict driver + v3 registry(IBIT lag 키 부재) = IBIT 수집 정지.
- 재시작 규율: 정적 파일만 변경 시 무재시작. cron 무변경(설치 금지). PM2/nginx 반사적 재시작 금지.

## 7. 적용 후 실증 → 최종 비준

- 적용 후 **다음 정규 IBIT 슬롯**을 **A~D 4분기 정합**으로 판독해 제출.
- 그 실증 + 서버 293 passed 확인 후 감리 최종 비준.

## 8. 계속 HOLD (반입과 무관, 착수 금지)

GBTC 활성화 · cron 설치 · 외부 수집 · 권리 게이트. Farside 브리지는 별도 창·별도 원장(`farside_*`)이며 이 반입에 영향 없음. 브리지의 `farside_*` DB 테이블 생성 재통보 시 "DB 무변경" 기준선에 "`farside_*` 제외" 단서 추가.

## 9. 참고 문서

- 인도 보고서(정정본): `F29_D5B_OPUS_DELIVERABLES_20260723.md` SHA `68380da6a1acca8e45a38c4556e10bd86b99c7476073e18fc37ca88769a0da27` — §3 지문·§9 applier·§13 서버단계·§16 감리 PASS.
- 설계 정본: `F29_D5B_DESIGN_20260722.md` SHA `6c300bf1…` / 착수조건: `F29_D5B_OPUS_START_20260722.md`.
