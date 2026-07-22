#!/usr/bin/env python3
"""
D3 patch applier for scripts/collect_etf_ibit.py.

Makes the completion target per-issuer:

  ratified lag (int >= 0)  -> expected_issuer_as_of is that many U.S.
                              business days behind the baseline; lag 0 is
                              the existing IBIT rule, so B-2/B-16 stay put
  lag is None              -> observation_only: collect, parse, store,
                              revision and collect_log all run, but no
                              done marker and no first_seen line

Because first_seen is reserved as the completion ledger, etf_collect_log
is the only promotion evidence for an unratified issuer.  An unchanged
file in a NEW window is therefore still an observation and gets one row,
keyed on (source_id, digest, window) so repeat slots never duplicate it.

Those rows outlive promotion, so the duplicate lookup can no longer be a
single fetchone(): once an issuer is ratified there are several rows for
the same digest with different windows and completed=0, and which one
SQLite returns is undefined.  The lookup is an explicit aggregate
instead, which also makes the branch independent of row order.

The registry does not carry target_lag_us_business_days yet (D5 scope),
so the resolver falls back to lag 0 for IBIT - preserving already-ratified
behaviour - and to None for everyone else, which is the safe direction.

  usage:  python3 d3_apply.py [--check]

Same contract as d1_apply / d4_apply: exact-string hunks with expected
match counts, three legal states only, a parse gate before writing, and
no write on abort.

Requires D4 to be applied first (the hunks anchor on D4 output).
"""

import hashlib
import os
import sys

TARGET = os.path.join("scripts", "collect_etf_ibit.py")

_HELPERS = '''def _expected_as_of(window_date, target_lag_us_business_days):
    """Completion target for a window.

    Lag 0 is the previous U.S. business day - the rule IBIT was ratified
    on.  Each additional unit steps one further business day back, so the
    holiday calendar is honoured at every step rather than only the first.
    """
    d = date.fromisoformat(window_date)
    for _ in range(target_lag_us_business_days + 1):
        d = prev_us_business_day(d)
    return d.isoformat()


def _target_lag_for(ticker, meta):
    """Return a ratified U.S.-business-day lag, or None for observation-only."""
    if "target_lag_us_business_days" in meta:
        lag = meta["target_lag_us_business_days"]
    elif ticker.lower() == _LEGACY_TICKER.lower():
        lag = 0
    else:
        return None

    if lag is None:
        return None
    # bool is a subclass of int, so reject it explicitly.
    if isinstance(lag, bool) or not isinstance(lag, int) or lag < 0:
        raise ValueError(
            "invalid target_lag_us_business_days for %s: %r" % (ticker, lag))
    return lag


def _first_seen_has_window(first_seen_log, window_date):
    """True when the first_seen ledger already carries this window.

    Distinguishes a crash that lost the line (write it) from a marker that
    was deleted after the line was already written (do not write it twice).
    """
    path = FIRST_SEEN_LOG if first_seen_log is None else first_seen_log
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return ("\\twindow=%s\\t" % window_date) in f.read()
    except OSError:
        return False


'''

_D3_META = '''    meta = asset_cfg.get("issuers", {}).get(ticker, {})

    # D3: the completion target belongs to the issuer, not to the driver.
    # An issuer whose lag is not ratified runs observation-only - it
    # collects and stores, but never claims a window complete, so neither
    # the done marker nor the first_seen ledger is touched.  That blank is
    # the intended state; the promotion evidence lives in etf_collect_log.
    target_lag = _target_lag_for(ticker, meta)
    observation_only = target_lag is None
    expected = None if observation_only else _expected_as_of(window, target_lag)'''

_DUP_OLD = '''        dup = con.execute(
            "SELECT window_date_kst, latest_as_of, completed FROM etf_collect_log "
            "WHERE source_id=? AND input_digest=?", (source_id, digest)).fetchone()
        if dup:
            dup_window, dup_latest, dup_completed = dup'''

_DUP_NEW = '''        # D3: observation rows mean one digest can span several windows, so
        # duplicate state is aggregated rather than sampled with a single
        # fetchone() - those rows survive promotion, and which one SQLite
        # would return is undefined.
        dup_stats = con.execute(
            "SELECT COUNT(*), MAX(latest_as_of), MAX(window_date_kst), "
            "MAX(CASE WHEN completed=1 THEN 1 ELSE 0 END), "
            "MAX(CASE WHEN completed=1 AND window_date_kst=? THEN 1 ELSE 0 END), "
            "MAX(CASE WHEN window_date_kst=? THEN 1 ELSE 0 END) "
            "FROM etf_collect_log WHERE source_id=? AND input_digest=?",
            (window, window, source_id, digest)).fetchone()
        dup = dup_stats[0] > 0
        if dup:
            # dup_window is kept for the existing run-log message only;
            # no branch depends on it any more.
            (_dup_rows, dup_latest, dup_window, has_completed_any,
             has_completed_current_window, has_current_window_row) = dup_stats
            if observation_only and not has_current_window_row:
                # first_seen stays empty for an unratified issuer, so this
                # ledger is the only promotion evidence.  One row per
                # window, however many slots poll it.
                con.execute(
                    "INSERT INTO etf_collect_log (source_id, input_digest, "
                    "processed_at, rows_added, revisions_added, "
                    "window_date_kst, latest_as_of, completed) "
                    "VALUES (?,?,?,0,0,?,?,0)",
                    (source_id, digest,
                     _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     window, dup_latest))
                con.commit()'''

_COMPLETE_OLD = '''            if dup_latest >= expected and not _done_today(window, done_marker):
                _write_done(window, expected, dup_latest, digest, done_marker)
                if dup_window == window:
                    _log_first_seen(window, dup_latest, first_seen_log)'''

_COMPLETE_NEW = '''            if (not observation_only and dup_latest >= expected
                    and not _done_today(window, done_marker)):
                # B-15 durability: the ledger commits BEFORE the marker.
                # The marker is what stops the next slot from running, so a
                # marker written ahead of the ledger would leave a window
                # that claims completion with no completed=1 row and no way
                # to recover it the same day.
                #
                # Settle this window in the ledger.  A row left over from
                # the observation period is promoted in place; if promotion
                # landed before any slot ran today, insert the completion.
                if not has_completed_current_window:
                    if has_current_window_row:
                        con.execute(
                            "UPDATE etf_collect_log SET completed=1 "
                            "WHERE source_id=? AND input_digest=? "
                            "AND window_date_kst=?",
                            (source_id, digest, window))
                    else:
                        con.execute(
                            "INSERT INTO etf_collect_log (source_id, input_digest, "
                            "processed_at, rows_added, revisions_added, "
                            "window_date_kst, latest_as_of, completed) "
                            "VALUES (?,?,?,0,0,?,?,1)",
                            (source_id, digest,
                             _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
                             window, dup_latest))
                    con.commit()
                _write_done(window, expected, dup_latest, digest, done_marker)
                # first_seen fires on the first completion this issuer has
                # ever had, or to make good a line this window lost to a
                # crash - never twice for the same window.
                if (not has_completed_any
                        or (has_completed_current_window
                            and not _first_seen_has_window(first_seen_log, window))):
                    _log_first_seen(window, dup_latest, first_seen_log)'''

HUNKS = [
    ("target lag resolver and ledger helpers", 1,
     'def main(asset="BTC", ticker="IBIT"):\n'
     '    os.makedirs(LEDGER, exist_ok=True)\n'
     '    done_marker, lockfile, first_seen_log, runlog_tag = _paths_for(ticker)',
     _HELPERS +
     'def main(asset="BTC", ticker="IBIT"):\n'
     '    os.makedirs(LEDGER, exist_ok=True)\n'
     '    done_marker, lockfile, first_seen_log, runlog_tag = _paths_for(ticker)'),

    ("per-issuer expected", 1,
     '    meta = asset_cfg.get("issuers", {}).get(ticker, {})',
     _D3_META),

    ("aggregate duplicate state + observation ledger", 1,
     _DUP_OLD, _DUP_NEW),

    ("completion settles the window and first_seen", 1,
     _COMPLETE_OLD, _COMPLETE_NEW),

    ("store branch respects observation_only", 1,
     '        target_reached = latest >= expected',
     '        target_reached = (not observation_only) and latest >= expected'),
]


def main():
    check_only = "--check" in sys.argv[1:]

    if not os.path.isfile(TARGET):
        sys.exit("not found: %s (run from the repo root)" % TARGET)

    src = open(TARGET, encoding="utf-8").read()
    print("target : %s" % TARGET)
    print("bytes  : %d" % len(src.encode()))
    print("sha256 : %s" % hashlib.sha256(src.encode()).hexdigest())
    print()

    applied = already = 0
    for label, expect, old, new in HUNKS:
        n_old, n_new = src.count(old), src.count(new)
        embedded_old = expect if old in new else 0
        if n_new == expect and n_old == embedded_old:
            print("  NOOP  %s (already applied)" % label)
            already += 1
            continue
        if not (n_new == 0 and n_old == expect):
            sys.exit("  ABORT %s: mixed or unexpected state "
                     "(old=%d, new=%d, expected old=%d/new=0 or old=%d/new=%d)"
                     % (label, n_old, n_new, expect, embedded_old, expect))
        src = src.replace(old, new)
        applied += 1
        print("  OK    %s  x%d" % (label, expect))

    print()
    if already == len(HUNKS):
        print("nothing to do - file already patched")
        return
    if applied != len(HUNKS):
        sys.exit("ABORT: partial match (%d applied, %d already) - not written"
                 % (applied, already))

    try:
        compile(src, TARGET, "exec")
    except SyntaxError as e:
        sys.exit("  ABORT patched result does not parse: line %s: %s"
                 % (e.lineno, e.msg))

    after = hashlib.sha256(src.encode()).hexdigest()
    if check_only:
        print("--check: would write %d bytes, sha256 %s"
              % (len(src.encode()), after))
        return

    open(TARGET, "w", encoding="utf-8").write(src)
    print("written: %d bytes" % len(src.encode()))
    print("sha256 : %s" % after)


if __name__ == "__main__":
    main()
