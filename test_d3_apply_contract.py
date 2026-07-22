"""
D3 applier contract test - d3_apply.py must fail closed.

The applier rewrites a live driver, so its state detection is the last
thing standing between a mis-shaped source and a corrupted file.  These
tests exercise the three states it is allowed to be in and prove that
everything else aborts *before* writing.

No server files are touched: every case runs on a synthetic copy in
tmp_path with cwd swapped there.

Run from the repo root:  python3 -m pytest -q
"""

import hashlib
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLIER = os.path.join(ROOT, "d3_apply.py")
DRIVER = os.path.join(ROOT, "scripts", "collect_etf_ibit.py")


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _stage(tmp_path, body):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    target = tmp_path / "scripts" / "collect_etf_ibit.py"
    target.write_text(body, encoding="utf-8")
    return target


def _run(tmp_path, *args):
    return subprocess.run([sys.executable, APPLIER] + list(args),
                          cwd=str(tmp_path), capture_output=True, text=True)


@pytest.fixture
def pristine():
    """The driver with D3 reversed - i.e. the D4-only state that d3_apply
    is meant to be run against.  D4 is left applied because the D3 hunks
    anchor on D4 output."""
    sys.path.insert(0, ROOT)
    import d3_apply
    src = open(DRIVER, encoding="utf-8").read()
    for _label, _expect, old, new in reversed(d3_apply.HUNKS):
        src = src.replace(new, old)
    return src


def test_applier_is_present():
    assert os.path.isfile(APPLIER), APPLIER


def test_fresh_source_applies_cleanly(tmp_path, pristine):
    target = _stage(tmp_path, pristine)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ABORT" not in r.stdout
    assert target.read_text() != pristine


def test_rerun_is_a_clean_noop(tmp_path, pristine):
    target = _stage(tmp_path, pristine)
    assert _run(tmp_path).returncode == 0
    once = _sha(str(target))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already patched" in r.stdout
    assert _sha(str(target)) == once, "a re-run must not change the file"


def test_mixed_state_aborts_without_writing(tmp_path, pristine):
    """A patched file carrying one leftover unpatched signature is not
    'already patched' - it is drift, and must abort."""
    target = _stage(tmp_path, pristine)
    assert _run(tmp_path).returncode == 0
    patched = target.read_text()

    stray = ('\n\ndef _d3_stray(latest, expected):\n'
             '    if True:\n'
             '        target_reached = latest >= expected\n')
    target.write_text(patched + stray, encoding="utf-8")
    before = _sha(str(target))

    r = _run(tmp_path)
    assert r.returncode != 0, "mixed state must not exit 0"
    assert "ABORT" in r.stdout + r.stderr
    assert _sha(str(target)) == before, "aborting run must not write"


def test_partial_apply_aborts_without_writing(tmp_path, pristine):
    """Half-applied source: one hunk reverted on an otherwise patched
    file."""
    sys.path.insert(0, ROOT)
    import d3_apply
    target = _stage(tmp_path, pristine)
    assert _run(tmp_path).returncode == 0
    patched = target.read_text()

    label, expect, old, new = [h for h in d3_apply.HUNKS
                               if h[0] == "store branch respects observation_only"][0]
    target.write_text(patched.replace(new, old), encoding="utf-8")
    before = _sha(str(target))

    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert _sha(str(target)) == before


def test_duplicated_hunk_aborts(tmp_path, pristine):
    """Two copies of a patched block is not a valid state either."""
    target = _stage(tmp_path, pristine)
    assert _run(tmp_path).returncode == 0
    patched = target.read_text()
    target.write_text(
        patched + '\n\n        target_reached = (not observation_only) and latest >= expected\n',
        encoding="utf-8")
    before = _sha(str(target))

    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert _sha(str(target)) == before


def test_unrelated_source_aborts(tmp_path):
    target = _stage(tmp_path, "import os\n\nprint('not the driver')\n")
    before = _sha(str(target))
    r = _run(tmp_path)
    assert r.returncode != 0
    assert "ABORT" in r.stdout + r.stderr
    assert _sha(str(target)) == before


def test_check_mode_never_writes(tmp_path, pristine):
    target = _stage(tmp_path, pristine)
    before = _sha(str(target))
    r = _run(tmp_path, "--check")
    assert r.returncode == 0
    assert _sha(str(target)) == before


def test_malformed_generated_source_is_not_written(tmp_path, pristine):
    """The hunks carry generated code.  If a hunk is ever mis-escaped the
    applier must abort on the parse, not leave a broken driver on disk.

    Exercised by running a copy of the applier whose injected block is
    deliberately unparseable.
    """
    target = _stage(tmp_path, pristine)
    before = _sha(str(target))

    broken = tmp_path / "d3_apply_broken.py"
    src = open(APPLIER, encoding="utf-8").read()
    marker = 'def _target_lag_for(ticker, meta):'
    assert marker in src
    broken.write_text(src.replace(marker, '_LEGACY_TICKER = "IBIT\n'),
                      encoding="utf-8")

    r = subprocess.run([sys.executable, str(broken)],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode != 0
    assert "does not parse" in (r.stdout + r.stderr)
    assert _sha(str(target)) == before, "unparseable result must not be written"
