#!/usr/bin/env python3
# F29 v7.2 contract regression - PATCH_REGRESSION_9 + BASELINE_NON_REGRESSION_3
# Run on server (needs brief_contract_v1_1.py + schema + context in /root/moneyflow):
#   cd /root/moneyflow && python3 regress_v72.py
#
# Ratified 9 cases (감리 2026-07-22) prove: substring false-positive removed,
#   body<->themes removed, body<->ticker two-way removed, exact ticker/theme
#   membership kept, article length ceiling boundary.
# Baseline 3 cases prove no regression of digest-required / forbidden / number-unit.
#
# Each fixture is valid EXCEPT the single condition under test, so a FAIL cannot
# leak from an unrelated missing field.

import importlib.util, json, copy, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BC = os.path.join(HERE, "brief_contract_v1_1.py")
CTX = os.path.join(HERE,
    "briefing_delivery/evidence/20260721T073716Z-89a6fcde/briefing_context_raw.json")

spec = importlib.util.spec_from_file_location("bc", BC)
bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)

context = json.load(open(CTX, encoding="utf-8"))
AS_OF = "2026-07-20"   # matches close_snapshot as_of in that evidence
DISC = ("이 글은 시장 구조를 분석한 참고 자료이며 투자 권유가 아닙니다. "
        "투자 판단과 그 결과에 대한 책임은 본인에게 있습니다.")

# real universe members (measured from context)
T_OK = "AMD"          # in allowed_tickers
THEME_OK = "반도체"    # in allowed_themes
THEME_OK2 = "반도체장비"
THEME_OK3 = "금융"


def pad(base, target):
    """Return a body string of exactly target chars, starting from base."""
    filler = "이 문장은 분량 경계를 맞추기 위한 서술이며 시장의 흐름을 설명합니다. "
    s = base
    while len(s) < target:
        s += filler
    return s[:target]


def valid_brief():
    """A minimal fully-valid ready brief: digest usable -> rotation &
    value_chain_radar required, present. No forbidden words, exact disclaimer."""
    body = ("미국장 마감 시점 기준으로 시장의 선택은 일부 업종에 집중된 모습이었습니다. "
            "지수 흐름보다 그 안에서 무엇이 앞섰는지가 더 중요했던 하루로 정리할 수 있습니다. "
            "전반적으로 큰 쏠림 없이 균형을 이룬 구성이었습니다.")
    rot = ("관심도 상위에는 금융이 자리했고 시간 축을 나누면 단기와 중장기 주도축이 서로 "
           "달랐습니다. 이런 어긋남은 시장의 선택이 옮겨가는 흐름으로 읽을 수 있습니다. "
           "며칠에 걸쳐 확인할 지점입니다.")
    vcr = ("산업 계열 안을 들여다보면 강약 차이가 뚜렷했습니다. 같은 우산 아래에서도 "
           "앞선 축과 뒤처진 축이 갈렸습니다. 개별 종목 단위에서도 결과가 나뉘었습니다.")
    nxt = ("다음 거래일에는 상위 흐름이 이어지는지 확인할 수 있습니다. 조건이 유지되는지 "
           "그리고 무효화되는지를 함께 살피는 것이 관건입니다.")
    return {
        "schema_version": "us_macro_brief_v1_1",
        "as_of": AS_OF,
        "headline": "지수보다 내부의 갈림이 컸던 하루였습니다",
        "deck": "시장 체력은 유지됐지만 같은 업종 안에서도 종목별 결과가 갈렸습니다.",
        "key_points": [
            "신고가 종목과 상승 거래량이 모두 앞서 시장 체력은 유지됐습니다.",
            "단기 강세축과 장기 주도축이 서로 다른 방향을 보였습니다.",
            "같은 산업 안에서도 종목별 상대강도 격차가 벌어졌습니다.",
        ],
        "sections": [
            {"id": "conclusion", "title": "오늘의 결론", "body": body,
             "tickers": [], "themes": [THEME_OK3]},
            {"id": "breadth", "title": "시장 체력과 스타일",
             "body": "신고가 종목이 신저가보다 많았고 상승 거래량이 앞섰습니다. "
                     "표면 아래에서도 오른 종목의 체결이 우위였습니다. 장기 추세는 유지됐습니다.",
             "tickers": [], "themes": []},
            {"id": "rotation", "title": "시장의 선택이 옮겨간 곳", "body": rot,
             "tickers": [], "themes": [THEME_OK3]},
            {"id": "value_chain_radar", "title": "산업 안의 강약", "body": vcr,
             "tickers": [T_OK], "themes": [THEME_OK, THEME_OK2]},
            {"id": "size_style", "title": "대형주와 소형주",
             "body": "대형주가 소형주를 앞섰고 시총가중이 동일가중보다 우위였습니다. "
                     "지수 상승이 규모가 큰 쪽에 기운 구성이었습니다. 폭은 넓지 않았습니다.",
             "tickers": [], "themes": []},
            {"id": "next_session", "title": "다음 거래일 확인", "body": nxt,
             "tickers": [], "themes": []},
        ],
        "watchpoints": ["금융이 상위 흐름을 유지하는지 확인할 지점입니다."],
        "social_summary": ("미국장은 지수보다 내부의 갈림이 컸던 하루였습니다. "
                           "시장 체력은 유지됐지만 같은 업종 안에서도 결과가 갈렸습니다."),
        "email_subject": "지수보다 내부 갈림이 컸던 미국장",
        "email_preview": "시장 체력은 유지됐지만 종목별 결과가 갈렸습니다.",
        "disclaimer": DISC,
    }


def run(brief):
    r = bc.validate_brief(brief, context, "ready", AS_OF)
    return r.to_dict()["violations"]


# sanity: the baseline valid brief must pass clean
_base_v = run(valid_brief())
if _base_v:
    print("FATAL: valid_brief() is not clean:")
    for v in _base_v:
        print("  -", v)
    sys.exit(2)


def art_len(b):
    return len(bc.article_text(b))


# ---------------------------------------------------------------- cases

def c1():   # 헬스케어만 -> 헬스 오탐 없음 (PASS)
    b = valid_brief()
    b["sections"][0]["body"] += " 헬스케어 관련 종목이 견조했습니다."
    return "PASS", run(b)

def c2():   # 반도체장비만 -> 반도체 오탐 없음 (PASS)
    b = valid_brief()
    b["sections"][3]["body"] += " 반도체장비 쪽 흐름이 앞섰습니다."
    b["sections"][3]["themes"] = [THEME_OK2]   # 장비만 태그
    return "PASS", run(b)

def c3():   # themes에 SOURCE 외 문자열 -> FAIL
    b = valid_brief()
    b["sections"][2]["themes"] = ["존재하지않는테마"]
    return "FAIL", run(b)

def c4():   # tickers에 시장지표 -> FAIL
    b = valid_brief()
    b["sections"][0]["tickers"] = ["SPY", "DXY", "CL1"]
    return "FAIL", run(b)

def c5():   # 허용 개별종목 -> PASS
    b = valid_brief()
    b["sections"][3]["tickers"] = [T_OK, "AVGO"]
    b["sections"][3]["body"] += " AMD와 AVGO가 관련 흐름에서 언급됩니다."
    return "PASS", run(b)

def c6():   # 허용 ticker가 본문에 문자 그대로 없어도 PASS (body<->ticker 제거 증명)
    b = valid_brief()
    b["sections"][3]["tickers"] = ["ARM"]        # body에 ARM/에이알엠 없음
    return "PASS", run(b)

def c7():   # 본문에 기업명 있고 tickers 빈 배열 -> PASS (역대조 제거 증명)
    b = valid_brief()
    b["sections"][3]["body"] += " 엔비디아와 AMD가 시장을 앞섰습니다."
    b["sections"][3]["tickers"] = []
    return "PASS", run(b)

def c8():   # ready 3200자 -> PASS
    b = valid_brief()
    cur = art_len(b)
    need = 3200 - cur + len(b["sections"][1]["body"])
    b["sections"][1]["body"] = pad(b["sections"][1]["body"], need)
    assert art_len(b) == 3200, art_len(b)
    return "PASS", run(b)

def c9():   # ready 3201자 -> FAIL
    b = valid_brief()
    cur = art_len(b)
    need = 3201 - cur + len(b["sections"][1]["body"])
    b["sections"][1]["body"] = pad(b["sections"][1]["body"], need)
    assert art_len(b) == 3201, art_len(b)
    return "FAIL", run(b)

# baseline non-regression

def a_digest():   # digest usable인데 value_chain_radar 누락 -> FAIL
    b = valid_brief()
    b["sections"] = [s for s in b["sections"] if s["id"] != "value_chain_radar"]
    return "FAIL", run(b)

def b_forbidden():   # 금칙어 -> FAIL
    b = valid_brief()
    b["sections"][0]["body"] += " 지금이 매수 추천 시점입니다."
    return "FAIL", run(b)

def c_numunit():   # 숫자+단위 충돌 (social이 본문에 없는 수치 도입) -> FAIL
    b = valid_brief()
    b["social_summary"] = ("미국장 요약입니다. 200일선 위 비율이 69%p로 집계됐고 "
                           "같은 업종 안에서도 결과가 갈렸습니다.")
    return "FAIL", run(b)


PATCH = [("1 헬스케어만", c1), ("2 반도체장비만", c2), ("3 themes 외부문자열", c3),
         ("4 tickers 시장지표", c4), ("5 허용종목 ticker", c5),
         ("6 허용ticker 본문없음", c6), ("7 기업명+빈tickers", c7),
         ("8 ready 3200", c8), ("9 ready 3201", c9)]
BASELINE = [("A digest 필수절 누락", a_digest), ("B 금칙어", b_forbidden),
            ("C 숫자단위 충돌", c_numunit)]


def report(group, cases):
    ok = 0
    for name, fn in cases:
        want, vio = fn()
        got = "FAIL" if vio else "PASS"
        mark = "OK" if got == want else "MISMATCH"
        if got == want:
            ok += 1
        print("  [%-8s] %-22s want=%-4s got=%-4s" % (mark, name, want, got))
        if mark == "MISMATCH":
            for v in vio[:6]:
                print("        -", v)
    print("  => %s %d/%d PASS" % (group, ok, len(cases)))
    return ok, len(cases)


print("=== PATCH_REGRESSION_9 ===")
p_ok, p_n = report("patch_regression", PATCH)
print()
print("=== BASELINE_NON_REGRESSION_3 ===")
b_ok, b_n = report("baseline_regression", BASELINE)
print()
print("patch_regression    %d/%d PASS" % (p_ok, p_n))
print("baseline_regression %d/%d PASS" % (b_ok, b_n))
print("total               %d/%d PASS" % (p_ok + b_ok, p_n + b_n))
sys.exit(0 if (p_ok + b_ok) == (p_n + b_n) else 1)
