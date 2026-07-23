"""
D5b fail-closed lag contract.

After D5b the driver's lag resolver has no legacy fallback: an issuer with
no target_lag_us_business_days key is a hard error, for every ticker
including IBIT.  Observation-only is expressed *only* as an explicit null.
The refusal happens before any network fetch, so a mis-shaped registry
can never spend a collection call.

  missing key            -> ValueError            (any ticker, IBIT too)
  explicit null          -> None                  (observation-only)
  explicit int >= 0      -> that int              (completion target)
  any other value        -> ValueError            (value validation intact)

Run from the repo root:  python3 -m pytest -q
"""

import json
import os

import pytest

from collectors import etf_issuer as E
import scripts.collect_etf_ibit as C


# --------------------------------------------------------------- resolver

def test_missing_key_raises_for_ibit():
    """IBIT loses its special case: no key is now an error, not a silent 0."""
    with pytest.raises(ValueError):
        C._target_lag_for("IBIT", {})
    with pytest.raises(ValueError):
        C._target_lag_for("ibit", {})


def test_missing_key_raises_for_non_ibit():
    for ticker in ("GBTC", "FBTC", "ARKB"):
        with pytest.raises(ValueError):
            C._target_lag_for(ticker, {})


def test_missing_key_message_names_explicit_null():
    """The error has to teach the fix: observation-only is an explicit
    null, not an absent key."""
    with pytest.raises(ValueError) as e:
        C._target_lag_for("GBTC", {})
    assert "explicit null" in str(e.value)


def test_explicit_null_is_observation_only():
    assert C._target_lag_for("GBTC", {"target_lag_us_business_days": None}) is None
    assert C._target_lag_for("IBIT", {"target_lag_us_business_days": None}) is None


def test_explicit_zero_is_completion():
    assert C._target_lag_for("IBIT", {"target_lag_us_business_days": 0}) == 0
    assert C._target_lag_for("GBTC", {"target_lag_us_business_days": 0}) == 0


def test_explicit_positive_lag_is_returned():
    assert C._target_lag_for("X", {"target_lag_us_business_days": 3}) == 3


@pytest.mark.parametrize("bad", ["0", 0.0, True, False, -1, "one", [], 1.5])
def test_invalid_values_still_rejected(bad):
    with pytest.raises(ValueError) as e:
        C._target_lag_for("X", {"target_lag_us_business_days": bad})
    assert "invalid target_lag_us_business_days" in str(e.value)


# ------------------------------------------------- refusal precedes fetch

@pytest.fixture
def strict_env(tmp_path, monkeypatch):
    """A registry whose only issuer is missing the lag key, plus an
    isolated ledger.  No DB is needed: the refusal fires before the
    driver reaches collection or persistence."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({
        "assets": {"BTC": {"enabled": True, "issuers": {
            "NOKEY": {"enabled": True, "kill_switch_active": False,
                      "download_url": "http://example.invalid/x",
                      "parser": "ishares_spreadsheetml"},
        }}},
        "freshness": {"max_lag_business_days": 5},
    }))
    monkeypatch.setattr(C, "LEDGER", str(ledger))
    monkeypatch.setattr(C, "REGISTRY", str(reg))
    monkeypatch.setattr(C, "DONE_MARKER", str(ledger / "done.json"))
    monkeypatch.setattr(C, "LOCKFILE", str(ledger / ".lock"))
    monkeypatch.setattr(C, "FIRST_SEEN_LOG", str(ledger / "fs.log"))
    monkeypatch.setattr(C, "_kst_window_date", lambda now_utc=None: "2026-07-17")
    return tmp_path


def test_missing_key_refuses_before_any_fetch(strict_env, monkeypatch):
    called = []
    monkeypatch.setattr(E, "poll_and_collect",
                        lambda *a, **k: called.append(1))
    with pytest.raises(ValueError):
        C.main("BTC", "NOKEY")
    assert called == [], "a fetch ran despite a missing lag key"
