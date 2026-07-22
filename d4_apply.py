#!/usr/bin/env python3
"""
D4 patch applier for scripts/collect_etf_ibit.py.

Derives the done marker, lock file, first-seen log and run-log tag from
the ticker (D4-1) while leaving IBIT bound to the existing module
globals, so the 33 existing tests keep their monkeypatch points (D4-2).

  usage:  python3 d4_apply.py [--check]

Every hunk is matched by exact string with an expected occurrence count.
A miscount aborts before anything is written.  Re-running on an already
patched file reports NOOP.

Scope: D4 only.  Does not touch the registry, cron, etf_issuer.py, the
D2 parser, or the expected/target_reached predicate (D3).
"""

import hashlib
import os
import sys

TARGET = os.path.join("scripts", "collect_etf_ibit.py")

_PATHS_FOR = '''_LEGACY_TICKER = "IBIT"
# fullmatch, not match: Python's "$" also matches immediately before a
# trailing newline character, so a match()-based guard accepts a ticker
# with one appended and leaks it into the derived filenames.
_SAFE_TICKER = re.compile(r"[A-Za-z0-9]+")


def _paths_for(ticker):
    """D4-1: per-ticker ledger artefacts.

    IBIT returns the module globals verbatim so that existing tests
    monkeypatching DONE_MARKER / LOCKFILE / FIRST_SEEN_LOG keep working
    and the live IBIT ledger keeps its filenames (migration-free).
    Every other ticker derives its own set, which is what keeps
    _done_today from being shared across issuers.

    The ticker lands in a filesystem path and is read before the
    registry is consulted, so it is charset-guarded here.
    """
    if not _SAFE_TICKER.fullmatch(ticker or ""):
        raise ValueError("unsafe ticker for path derivation: %r" % (ticker,))
    t = ticker.lower()
    if t == _LEGACY_TICKER.lower():
        return DONE_MARKER, LOCKFILE, FIRST_SEEN_LOG, "etf_ibit"
    return (os.path.join(LEDGER, "etf_%s_done.json" % t),
            os.path.join(LEDGER, ".etf_%s.lock" % t),
            os.path.join(LEDGER, "%s_first_seen.log" % t),
            "etf_%s" % t)


'''

HUNKS = [
    ("import re", 1,
     "import fcntl\nimport json\nimport os\nimport sqlite3",
     "import fcntl\nimport json\nimport os\nimport re\nimport sqlite3"),

    ("_done_today takes an explicit marker path", 1,
     '''def _done_today(window_date: str) -> bool:
    if not os.path.exists(DONE_MARKER):
        return False
    try:
        with open(DONE_MARKER, encoding="utf-8") as f:''',
     '''def _done_today(window_date: str, done_marker: str = None) -> bool:
    done_marker = DONE_MARKER if done_marker is None else done_marker
    if not os.path.exists(done_marker):
        return False
    try:
        with open(done_marker, encoding="utf-8") as f:'''),

    ("_write_done signature", 1,
     'def _write_done(window_date: str, expected_issuer_as_of: str, as_of: str, digest: str):',
     'def _write_done(window_date: str, expected_issuer_as_of: str, as_of: str, digest: str,\n'
     '                done_marker: str = None):'),

    ("_write_done tmp path", 1,
     '    tmp = DONE_MARKER + ".tmp"',
     '    done_marker = DONE_MARKER if done_marker is None else done_marker\n'
     '    tmp = done_marker + ".tmp"'),

    ("_write_done replace target", 1,
     '    os.replace(tmp, DONE_MARKER)',
     '    os.replace(tmp, done_marker)'),

    ("_log_first_seen signature", 1,
     'def _log_first_seen(window_date: str, as_of: str):',
     'def _log_first_seen(window_date: str, as_of: str, first_seen_log: str = None):'),

    ("_log_first_seen target", 1,
     '    with open(FIRST_SEEN_LOG, "a", encoding="utf-8") as f:',
     '    first_seen_log = FIRST_SEEN_LOG if first_seen_log is None else first_seen_log\n'
     '    with open(first_seen_log, "a", encoding="utf-8") as f:'),

    ("_paths_for + main derivation", 1,
     'def main(asset="BTC", ticker="IBIT"):\n    os.makedirs(LEDGER, exist_ok=True)',
     _PATHS_FOR + 'def main(asset="BTC", ticker="IBIT"):\n'
     '    os.makedirs(LEDGER, exist_ok=True)\n'
     '    done_marker, lockfile, first_seen_log, runlog_tag = _paths_for(ticker)'),

    ("lock file", 1,
     '    lock_fd = open(LOCKFILE, "w")',
     '    lock_fd = open(lockfile, "w")'),

    ("_done_today call (pre-network gate)", 1,
     '    if _done_today(window):',
     '    if _done_today(window, done_marker):'),

    ("_done_today call (dup branch)", 1,
     '            if dup_latest >= expected and not _done_today(window):',
     '            if dup_latest >= expected and not _done_today(window, done_marker):'),

    ("_write_done call (dup branch)", 1,
     '                _write_done(window, expected, dup_latest, digest)',
     '                _write_done(window, expected, dup_latest, digest, done_marker)'),

    ("_write_done call (store branch)", 1,
     '            _write_done(window, expected, latest, digest)',
     '            _write_done(window, expected, latest, digest, done_marker)'),

    ("_log_first_seen call (dup branch)", 1,
     '                    _log_first_seen(window, dup_latest)',
     '                    _log_first_seen(window, dup_latest, first_seen_log)'),

    ("_log_first_seen call (store branch)", 1,
     '            _log_first_seen(window, latest)',
     '            _log_first_seen(window, latest, first_seen_log)'),

    ("run-log tag (5 call sites)", 5,
     '_run_log(con, "etf_ibit", ',
     '_run_log(con, runlog_tag, '),
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
        # Some hunks append after their anchor, so the patched text still
        # contains the unpatched text.  Account for that, then admit only
        # two clean states - anything else (partial apply, mixed source,
        # duplicated block, upstream drift) aborts before any write.
        embedded_old = expect if old in new else 0
        if n_new == expect and n_old == embedded_old:
            print("  NOOP  %s (already applied)" % label)
            already += 1
            continue
        if not (n_new == 0 and n_old == expect):
            sys.exit("  ABORT %s: mixed or unexpected state "
                     "(old=%d, new=%d, expected old=%d/new=0 or "
                     "old=%d/new=%d)"
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

    # The hunks carry generated source; if anything about them is
    # malformed the result must never reach disk.
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
