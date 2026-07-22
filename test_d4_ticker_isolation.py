"""
D4-5 tests - per-ticker ledger isolation.

Everything here runs against tmp_path with collectors.etf_issuer
.poll_and_collect monkeypatched, so there is no network call, no write to
the live ledger, and no write to the live database.

What is being locked:
  D4-1  artefact names derive from the ticker
  D4-2  IBIT keeps the module globals, so the existing monkeypatch points
        in tests/test_etf_issuer.py stay valid
  D4-5  a marker written by one ticker must not complete another ticker's
        window, in both directions
  guard an unsafe ticker never reaches the filesystem

Run from the repo root:  python3 -m pytest -q
"""

import json
import os
import sqlite3

import pytest

from collectors import etf_issuer as E
import scripts.collect_etf_ibit as C

SCHEMA = """
CREATE TABLE etf_daily (asset TEXT, ticker TEXT, issuer_as_of_date TEXT,
  effective_trade_date TEXT, delta_shares REAL, nav_per_share REAL,
  est_creation_usd REAL, source_id TEXT, input_digest TEXT,
  first_seen_at TEXT, last_seen_at TEXT, persistence_mode TEXT,
  alignment_status TEXT, PRIMARY KEY (asset, ticker, issuer_as_of_date));
CREATE TABLE etf_daily_revisions (asset TEXT, ticker TEXT,
  issuer_as_of_date TEXT, delta_shares REAL, nav_per_share REAL,
  est_creation_usd REAL, source_revision_digest TEXT, seen_at TEXT,
  PRIMARY KEY (asset, ticker, issuer_as_of_date, source_revision_digest));
CREATE TABLE etf_collect_log (source_id TEXT, input_digest TEXT,
  processed_at TEXT, rows_added INT, revisions_added INT,
  window_date_kst TEXT, latest_as_of TEXT, completed INT);
CREATE TABLE source_health (source_id TEXT PRIMARY KEY, last_success_at TEXT,
  last_status TEXT, consecutive_failures INT);
CREATE TABLE pipeline_runs (run_id TEXT, started_at TEXT, finished_at TEXT,
  step TEXT, status TEXT, notes TEXT);
"""

REGISTRY = {
    "assets": {"BTC": {"enabled": True, "issuers": {
        "IBIT": {"enabled": True, "kill_switch_active": False,
                 "download_url": "http://example.invalid/ibit",
                 "parser": "ishares_spreadsheetml"},
        # D3: this suite is about marker/lock/log isolation between two
        # COMPLETABLE tickers, so GBTC declares a ratified lag here.  The
        # observation-only path is locked separately in the D3 suite.
        "GBTC": {"enabled": True, "kill_switch_active": False,
                 "download_url": "http://example.invalid/gbtc",
                 "parser": "grayscale_ooxml",
                 "target_lag_us_business_days": 0},
    }}},
    "freshness": {"max_lag_business_days": 5},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every module global into tmp_path, mirroring the shape
    the existing suite's _script_env uses."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    db = tmp_path / "core.sqlite"
    con = sqlite3.connect(str(db))
    con.executescript(SCHEMA)
    con.commit()
    con.close()

    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(REGISTRY))

    monkeypatch.setattr(C, "LEDGER", str(ledger))
    monkeypatch.setattr(C, "DB", str(db))
    monkeypatch.setattr(C, "REGISTRY", str(reg))
    # Deliberately NOT the derived names.  The existing suite patches
    # these to arbitrary paths (tmp_path/"done.json", tmp_path/"fs.log"),
    # so IBIT must read the globals rather than re-deriving - and the
    # fixture has to be able to tell the two apart.
    monkeypatch.setattr(C, "DONE_MARKER", str(ledger / "done.json"))
    monkeypatch.setattr(C, "LOCKFILE", str(ledger / ".lock"))
    monkeypatch.setattr(C, "FIRST_SEEN_LOG", str(ledger / "fs.log"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    return tmp_path, ledger


def _poll(as_of, digest):
    def fn(*a, **k):
        return {"input_digest": digest, "persistence_mode": "ephemeral_memory",
                "freshness": "ok", "latest_as_of": as_of,
                "creation_series": [
                    {"as_of": "2026-07-15", "delta_shares": 1.0,
                     "nav_per_share": 10.0, "est_creation_usd": 10.0},
                    {"as_of": as_of, "delta_shares": 2.0,
                     "nav_per_share": 10.0, "est_creation_usd": 20.0}]}
    return fn


# ------------------------------------------------ D4-2: IBIT unchanged
def test_ibit_reuses_the_module_globals(env):
    assert C._paths_for("IBIT") == (
        C.DONE_MARKER, C.LOCKFILE, C.FIRST_SEEN_LOG, "etf_ibit")


def test_ibit_honours_arbitrary_monkeypatched_paths(env):
    """Discriminating test: the globals are patched to names that the
    D4-1 rule would never produce.  If IBIT ever re-derives instead of
    returning the globals, the existing suite's patch points break."""
    tmp, ledger = env
    done, lock, fs, tag = C._paths_for("IBIT")
    assert done == str(ledger / "done.json")
    assert lock == str(ledger / ".lock")
    assert fs == str(ledger / "fs.log")
    assert "etf_ibit_done.json" not in done
    assert "ibit_first_seen.log" not in fs


# ------------------------------------------------ D4-1: derivation
def test_new_ticker_derives_its_own_artefacts(env):
    tmp, ledger = env
    done, lock, fs, tag = C._paths_for("GBTC")
    assert done == os.path.join(str(ledger), "etf_gbtc_done.json")
    assert lock == os.path.join(str(ledger), ".etf_gbtc.lock")
    assert fs == os.path.join(str(ledger), "gbtc_first_seen.log")
    assert tag == "etf_gbtc"


def test_ticker_case_is_normalised(env):
    assert C._paths_for("gbtc") == C._paths_for("GBTC")


def test_every_artefact_differs_between_tickers(env):
    a, b = C._paths_for("IBIT"), C._paths_for("GBTC")
    assert len(set(a) & set(b)) == 0, "no artefact may be shared"


# ------------------------------------------------ guard
@pytest.mark.parametrize("bad", ["", "../../etc/passwd", "GB TC", "GB-TC",
                                 "GB.TC", "GB/TC", "GB;TC",
                                 "GBTC\n", "GBTC\r\n", "\nGBTC", "GB\nTC",
                                 "GBTC\t", "GBTC ", "\u0661\u0662"])
def test_unsafe_ticker_never_reaches_the_filesystem(bad, env):
    tmp, ledger = env
    before = set(os.listdir(str(ledger)))
    with pytest.raises(ValueError) as e:
        C._paths_for(bad)
    assert "unsafe ticker" in str(e.value)
    assert set(os.listdir(str(ledger))) == before


def test_unsafe_ticker_is_rejected_before_the_lock_file(env):
    """The lock is opened before the registry is consulted, so the guard
    has to fire earlier than that."""
    tmp, ledger = env
    with pytest.raises(ValueError):
        C.main("BTC", "../../evil")
    assert not any(p.startswith(".etf_") for p in os.listdir(str(ledger)))


# ------------------------------------------------ D4-5: cross-contamination
def test_ibit_marker_does_not_complete_gbtc(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digIBIT"))
    assert C.main("BTC", "IBIT") == 0
    assert os.path.exists(str(ledger / "done.json"))

    ibit_done, _, _, _ = C._paths_for("IBIT")
    gbtc_done, _, _, _ = C._paths_for("GBTC")
    assert C._done_today("2026-07-17", ibit_done) is True
    assert C._done_today("2026-07-17", gbtc_done) is False

    # GBTC must still reach the network and write its own marker.
    reached = []

    def gbtc_poll(*a, **k):
        reached.append(1)
        return _poll("2026-07-16", "digGBTC")()
    monkeypatch.setattr(E, "poll_and_collect", gbtc_poll)
    assert C.main("BTC", "GBTC") == 0
    assert reached == [1], "IBIT marker blocked GBTC from polling"
    assert os.path.exists(str(ledger / "etf_gbtc_done.json"))


def test_gbtc_marker_does_not_complete_ibit(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digGBTC"))
    assert C.main("BTC", "GBTC") == 0
    assert os.path.exists(str(ledger / "etf_gbtc_done.json"))
    assert not os.path.exists(str(ledger / "done.json"))

    reached = []

    def ibit_poll(*a, **k):
        reached.append(1)
        return _poll("2026-07-16", "digIBIT")()
    monkeypatch.setattr(E, "poll_and_collect", ibit_poll)
    assert C.main("BTC", "IBIT") == 0
    assert reached == [1], "GBTC marker blocked IBIT from polling"


def test_ledgers_and_runlog_tags_stay_separate(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digIBIT"))
    C.main("BTC", "IBIT")
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digGBTC"))
    C.main("BTC", "GBTC")

    assert os.path.exists(str(ledger / "fs.log"))
    assert os.path.exists(str(ledger / "gbtc_first_seen.log"))
    ibit_fs = open(str(ledger / "fs.log")).read()
    gbtc_fs = open(str(ledger / "gbtc_first_seen.log")).read()
    assert len(ibit_fs.strip().splitlines()) == 1
    assert len(gbtc_fs.strip().splitlines()) == 1

    con = sqlite3.connect(str(tmp / "core.sqlite"))
    steps = {r[0] for r in con.execute("SELECT DISTINCT step FROM pipeline_runs")}
    assert steps == {"etf_ibit", "etf_gbtc"}
    sources = {r[0] for r in con.execute("SELECT DISTINCT source_id FROM etf_collect_log")}
    assert sources == {"etf_issuer_ibit", "etf_issuer_gbtc"}
    con.close()


def test_lock_files_do_not_serialise_tickers(env):
    """Separate cronlock/lock names are what let two issuers run in the
    same slot window."""
    import fcntl
    tmp, ledger = env
    _, ibit_lock, _, _ = C._paths_for("IBIT")
    _, gbtc_lock, _, _ = C._paths_for("GBTC")
    assert ibit_lock != gbtc_lock

    a = open(ibit_lock, "w")
    fcntl.flock(a, fcntl.LOCK_EX | fcntl.LOCK_NB)
    b = open(gbtc_lock, "w")
    fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)   # must not raise
    fcntl.flock(b, fcntl.LOCK_UN); b.close()
    fcntl.flock(a, fcntl.LOCK_UN); a.close()


# ------------------------------------------------ D4-5: duplicate / B-16 recovery
def test_gbtc_duplicate_recovery_stays_on_gbtc_artefacts(env, monkeypatch):
    """Marker loss + same digest re-run enters the dup branch, which has
    its own _done_today / _write_done / _log_first_seen call sites."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digGBTC"))
    assert C.main("BTC", "GBTC") == 0
    gbtc_done = str(ledger / "etf_gbtc_done.json")
    gbtc_fs = str(ledger / "gbtc_first_seen.log")
    assert os.path.exists(gbtc_done)
    assert len(open(gbtc_fs).read().strip().splitlines()) == 1

    os.remove(gbtc_done)                      # simulate marker loss
    before = set(os.listdir(str(ledger)))

    assert C.main("BTC", "GBTC") == 0         # same digest -> dup branch
    assert os.path.exists(gbtc_done), "dup branch did not restore the marker"
    # D3: first_seen is written once per window.  Run 1 already logged it,
    # so recovering a deleted marker must not append a second line.
    assert len(open(gbtc_fs).read().strip().splitlines()) == 1

    # nothing belonging to IBIT was created or touched
    assert not os.path.exists(str(ledger / "done.json"))
    assert not os.path.exists(str(ledger / "fs.log"))
    assert not os.path.exists(str(ledger / "etf_ibit_done.json"))
    assert not os.path.exists(str(ledger / "ibit_first_seen.log"))
    assert set(os.listdir(str(ledger))) - before == {"etf_gbtc_done.json"}

    con = sqlite3.connect(str(tmp / "core.sqlite"))
    steps = [r[0] for r in con.execute(
        "SELECT step FROM pipeline_runs WHERE status='NOOP'")]
    assert steps == ["etf_gbtc"], "dup NOOP logged under the wrong tag"
    con.close()


def test_ibit_duplicate_recovery_uses_the_monkeypatched_globals(env, monkeypatch):
    """The globals are patched to names the D4-1 rule never produces, so
    this fails if the dup branch re-derives instead of using them."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digIBIT"))
    assert C.main("BTC", "IBIT") == 0
    ibit_done = str(ledger / "done.json")
    ibit_fs = str(ledger / "fs.log")
    assert os.path.exists(ibit_done)
    assert len(open(ibit_fs).read().strip().splitlines()) == 1

    os.remove(ibit_done)

    assert C.main("BTC", "IBIT") == 0         # same digest -> dup branch
    assert os.path.exists(ibit_done), "dup branch did not restore the marker"
    assert len(open(ibit_fs).read().strip().splitlines()) == 1   # see above


    # the derived names must never appear for IBIT
    assert not os.path.exists(str(ledger / "etf_ibit_done.json"))
    assert not os.path.exists(str(ledger / "ibit_first_seen.log"))
    assert not os.path.exists(str(ledger / "etf_gbtc_done.json"))

    con = sqlite3.connect(str(tmp / "core.sqlite"))
    steps = [r[0] for r in con.execute(
        "SELECT step FROM pipeline_runs WHERE status='NOOP'")]
    assert steps == ["etf_ibit"]
    con.close()


def test_duplicate_recovery_does_not_cross_tickers(env, monkeypatch):
    """Both issuers lose their marker; each recovers only its own."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digIBIT"))
    C.main("BTC", "IBIT")
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digGBTC"))
    C.main("BTC", "GBTC")

    os.remove(str(ledger / "done.json"))
    os.remove(str(ledger / "etf_gbtc_done.json"))

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digIBIT"))
    C.main("BTC", "IBIT")
    assert os.path.exists(str(ledger / "done.json"))
    assert not os.path.exists(str(ledger / "etf_gbtc_done.json")), \
        "IBIT recovery wrote GBTC's marker"

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digGBTC"))
    C.main("BTC", "GBTC")
    assert os.path.exists(str(ledger / "etf_gbtc_done.json"))


def test_trailing_newline_ticker_is_rejected_before_lock(env):
    """Python's "$" matches before a trailing newline, so a match()-based
    guard would let "GBTC\n" through and derive
    'etf_gbtc\n_done.json'.  fullmatch() is what actually enforces the
    "ASCII alphanumerics only" contract."""
    tmp, ledger = env
    before = set(os.listdir(str(ledger)))

    with pytest.raises(ValueError):
        C._paths_for("GBTC\n")
    with pytest.raises(ValueError):
        C.main("BTC", "GBTC\n")

    after = set(os.listdir(str(ledger)))
    assert after == before
    assert not any("\n" in name for name in after)
    assert not any(name.startswith(".etf_") for name in after)


def test_guard_uses_fullmatch_semantics(env):
    """Direct assertion on the predicate, independent of filesystem
    side effects."""
    assert C._SAFE_TICKER.fullmatch("GBTC")
    for bad in ("GBTC\n", "GBTC ", "\nGBTC", ""):
        assert not C._SAFE_TICKER.fullmatch(bad), repr(bad)
