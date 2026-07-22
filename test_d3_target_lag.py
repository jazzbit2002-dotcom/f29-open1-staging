"""
D3 tests - per-issuer completion target and observation-only mode.

Contract under test:

  ratified lag (int >= 0)   expected_issuer_as_of is that many U.S.
                            business days behind the baseline; lag 0 is
                            the rule IBIT was ratified on
  lag is None               observation_only - collect, parse, store,
                            revision and collect_log all run, but the
                            done marker and the first_seen ledger are
                            never written

The blank first_seen under observation-only is deliberate.  first_seen is
the completion ledger ("first reached this window's target"), and an
issuer whose target is not ratified has no target to have reached.  The
promotion evidence lives in etf_collect_log instead.  Nothing here should
ever be "fixed" by backfilling first_seen.

No network: collectors.etf_issuer.poll_and_collect is monkeypatched
throughout, and every path runs against tmp_path.

Run from the repo root:  python3 -m pytest -q
"""

import json
import os
import sqlite3

import pytest

from collectors import etf_issuer as E
import scripts.collect_etf_ibit as C

SCHEMA = """
-- Verbatim from the production sqlite_master (2026-07-22).  Do not
-- hand-write this: etf_collect_log carries PRIMARY KEY
-- (source_id, input_digest), and a replica without it silently
-- validates designs the real database rejects.
CREATE TABLE etf_daily (
  asset TEXT NOT NULL, ticker TEXT NOT NULL,
  issuer_as_of_date TEXT NOT NULL,
  effective_trade_date TEXT,
  delta_shares REAL, nav_per_share REAL, est_creation_usd REAL,
  source_id TEXT, input_digest TEXT,
  first_seen_at TEXT, last_seen_at TEXT,
  persistence_mode TEXT,
  alignment_status TEXT DEFAULT 'provisional',
  PRIMARY KEY (asset, ticker, issuer_as_of_date)
);
CREATE TABLE etf_daily_revisions (
  asset TEXT NOT NULL, ticker TEXT NOT NULL, issuer_as_of_date TEXT NOT NULL,
  delta_shares REAL, nav_per_share REAL, est_creation_usd REAL,
  source_revision_digest TEXT NOT NULL, seen_at TEXT,
  PRIMARY KEY (asset, ticker, issuer_as_of_date, source_revision_digest)
);
CREATE TABLE etf_collect_log (
  source_id TEXT NOT NULL, input_digest TEXT NOT NULL,
  processed_at TEXT, rows_added INTEGER, revisions_added INTEGER,
  window_date_kst TEXT, latest_as_of TEXT,
  completed INTEGER DEFAULT 0,
  PRIMARY KEY (source_id, input_digest)
);
CREATE TABLE source_health (
  source_id TEXT PRIMARY KEY,
  last_success_at TEXT, last_status TEXT, consecutive_failures INTEGER DEFAULT 0,
  kill_switch_active INTEGER DEFAULT 0, rights_status TEXT, owner_override TEXT
);
CREATE TABLE pipeline_runs (
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
  step TEXT, status TEXT, notes TEXT
);
"""


def _issuer(**extra):
    d = {"enabled": True, "kill_switch_active": False,
         "download_url": "http://example.invalid/x",
         "parser": "ishares_spreadsheetml"}
    d.update(extra)
    return d


REGISTRY = {
    "assets": {"BTC": {"enabled": True, "issuers": {
        # no field -> legacy fallback keeps the ratified lag of 0
        "IBIT": _issuer(),
        # ratified explicitly
        "GBTC": _issuer(target_lag_us_business_days=0),
        "LAGONE": _issuer(target_lag_us_business_days=1),
        # no field, not IBIT -> observation-only
        "OBSV": _issuer(),
        # explicitly unratified
        "NULLED": _issuer(target_lag_us_business_days=None),
    }}},
    "freshness": {"max_lag_business_days": 5},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
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
    monkeypatch.setattr(C, "DONE_MARKER", str(ledger / "done.json"))
    monkeypatch.setattr(C, "LOCKFILE", str(ledger / ".lock"))
    monkeypatch.setattr(C, "FIRST_SEEN_LOG", str(ledger / "fs.log"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    return tmp_path, ledger


def _series(latest):
    return [{"as_of": "2026-07-14", "delta_shares": 1.0,
             "nav_per_share": 10.0, "est_creation_usd": 10.0},
            {"as_of": latest, "delta_shares": 2.0,
             "nav_per_share": 10.0, "est_creation_usd": 20.0}]


def _poll(latest, digest):
    def fn(*a, **k):
        return {"input_digest": digest, "persistence_mode": "ephemeral_memory",
                "freshness": "ok", "latest_as_of": latest,
                "creation_series": _series(latest)}
    return fn


def _counts(tmp, ticker):
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    src = "etf_issuer_%s" % ticker.lower()
    daily = con.execute("SELECT COUNT(*) FROM etf_daily WHERE ticker=?",
                        (ticker,)).fetchone()[0]
    log = con.execute("SELECT COUNT(*) FROM etf_collect_log WHERE source_id=?",
                      (src,)).fetchone()[0]
    con.close()
    return daily, log


def _fs_lines(path):
    return len(open(path).read().strip().splitlines()) if os.path.exists(path) else 0


# ---------------------------------------------------------- 1-2  resolver
def test_ibit_without_field_falls_back_to_zero():
    assert C._target_lag_for("IBIT", {}) == 0
    assert C._target_lag_for("ibit", {}) == 0


def test_non_ibit_without_field_is_observation_only():
    assert C._target_lag_for("GBTC", {}) is None
    assert C._target_lag_for("FBTC", {}) is None


# ---------------------------------------------------------- 3-5  values
def test_explicit_zero_is_completion_mode(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digG"))
    assert C.main("BTC", "GBTC") == 0
    assert os.path.exists(str(ledger / "etf_gbtc_done.json"))


def test_explicit_positive_lag_moves_the_target(env, monkeypatch):
    """LAGONE targets 07-15 for a 07-17 window, so a 07-15 file completes
    it while the same file would be below IBIT's 07-16 target."""
    tmp, ledger = env
    assert C._expected_as_of("2026-07-17", 0) == "2026-07-16"
    assert C._expected_as_of("2026-07-17", 1) == "2026-07-15"

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-15", "digL"))
    assert C.main("BTC", "LAGONE") == 0
    marker = json.loads(open(str(ledger / "etf_lagone_done.json")).read())
    assert marker["expected_issuer_as_of"] == "2026-07-15"
    assert marker["as_of"] == "2026-07-15"


def test_explicit_none_is_observation_only(env, monkeypatch):
    tmp, ledger = env
    assert C._target_lag_for("NULLED", {"target_lag_us_business_days": None}) is None
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digN"))
    assert C.main("BTC", "NULLED") == 0
    assert not os.path.exists(str(ledger / "etf_nulled_done.json"))


# ------------------------------------------- U.S. business-day boundary
@pytest.mark.parametrize("window,lag,expected", [
    # 2026-07-03 is the observed holiday for Saturday the 4th, and the 4th
    # and 5th are the weekend - so a Monday window steps back to Thursday.
    ("2026-07-06", 0, "2026-07-02"),
    ("2026-07-20", 0, "2026-07-17"),      # Monday -> Friday
    ("2026-07-17", 0, "2026-07-16"),      # plain weekday
    # Discriminating cases: the SECOND step is the one that has to cross a
    # non-business stretch.  Subtracting calendar days after a single
    # prev_us_business_day() call would land on 07-05 (Sunday) and 07-18
    # (Saturday) respectively.
    ("2026-07-07", 1, "2026-07-02"),
    ("2026-07-21", 2, "2026-07-16"),
])
def test_expected_as_of_crosses_holidays_and_weekends(window, lag, expected):
    """Locks the per-issuer helper itself, not just the calendar it calls:
    every lag step has to go through prev_us_business_day, or a multi-day
    lag would skip a holiday it should have stepped over."""
    assert C._expected_as_of(window, lag) == expected


# ---------------------------------------------------------- 6  validation
@pytest.mark.parametrize("bad", ["0", 0.0, True, False, -1, "one", [], 1.5])
def test_invalid_lag_values_are_rejected(bad):
    with pytest.raises(ValueError) as e:
        C._target_lag_for("X", {"target_lag_us_business_days": bad})
    assert "invalid target_lag_us_business_days" in str(e.value)


@pytest.mark.parametrize("bad", ["0", 0.0, True, -1])
def test_invalid_lag_fails_before_any_fetch(bad, env, monkeypatch, tmp_path):
    tmp, ledger = env
    reg = json.loads(json.dumps(REGISTRY))
    reg["assets"]["BTC"]["issuers"]["BADLAG"] = _issuer(
        target_lag_us_business_days=bad)
    (tmp / "registry.json").write_text(json.dumps(reg))

    called = []
    monkeypatch.setattr(E, "poll_and_collect",
                        lambda *a, **k: called.append(1))
    with pytest.raises(ValueError):
        C.main("BTC", "BADLAG")
    assert called == [], "fetch ran despite an invalid lag"
    assert not os.path.exists(str(ledger / "etf_badlag_done.json"))




# ------------------------------------------------- observation-only (A-safe)
def _log_rows(tmp, ticker):
    """Ordered by digest, not by processed_at: two rows written in the same
    second would otherwise come back in an undefined order."""
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    rows = list(con.execute(
        "SELECT window_date_kst, latest_as_of, rows_added, revisions_added, "
        "completed FROM etf_collect_log WHERE source_id=? ORDER BY input_digest",
        ("etf_issuer_%s" % ticker.lower(),)))
    con.close()
    return rows


def _log_row(tmp, ticker, digest):
    """The single row for one digest - collect_log is keyed on it."""
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    row = con.execute(
        "SELECT window_date_kst, latest_as_of, rows_added, revisions_added, "
        "completed FROM etf_collect_log WHERE source_id=? AND input_digest=?",
        ("etf_issuer_%s" % ticker.lower(), digest)).fetchone()
    con.close()
    return row


def _runs(tmp, ticker, status=None):
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    q, a = "SELECT status, notes FROM pipeline_runs WHERE step=?", \
           ["etf_%s" % ticker.lower()]
    if status:
        q += " AND status=?"
        a.append(status)
    rows = list(con.execute(q, a))
    con.close()
    return rows


def _ratify(tmp, ticker, lag):
    """Flip an issuer from observation-only to ratified, as D5 would."""
    reg = json.loads((tmp / "registry.json").read_text())
    reg["assets"]["BTC"]["issuers"][ticker]["target_lag_us_business_days"] = lag
    (tmp / "registry.json").write_text(json.dumps(reg))


def test_observation_only_fresh_stores_but_marks_nothing(env, monkeypatch):
    """A new digest still leaves its first-observation row - that row IS the
    lag sample.  Nothing claims completion."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    assert C.main("BTC", "OBSV") == 0

    daily, _ = _counts(tmp, "OBSV")
    assert daily == 2, "canonical rows must still be written"
    rows = _log_rows(tmp, "OBSV")
    assert len(rows) == 1
    assert rows[0] == ("2026-07-17", "2026-07-16", 2, 0, 0), \
        "first-observation row must carry its window, as_of and completed=0"

    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0
    assert not os.path.exists(str(ledger / "done.json"))
    assert _fs_lines(str(ledger / "fs.log")) == 0


def test_observation_only_same_digest_same_window_is_a_noop(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    C.main("BTC", "OBSV")
    before = _log_rows(tmp, "OBSV")

    assert C.main("BTC", "OBSV") == 0
    assert _log_rows(tmp, "OBSV") == before, "collect_log was touched"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0


def test_observation_only_same_digest_new_window_is_a_noop(env, monkeypatch):
    """collect_log is keyed (source_id, input_digest): an unchanged file in a
    later window is not a new lag sample and must not be recorded."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    C.main("BTC", "OBSV")
    before = _log_rows(tmp, "OBSV")

    for w in ("2026-07-18", "2026-07-20", "2026-07-21"):
        monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None, _w=w: _w)
        assert C.main("BTC", "OBSV") == 0

    assert _log_rows(tmp, "OBSV") == before, "a later window added or rewrote a row"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0


def test_liveness_is_recorded_in_pipeline_runs(env, monkeypatch):
    """Execution liveness lives in pipeline_runs, not collect_log."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    C.main("BTC", "OBSV")
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-18")
    C.main("BTC", "OBSV")

    noops = _runs(tmp, "OBSV", "NOOP")
    assert len(noops) == 1, "the duplicate run left no liveness evidence"
    assert "observation_only=True" in noops[0][1]


def test_observation_only_never_reaches_write_done(env, monkeypatch):
    tmp, ledger = env
    calls = []
    real = C._write_done
    monkeypatch.setattr(C, "_write_done",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    C.main("BTC", "OBSV")
    C.main("BTC", "OBSV")
    assert calls == []


# ------------------------------------------------- ratification takes effect
def test_ratified_issuer_below_target_writes_no_marker(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-15", "digBelow"))
    assert C.main("BTC", "GBTC") == 0          # target is 07-16
    daily, _ = _counts(tmp, "GBTC")
    assert daily == 2, "below-target data is still stored"
    assert not os.path.exists(str(ledger / "etf_gbtc_done.json"))
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 0


def test_ratified_issuer_at_target_writes_marker(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-15", "digBelow"))
    C.main("BTC", "GBTC")
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digTarget"))
    assert C.main("BTC", "GBTC") == 0
    marker = json.loads(open(str(ledger / "etf_gbtc_done.json")).read())
    assert marker["expected_issuer_as_of"] == "2026-07-16"
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 1
    assert _log_row(tmp, "GBTC", "digBelow")[4] == 0
    assert _log_row(tmp, "GBTC", "digTarget")[4] == 1


def test_ratification_does_not_promote_an_observation_row(env, monkeypatch):
    """A-safe: the unratified row keeps completed=0 and its first window.
    Promoting it in place would make crash recovery and holiday reuse
    indistinguishable, so ratification waits for the next new digest."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digOld"))
    C.main("BTC", "OBSV")
    before = _log_rows(tmp, "OBSV")
    assert before[0][4] == 0

    _ratify(tmp, "OBSV", 0)
    assert C.main("BTC", "OBSV") == 0          # same digest, target met

    assert _log_rows(tmp, "OBSV") == before, "observation row was rewritten"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json")), \
        "an unratified-era row must not produce a marker"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0
    assert any("completed=0" in n for _s, n in _runs(tmp, "OBSV", "NOOP"))


def test_ratification_takes_effect_on_the_next_new_digest(env, monkeypatch):
    """The post-ratification digest flows through the untouched fresh/store
    path: ledger commit, then marker, then first_seen."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digOld"))
    C.main("BTC", "OBSV")
    _ratify(tmp, "OBSV", 0)
    C.main("BTC", "OBSV")                      # still a no-op

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digNew"))
    assert C.main("BTC", "OBSV") == 0

    assert len(_log_rows(tmp, "OBSV")) == 2
    assert _log_row(tmp, "OBSV", "digOld")[4] == 0, \
        "the observation row must stay untouched"
    assert _log_row(tmp, "OBSV", "digNew")[4] == 1, \
        "the new digest must settle as completed"
    assert json.loads(open(str(ledger / "etf_obsv_done.json")).read())["as_of"] \
        == "2026-07-16"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1


def test_ledger_commits_before_the_marker(env, monkeypatch):
    """B-15 durability: a crash at _write_done leaves the ledger settled and
    the window recoverable."""
    tmp, ledger = env
    _ratify(tmp, "OBSV", 0)
    real_write = C._write_done

    def crash(*a, **k):
        raise OSError("simulated crash before the marker")
    monkeypatch.setattr(C, "_write_done", crash)
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digDur"))
    with pytest.raises(OSError):
        C.main("BTC", "OBSV")

    rows = _log_rows(tmp, "OBSV")
    assert len(rows) == 1 and rows[0][4] == 1, \
        "ledger was not durable before the marker"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0

    monkeypatch.setattr(C, "_write_done", real_write)
    assert C.main("BTC", "OBSV") == 0
    assert os.path.exists(str(ledger / "etf_obsv_done.json")), "marker not recovered"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1
    assert len(_log_rows(tmp, "OBSV")) == 1, "recovery duplicated a row"


# ------------------------------------------------- IBIT no-regression
def test_ibit_semantics_are_untouched_by_d3(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digI"))
    assert C.main("BTC", "IBIT") == 0
    marker = json.loads(open(str(ledger / "done.json")).read())
    assert marker["expected_issuer_as_of"] == "2026-07-16"
    assert _fs_lines(str(ledger / "fs.log")) == 1
    assert not os.path.exists(str(ledger / "etf_ibit_done.json"))


def test_ibit_completed_duplicate_keeps_b16(env, monkeypatch):
    """An already-completed digest re-read in the same window recovers the
    marker and tops up first_seen, exactly as before D3."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digI"))
    C.main("BTC", "IBIT")
    os.remove(str(ledger / "done.json"))
    assert C.main("BTC", "IBIT") == 0
    assert os.path.exists(str(ledger / "done.json"))
    assert _fs_lines(str(ledger / "fs.log")) == 2


def test_ibit_holiday_same_digest_keeps_b16(env, monkeypatch):
    """Prior window completed, same digest satisfies today's target: marker
    only, and no first_seen because the originating window already has it."""
    tmp, ledger = env
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    con.execute("INSERT INTO etf_collect_log (source_id, input_digest, "
                "processed_at, rows_added, revisions_added, window_date_kst, "
                "latest_as_of, completed) VALUES (?,?,?,?,?,?,?,?)",
                ("etf_issuer_ibit", "digHol", "2026-07-16T01:00:00Z", 1, 0,
                 "2026-07-16", "2026-07-16", 1))
    con.commit()
    con.close()

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digHol"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    assert C.main("BTC", "IBIT") == 0
    marker = json.loads(open(str(ledger / "done.json")).read())
    assert marker["window_date_kst"] == "2026-07-17"
    assert marker["expected_issuer_as_of"] == "2026-07-16"
    assert _fs_lines(str(ledger / "fs.log")) == 0
