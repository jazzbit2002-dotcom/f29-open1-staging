#!/usr/bin/env python3
# us_p1_map40_v3_1.py -- US P1 benchmark selection mapping (READ-ONLY, 40 rows)
#
# v3.1 corrections (audit 2026-07-22, two blocking defects in v3):
#   D1 v3 derived reference_date as max(last bars) over the files it read.
#      If every stock AND benchmark were stale at the same old date, the file
#      set validated against itself and reported PASS -- the exact failure
#      mode of the 2026-07-20 GATE_PRICE PASS. v3.1 REQUIRES an explicit
#      --reference-date and puts freshness_equal in the invariant set.
#   D2 v3 treated a missing/!unreadable closes file as insufficient_bars and
#      excluded it from the denominator, so deleting a file produced PASS.
#      Denominator exclusion is only for a READABLE file whose real bar count
#      is under 60 (SPCX at 24). Missing or schema-broken files are data
#      defects and now count as other_fail_closed.
#
# v3 (kept): eligibility denominator, stock_last_bar / eligible /
#            freshness_equal columns.
# v2 (kept): fixed master schema, no sniffing.
#
# Source of truth: /root/moneyflow/posradar_master.json ["stocks"] list[40]
#   {ticker, active_primary, secondary}   (secondary, NOT active_secondary)
#   consumer: positions.py:199
#
# Contract (Sky 2026-07-20, P+S fixed fallback):
#   1st active_primary -> 2nd secondary -> else FAIL_CLOSED (no price-only)
#   match = last 60 dates identical to the stock's last 60 dates
#
# Invariants (exit 2 if violated):
#   rows                == 40
#   selected_benchmark  == eligible_rows
#   dates_equal         == eligible_rows
#   freshness_equal     == eligible_rows
#   other_fail_closed   == 0
#
# No writes. No network. Stdout only. Pure ASCII. Stdlib only.

import argparse, json, os, sys

N_LAST = 60
MASTER = "/root/moneyflow/posradar_master.json"
CLOSES = "/var/www/f29-pattern-lab/data/closes"


def die(code, msg):
    sys.stdout.write("FATAL: %s\n" % msg)
    sys.exit(code)


def load_json(path):
    if not os.path.isfile(path):
        die(3, "file not found: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError as e:
            die(3, "invalid json: %s (%s)" % (path, e))


def extract_stocks(m, path):
    if not isinstance(m, dict):
        die(3, "schema: top level is %s, expected object (%s)" % (type(m).__name__, path))
    if "stocks" not in m:
        die(3, "schema: no 'stocks' key. top keys = %s" % list(m)[:10])
    recs = m["stocks"]
    if not isinstance(recs, list):
        die(3, "schema: 'stocks' is %s, expected list" % type(recs).__name__)
    for idx, r in enumerate(recs):
        if not isinstance(r, dict):
            die(3, "schema: stocks[%d] is %s, expected object" % (idx, type(r).__name__))
        missing = [k for k in ("ticker", "active_primary", "secondary") if k not in r]
        if missing:
            die(3, "schema: stocks[%d] (%s) missing %s"
                % (idx, r.get("ticker", "?"), ",".join(missing)))
    return recs


def read_dates(closes_dir, name):
    path = os.path.join(closes_dir, "%s.json" % name)
    if not os.path.isfile(path):
        return None, 0, "no_file"
    j = load_json(path)
    dates = j.get("dates")
    if not isinstance(dates, list) or not dates:
        return None, 0, "no_dates_key"
    return dates, len(dates), "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--closes-dir", default=CLOSES)
    ap.add_argument("--reference-date", required=True,
                    help="expected latest trading day, e.g. 2026-07-21. "
                         "Taken from the natural build_core run, not inferred.")
    a = ap.parse_args()

    ref_date = a.reference_date.strip()
    if not ref_date:
        die(3, "--reference-date is empty")
    if not os.path.isdir(a.closes_dir):
        die(3, "closes dir not found: %s" % a.closes_dir)

    recs = extract_stocks(load_json(a.master), a.master)

    sys.stdout.write("MASTER          %s\n" % a.master)
    sys.stdout.write("CLOSES          %s\n" % a.closes_dir)
    sys.stdout.write("REFERENCE_DATE  %s   (explicit argument, not derived)\n\n" % ref_date)

    header = ["ticker", "active_primary", "secondary",
              "selected_benchmark", "selection_reason",
              "stock_n", "stock_last_bar", "eligible", "freshness_equal",
              "benchmark_n", "dates_equal"]
    sys.stdout.write("\t".join(header) + "\n")

    rows = n_primary = n_secondary = n_eq = 0
    n_eligible = n_insuff = n_other_fail = n_fresh = 0
    observed_lasts = []
    fallback_detail = []
    insuff_detail = []
    stale_detail = []
    missing_detail = []

    def emit(*cells):
        sys.stdout.write("\t".join(str(c) for c in cells) + "\n")

    for rec in recs:
        rows += 1
        ticker = str(rec["ticker"])
        prim = rec["active_primary"]
        sec = rec["secondary"]

        s_dates, s_n, s_st = read_dates(a.closes_dir, ticker)

        # D2: missing / schema-broken closes is a DATA DEFECT, not a
        #     "still accumulating" state. It never leaves the denominator
        #     quietly; it counts as other_fail_closed.
        if s_st != "ok":
            n_other_fail += 1
            missing_detail.append("%s:%s" % (ticker, s_st))
            emit(ticker, prim, sec, "FAIL_CLOSED", "stock_closes_%s" % s_st,
                 s_n, "-", "false", "n/a", 0, "n/a")
            continue

        s_last = s_dates[-1]
        observed_lasts.append(s_last)
        fresh = (s_last == ref_date)

        if s_n < N_LAST:
            n_insuff += 1
            insuff_detail.append("%s:n=%d" % (ticker, s_n))
            emit(ticker, prim, sec, "INSUFFICIENT_BARS", "bars_lt_60",
                 s_n, s_last, "false", str(fresh).lower(), 0, "n/a")
            continue

        n_eligible += 1
        if fresh:
            n_fresh += 1
        else:
            stale_detail.append("%s:%s" % (ticker, s_last))

        s_tail = s_dates[-N_LAST:]
        selected = reason = None
        b_n = 0
        dates_equal = "false"
        why_not_primary = None

        for cand, tag in ((prim, "primary"), (sec, "secondary_fallback")):
            if not cand:
                if tag == "primary":
                    why_not_primary = "primary_null"
                continue
            b_dates, bn, b_st = read_dates(a.closes_dir, str(cand))
            if b_st != "ok":
                if tag == "primary":
                    why_not_primary = "primary_%s" % b_st
                continue
            if b_dates[-N_LAST:] == s_tail:
                selected, reason, b_n, dates_equal = str(cand), tag, bn, "true"
                break
            if tag == "primary":
                why_not_primary = "primary_dates_mismatch"

        if selected is None:
            selected, reason = "FAIL_CLOSED", "both_failed"
            n_other_fail += 1
        else:
            n_eq += 1
            if reason == "primary":
                n_primary += 1
            else:
                n_secondary += 1
                fallback_detail.append("%s:%s" % (ticker, why_not_primary or "primary_unavailable"))

        emit(ticker, prim, sec, selected, reason,
             s_n, s_last, "true", str(fresh).lower(), b_n, dates_equal)

    n_sel = n_primary + n_secondary
    obs_max = max(observed_lasts) if observed_lasts else "n/a"

    sys.stdout.write("\n== SUMMARY ==\n")
    sys.stdout.write("reference_date         %s   (argument)\n" % ref_date)
    sys.stdout.write("observed_max_last_bar  %s   (observation only)\n" % obs_max)
    sys.stdout.write("rows                   %d\n" % rows)
    sys.stdout.write("eligible_rows          %d\n" % n_eligible)
    sys.stdout.write("insufficient_bars_rows %d\n" % n_insuff)
    sys.stdout.write("selected_benchmark     %d/%d\n" % (n_sel, n_eligible))
    sys.stdout.write("dates_equal            %d/%d\n" % (n_eq, n_eligible))
    sys.stdout.write("freshness_equal        %d/%d\n" % (n_fresh, n_eligible))
    sys.stdout.write("other_fail_closed      %d\n" % n_other_fail)
    sys.stdout.write("primary                %d   (observation)\n" % n_primary)
    sys.stdout.write("secondary_fallback     %d   (observation)\n" % n_secondary)
    sys.stdout.write("new_api_requests       0   (script performs no network I/O)\n")
    if missing_detail:
        sys.stdout.write("missing_or_invalid     %s\n" % " ".join(missing_detail))
    if insuff_detail:
        sys.stdout.write("insufficient_detail    %s\n" % " ".join(insuff_detail))
    if stale_detail:
        sys.stdout.write("stale_detail           %s\n" % " ".join(stale_detail))
    if fallback_detail:
        sys.stdout.write("fallback_detail        %s\n" % " ".join(fallback_detail))

    bad = []
    if rows != 40:
        bad.append("rows!=40 (%d)" % rows)
    if n_eligible == 0:
        bad.append("eligible_rows=0")
    if n_sel != n_eligible:
        bad.append("selected %d/%d" % (n_sel, n_eligible))
    if n_eq != n_eligible:
        bad.append("dates_equal %d/%d" % (n_eq, n_eligible))
    if n_fresh != n_eligible:
        bad.append("freshness_equal %d/%d" % (n_fresh, n_eligible))
    if n_other_fail != 0:
        bad.append("other_fail_closed=%d" % n_other_fail)

    if bad:
        sys.stdout.write("INVARIANT: FAIL  [%s]\n" % "; ".join(bad))
        sys.exit(2)
    sys.stdout.write("INVARIANT: PASS\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
