"""
D5b applier contract test - d5b_apply.py must fail closed.

d5b_apply rewrites two live files (the driver and the validator) in one
run, so its state detection is the last thing standing between a
mis-shaped tree and a corrupted file.  These tests exercise the states it
is allowed to be in and prove that everything else aborts *before* any
write, and that the write it does perform is all-or-nothing across both
files.

No server files are mutated: every case runs on synthetic copies in
tmp_path with cwd swapped there.

Run from the repo root:  python3 -m pytest -q
"""

import hashlib
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLIER = os.path.join(ROOT, "d5b_apply.py")
DRIVER = os.path.join(ROOT, "scripts", "collect_etf_ibit.py")
VALIDATOR = os.path.join(ROOT, "scripts", "validate_registry.py")

REL = {"scripts/collect_etf_ibit.py": DRIVER,
       "scripts/validate_registry.py": VALIDATOR}


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _stage(tmp_path, driver_body, valid_body):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    d = tmp_path / "scripts" / "collect_etf_ibit.py"
    v = tmp_path / "scripts" / "validate_registry.py"
    d.write_text(driver_body, encoding="utf-8")
    v.write_text(valid_body, encoding="utf-8")
    return d, v


def _run(tmp_path, *args, applier=APPLIER):
    return subprocess.run([sys.executable, applier] + list(args),
                          cwd=str(tmp_path), capture_output=True, text=True)


# Deletion hunks leave no positive marker, so reversing one means putting
# the removed block back in front of a stable neighbour.  These anchors are
# fixture-local reconstruction knowledge, deliberately kept out of the
# applier (whose H2/H3b anchors stay the single ratified lines/blocks).
_REINSERT = {
    "H2 driver dead-assignment removal":
        "    if _done_today(window, done_marker):",
    "H3b validator drop _materialization_ok":
        "def _require_real_change_conditions(",
}


def _to_pristine(src, relpath):
    """Reconstruct the pre-D5b text of one file whether the live tree is
    still pre-D5b or already carries D5b.  Positive hunks reverse by
    swapping the post-image back to the pre-image; deletion hunks reverse
    by re-inserting the removed block ahead of its neighbour.  A pre-D5b
    tree is left untouched (the reversal is a no-op)."""
    for label, rel, _expect, old, new in _hunks():
        if rel != relpath:
            continue
        if new == "":
            if old not in src:                       # deletion already applied
                anchor = _REINSERT[label]
                src = src.replace(anchor, old + anchor, 1)
        elif new in src and old not in src:          # positive hunk applied
            src = src.replace(new, old)
    return src


@pytest.fixture
def pristine():
    """The pre-D5b driver and validator - exactly what d5b_apply is meant
    to run against.  Reconstructed from the live sources so the contract
    holds whether the suite runs before or after D5b is deployed."""
    driver = open(DRIVER, encoding="utf-8").read()
    valid = open(VALIDATOR, encoding="utf-8").read()
    return (_to_pristine(driver, "scripts/collect_etf_ibit.py"),
            _to_pristine(valid, "scripts/validate_registry.py"))


def _hunks():
    sys.path.insert(0, ROOT)
    import d5b_apply
    return d5b_apply.HUNKS


def test_applier_is_present():
    assert os.path.isfile(APPLIER), APPLIER


def test_fresh_source_applies_cleanly(tmp_path, pristine):
    d, v = _stage(tmp_path, *pristine)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ABORT" not in r.stdout
    assert d.read_text() != pristine[0]
    assert v.read_text() != pristine[1]


def test_apply_removes_known_signatures(tmp_path, pristine):
    """A hard-coded outcome check, independent of the applier's HUNKS: if
    any hunk were dropped from the applier (mutation A1) its signature
    would survive here and this fails."""
    d, v = _stage(tmp_path, *pristine)
    assert _run(tmp_path).returncode == 0
    driver, valid = d.read_text(), v.read_text()
    # H1: the legacy IBIT fallback branch is gone, fail-closed raise present
    assert "elif ticker.lower() == _LEGACY_TICKER.lower():" not in driver
    assert "target_lag_us_business_days key missing for" in driver
    # H1 must not have removed the constant the path derivation needs
    assert '_LEGACY_TICKER = "IBIT"' in driver
    # H2: the dead pre-assignment is gone
    assert ("expected = prev_us_business_day(date.fromisoformat(window))"
            ".isoformat()") not in driver
    # H3: materialization machinery is gone, simplified NO_CHANGE present
    for tok in ("_materialization_ok", "key_moved", "MATERIALIZATION"):
        assert tok not in valid, tok
    assert "if old_lag == new_lag:" in valid


def test_rerun_is_a_clean_noop(tmp_path, pristine):
    d, v = _stage(tmp_path, *pristine)
    assert _run(tmp_path).returncode == 0
    once = (_sha(str(d)), _sha(str(v)))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already patched" in r.stdout
    assert (_sha(str(d)), _sha(str(v))) == once, "a re-run must not write"


def test_within_file_drift_aborts(tmp_path, pristine):
    """One hunk reverted on an otherwise-patched file is drift, not
    'already patched' - it must abort (mutation A2 guard)."""
    d, v = _stage(tmp_path, *pristine)
    assert _run(tmp_path).returncode == 0
    patched = d.read_text()
    h1 = [h for h in _hunks() if h[0].startswith("H1")][0]
    _l, _r, _e, old, new = h1
    d.write_text(patched.replace(new, old), encoding="utf-8")  # revert H1 only
    before = (_sha(str(d)), _sha(str(v)))
    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert (_sha(str(d)), _sha(str(v))) == before, "abort must not write"


def test_cross_file_partial_aborts(tmp_path, pristine):
    """Driver patched, validator still pristine: a half-applied run.  It is
    indistinguishable from drift, so it must abort (mutation A2 guard)."""
    driver0, valid0 = pristine
    # produce a patched driver by applying once in isolation, then re-stage
    d, v = _stage(tmp_path, driver0, valid0)
    assert _run(tmp_path).returncode == 0
    patched_driver = d.read_text()
    d2, v2 = _stage(tmp_path, patched_driver, valid0)  # driver patched, valid pristine
    before = (_sha(str(d2)), _sha(str(v2)))
    r = _run(tmp_path)
    assert r.returncode != 0, r.stdout
    assert "ABORT" in r.stdout + r.stderr
    assert (_sha(str(d2)), _sha(str(v2))) == before, "abort must not write"


def test_unrelated_driver_aborts(tmp_path, pristine):
    _driver0, valid0 = pristine
    d, v = _stage(tmp_path, "import os\n\nprint('not the driver')\n", valid0)
    before = (_sha(str(d)), _sha(str(v)))
    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert (_sha(str(d)), _sha(str(v))) == before


def test_duplicated_hunk_aborts(tmp_path, pristine):
    """Two copies of a patched post-image is not a valid state either: the
    hunk's post-image count exceeds its expected count, which is drift."""
    d, v = _stage(tmp_path, *pristine)
    assert _run(tmp_path).returncode == 0
    h1 = [h for h in _hunks() if h[0].startswith("H1")][0]
    new = h1[4]
    d.write_text(d.read_text() + "\n\n" + new, encoding="utf-8")  # 2nd copy
    before = (_sha(str(d)), _sha(str(v)))
    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert (_sha(str(d)), _sha(str(v))) == before


def test_check_mode_never_writes(tmp_path, pristine):
    d, v = _stage(tmp_path, *pristine)
    before = (_sha(str(d)), _sha(str(v)))
    r = _run(tmp_path, "--check")
    assert r.returncode == 0
    assert (_sha(str(d)), _sha(str(v))) == before


def test_malformed_generated_source_is_not_written(tmp_path, pristine):
    """If a hunk's post-image is ever mis-shaped the applier must abort on
    the parse (mutation A3 guard: compile-before-write), not leave a
    broken file on disk.  Exercised with a copy of the applier whose H1
    post-image is deliberately made unparseable."""
    d, v = _stage(tmp_path, *pristine)
    before = (_sha(str(d)), _sha(str(v)))

    broken = tmp_path / "d5b_apply_broken.py"
    src = open(APPLIER, encoding="utf-8").read()
    marker = "raise ValueError("
    assert src.count(marker) == 1, src.count(marker)
    broken.write_text(src.replace(marker, "raise ValueError(("),
                      encoding="utf-8")

    r = _run(tmp_path, applier=str(broken))
    assert r.returncode != 0
    assert "does not parse" in (r.stdout + r.stderr)
    assert (_sha(str(d)), _sha(str(v))) == before, "unparseable must not write"


def test_second_replace_failure_rolls_back(tmp_path, pristine, monkeypatch):
    """A handled OSError partway through the swaps must restore every file
    already replaced, drop all temps, and exit non-zero.  Run in-process so
    the failure can be injected on the second os.replace via the applier's
    _REPLACE indirection - all-or-rollback, not just clean input states."""
    sys.path.insert(0, ROOT)
    import d5b_apply

    d, v = _stage(tmp_path, *pristine)
    before = (_sha(str(d)), _sha(str(v)))

    real = d5b_apply._REPLACE
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("injected second-replace failure")
        return real(src, dst)

    monkeypatch.setattr(d5b_apply, "_REPLACE", flaky)
    monkeypatch.chdir(tmp_path)
    rc = d5b_apply.main([])

    assert rc != 0, "a failed swap must exit non-zero"
    assert calls["n"] == 2, "the second replace must have been attempted"
    assert (_sha(str(d)), _sha(str(v))) == before, \
        "rollback must restore both files to their original bytes"
    leftover = sorted((tmp_path / "scripts").glob("*.d5b.tmp"))
    assert leftover == [], leftover
