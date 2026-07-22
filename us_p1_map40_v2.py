#!/usr/bin/env python3
# us_p1_map40_v2.py -- US P1 benchmark selection mapping (READ-ONLY, 40 rows)
#
# v2 change vs v1: the master file and its schema are FIXED, not sniffed.
#   v1 read /root/moneyflow/positions_output.json with a tolerant walker and
#   silently produced 40 bogus FAIL_CLOSED rows because that file has no
#   benchmark fields at all. Tolerant parsing turned a wrong input into a
#   plausible-looking verdict. v2 fails loudly instead.
#
# Source of truth (measured 2026-07-22):
#   /root/moneyflow/posradar_master.json
#     ["stocks"] -> list[40] of {ticker, active_primary, secondary, ...}
#   consumer: positions.py:199  prim=st["active_primary"]; sec=st["secondary"]
#   NOTE the secondary key is "secondary", NOT "active_secondary".
#
# Contract (Sky ruling 2026-07-20, P+S fixed fallback):
#   1st: active_primary  -- closes file exists AND last-60 dates identical
#   2nd: secondary       -- only if primary absent/unaligned, same date check
#   both fail            -- FAIL_CLOSED (must be 0 in practice)
#
# Invariants (exit 2 if violated):
#   rows==40, selected 40/40, dates_equal 40/40, fail_closed==0
# primary/secondary split counts are OBSERVATIONS only (non-blocking).
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
    # FIXED schema. No sniffing, no fallback paths.
    if not isinstance(m, dict):
        die(3, "schema: top level is %s, expected object (%s)" % (type(m).__name__, path))
    if "stocks" not in m:
        die(3, "schema: no 'stocks' key. top keys = %s" % list(m)[:10])
    recs = m["stocks"]
    if not isinstance(recs, list):
        die(3, "schema: 'stocks' is %s, expected list" % type(recs).__name__)
    required = ("ticker", "active_primary", "secondary")
    for idx, r in enumerate(recs):
        if not isinstance(r, dict):
            die(3, "schema: stocks[%d] is %s, expected object" % (idx, type(r).__name__))
        missing = [k for k in required if k not in r]
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
    a = ap.parse_args()

    if not os.path.isdir(a.closes_dir):
        die(3, "closes dir not found: %s" % a.closes_dir)

    recs = extract_stocks(load_json(a.master), a.master)

    sys.stdout.write("MASTER  %s\n" % a.master)
    sys.stdout.write("CLOSES  %s\n\n" % a.closes_dir)

    header = ["ticker", "active_primary", "secondary",
              "selected_benchmark", "selection_reason",
              "stock_n", "benchmark_n", "dates_equal"]
    sys.stdout.write("\t".join(header) + "\n")

    rows = n_primary = n_secondary = n_fail = n_eq = 0
    fallback_detail = []
    ref_date = None

    for rec in recs:
        rows += 1
        ticker = str(rec["ticker"])
        prim = rec["active_primary"]
        sec = rec["secondary"]

        s_dates, s_n, s_st = read_dates(a.closes_dir, ticker)
        if s_st != "ok":
            sys.stdout.write("\t".join([ticker, str(prim), str(sec), "FAIL_CLOSED",
                                        "stock_closes_%s" % s_st, str(s_n), "0", "n/a"]) + "\n")
            n_fail += 1
            continue
        s_tail = s_dates[-N_LAST:]
        if ref_date is None:
            ref_date = s_tail[-1]

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
            if len(s_tail) == N_LAST and b_dates[-N_LAST:] == s_tail:
                selected, reason, b_n, dates_equal = str(cand), tag, bn, "true"
                break
            if tag == "primary":
                why_not_primary = "primary_dates_mismatch"

        if selected is None:
            selected, reason = "FAIL_CLOSED", "both_failed"
            n_fail += 1
        else:
            n_eq += 1
            if reason == "primary":
                n_primary += 1
            else:
                n_secondary += 1
                fallback_detail.append("%s:%s" % (ticker, why_not_primary or "primary_unavailable"))

        sys.stdout.write("\t".join([ticker, str(prim), str(sec), selected, reason,
                                    str(s_n), str(b_n), dates_equal]) + "\n")

    n_sel = n_primary + n_secondary

    sys.stdout.write("\n== SUMMARY ==\n")
    sys.stdout.write("reference_date       %s\n" % (ref_date or "n/a"))
    sys.stdout.write("rows                 %d\n" % rows)
    sys.stdout.write("selected_benchmark   %d/%d\n" % (n_sel, rows))
    sys.stdout.write("dates_equal          %d/%d\n" % (n_eq, rows))
    sys.stdout.write("primary              %d   (observation)\n" % n_primary)
    sys.stdout.write("secondary_fallback   %d   (observation)\n" % n_secondary)
    sys.stdout.write("fail_closed          %d\n" % n_fail)
    sys.stdout.write("new_api_requests     0   (script performs no network I/O)\n")
    if fallback_detail:
        sys.stdout.write("fallback_detail      %s\n" % " ".join(fallback_detail))

    bad = []
    if rows != 40:
        bad.append("rows!=40 (%d)" % rows)
    if n_sel != rows:
        bad.append("selected %d/%d" % (n_sel, rows))
    if n_eq != rows:
        bad.append("dates_equal %d/%d" % (n_eq, rows))
    if n_fail != 0:
        bad.append("fail_closed=%d" % n_fail)

    if bad:
        sys.stdout.write("INVARIANT: FAIL  [%s]\n" % "; ".join(bad))
        sys.exit(2)
    sys.stdout.write("INVARIANT: PASS\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
