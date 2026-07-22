#!/usr/bin/env python3
"""
D3 patch applier for scripts/collect_etf_ibit.py  (A-safe).

Makes the completion target per-issuer:

  ratified lag (int >= 0)  -> expected_issuer_as_of is that many U.S.
                              business days behind the baseline; lag 0 is
                              the existing IBIT rule, so B-2/B-15/B-16 stay
                              exactly as ratified
  lag is None              -> observation_only: collect, parse, store,
                              revision and the new-digest collect_log row
                              all run, but no done marker and no first_seen

etf_collect_log is keyed PRIMARY KEY (source_id, input_digest), so it is a
first-observation ledger, not a per-window one: exactly one row per digest,
never rewritten.  An unchanged file in a later window is not a new lag
sample and gets no row.  Execution liveness lives in pipeline_runs and the
cron log.

A row written while an issuer was unratified carries completed=0 and a
window_date_kst pinned to its FIRST observation.  It is deliberately NOT
promoted in place after ratification: window_date_kst must keep the first
observation for lag calculation, so "settled this window then crashed" and
"old completed digest reused across a holiday" would be indistinguishable.
Ratification therefore takes effect from the next new digest, which flows
through the untouched fresh/store path.

The registry does not carry target_lag_us_business_days yet (D5 scope), so
the resolver falls back to lag 0 for IBIT - preserving already-ratified
behaviour - and to None for everyone else, which is the safe direction.

  usage:  python3 d3_apply.py [--check]

Same contract as d1_apply / d4_apply: exact-string hunks with expected
match counts, three legal states only, a parse gate before writing, and no
write on abort.

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


'''

_D3_META = '''    meta = asset_cfg.get("issuers", {}).get(ticker, {})

    # D3: the completion target belongs to the issuer, not to the driver.
    # An issuer whose lag is not ratified runs observation-only - it
    # collects and stores, but never claims a window complete, so neither
    # the done marker nor the first_seen ledger is touched.  That blank is
    # the intended state; the lag evidence is the first-observation row
    # each new digest leaves in etf_collect_log.
    target_lag = _target_lag_for(ticker, meta)
    observation_only = target_lag is None
    expected = None if observation_only else _expected_as_of(window, target_lag)'''

_DUP_OLD = '''            if dup_latest >= expected and not _done_today(window, done_marker):'''

_DUP_NEW = '''            if observation_only or not dup_completed:
                # Two cases collapse into a plain no-op, and neither may
                # touch collect_log, the marker or first_seen:
                #  - observation_only: no ratified target exists, so nothing
                #    can claim completion.
                #  - not dup_completed: this row was written while the issuer
                #    was still unratified.  Promoting it in place is unsafe,
                #    because window_date_kst has to keep the FIRST
                #    observation window for lag calculation - which leaves
                #    "settled this window then crashed" and "old completed
                #    digest reused across a holiday" indistinguishable.
                #    Ratification takes effect from the next new digest.
                _run_log(con, runlog_tag, "NOOP",
                         "digest=%s no-op observation_only=%s completed=%s"
                         % (digest[:12], observation_only, dup_completed))
                print("[noop] %s digest unchanged - no marker, no first_seen"
                      % ticker)
            elif dup_latest >= expected and not _done_today(window, done_marker):'''

HUNKS = [
    ("target lag resolver", 1,
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

    ("duplicate branch: observation-only and unratified rows no-op", 1,
     _DUP_OLD, _DUP_NEW),

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
