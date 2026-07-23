# F29 D5b Opus 구현 인도 보고서 (2026-07-23)

> 역할: 구현(Opus). 설계·판정 = Fable5, 반입·회귀 = Sonnet.
> 정본 설계 = `F29_D5B_DESIGN_20260722.md` (SHA `6c300bf1…`), 착수 조건 = `F29_D5B_OPUS_START_20260722.md` §1 (감리 보정 5건).
> 본 보고서는 실행 상태·증거 기록이다. 감사표 승격·최종 배포 LOCK은 Sky/감리 판정 사항이며 본 문서가 대체하지 않는다.
> **본 세션은 클라우드 샌드박스다. VPS(root@vultr) 직접 접근 0회.** 아래 "서버" 사실은 전부 운영자(Sky) PRE-GATE 릴레이 증거이며, 독립 실측이 아니다.

---

## 0. 핵심 요지 (한 줄)

드라이버 lag 리졸버의 레거시 폴백(`_LEGACY_TICKER` 특수처리)을 제거하고, `target_lag_us_business_days` 키 부재를 **모든 티커(IBIT 포함) 공통 ValueError**로 fail-close 했다. 관측 전용(observation-only)은 **명시적 null 하나로만** 표현된다. 레지스트리 정책·활성화·cron·외부수집·권리게이트는 전부 HOLD 유지(무변경).

---

## 1. 승인 범위 = 정확히 7파일 (그 외 무변경)

| # | 파일 | 성격 | 변경 요지 |
|---|---|---|---|
| 1 | `scripts/collect_etf_ibit.py` | 패치 | H1 폴백 제거·fail-close / H2 死대입 1줄 제거 |
| 2 | `scripts/validate_registry.py` | 패치 | H3 materialization 분기·헬퍼 제거 |
| 3 | `tests/test_d3_target_lag.py` | 개정 | 폴백 테스트 2종 → ValueError 계약 + 합성 엔트리 2종 |
| 4 | `tests/test_registry_v4.py` | 재작성 | fixture v4화 / materialization 4종 제거 / 전이 5종 신설 |
| 5 | `tests/test_d5b_strict_lag.py` | 신규 | fail-close 리졸버 + fetch-0 순서 계약 |
| 6 | `d5b_apply.py` | 신규 | 2파일 handled-I/O all-or-rollback applier |
| 7 | `tests/test_d5b_apply_contract.py` | 신규 | applier 계약 테스트 |

**MUST NOT touch (무변경 확인):** test_etf_issuer.py, test_d4_ticker_isolation.py, test_registry_v4_live.py, collectors/etf_issuer.py, config registry, cron 스크립트, crontab, DB, ledger.

---

## 2. PRE-GATE (서버 — 운영자 릴레이, 인용)

착수 전 서버 PRE-GATE 통과 기록(운영자 실측, 본 세션 재현 아님):

- 라이브 레지스트리 SHA = `fe42a4a456d97eef73dc9d715b3d939ebd7f3bd401c9d087797b887925baf264` (v4)
- 전체 pytest = **265 passed, 0 skipped**
- cron 게이트 = 2 / 0 / 0
- IBIT raw 키+값0 = 4중 확인

운영자 제공 실측 앵커: H2 = 227행 1건 / H3 = validator 383·385·388·389·398행 / test_d3 개정 = 153·158행(허용목록 일치). 아래 §5 앵커 검증은 이 실측과 정합한다.

---

## 3. 산출물 SHA-256 · 바이트 (`wc -c`, 감리 2차 반영 후 실측)

| 파일 | SHA-256 | bytes |
|---|---|---|
| scripts/collect_etf_ibit.py | `a48e592d2ee7d04b263fc399d2a9c15d9f193585afac191e7118aa280b3f21fa` | 17,139 |
| scripts/validate_registry.py | `fb3798474522f46c832a5c11bc342e7d7e8d5c3e8c8021a927a68d782ab314cc` | 17,201 |
| tests/test_d3_target_lag.py | `9d8f8b30052158f6ae33b79db434760746053d321a3bf419fca6e59776c31ba6` | 20,517 |
| tests/test_registry_v4.py | `d28f102762a8479cff5576d1ddf37df9c18db92a996135f51c2c85a3e1a3f77e` | 24,336 |
| tests/test_d5b_strict_lag.py | `2a2abbcef307bb3c7b697b35cb2feb78106c19c298a02509b0b31b43f2a7a76f` | 3,935 |
| tests/test_d5b_apply_contract.py | `6156e1cc6aa459c540256e6fba79eebbecc22be3f3225d26cf32a761b31816ba` | 10,057 |
| d5b_apply.py | `90508f27cdc53650dc9711681877887c35231e9487bb1b73d724abd6d2989921` | 8,978 |

- 7/7 `py_compile` PASS. `d5b_apply.py` 순 ASCII(CJK 0).
- 감리 2차 대비 변경 3파일: test_registry_v4.py(결함1·2), test_d5b_apply_contract.py(결함3 테스트), d5b_apply.py(결함3 롤백). 나머지 4파일 무변경.

---

## 4. H1·H2·H3 앵커 증거 (count==1, 순 ASCII, 컴파일, 구조)

4개 훅 전건 소스에서 **추출·대조**(재타이핑 아님), 각 `old` count==1, 순 ASCII, `embedded_old=0`:

```
H1 driver fallback->fail-closed      old_count=1 ascii=True new_empty=False
H2 driver dead-assignment removal    old_count=1 ascii=True new_empty=True
H3a validator NO_CHANGE + drop MAT   old_count=1 ascii=True new_empty=False
H3b validator drop _materialization  old_count=1 ascii=True new_empty=True
```

**H1** — `_target_lag_for` 드라이버. `if "..." in meta / elif ticker==_LEGACY_TICKER: lag=0 / else: return None` → `if "..." not in meta: raise ValueError("...explicit null...")`. 값검증(bool/int/음수 거부)·docstring 보존. **`_LEGACY_TICKER="IBIT"` 상수는 유지**(`_paths_for`가 사용 — D4 경로격리 의존).

**H2** — 死대입 1줄 `    expected = prev_us_business_day(...).isoformat()\n` 삭제. 순 ASCII 규약상 앵커는 대입문 1줄만; 직전 CJK 주석(`# B-16 …`)은 의도적으로 잔존(설계 scope "1줄"). 살짝 고아가 된 주석은 수용·명기.
검증: 패치 후 `grep -c "expected = prev_us_business_day"` → **0** (1→0).

**H3a** — `key_moved` + NO_CHANGE + MATERIALIZATION 분기 → `if old_lag == new_lag: return  # NO_CHANGE`.
**H3b** — `_materialization_ok()` 함수 제거, 공백 2줄로 수축. `LAG_KEY` 정의는 유지(S2에서 사용).

**구조 계약(보정3)** — 패치 validator를 `import` 후 `inspect.getsource`:
```
_materialization_ok  in getsource: False
key_moved            in getsource: False
MATERIALIZATION      in getsource: False
```

패치 후 바이트: 드라이버 17,154→17,139 / validator 18,173→17,201. 양쪽 `py_compile` PASS.

---

## 5. H1 행동 검증 (패치 드라이버 격리 import)

| 입력 | 결과 |
|---|---|
| `_target_lag_for("IBIT", {})` (키부재) | **ValueError** |
| `_target_lag_for("GBTC", {})` (키부재) | **ValueError** |
| `{lag: None}` (명시 null) | `None` (관측전용) |
| `{lag: 0}` / `{lag: 3}` | `0` / `3` |
| `{lag: True}` / `{lag:"0"}` / `{lag:-1}` | ValueError (값검증 유지) |
| `_LEGACY_TICKER` | `"IBIT"` (유지) |
| `_paths_for("IBIT")[3]` / `_paths_for("gbtc")[3]` | `etf_ibit` / `etf_gbtc` (D4 경로격리 보존) |

---

## 6. test_d3_target_lag.py 개정 — 허용목록 감사 (diff 실측)

pristine 대비 **정확히 4개 변경 훅**, 그 외 무변경(diff로 확인):

1. IBIT 합성 엔트리 `_issuer()` → `_issuer(target_lag_us_business_days=0)` + 주석 — **허용목록 항목1**
2. resolver `test_ibit_without_field_falls_back_to_zero` → `test_ibit_without_field_raises`(ValueError) — **항목2** (153행)
3. resolver `test_non_ibit_without_field_is_observation_only` → `test_non_ibit_without_field_raises`(ValueError) — **항목3** (158행)
4. ⚠️ **OBSV 합성 엔트리** `_issuer()` → `_issuer(target_lag_us_business_days=None)` + 주석 — **§7 판정 건 (허용목록에 문자 그대로 열거되지 않음)**

주석 문구 변경은 항목4(라벨 정정)에 포함. 스테일 폴백 단언(`== 0` / `is None` 무필드) 잔존 0.

---

## 7. ⚠️ 판정 필요 — OBSV 명시-None 전환 (감리 veto 대상)

**무엇:** test_d3의 `OBSV` 합성 엔트리를 무필드(`_issuer()`)에서 명시 null(`_issuer(target_lag_us_business_days=None)`)로 바꿨다.

**왜 (근거):** 관측전용 테스트 7종 전부 `C.main("BTC","OBSV")`를 호출한다. H1 적용 후 무필드 OBSV는 리졸버에서 ValueError를 던져 이 7종이 전부 크래시한다. 설계 §1 "유지" 조항은 "명시 None observation-only(NULLED·OBSV)"를 명시하므로 OBSV는 명시 None이어야 하며, 기존 주석 "no field, not IBIT → observation-only"는 이제 거짓이다(항목4 정정 필요와 맞물림).

**경계:** 이 변경은 허용목록 항목1~4(문자 그대로는 IBIT 엔트리 + 두 테스트 전환만 열거)에 **문자 그대로 열거되지 않았다.** 대안(미변경)은 7개 테스트를 확정적으로 깨뜨린다. 유지-조항 + 항목4에 근거해 진행했으나, **엄격 해석 시 veto 가능**하므로 별도 판정을 요청한다.

---

## 8. test_registry_v4.py — 델타 (감리 2차 반영)

- fixture `current_v3_like()`(v3 시뮬) → **`current_v4()`**(`good_registry()` 반환, lag 키 유지). 호출부 **46곳** 개명, 잔존 `current_v3_like` = **0**.
- **제거 4종:** `test_ibit_materialization_marker_matches` / `_marker_mismatch` / `_without_marker` / `test_non_ibit_materialization_of_null`.
- **신설 5종(전이):** `test_current_missing_lag_key_is_refused`(→C3) / `test_explicit_zero_to_zero_is_no_change` / `test_null_to_zero_disabled_without_marker_passes` / `test_null_to_zero_with_current_marker_is_refused`(→T1) / `test_zero_to_null_with_current_marker_is_refused`(→T1). 유지·개명: `test_ibit_real_lag_change_is_refused`(0→1 T1).
- **[감리 결함1 수정]** `test_ledger_isolation_marker_is_read_from_given_dir` — v3 fixture + materialization에 의존하던 stale 테스트(개명 후 current==candidate NO_CHANGE → 마커 미검사 → exit 0, 그런데 ==1 기대 = 실패). GBTC null→0 REAL_CHANGE로 바꾸고 `etf_gbtc_done.json` 유무로 T1(exit 1)↔PASS(exit 0)가 갈리도록 수정.
- **[감리 결함2 추가]** `test_materialization_contract_is_absent_from_validator` — 실제 `scripts.validate_registry` 모듈을 import 후 `inspect.getsource(V)`로 `_materialization_ok`/`key_moved`/`MATERIALIZATION` 부재를 **영속 회귀**로 단언(수동 grep·보고서 기록 대체 아님).
- 테스트 함수 수 54 → **56**(제거 4·신설 5·순증 1·결함2 구조 테스트 +1). `py_compile` PASS. 잔존 `-registry-v3`(135행)은 스키마 거부 테스트의 의도적 잘못된 버전 문자열(정당).

**로컬 전체 실행 확정(이전 "로컬 불가" 판단 정정):** validator 스위트는 DB가 불필요해 패치 validator + 스텁으로 **완전 실행 가능**. 결과 **77 passed, 0 failed**. 환경 패리티 검증: 수정 **전** 버전을 로컬 실행 시 감리와 동일하게 `test_ledger_isolation…` **1건만** 실패(`window=2026-07-22 errors=0` = NO_CHANGE→exit0) — 제 로컬 하네스가 감리 환경과 일치함을 확인.

**핵심 계약 근거:** current측 키부재→C3는 validator 실경로로 입증 — `_effective_lag`(137행)가 `_target_lag_for` ValueError를 잡아(141행) `diags.error(scope,"C3",…)`(321행), 전이 조기복귀(372행). 마커 전이 신설분은 기존 통과 테스트 `test_lag_change_disabled_with_current_marker`(현 414행)와 lag 값만 다른 동형.

---

## 9. applier 3상태 + 쓰기 all-or-rollback + A1/A2/A3 (감리 2차 반영, 로컬 실행)

`d5b_apply.py` = 5-튜플 HUNKS(2파일 스팬), 파일별 3상태(`patched`/`unpatched`/`drift`), 삭제훅(new=="")은 old count로 상태 판정.

**교차파일 균일성:** 파일내 drift → ABORT / 전건 noop → "already patched" / 전건 apply → 적용 / **혼합(교차파일 부분) → ABORT.** 쓰기 전 전 결과 `compile()`, `--check` 무기록.

**[감리 결함3 수정] 쓰기 = handled I/O 실패에 대한 all-or-rollback**(절대 원자성 아님, 문구 정정):
- 적용 대상 전부를 먼저 temp로 스테이징(원본 mode 복사), 원본 바이트·mode 스냅샷 후 순차 `_REPLACE`(=`os.replace` 간접, 테스트 주입점).
- 교체 도중 `OSError` 발생 시 **이미 교체된 파일을 원본 바이트·mode로 복원**, 전 temp 제거, 비정상 종료. 트리를 반쯤 쓴 상태로 남기지 않음.
- docstring에서 "atomically"·"true multi-file atomic" 제거, "all-or-rollback on a handled I/O failure, not crash-proof atomicity" + 프로세스 강제종료 절대 원자성은 journal 필요(과설계 회피, 서버 사전 백업이 수용선)로 정확히 기술.

로컬 실증: `--check`(무기록) / fresh apply(양쪽 compile·H2 앵커 1→0) / 재실행 멱등 noop / unrelated·파일내 drift·교차파일 부분·중복 post-image → 전부 ABORT·무기록·temp 0.

**계약 테스트 `test_d5b_apply_contract.py` = 11/11 PASS** (2파일 tmp 스테이징). `pristine` fixture는 훅 역적용으로 **트리 상태 무관** 재구성 → 적용 전/후 양쪽에서 11/11 재현.

**[결함3 신규 테스트] `test_second_replace_failure_rolls_back`** — in-process로 2번째 `_REPLACE`에 `OSError` 1회 주입:
- 비정상 종료(rc≠0) / driver SHA 불변 / validator SHA 불변 / `*.d5b.tmp` 잔존 0 — 전건 단언 PASS.
- **판별력 확인:** 롤백 없는 순차-replace 변이에 대해 이 테스트가 실패(OSError 전파·driver 오염) → 결함3을 실제 검출.

**뮤테이션 매트릭스(계약 테스트가 검출):**
```
BASELINE                         : 11 passed
A1 remove H1 hunk                : 4 failed  -> DETECTED
A2 allow cross-file mixed        : 1 failed  -> DETECTED
A3 remove compile-before-write   : 1 failed  -> DETECTED
no-rollback commit (결함3 변이)    : test_second_replace_failure_rolls_back FAIL -> DETECTED
```

---

## 10. test_d5b_strict_lag.py (로컬 실행)

- 패치 드라이버 대비 **15/15 PASS** (리졸버 fail-close + fetch-0 순서: 키부재 시 `main`이 `poll_and_collect` **전에** ValueError → 스파이 미호출).
- pristine(폴백 잔존 ≈ D1 뮤테이션) 드라이버 대비 **4 FAIL**(IBIT/비IBIT 키부재 raise·메시지·fetch-0) — 진짜 fail-close 계약이며 **D1(폴백 복원) 검출**을 로컬 증명.

---

## 11. 롤백·의존순서 (C6, applier 문서화)

- 적용순: **D3 → D5b** (H1/H3 앵커는 post-D3 드라이버·validator에 결속. pre-D3 트리에 D5b 단독 실행 시 앵커 미발견 → ABORT).
- **v3 롤백 시 D5b를 먼저 되돌려야 한다**: strict 드라이버가 IBIT lag 키 없는 v3 레지스트리를 만나면 IBIT 전면 중단.
- 백업: 공개 디렉터리 `.bak` 금지, 비공개 `/root/f29-backups/<UTC타임스탬프>/` + manifest(원본경로·소유자·권한·크기·변경전 SHA). Sonnet 반입 단계 소관.

---

## 12. HOLD 무변경 확인

레지스트리 정책·활성화·cron·crontab·외부수집·권리게이트(rights/kill_switch)·DB·ledger — **전부 무변경**. 라이브 레지스트리 v4 그대로. 본 D5b는 "키 부재 해석"만 바꾼다(폴백 0 → 하드 에러). 값 계약(명시 0=완료목표, 명시 null=관측전용, 음수·비정수 거부)은 불변.

---

## 13. Sonnet 반입(서버) 단계 — 로컬 불가 항목 (조작 금지, 실측 필수)

로컬에서 확정된 것: **test_registry_v4 = 77 passed**(validator 스위트, DB 불필요), test_d5b_apply_contract = 11 passed(양쪽 상태), test_d5b_strict_lag = 15 passed. 아래는 서버에서만 확정된다. 서버 pass 수를 **날조하지 말 것.**

1. **전체 pytest 실측.** 예상 산식(참고, Sonnet 확정): PRE-GATE 265 + registry_v4 순증(materialization −4·전이 +5·구조 +1 = +2, 단 라이브 하네스의 collect 수와 무관) + strict_lag 15 + apply_contract 11. 감리 산정과 정합하게 **최소 약 293 passed, 0 skipped** 예상. 절대값은 서버 collect로 확정.
2. **test_d3_target_lag.py 전체 실행** — 드라이버 collect/store(DB)·공휴일 경계 필요, 로컬 미실행(감리 서버 실행 = 35 passed 확인). test_registry_v4는 로컬 77 확정이나 서버 재확인 권장.
3. 행동 뮤테이션 **D2/D4/D7** 서버 확인: D2(값검증 제거)→값검증 테스트 FAIL / D4(명시 null→ValueError)→`test_explicit_none_is_observation_only` FAIL / D7(lag 체크를 fetch 뒤로)→`test_missing_key_refuses_before_any_fetch` FAIL. D1(폴백 복원)·D3(`_LEGACY_TICKER` 제거)은 로컬 선증명(D1=strict_lag 4 FAIL, D3=`_paths_for` 경로격리).
4. 백업 생성(`/root/f29-backups/<UTC>/` + manifest) + 의존순서 롤백(§11). 감리 2라운드 상한 유지.

---

## 14. production 변경 누적

- 본 세션: **0건** (`/mnt/user-data/outputs` 산출물만; VPS 접근 0회).
- 서버 반입은 GitHub raw(`jazzbit2002-dotcom`) → curl → apply(d5b_apply.py 또는 앵커 패치) → Sonnet 회귀. 감리 2라운드 상한 유지.

---

## 15. 감리 2차 반영 (HOLD 차단 결함 3건 처리)

감리 판정(HOLD, 서버 반입 금지) 대비 3건 전부 수정. OBSV 편차는 감리 **승인** — §7 유지.

| 감리 결함 | 조치 | 검증 |
|---|---|---|
| **결함1** test_registry_v4 1건 실패 (`test_ledger_isolation_marker_is_read_from_given_dir` — materialization 제거 후 NO_CHANGE인데 ERROR 기대) | GBTC null→0 REAL_CHANGE + `etf_gbtc_done.json` 유무로 T1↔PASS 분기(감리 처방 계약 그대로) | 로컬 **77 passed 0 failed**. 수정 전 로컬 재현 = 감리와 동일 1건 실패(환경 패리티) |
| **결함2** `inspect.getsource` 구조 회귀 테스트 미구현(수동 확인만) | `test_materialization_contract_is_absent_from_validator` 신설 — 실제 모듈 import 후 `inspect.getsource(V)`로 3토큰 부재 단언 | 로컬 PASS (77 passed에 포함) |
| **결함3** applier 2파일 원자 아님(2번째 `os.replace` 실패 시 부분 적용) | handled I/O all-or-rollback으로 재작성(전 temp 선작성·원본 스냅샷·교체 실패 시 복원·temp 제거·비정상 종료) + 문구 정정 | `test_second_replace_failure_rolls_back` 신설·PASS(driver/validator SHA 불변·temp 0·rc≠0). 롤백 없는 변이에 대해 이 테스트가 실패 = 판별력 확인 |

**감리 요구 재제출 체크리스트 대응:**
- 갱신 파일 SHA·바이트 → §3 (변경 3파일)
- test_registry_v4 전건 PASS → 로컬 77 passed (서버 재확인 권장)
- applier 계약 pre/post 양쪽 PASS → 11/11 × 2 상태
- 새 실패주입 테스트 판별력 → §9 (no-rollback 변이 검출 확인)
- 구조 계약 테스트 → 결함2 신설
- 전체 예상 최소 약 293 passed 0 skipped → §13 (서버 확정)
- 행동 뮤테이션 재검증 → §13 (D1·D3 로컬 선증명 / D2·D4·D7 서버)

**무변경 재확인:** 기존 33건(test_etf_issuer), D4 격리(test_d4_ticker_isolation), live registry, collector, registry config, cron, DB, ledger — 전부 변경 금지 준수. GBTC 활성화·cron·외부수집·권리게이트 계속 HOLD.

---

## 16. 감리 3차 판정 = PASS (서버 스테이징 반입 승인, 2026-07-23)

- 승인 ZIP SHA256: `4e1bec84524195b5e4bd1f18e4b4fce05c45bcbe7cc17f886aac300712e88f8e` (구현·테스트 7파일 + 인도 보고서). 구현 7파일 지문 = §3 표와 전건 일치, **동결**(반입 절차 SHA 확인 대상).
- 차단 결함 3건 전건 해소 확인. OBSV 편차 최종 승인. 감리 독립 회귀: registry_v4 77 / strict_lag 15 / apply_contract 11 / test_d3 35 = **138 passed**. 상태 무관 fixture 역구성도 감리 직접 재현.

**비차단 기록 2건 (감리 지적):**
1. 인도 보고서 §1 표의 "2파일 원자 applier" 표현 스테일 → 본 개정에서 "2파일 handled-I/O all-or-rollback applier"로 정정(§1). 코드·§9 상세는 이미 정확했음. **구현 7파일 SHA 불변**(문서만 정정).
2. staging 단계(2번째 temp의 write/`chmod`)가 실패하면 라이브 파일은 무변경이나 생성 중이던 `.d5b.tmp` 1개가 남을 수 있음 — **교체 단계 부분적용과 별개, 운영 파일 손상 없음.** 감리 판정 = 이번 일회성 applier·사전 백업 기준에서 **비차단**(승인본 코드 무접촉 유지). **Sonnet 절차 필수 체크**: 실행 전후 `*.d5b.tmp` 0 확인, 발생 시 즉시 중단.

**서버 수용 기준 (Sonnet 실측 확정):** D5a-2 기준선 = 265 passed → 최종 기대 **293 passed, 0 skipped, pytest_rc=0**. 반입 전 게이트: 라이브 registry `fe42a4a4…` / 전 issuer lag 키 존재 / IBIT 원시 lag 키·int·0·helper 0 / 기준선 265 / cron_ibit 2·cron_etf 0·GBTC·FBTC·ARKB cron 0 / ledger `*.d5b.tmp` 0 / GBTC DB·ledger 산출물 0. 반입: 백업 → 승인본 SHA 확인 → `--check` → apply → 7파일 py_compile → 전체 pytest.

**행동 뮤테이션(서버):** D2(missing-key→None 복원)→missing-key 테스트 FAIL / D4(명시 null 차단)→observation-only 테스트 FAIL / D7(lag 검사 fetch 이후)→fetch-0 테스트 FAIL.

**롤백 규율:** 실패 시 부분 롤백 금지 — driver·validator·관련 테스트를 백업 묶음으로 전량 복원. v3 registry 롤백 시 **D5b를 먼저** 롤백(strict driver + v3 = IBIT 수집 정지).

**최종 비준 조건:** 서버 293 passed + 적용 후 다음 정규 IBIT 슬롯의 A~D 4분기 정합 실증. 그때까지 GBTC 활성화·cron 설치·외부수집·권리게이트 HOLD.
