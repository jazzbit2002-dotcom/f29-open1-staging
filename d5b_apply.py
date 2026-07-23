#!/usr/bin/env python3
"""d5b_apply.py - apply the D5b hunks (H1, H2, H3), fail-closed.

Rewrites two live files in a single run:
    scripts/collect_etf_ibit.py   H1  legacy lag fallback -> fail-closed
                                  H2  dead `expected` pre-assignment removed
    scripts/validate_registry.py  H3  materialization branch + helper removed

Per target file the state is read as a whole:
    every hunk unpatched  -> apply
    every hunk patched    -> idempotent no-op
    anything in between    -> ABORT, nothing written

A drifted, partial, duplicated or unrelated tree aborts before the first
write, and no live file is touched unless every target resolves cleanly
AND every rewritten text compiles.

Write model - all-or-rollback on a handled I/O failure, not crash-proof
atomicity: every applying target is staged to a temp (permissions copied
from the original) and only then swapped in.  Each target's original
bytes and mode are snapshotted first, so an OSError partway through the
swaps restores whatever was already replaced, deletes every temp, and
exits non-zero - the tree is never left half-written by a handled error.
Absolute atomicity across a process kill would need a journal; for this
one-shot applier the handled-error rollback plus the server-side
pre-backup is the accepted line.

Restore order (C6): D3 is applied before D5b - the H1/H3 anchors are the
post-D3 driver/validator, so D5b run alone against a pre-D3 tree simply
finds no anchors and aborts.  D5b without D3 would leave the legacy
fallback in place.  A v3 rollback MUST roll D5b back first: a strict
driver against a v3 registry with no IBIT lag key halts IBIT entirely.

Run from the repo root:  python3 d5b_apply.py [--check]
"""
import os
import sys

# indirection so a contract test can inject a replace failure mid-sequence
_REPLACE = os.replace

# (label, relpath, expect_count, old, new).  new == "" marks a deletion
# hunk (no positive post-image to count, so state is read from old alone).
HUNKS = [
    ('H1 driver fallback->fail-closed',
     'scripts/collect_etf_ibit.py', 1,
     ('    if "target_lag_us_business_days" in meta:\n'
     '        lag = meta["target_lag_us_business_days"]\n'
     '    elif ticker.lower() == _LEGACY_TICKER.lower():\n'
     '        lag = 0\n'
     '    else:\n'
     '        return None\n'
     '\n'
     '    if lag is None:\n'
     '        return None\n'),
     ('    if "target_lag_us_business_days" not in meta:\n'
     '        raise ValueError(\n'
     '            "target_lag_us_business_days key missing for %s "\n'
     '            "(observation-only must be an explicit null)" % (ticker,))\n'
     '    lag = meta["target_lag_us_business_days"]\n'
     '    if lag is None:\n'
     '        return None\n')),
    ('H2 driver dead-assignment removal',
     'scripts/collect_etf_ibit.py', 1,
     ('    expected = prev_us_business_day(date.fromisoformat(window)).isoformat()\n'),
     ""),
    ('H3a validator NO_CHANGE + drop MATERIALIZATION',
     'scripts/validate_registry.py', 1,
     ('    key_moved = (LAG_KEY in old_meta) != (LAG_KEY in new_meta)\n'
     '\n'
     '    if old_lag == new_lag and not key_moved:\n'
     '        return                                            # NO_CHANGE\n'
     '\n'
     '    if old_lag == new_lag and key_moved:                  # MATERIALIZATION\n'
     '        if _materialization_ok(ticker, old_lag, new_lag, window, ledger_dir):\n'
     '            return\n'
     '        # falls through to the REAL_CHANGE rules deliberately\n'
     '\n'),
     ('    if old_lag == new_lag:\n'
     '        return                                            # NO_CHANGE\n'
     '\n')),
    ('H3b validator drop _materialization_ok',
     'scripts/validate_registry.py', 1,
     ('def _materialization_ok(ticker, old_lag, new_lag, window, ledger_dir):\n'
     '    """No-op materialization of an already-effective lag.\n'
     '\n'
     '    Deliberately blind to the ticker name: an issuer is not exempt for\n'
     '    being IBIT, it is exempt for the value being provably unchanged.\n'
     '    """\n'
     '    if old_lag is None or new_lag != old_lag:\n'
     '        return False\n'
     '    marker = _current_marker(ticker, window, ledger_dir)\n'
     '    if marker is None:\n'
     '        return True     # no stale marker exists, so B-2 cannot be misled\n'
     '    return marker.get("expected_issuer_as_of") == C._expected_as_of(window,\n'
     '                                                                    new_lag)\n'
     '\n'
     '\n'),
     ""),
]

TARGETS = ["scripts/collect_etf_ibit.py", "scripts/validate_registry.py"]


def _hunk_state(src, expect, old, new):
    """'patched' | 'unpatched' | 'drift' for a single hunk."""
    c_old = src.count(old)
    if new == "":
        if c_old == 0:
            return "patched"
        if c_old == expect:
            return "unpatched"
        return "drift"
    embedded_old = expect if old in new else 0
    c_new = src.count(new)
    if c_new == expect and c_old == embedded_old:
        return "patched"
    if c_new == 0 and c_old == expect:
        return "unpatched"
    return "drift"


def _file_plan(relpath, src):
    """(action, new_src) where action is 'apply' | 'noop' | 'abort'."""
    mine = [(e, o, n) for (_l, r, e, o, n) in HUNKS if r == relpath]
    states = [_hunk_state(src, e, o, n) for (e, o, n) in mine]
    if states and all(s == "patched" for s in states):
        return "noop", None
    if states and all(s == "unpatched" for s in states):
        out = src
        for (e, o, n) in mine:
            if out.count(o) != e:
                return "abort", None
            out = out.replace(o, n)
        return "apply", out
    return "abort", None


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _commit(plans, verdicts):
    """Stage every applying target to a temp, then swap them in, rolling
    back on a handled OSError so the tree is never left half-written."""
    work = [plans[rel] for rel in TARGETS if verdicts[rel] == "apply"]
    staged = []          # (tmp, path)
    snapshots = []       # (path, original_bytes, original_mode)
    try:
        for path, out in work:
            mode = os.stat(path).st_mode
            snapshots.append((path, open(path, "rb").read(), mode))
            tmp = path + ".d5b.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(out)
            os.chmod(tmp, mode)              # keep the original's permissions
            staged.append((tmp, path))
    except OSError as exc:
        for tmp, _ in staged:
            _silent_remove(tmp)
        print("ABORT: staging failed (%s); nothing changed" % exc)
        return 1

    replaced = []
    try:
        for tmp, path in staged:
            _REPLACE(tmp, path)
            replaced.append(path)
    except OSError as exc:
        for path, data, mode in snapshots:
            if path in replaced:            # undo the swaps that did happen
                with open(path, "wb") as fh:
                    fh.write(data)
                os.chmod(path, mode)
        for tmp, _ in staged:               # remove any temp still on disk
            _silent_remove(tmp)
        print("ABORT: write failed (%s); rolled back, nothing left changed"
              % exc)
        return 1

    print("applied")
    return 0


def main(argv):
    check = "--check" in argv
    root = os.getcwd()
    plans, verdicts = {}, {}
    for rel in TARGETS:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            print("ABORT: missing target %s" % rel)
            return 2
        src = open(path, encoding="utf-8").read()
        action, out = _file_plan(rel, src)
        verdicts[rel] = action
        plans[rel] = (path, out)
        print("%-40s %s" % (rel, action))

    vs = set(verdicts.values())
    if "abort" in vs:
        print("ABORT: drifted or partially-applied file; nothing written")
        return 1
    if vs == {"noop"}:
        print("already patched; nothing to do")
        return 0
    if vs != {"apply"}:
        # a tree where one target is patched and another is not is a
        # half-applied run, indistinguishable here from drift: fail closed.
        print("ABORT: cross-file partial state (some targets patched, some "
              "not); nothing written")
        return 1

    # compile every result before touching any live file (fail before write)
    for rel in TARGETS:
        if verdicts[rel] != "apply":
            continue
        path, out = plans[rel]
        try:
            compile(out, path, "exec")
        except SyntaxError as exc:
            print("ABORT: generated %s does not parse: %s" % (rel, exc))
            return 1

    if check:
        print("--check: would apply cleanly; no write")
        return 0

    return _commit(plans, verdicts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
