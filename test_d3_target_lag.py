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


# ---------------------------------------------------------- 7-8  observation
def test_observation_only_fresh_stores_but_marks_nothing(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    assert C.main("BTC", "OBSV") == 0

    daily, log = _counts(tmp, "OBSV")
    assert daily == 2, "canonical rows must still be written"
    assert log == 1, "collect_log must still record the observation"

    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0
    assert not os.path.exists(str(ledger / "done.json"))
    assert _fs_lines(str(ledger / "fs.log")) == 0

    con = sqlite3.connect(str(tmp / "core.sqlite"))
    assert con.execute(
        "SELECT completed FROM etf_collect_log WHERE source_id='etf_issuer_obsv'"
    ).fetchone()[0] == 0
    con.close()


def test_observation_only_duplicate_marks_nothing(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    assert C.main("BTC", "OBSV") == 0
    before = _fs_lines(str(ledger / "obsv_first_seen.log"))

    assert C.main("BTC", "OBSV") == 0          # same digest -> dup branch
    daily, log = _counts(tmp, "OBSV")
    assert (daily, log) == (2, 1), "duplicate must not double-write"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == before == 0

    con = sqlite3.connect(str(tmp / "core.sqlite"))
    noop = [r[0] for r in con.execute(
        "SELECT status FROM pipeline_runs WHERE step='etf_obsv'")]
    assert "NOOP" in noop, "duplicate path did not run"
    con.close()


def test_observation_only_never_reaches_write_done(env, monkeypatch):
    """Belt and braces: no code path may call _write_done for an
    unratified issuer, marker recovery included."""
    tmp, ledger = env
    calls = []
    real = C._write_done
    monkeypatch.setattr(C, "_write_done",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digO"))
    C.main("BTC", "OBSV")
    C.main("BTC", "OBSV")
    assert calls == []


# ---------------------------------------------------------- 9-10  targets
def test_ratified_issuer_below_target_writes_no_marker(env, monkeypatch):
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-15", "digBelow"))
    assert C.main("BTC", "GBTC") == 0          # target is 07-16
    daily, log = _counts(tmp, "GBTC")
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


# ---------------------------------------------------------- 11  B-16 recovery
def test_ratified_issuer_recovers_marker_after_crash(env, monkeypatch):
    """B-16: canonical committed, collect_log missing, marker missing.
    A re-run must store idempotently and then complete the window."""
    tmp, ledger = env
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    C.store_new_and_revisions(con, "BTC", "GBTC", "etf_issuer_gbtc",
                              "digCrash", "ephemeral_memory",
                              _series("2026-07-16"))
    con.close()

    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digCrash"))
    assert C.main("BTC", "GBTC") == 0
    marker = json.loads(open(str(ledger / "etf_gbtc_done.json")).read())
    assert marker["as_of"] == "2026-07-16"
    daily, log = _counts(tmp, "GBTC")
    assert daily == 2, "recovery must be idempotent"


# ---------------------------------------------------------- 12  holiday
def test_holiday_same_digest_keeps_b16_semantics(env, monkeypatch):
    """A previous window's digest still completes today when it satisfies
    today's target - the rule that keeps a holiday from re-fetching all
    day.  Unchanged by D3 for a ratified issuer."""
    tmp, ledger = env
    expected = C._expected_as_of("2026-07-17", 0)
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    con.execute("INSERT INTO etf_collect_log (source_id, input_digest, "
                "processed_at, rows_added, revisions_added, window_date_kst, "
                "latest_as_of, completed) VALUES (?,?,?,?,?,?,?,?)",
                ("etf_issuer_gbtc", "digHol", "t", 1, 0, "2026-07-16",
                 expected, 1))
    con.commit()
    con.close()

    monkeypatch.setattr(E, "poll_and_collect", _poll(expected, "digHol"))
    assert C.main("BTC", "GBTC") == 0
    marker = json.loads(open(str(ledger / "etf_gbtc_done.json")).read())
    assert marker["window_date_kst"] == "2026-07-17"
    assert marker["expected_issuer_as_of"] == expected
    # first_seen was already recorded in the originating window
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 0


def test_ibit_semantics_are_untouched_by_d3(env, monkeypatch):
    """IBIT has no registry field, so the legacy fallback must reproduce
    the pre-D3 behaviour exactly."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digI"))
    assert C.main("BTC", "IBIT") == 0
    marker = json.loads(open(str(ledger / "done.json")).read())
    assert marker["expected_issuer_as_of"] == "2026-07-16"
    assert marker["as_of"] == "2026-07-16"
    assert _fs_lines(str(ledger / "fs.log")) == 1
    assert not os.path.exists(str(ledger / "etf_ibit_done.json"))


# ------------------------------------------- observation ledger (new window)
def _log_rows(tmp, ticker):
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    rows = list(con.execute(
        "SELECT window_date_kst, latest_as_of, rows_added, revisions_added, "
        "completed FROM etf_collect_log WHERE source_id=? "
        "ORDER BY processed_at, window_date_kst",
        ("etf_issuer_%s" % ticker.lower(),)))
    con.close()
    return rows


def test_observation_new_window_same_digest_adds_one_row(env, monkeypatch):
    """first_seen stays empty for an unratified issuer, so etf_collect_log
    is the only promotion evidence.  An unchanged file in a NEW window is
    still an observation and must be recorded."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digSame"))
    assert C.main("BTC", "OBSV") == 0
    assert len(_log_rows(tmp, "OBSV")) == 1

    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-18")
    assert C.main("BTC", "OBSV") == 0

    rows = _log_rows(tmp, "OBSV")
    assert len(rows) == 2, "new window left no observation evidence"
    second = [r for r in rows if r[0] == "2026-07-18"]
    assert len(second) == 1
    win, latest, added, revised, completed = second[0]
    assert latest == "2026-07-16", "observed as_of must be carried through"
    assert (added, revised, completed) == (0, 0, 0)

    # canonical untouched, and still no completion artefacts
    daily, _ = _counts(tmp, "OBSV")
    assert daily == 2
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0


def test_observation_repeat_in_same_new_window_adds_nothing(env, monkeypatch):
    """One row per window, however many slots poll it."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digSame"))
    C.main("BTC", "OBSV")
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-18")
    C.main("BTC", "OBSV")
    assert len(_log_rows(tmp, "OBSV")) == 2

    for _ in range(3):
        assert C.main("BTC", "OBSV") == 0
    assert len(_log_rows(tmp, "OBSV")) == 2, "repeat polling duplicated evidence"


def test_observation_holiday_window_same_digest_is_recorded(env, monkeypatch):
    """A U.S. holiday leaves as_of and digest identical to the previous
    window; the current window still needs its own observation row."""
    tmp, ledger = env
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    con.execute("INSERT INTO etf_collect_log (source_id, input_digest, "
                "processed_at, rows_added, revisions_added, window_date_kst, "
                "latest_as_of, completed) VALUES (?,?,?,?,?,?,?,?)",
                ("etf_issuer_obsv", "digHol", "2026-07-03T01:00:00Z", 2, 0,
                 "2026-07-03", "2026-07-02", 0))
    con.commit()
    con.close()

    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-06")
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-02", "digHol"))
    assert C.main("BTC", "OBSV") == 0

    rows = _log_rows(tmp, "OBSV")
    assert [r[0] for r in rows] == ["2026-07-03", "2026-07-06"]
    assert rows[1] == ("2026-07-06", "2026-07-02", 0, 0, 0)
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0


def test_ratified_issuer_gets_no_observation_rows(env, monkeypatch):
    """The observation ledger is an observation-only affordance; a
    ratified issuer keeps the plain B-5 no-op."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digR"))
    C.main("BTC", "GBTC")
    assert len(_log_rows(tmp, "GBTC")) == 1
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-18")
    C.main("BTC", "GBTC")
    assert len(_log_rows(tmp, "GBTC")) == 1


# ------------------------------------------- observation -> ratified promotion
def _ratify(tmp, ticker, lag):
    """Flip an issuer from observation-only to ratified, as D5 would."""
    reg = json.loads((tmp / "registry.json").read_text())
    reg["assets"]["BTC"]["issuers"][ticker]["target_lag_us_business_days"] = lag
    (tmp / "registry.json").write_text(json.dumps(reg))


def _accumulate(monkeypatch, windows, digest, latest, ticker="OBSV"):
    monkeypatch.setattr(E, "poll_and_collect", _poll(latest, digest))
    for w in windows:
        monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None, _w=w: _w)
        assert C.main("BTC", ticker) == 0


def test_promotion_from_observation_completes_once(env, monkeypatch):
    """The rows an issuer accumulated while unratified survive promotion,
    so the duplicate branch must aggregate them rather than sample one."""
    tmp, ledger = env
    _accumulate(monkeypatch, ["2026-07-17", "2026-07-20", "2026-07-21"],
                "digProm", "2026-07-21")
    rows = _log_rows(tmp, "OBSV")
    assert len(rows) == 3 and all(r[4] == 0 for r in rows)
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0

    _ratify(tmp, "OBSV", 0)
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-22")
    assert C.main("BTC", "OBSV") == 0            # target 07-21, latest 07-21

    marker = json.loads(open(str(ledger / "etf_obsv_done.json")).read())
    assert marker["window_date_kst"] == "2026-07-22"
    assert marker["expected_issuer_as_of"] == "2026-07-21"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1, \
        "first ratified completion must log first_seen exactly once"

    rows = _log_rows(tmp, "OBSV")
    current = [r for r in rows if r[0] == "2026-07-22"]
    assert len(current) == 1 and current[0][4] == 1, \
        "current window must be settled as completed"
    assert all(r[4] == 0 for r in rows if r[0] != "2026-07-22"), \
        "historical observation rows must stay completed=0"


def test_promotion_marker_loss_does_not_duplicate_first_seen(env, monkeypatch):
    tmp, ledger = env
    _accumulate(monkeypatch, ["2026-07-17", "2026-07-20", "2026-07-21"],
                "digProm", "2026-07-21")
    _ratify(tmp, "OBSV", 0)
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-22")
    C.main("BTC", "OBSV")
    before_rows = len(_log_rows(tmp, "OBSV"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1

    os.remove(str(ledger / "etf_obsv_done.json"))
    assert C.main("BTC", "OBSV") == 0

    assert os.path.exists(str(ledger / "etf_obsv_done.json")), "marker not recovered"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1, \
        "marker recovery must not append a second first_seen line"
    rows = _log_rows(tmp, "OBSV")
    assert len(rows) == before_rows, "recovery duplicated a collect_log row"
    assert len([r for r in rows if r[0] == "2026-07-22" and r[4] == 1]) == 1


def test_ratified_holiday_with_prior_completion_logs_no_first_seen(env, monkeypatch):
    """Already-ratified issuer, previous window completed, same digest in a
    new window: marker only, no first_seen."""
    tmp, ledger = env
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-16", "digHol2"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    C.main("BTC", "GBTC")
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 1

    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-18")
    # target for 07-18 is 07-17; the file only reaches 07-16, so no marker
    assert C.main("BTC", "GBTC") == 0
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 1

    # a Monday window whose target is still 07-16 (07-17 Fri, 07-18/19 weekend)
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    os.remove(str(ledger / "etf_gbtc_done.json"))
    assert C.main("BTC", "GBTC") == 0
    assert os.path.exists(str(ledger / "etf_gbtc_done.json"))
    assert _fs_lines(str(ledger / "gbtc_first_seen.log")) == 1, \
        "prior completion means no new first_seen"


def test_duplicate_branch_is_row_order_independent(env, monkeypatch):
    """Same history, different physical insert order -> same outcome."""
    tmp, ledger = env
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    hist = [("2026-07-21", "2026-07-21T05:00:00Z"),
            ("2026-07-17", "2026-07-17T01:00:00Z"),
            ("2026-07-20", "2026-07-20T03:00:00Z")]      # deliberately shuffled
    for win, ts in hist:
        con.execute("INSERT INTO etf_collect_log (source_id, input_digest, "
                    "processed_at, rows_added, revisions_added, window_date_kst, "
                    "latest_as_of, completed) VALUES (?,?,?,0,0,?,?,0)",
                    ("etf_issuer_obsv", "digOrder", ts, win, "2026-07-21"))
    con.commit()
    con.close()

    _ratify(tmp, "OBSV", 0)
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-21", "digOrder"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-22")
    assert C.main("BTC", "OBSV") == 0

    marker = json.loads(open(str(ledger / "etf_obsv_done.json")).read())
    assert marker["as_of"] == "2026-07-21", "MAX(latest_as_of) not used"
    assert marker["expected_issuer_as_of"] == "2026-07-21"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1
    rows = _log_rows(tmp, "OBSV")
    assert len([r for r in rows if r[0] == "2026-07-22" and r[4] == 1]) == 1


def test_dup_latest_takes_the_newest_row_not_an_arbitrary_one(env, monkeypatch):
    """MAX(latest_as_of), not a sampled row.

    A stale row carrying the same digest but an older latest_as_of would,
    if picked, put the issuer below target and silently suppress the
    completion.  The aggregate has to read the newest.
    """
    tmp, ledger = env
    con = sqlite3.connect(str(tmp / "core.sqlite"))
    for win, ts, latest in [("2026-07-16", "2026-07-16T01:00:00Z", "2026-07-15"),
                            ("2026-07-21", "2026-07-21T01:00:00Z", "2026-07-21")]:
        con.execute("INSERT INTO etf_collect_log (source_id, input_digest, "
                    "processed_at, rows_added, revisions_added, window_date_kst, "
                    "latest_as_of, completed) VALUES (?,?,?,0,0,?,?,0)",
                    ("etf_issuer_obsv", "digStale", ts, win, latest))
    con.commit()
    con.close()

    _ratify(tmp, "OBSV", 0)
    monkeypatch.setattr(E, "poll_and_collect", _poll("2026-07-21", "digStale"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-22")
    assert C.main("BTC", "OBSV") == 0          # target 07-21

    assert os.path.exists(str(ledger / "etf_obsv_done.json")), \
        "a stale duplicate row suppressed the completion"
    marker = json.loads(open(str(ledger / "etf_obsv_done.json")).read())
    assert marker["as_of"] == "2026-07-21"


def test_ledger_commits_before_the_marker(env, monkeypatch):
    """B-15 durability: the marker is the gate that stops the next slot, so
    it must never exist without a settled ledger row.  A crash between the
    two has to leave a recoverable state, not a marker that claims a
    completion the database has no record of.
    """
    tmp, ledger = env
    _accumulate(monkeypatch, ["2026-07-17", "2026-07-20", "2026-07-21"],
                "digDur", "2026-07-21")
    _ratify(tmp, "OBSV", 0)
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-22")
    daily_before, _ = _counts(tmp, "OBSV")

    real_write = C._write_done

    def crash(*a, **k):
        raise OSError("simulated crash before the marker")
    monkeypatch.setattr(C, "_write_done", crash)
    with pytest.raises(OSError):
        C.main("BTC", "OBSV")

    rows = _log_rows(tmp, "OBSV")
    current = [r for r in rows if r[0] == "2026-07-22"]
    assert len(current) == 1 and current[0][4] == 1, \
        "ledger was not durable before the marker"
    assert not os.path.exists(str(ledger / "etf_obsv_done.json"))
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 0

    # recovery run: marker restored, first_seen made good exactly once.
    # Only _write_done is restored - undo() would also revert the fixture's
    # LEDGER/DB/REGISTRY patches.
    monkeypatch.setattr(C, "_write_done", real_write)
    assert C.main("BTC", "OBSV") == 0

    assert os.path.exists(str(ledger / "etf_obsv_done.json")), "marker not recovered"
    assert _fs_lines(str(ledger / "obsv_first_seen.log")) == 1
    rows = _log_rows(tmp, "OBSV")
    assert len([r for r in rows if r[0] == "2026-07-22"]) == 1, \
        "recovery duplicated the settled row"
    assert len([r for r in rows if r[0] == "2026-07-22" and r[4] == 1]) == 1
    daily_after, _ = _counts(tmp, "OBSV")
    assert daily_after == daily_before, "canonical rows changed during recovery"
