#!/usr/bin/env python3
"""Mutation runner: each entry must have exactly one anchor match and must
flip the suite to failure.  An anchor that matches twice would be applied
silently to the wrong place (D1 and D3 both lost a mutation that way)."""
import os
import re
import subprocess
import sys

TARGET = "scripts/validate_registry.py"
ORIG = open(TARGET, encoding="utf-8").read()

MUTS = [
    ("N1  S2 lag-key enforcement removed",
     '        diags.error(scope, "S2", "%s key missing" % LAG_KEY)',
     '        pass  # MUT'),
    ("N2  S3 delegated value error not reported",
     '    if err is not None:\n        diags.error(scope, "S3", err)',
     '    if err is not None:\n        pass  # MUT'),
    ("N3  S6 parser cross-check removed",
     '    elif _is_nonempty_str(parser) and parser not in PARSERS:',
     '    elif False:  # MUT'),
    ("N4  T1 conditions disabled wholesale",
     '    detail = "lag %r -> %r" % (old_lag, new_lag)',
     '    return  # MUT\n    detail = "lag %r -> %r" % (old_lag, new_lag)'),
    ("N5  materialization exempted by ticker name",
     '    old_lag, old_err = _effective_lag(ticker, old_meta)',
     '    if ticker.upper() == "IBIT":\n        return  # MUT\n'
     '    old_lag, old_err = _effective_lag(ticker, old_meta)'),
    ("N6  T2 marker-expected comparison removed",
     '    marker = _current_marker(ticker, window, ledger_dir)\n'
     '    if marker is None:',
     '    return True  # MUT\n'
     '    marker = _current_marker(ticker, window, ledger_dir)\n'
     '    if marker is None:'),
    ("N7  T1 marker-absence condition removed",
     '    if _current_marker(ticker, window, ledger_dir) is not None:',
     '    if False:  # MUT'),
    ("N8  S7 mapping_promotion validation removed",
     'def check_mapping_promotion(reg, diags):',
     'def check_mapping_promotion(reg, diags):\n    return  # MUT'),
    ("N10 only LEDGER rebound (IBIT globals left operational)",
     '        for name in ("DONE_MARKER", "LOCKFILE", "FIRST_SEEN_LOG"):\n'
     '            setattr(C, name,\n'
     '                    os.path.join(ledger_dir, '
     'os.path.basename(saved[name])))',
     '        pass  # MUT'),
    ("N11 finally restoration removed",
     '    finally:\n        for name, value in saved.items():\n'
     '            setattr(C, name, value)',
     '    finally:\n        pass  # MUT'),
    ("N12a bool check reduced to truthiness",
     '    return isinstance(v, bool)',
     '    return v is not None  # MUT'),
    ("N12b int check accepts bool",
     '    return isinstance(v, int) and not isinstance(v, bool) and v >= low',
     '    return isinstance(v, int) and v >= low  # MUT'),
    ("N13 sys.dont_write_bytecode removed",
     'sys.dont_write_bytecode = True',
     'pass  # MUT'),
    ("N16 current enabled bool guard removed",
     '            if not _is_bool(meta.get("enabled")):',
     '            if False:  # MUT'),
    ("N17 current lag error not reported",
     '            _lag, err = _effective_lag(ticker, meta)\n'
     '            if err is not None:\n'
     '                diags.error(scope, "C3", err)\n'
     '                usable = False',
     '            _lag, err = _effective_lag(ticker, meta)\n'
     '            if err is not None:\n'
     '                pass  # MUT'),
    ("N18 candidate structure guard removed",
     '    assets = reg.get("assets")\n    if not isinstance(assets, dict):',
     '    assets = reg.get("assets")\n    if False:  # MUT'),
    ("N19 current structure guard removed",
     '    assets = current.get("assets")\n    if not isinstance(assets, dict):',
     '    assets = current.get("assets")\n    if False:  # MUT'),
    ("N14 lockfile opened for write",
     '        done_marker = C._paths_for(ticker)[0]',
     '        done_marker = C._paths_for(ticker)[0]\n'
     '        open(C._paths_for(ticker)[1], "w").close()  # MUT'),
]


def run():
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "-p", "no:cacheprovider", "tests/"],
                          capture_output=True, text=True, env=env)
    tail = proc.stdout.strip().splitlines()[-1]
    return proc.returncode, tail


def main():
    rc, tail = run()
    print("BASELINE            rc=%d  %s" % (rc, tail))
    if rc != 0:
        return 1
    bad = 0
    for label, old, new in MUTS:
        count = ORIG.count(old)
        if count != 1:
            print("%-52s ANCHOR count=%d  <-- REJECTED" % (label, count))
            bad += 1
            continue
        open(TARGET, "w", encoding="utf-8").write(ORIG.replace(old, new, 1))
        rc, tail = run()
        failed = re.search(r"(\d+) failed", tail)
        n = int(failed.group(1)) if failed else 0
        ok = "OK" if (rc != 0 and n >= 1) else "NO DISCRIMINATION"
        print("%-52s anchor_count=1  rc=%d  %-28s %s"
              % (label, rc, tail[:28], ok))
        if ok != "OK":
            bad += 1
        open(TARGET, "w", encoding="utf-8").write(ORIG)
    rc, tail = run()
    print("RESTORED            rc=%d  %s" % (rc, tail))
    return 1 if (bad or rc) else 0


if __name__ == "__main__":
    raise SystemExit(main())
