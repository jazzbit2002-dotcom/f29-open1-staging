#!/usr/bin/env python3
# F29 LOCAL REVIEW VIEWER (2026-07-18)
# Derived artifact only. Reads evidence/<run_id>/{evidence.json, response.txt, briefing_context_raw.json}
# Writes evidence/<run_id>/review.html + review/index.html + review/latest.html
# Constraints: single file HTML, no external CSS/JS/CDN, full escaping,
#              never modifies canonical files, no public web root, no nginx, no cron.

import os, re, json, html, sys, shutil

BASE = "/root/moneyflow/briefing_delivery"
EVIDIR = os.path.join(BASE, "evidence")
REVDIR = os.path.join(BASE, "review")

INTERNAL = ["F29", "briefing-context", "market_internals", "market_close_snapshot",
            "market_close_comparison", "lifecycle", "freshness", "theme_flow", "intraday"]
FORBIDDEN = ["매수 추천", "매도 신호", "목표가", "손절", "순유입", "순유출",
             "진입", "청산", "예측", "적중", "신뢰도", "적중률"]
BADPHRASE = ["공식 종가", "settlement", "확정 종가", "공식 일일"]
DISCLAIMER = "투자 권유가 아닙니다"
REL_TERMS = ["상대", "대비", "%p", "더 약", "더 강", "잘 버"]

CSS = """
:root{--bg:#0A0E17;--card:#131A28;--line:#1F2A3D;--txt:#E8EDF7;--txt2:#8B9AB5;
--txt3:#5A6B84;--teal:#3DD8B0;--gold:#D8B45F;--red:#F0997B}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);line-height:1.6;
font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:20px}
h1{font-size:18px;color:var(--teal);margin-bottom:4px}
.sub{font-size:12px;color:var(--txt3);margin-bottom:18px}
.card{background:var(--card);border-radius:10px;padding:14px 16px;margin-bottom:16px}
.card h2{font-size:12px;color:var(--txt3);text-transform:uppercase;letter-spacing:.08em;
padding-bottom:8px;border-bottom:.5px solid var(--line);margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td{padding:5px 0;border-bottom:.5px solid var(--line);vertical-align:top}
td:first-child{color:var(--txt2);width:40%}
td.mono,.mono{font-family:ui-monospace,Menlo,monospace;font-size:11px;word-break:break-all}
.chk{font-size:13px;padding:6px 0;border-bottom:.5px solid var(--line)}
.chk:last-child{border-bottom:none}
.ok{color:var(--teal)}.warn{color:var(--gold)}.bad{color:var(--red)}
.body{white-space:pre-wrap;font-size:14.5px;line-height:1.85}
a{color:var(--teal);text-decoration:none}
.idx td{font-size:12.5px}
.note{font-size:11px;color:var(--txt3);margin-top:14px;line-height:1.7}
"""


def eligible_for_latest(ev):
    """latest.html 후보 자격. 개별 review.html은 응답만 있으면 생성하되,
    latest는 아래를 모두 통과한 run만 갱신한다."""
    return (ev.get("stop_reason") == "end_turn"
            and ev.get("close_snapshot_state") == "fresh"
            and ev.get("daily_state") == "fresh"
            and ev.get("comparison_status") in {"baseline_only", "ready"}
            and bool(ev.get("output_sha256")))


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def sentences(t):
    # split on sentence-ending punctuation, but NOT on decimal points (743.23)
    return [x for x in re.split(r"(?<!\d)[.!?](?!\d)|\n+", t) if x and x.strip()]


def run_checks(text, ev, raw, rd=None):
    out = []

    # integrity: re-hash canonical files and compare with recorded SHA
    if rd:
        import hashlib
        for fn, key in (("response.txt", "output_sha256"), ("prompt.txt", "prompt_sha256")):
            fp = os.path.join(rd, fn)
            rec = ev.get(key)
            if os.path.isfile(fp) and rec:
                actual = hashlib.sha256(open(fp, "rb").read()).hexdigest()
                same = (actual == rec)
                out.append(("%s SHA 대조" % fn, "일치" if same else "불일치(변조 의심)",
                            "ok" if same else "bad"))

    n = len(text)
    ok = 1500 <= n <= 2500
    out.append(("분량", "%d자" % n, "ok" if ok else "warn"))

    sr = ev.get("stop_reason")
    out.append(("stop_reason", str(sr), "ok" if sr == "end_turn" else "bad"))

    hits = [w for w in INTERNAL if w in text]
    out.append(("내부 명칭 노출", "0건" if not hits else "위반 " + ", ".join(hits),
                "ok" if not hits else "bad"))

    fh = [w for w in FORBIDDEN if w in text]
    out.append(("금칙어 12종", "0건" if not fh else "위반 " + ", ".join(fh),
                "ok" if not fh else "bad"))

    bh = [w for w in BADPHRASE if w in text]
    out.append(("금지 표현", "0건" if not bh else "위반 " + ", ".join(bh),
                "ok" if not bh else "bad"))

    tbl = ("|---" in text) or ("|--" in text)
    out.append(("표 사용", "없음" if not tbl else "발견", "ok" if not tbl else "bad"))

    dis = DISCLAIMER in text
    out.append(("면책 문구", "있음" if dis else "없음", "ok" if dis else "bad"))

    # absolute level comparison heuristic:
    # flag sentences containing 2+ distinct close-snapshot level values
    lv = []
    try:
        cs = ((raw or {}).get("market_internals") or {}).get("market_close_snapshot") or {}
        for v in (cs.get("data") or {}).values():
            s = ("%g" % float(v))
            if len(s) >= 3:
                lv.append(s)
    except Exception:
        pass
    flagged = 0
    if lv:
        for s in sentences(text):
            if sum(1 for x in set(lv) if x in s) >= 2:
                flagged += 1
    out.append(("절대 레벨값 2개 이상 동시 등장 문장", "%d건" % flagged,
                "ok" if flagged == 0 else "warn"))

    # relative performance usage (positive check when comparison ready)
    if ev.get("comparison_status") == "ready":
        rel = sum(1 for w in REL_TERMS if w in text)
        out.append(("상대 비교 표현", "%d종 사용" % rel, "ok" if rel >= 2 else "warn"))
    else:
        out.append(("비교 상태", str(ev.get("comparison_status")), "warn"))

    return out


def render_review(run_id, ev, text, raw, comparison, rd=None):
    checks = run_checks(text, ev, raw, rd)
    rows = [
        ("현재 기준일", ev.get("current_as_of")),
        ("비교 기준일", ev.get("previous_as_of") or "없음 (baseline)"),
        ("비교 상태", ev.get("comparison_status")),
        ("수집 시각", ev.get("fetch_started_at")),
        ("원천 generated", ev.get("source_generated_at")),
        ("모델", ev.get("model")),
        ("input_tokens", ev.get("input_tokens")),
        ("output_tokens", ev.get("output_tokens")),
        ("cache_read / creation", "%s / %s" % (ev.get("cache_read_input_tokens"),
                                               ev.get("cache_creation_input_tokens"))),
        ("실측 비용", "$%s" % ev.get("cost_usd")),
        ("close_snapshot 상태", ev.get("close_snapshot_state")),
        ("daily 상태", ev.get("daily_state")),
        ("스냅샷 저장", ev.get("snapshot_store_status")),
    ]
    sha_rows = [
        ("snapshot_sha256", ev.get("snapshot_sha256")),
        ("prompt_sha256", ev.get("prompt_sha256")),
        ("output_sha256", ev.get("output_sha256")),
        ("close_snapshot_data_sha256", ev.get("close_snapshot_data_sha256")),
    ]

    def tr(k, v, mono=False):
        return "<tr><td>%s</td><td%s>%s</td></tr>" % (
            esc(k), ' class="mono"' if mono else "", esc(v))

    chk_html = "".join(
        '<div class="chk"><span class="%s">%s</span> %s <span class="%s">%s</span></div>'
        % (c[2], "PASS" if c[2] == "ok" else ("WARN" if c[2] == "warn" else "FAIL"),
           esc(c[0]), c[2], esc(c[1]))
        for c in checks)

    cmp_html = ""
    mc = (comparison or {}).get("market_close_comparison") or {}
    if mc.get("status") == "ready":
        def block(title, dct, unit):
            if not dct:
                return ""
            items = "".join("<tr><td>%s</td><td>%s%s</td></tr>" % (esc(k), esc(v), esc(unit))
                            for k, v in sorted(dct.items()))
            return "<h2>%s</h2><table>%s</table>" % (esc(title), items)
        vol = mc.get("volatility_change") or {}
        volflat = {k: "%s p (%s%%)" % (v.get("points"), v.get("pct")) for k, v in vol.items()}
        cmp_html = ('<div class="card">'
                    + block("상대수익률 (%p)", mc.get("relative_performance_pct") or {}, "")
                    + block("가격 변화율 (%)", mc.get("price_change_pct") or {}, "")
                    + block("금리 변화 (bp)", mc.get("rate_change_bp") or {}, "")
                    + block("변동성 변화", volflat, "")
                    + "</div>")

    return """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>검수 %s</title><style>%s</style></head><body><div class="wrap">
<h1>미국장 매크로 데일리 초안 검수</h1>
<div class="sub">run_id %s &nbsp;|&nbsp; 내부 검수용 파생 문서. 게시물 아님.</div>
<div class="card"><h2>실행 정보</h2><table>%s</table></div>
<div class="card"><h2>무결성</h2><table>%s</table></div>
<div class="card"><h2>자동 검사 (검수자 참고용, 품질 판정 아님)</h2>%s</div>
%s
<div class="card"><h2>초안 전문</h2><div class="body">%s</div></div>
<div class="note">response.txt와 evidence.json이 정본이며 이 HTML은 파생 산출물입니다.
언제든 재생성 가능하며 정본을 수정하지 않습니다.</div>
</div></body></html>""" % (
        esc(run_id), CSS, esc(run_id),
        "".join(tr(k, v) for k, v in rows),
        "".join(tr(k, v, True) for k, v in sha_rows),
        chk_html, cmp_html, esc(text))


def render_index(runs):
    rows = "".join(
        '<tr><td><a href="runs/%s.html">%s</a></td><td>%s</td><td>%s</td>'
        '<td>%s</td><td>$%s</td><td>%s자</td><td>%s</td></tr>'
        % (esc(r["run_id"]), esc(r["run_id"][:15]), esc(r["ev"].get("current_as_of")),
           esc(r["ev"].get("previous_as_of") or "-"), esc(r["ev"].get("comparison_status")),
           esc(r["ev"].get("cost_usd")), esc(r["ev"].get("output_chars")),
           "적격" if r["eligible"] else "부적격")
        for r in runs)
    return """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>초안 검수 목록</title><style>%s</style></head><body><div class="wrap">
<h1>미국장 매크로 데일리 초안 검수 목록</h1>
<div class="sub">총 %d건 &nbsp;|&nbsp; 내부 검수용. 게시물 아님.</div>
<div class="card"><table class="idx">
<tr><td>run_id</td><td>기준일</td><td>비교일</td><td>상태</td><td>비용</td><td>분량</td><td>latest 자격</td></tr>
%s</table></div>
<div class="note">최근 검수본은 latest.html 입니다.</div>
</div></body></html>""" % (CSS, len(runs), rows)


def main():
    if not os.path.isdir(EVIDIR):
        print("no evidence dir:", EVIDIR); return 1
    os.makedirs(REVDIR, exist_ok=True)

    runs = []
    for rid in sorted(os.listdir(EVIDIR)):
        rd = os.path.join(EVIDIR, rid)
        ep = os.path.join(rd, "evidence.json")
        rp = os.path.join(rd, "response.txt")
        if not (os.path.isfile(ep) and os.path.isfile(rp)):
            continue
        ev = json.load(open(ep, encoding="utf-8"))
        text = open(rp, encoding="utf-8").read()
        raw = None
        cmpj = None
        try:
            raw = json.load(open(os.path.join(rd, "briefing_context_raw.json"), encoding="utf-8"))
        except Exception:
            pass
        try:
            cmpj = json.load(open(os.path.join(rd, "comparison.json"), encoding="utf-8"))
        except Exception:
            pass
        h = render_review(rid, ev, text, raw, cmpj, rd)
        tmp = os.path.join(rd, "review.html.tmp")
        open(tmp, "w", encoding="utf-8").write(h)
        os.replace(tmp, os.path.join(rd, "review.html"))
        # portable copy: review/runs/<run_id>.html (derived artifact only)
        rundir = os.path.join(REVDIR, "runs")
        os.makedirs(rundir, exist_ok=True)
        tmp2 = os.path.join(rundir, rid + ".html.tmp")
        open(tmp2, "w", encoding="utf-8").write(h)
        os.replace(tmp2, os.path.join(rundir, rid + ".html"))
        runs.append({"run_id": rid, "ev": ev, "html": h, "eligible": eligible_for_latest(ev)})
        print("review.html ->", os.path.join(rd, "review.html"),
              "| runs/%s.html" % rid, "| latest자격:", "O" if eligible_for_latest(ev) else "X")

    if not runs:
        print("no successful runs found"); return 0

    runs.sort(key=lambda r: r["run_id"], reverse=True)
    tmp = os.path.join(REVDIR, "index.html.tmp")
    open(tmp, "w", encoding="utf-8").write(render_index(runs))
    os.replace(tmp, os.path.join(REVDIR, "index.html"))
    print("index.html   ->", os.path.join(REVDIR, "index.html"))

    elig = [r for r in runs if r["eligible"]]
    if elig:
        tmp = os.path.join(REVDIR, "latest.html.tmp")
        open(tmp, "w", encoding="utf-8").write(elig[0]["html"])
        os.replace(tmp, os.path.join(REVDIR, "latest.html"))
        print("latest.html  ->", os.path.join(REVDIR, "latest.html"),
              "(run %s)" % elig[0]["run_id"])
    else:
        print("latest.html  -> 갱신 안 함 (적격 run 없음, 기존 latest 유지)")
    print("REVIEW BUILD: DONE (%d runs)" % len(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
