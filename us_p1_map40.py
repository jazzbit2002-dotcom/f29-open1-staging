#!/usr/bin/env python3
# us_p1_map40.py -- US P1 benchmark selection mapping (READ-ONLY, 40 rows)
# Contract: Sky ruling 2026-07-20 (P+S fixed fallback).
#   1st: active_primary   -- closes file exists AND last-60 dates identical
#   2nd: active_secondary -- only if primary absent/unaligned, same date check
#   both fail             -- FAIL_CLOSED (card fail-closed; must be 0 in practice)
# Invariants (exit 2 if violated):
#   rows==40, selected 40/40, dates_equal 40/40, fail_closed==0
# primary/secondary split counts are OBSERVATIONS only (non-blocking).
# No writes. No network. Stdout only. Pure ASCII. Stdlib only.
#
# Usage:
#   python3 us_p1_map40.py --positions /root/moneyflow/positions_output.json \
#                          --closes-dir <PUBLIC_CLOSES_DIR>
#
# Both arguments are REQUIRED (no defaults -- operator supplies real paths).

import argparse, json, os, sys

N_LAST = 60

def die(code, msg):
    sys.stdout.write("FATAL: %s\n" % msg)
    sys.exit(code)

def load_json(path):
    if not os.path.isfile(path):
        die(3, "file not found: %s" % path)
    with open(path, "r") as f:
        try:
            return json.load(f)
        except ValueError as e:
            die(3, "invalid json: %s (%s)" % (path, e))

def extract_records(pos):
    # Tolerant loader: dict{ticker:rec} | list[rec with 'ticker'] |
    # wrapper dict containing such a structure under a single plausible key.
    def norm(obj):
        if isinstance(obj, dict):
            vals = list(obj.values())
            if vals and all(isinstance(v, dict) for v in vals):
                sample = vals[0]
                if "active_primary" in sample or "active_secondary" in sample:
                    return [(k, v) for k, v in sorted(obj.items())]
        if isinstance(obj, list):
            if obj and all(isinstance(v, dict) and "ticker" in v for v in obj):
                return [(v["ticker"], v) for v in obj]
        return None
    recs = norm(pos)
    if recs is None and isinstance(pos, dict):
        for key in ("positions", "stocks", "data", "output"):
            if key in pos:
                recs = norm(pos[key])
                if recs is not None:
                    break
    if recs is None:
        keys = list(pos.keys())[:10] if isinstance(pos, dict) else type(pos).__name__
        die(3, "unrecognized positions schema; top-level keys/type: %s" % keys)
    return recs

def read_closes(closes_dir, name):
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
    ap.add_argument("--positions", required=True)
    ap.add_argument("--closes-dir", required=True)
    a = ap.parse_args()

    if not os.path.isdir(a.closes_dir):
        die(3, "closes dir not found: %s" % a.closes_dir)

    recs = extract_records(load_json(a.positions))

    header = ["ticker", "active_primary", "active_secondary",
              "selected_benchmark", "selection_reason",
              "stock_n", "benchmark_n", "dates_equal"]
    sys.stdout.write("\t".join(header) + "\n")

    rows = 0
    n_primary = 0
    n_secondary = 0
    n_fail_closed = 0
    n_dates_equal = 0
    fallback_reasons = []
    schema_missing = []

    for ticker, rec in recs:
        rows += 1
        prim = rec.get("active_primary")
        sec = rec.get("active_secondary")
        if prim is None and sec is None:
            schema_missing.append(ticker)

        s_dates, s_n, s_st = read_closes(a.closes_dir, ticker)
        if s_st != "ok":
            # stock closes itself unreadable -> fail-closed row
            sys.stdout.write("\t".join([ticker, str(prim), str(sec),
                "FAIL_CLOSED", "stock_closes_%s" % s_st, str(s_n), "0", "n/a"]) + "\n")
            n_fail_closed += 1
            continue
        s_tail = s_dates[-N_LAST:]

        selected = None
        reason = None
        b_n = 0
        dates_equal = "n/a"
        why_not_primary = None

        for cand, tag in ((prim, "primary"), (sec, "secondary_fallback")):
            if not cand:
                if tag == "primary":
                    why_not_primary = "primary_null"
                continue
            b_dates, bn, b_st = read_closes(a.closes_dir, cand)
            if b_st != "ok":
                if tag == "primary":
                    why_not_primary = "primary_%s" % b_st
                continue
            if b_dates[-N_LAST:] == s_tail and len(s_tail) == N_LAST:
                selected, reason, b_n, dates_equal = cand, tag, bn, "true"
                break
            else:
                if tag == "primary":
                    why_not_primary = "primary_dates_mismatch"

        if selected is None:
            selected, reason, dates_equal = "FAIL_CLOSED", "both_failed", "false"
            n_fail_closed += 1
        else:
            if reason == "primary":
                n_primary += 1
            else:
                n_secondary += 1
                fallback_reasons.append("%s:%s" % (ticker, why_not_primary or "primary_unavailable"))
            n_dates_equal += 1

        sys.stdout.write("\t".join([ticker, str(prim), str(sec),
            selected, reason, str(s_n), str(b_n), dates_equal]) + "\n")

    n_selected = n_primary + n_secondary

    sys.stdout.write("\n== SUMMARY ==\n")
    sys.stdout.write("rows                 %d\n" % rows)
    sys.stdout.write("selected_benchmark   %d/%d\n" % (n_selected, rows))
    sys.stdout.write("dates_equal          %d/%d\n" % (n_dates_equal, rows))
    sys.stdout.write("primary              %d   (observation)\n" % n_primary)
    sys.stdout.write("secondary_fallback   %d   (observation)\n" % n_secondary)
    sys.stdout.write("fail_closed          %d\n" % n_fail_closed)
    sys.stdout.write("new_api_requests     0   (script performs no network I/O)\n")
    if fallback_reasons:
        sys.stdout.write("fallback_detail      %s\n" % " ".join(fallback_reasons))
    if schema_missing:
        sys.stdout.write("WARN schema: no active_primary/secondary keys: %s\n"
                         % ",".join(schema_missing))

    inv_fail = []
    if rows != 40:
        inv_fail.append("rows!=40 (%d)" % rows)
    if n_selected != rows:
        inv_fail.append("selected!=%d/%d" % (rows, rows))
    if n_dates_equal != rows:
        inv_fail.append("dates_equal!=%d/%d" % (rows, rows))
    if n_fail_closed != 0:
        inv_fail.append("fail_closed=%d" % n_fail_closed)

    if inv_fail:
        sys.stdout.write("INVARIANT: FAIL  [%s]\n" % "; ".join(inv_fail))
        sys.exit(2)
    sys.stdout.write("INVARIANT: PASS\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
