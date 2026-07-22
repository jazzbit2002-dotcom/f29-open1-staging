"""
D4-4 test - scripts/cron_etf.sh

Scope note: these tests never let the wrapper reach its python line.
Argument-validation paths exit before it, and the log-derivation test
runs a copy whose final line is replaced by `echo`.  No collector run,
no network, no ledger or DB writes.

Run from the repo root:  python3 -m pytest -q
"""

import os
import shutil
import subprocess

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.join(BASE, "scripts", "cron_etf.sh")


def _run(args, cwd=None):
    return subprocess.run(["bash", WRAPPER] + args, cwd=cwd or BASE,
                          capture_output=True, text=True)


def test_cron_etf_wrapper_exists():
    assert os.path.isfile(WRAPPER), WRAPPER


def test_cron_etf_wrapper_syntax():
    """bash -n : same gate the IBIT wrapper is held to."""
    r = subprocess.run(["bash", "-n", WRAPPER], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("args", [[], ["BTC"], ["BTC", "GBTC", "extra"]])
def test_wrong_argument_count_is_rejected(args):
    r = _run(args)
    assert r.returncode == 2
    assert "usage:" in r.stderr


@pytest.mark.parametrize("ticker", ["", "GB/TC", "GB TC", "GB;TC", "../GBTC",
                                    "GB.TC", "GB-TC"])
def test_unsafe_ticker_is_rejected(ticker):
    """Ticker reaches a file path and a DB source_id."""
    r = _run(["BTC", ticker])
    assert r.returncode == 2
    assert "invalid ticker" in r.stderr


@pytest.mark.parametrize("asset", ["", "B/TC", "B TC", "../BTC"])
def test_unsafe_asset_is_rejected(asset):
    r = _run([asset, "GBTC"])
    assert r.returncode == 2
    assert "invalid asset" in r.stderr


def test_log_path_and_args_follow_d4_1(tmp_path):
    """D4-1: log = ledger/cron_<tolower(ticker)>.log, and the ticker is
    forwarded verbatim to the collector.

    The collector invocation is swapped for `echo` so nothing is
    collected; we assert on the arguments and the redirect target.
    """
    stage = tmp_path / "repo"
    (stage / "scripts").mkdir(parents=True)
    src = open(WRAPPER).read()
    assert "python3 scripts/collect_etf_ibit.py" in src
    src = src.replace("python3 scripts/collect_etf_ibit.py",
                      "echo COLLECT")
    probe = stage / "scripts" / "cron_etf.sh"
    probe.write_text(src)

    r = subprocess.run(["bash", str(probe), "BTC", "GBTC"],
                       cwd=str(stage), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    log = stage / "ledger" / "cron_gbtc.log"
    assert log.is_file(), sorted(p.name for p in (stage / "ledger").iterdir())
    body = log.read_text()
    assert "--asset BTC" in body
    assert "--ticker GBTC" in body


def test_ibit_wrapper_is_untouched():
    """D4-4: cron_ibit.sh keeps its own hard-coded names."""
    ibit = os.path.join(BASE, "scripts", "cron_ibit.sh")
    # Asserted, not skipped: a missing cron_ibit.sh would itself be a
    # D4-4 contract breach ("existing IBIT wiring unchanged"), and a skip
    # would hide it behind a green run.
    assert os.path.isfile(ibit), "cron_ibit.sh must remain in place: %s" % ibit
    src = open(ibit).read()
    assert "ledger/cron_ibit.log" in src
    assert "--ticker IBIT" in src


def test_wrapper_does_not_hardcode_ibit_ledger_paths():
    """No IBIT-fixed ledger/lock/ticker names may survive in the body.

    The collector module name `collect_etf_ibit.py` IS retained on
    purpose - renaming it would force edits to the 33 existing tests
    that do `import scripts.collect_etf_ibit`, which D4 scope forbids.
    So the check targets the derived artefacts, not the module name.
    """
    src = open(WRAPPER).read()
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "cron_ibit.log" not in body
    assert "ledger/cron_ibit" not in body
    assert ".etf_ibit." not in body
    assert "ibit_first_seen" not in body
    assert "--ticker IBIT" not in body
    assert "collect_etf_ibit.py" in body  # retained by design
