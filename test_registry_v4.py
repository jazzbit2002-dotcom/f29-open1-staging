"""registry v4 validator contract tests (D5a-1).

The validator is imported from the operational tree, not from a delivered
copy, so a merge failure surfaces as an ImportError rather than as a quiet
pass.  Every case runs against synthetic registries in tmp_path with a
synthetic ledger; the operational registry, ledger, lockfile, DB and the
network are never touched.

Run from the repo root:  python3 -m pytest -q
"""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.collect_etf_ibit as C            # noqa: E402
import scripts.validate_registry as V           # noqa: E402
from collectors.etf_issuer import PARSERS       # noqa: E402

VALIDATOR = os.path.join(ROOT, "scripts", "validate_registry.py")
WINDOW = "2026-07-22"
REAL_PARSER = "ishares_spreadsheetml"


# ---------------------------------------------------------------- helpers

def _issuer(enabled=False, lag=None, lag_key=True, url=None, parser=None):
    meta = {"issuer": "X", "enabled": enabled, "kill_switch_active": False,
            "download_url": url, "parser": parser, "verified_p0": False,
            "rights_status": "pending", "owner_override": "accepted"}
    if lag_key:
        meta["target_lag_us_business_days"] = lag
    return meta


def good_registry():
    """A candidate that must pass both static and transition checks."""
    return {
        "schema_version": "etf-issuer-registry-v4",
        "assets": {"BTC": {"enabled": True, "core_basket": ["IBIT", "GBTC"],
                           "issuers": {
                               "IBIT": _issuer(True, 0, url="https://x/y",
                                               parser=REAL_PARSER),
                               "GBTC": _issuer(False, None)}}},
        "freshness": {"max_lag_business_days": 5},
        "mapping_promotion": {"required_valid_samples": 10,
                              "sample_key": "latest_as_of",
                              "sample_window": "first_observed_window",
                              "duplicate_digest_policy":
                                  "collapse_and_flag_revision",
                              "holiday_crossing_min": 1},
    }


def current_v3_like():
    """Pre-migration state: IBIT relies on the legacy fallback."""
    reg = good_registry()
    reg["schema_version"] = "etf-issuer-registry-v3"
    del reg["assets"]["BTC"]["issuers"]["IBIT"]["target_lag_us_business_days"]
    del reg["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"]
    return reg


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


@pytest.fixture
def env(tmp_path):
    """Synthetic ledger + registry pair, isolated from the server tree."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()

    class Env(object):
        pass

    e = Env()
    e.tmp = tmp_path
    e.ledger = str(ledger)
    e.marker_name = os.path.basename(C.DONE_MARKER)
    e.lock_name = os.path.basename(C.LOCKFILE)

    def run(candidate, current=None, extra=()):
        cand = _write(tmp_path, "candidate.json", candidate)
        argv = ["--candidate", cand, "--ledger", e.ledger,
                "--now-window", WINDOW]
        if current is not None:
            argv += ["--current", _write(tmp_path, "current.json", current)]
        argv += list(extra)
        return V.main(argv)

    def marker(expected, window=WINDOW, name=None):
        (ledger / (name or e.marker_name)).write_text(
            json.dumps({"window_date_kst": window,
                        "expected_issuer_as_of": expected,
                        "as_of": expected, "digest": "d" * 8,
                        "done_at": "2026-07-22T01:00:01Z"}), encoding="utf-8")

    e.run = run
    e.marker = marker
    return e


def _rules(capsys):
    out = capsys.readouterr().out
    return [line.split()[1] for line in out.splitlines()
            if line.startswith(("ERROR", "WARN"))], out


# ------------------------------------------------------- positive control

def test_positive_control_static_and_transition_pass(env, capsys):
    assert env.run(good_registry(), current_v3_like()) == 0
    rules, out = _rules(capsys)
    assert [r for r in rules if r.startswith("S") or r.startswith("T")] == []
    assert "errors=0" in out


def test_positive_control_static_only(env, capsys):
    assert env.run(good_registry(), extra=["--static-only"]) == 0
    assert "errors=0" in capsys.readouterr().out


# ---------------------------------------------------------- static checks

def test_schema_version_wrong(env, capsys):
    reg = good_registry()
    reg["schema_version"] = "etf-issuer-registry-v3"
    assert env.run(reg, current_v3_like()) == 1
    assert "S1" in _rules(capsys)[0]


def test_lag_key_missing(env, capsys):
    reg = good_registry()
    del reg["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"]
    assert env.run(reg, current_v3_like()) == 1
    assert "S2" in _rules(capsys)[0]


@pytest.mark.parametrize("bad", ["0", 0.0, True, -1])
def test_lag_value_rejected(env, capsys, bad):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = bad
    assert env.run(reg, current_v3_like()) == 1
    assert "S3" in _rules(capsys)[0]


def test_enabled_issuer_url_null(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["download_url"] = None
    assert env.run(reg, current_v3_like()) == 1
    assert "S5" in _rules(capsys)[0]


def test_enabled_issuer_url_empty(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["download_url"] = ""
    assert env.run(reg, current_v3_like()) == 1
    assert "S5" in _rules(capsys)[0]


def test_enabled_issuer_parser_null(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["parser"] = None
    assert env.run(reg, current_v3_like()) == 1
    assert "S5" in _rules(capsys)[0]


def test_parser_not_registered(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["parser"] = "no_such_parser"
    assert env.run(reg, current_v3_like()) == 1
    assert "S6" in _rules(capsys)[0]


def test_parser_names_come_from_live_registry():
    assert REAL_PARSER in PARSERS and len(PARSERS) >= 1


@pytest.mark.parametrize("bad", [["a"], ""])
def test_parser_type_rejected(env, capsys, bad):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["parser"] = bad
    assert env.run(reg, current_v3_like()) == 1
    assert "S5" in _rules(capsys)[0]


@pytest.mark.parametrize("bad", ["GB TC", "GBTC\n", ""])
def test_ticker_charset(env, capsys, bad):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"][bad] = _issuer(False, None)
    assert env.run(reg, current_v3_like()) == 1
    assert "S4" in _rules(capsys)[0]


def test_asset_enabled_must_be_bool(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["enabled"] = "true"
    assert env.run(reg, current_v3_like()) == 1
    assert "S12" in _rules(capsys)[0]


def test_issuer_enabled_must_be_bool(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["GBTC"]["enabled"] = 1
    assert env.run(reg, current_v3_like()) == 1
    assert "S12" in _rules(capsys)[0]


def test_kill_switch_must_be_bool(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["GBTC"]["kill_switch_active"] = "false"
    assert env.run(reg, current_v3_like()) == 1
    assert "S12" in _rules(capsys)[0]


@pytest.mark.parametrize("bad", [True, "5", -1])
def test_freshness_rejected(env, capsys, bad):
    reg = good_registry()
    reg["freshness"]["max_lag_business_days"] = bad
    assert env.run(reg, current_v3_like()) == 1
    assert "S8" in _rules(capsys)[0]


def test_freshness_missing(env, capsys):
    reg = good_registry()
    del reg["freshness"]
    assert env.run(reg, current_v3_like()) == 1
    assert "S8" in _rules(capsys)[0]


@pytest.mark.parametrize("key,bad", [("required_valid_samples", True),
                                     ("holiday_crossing_min", False),
                                     ("required_valid_samples", 0),
                                     ("sample_key", "digest"),
                                     ("sample_window", "latest"),
                                     ("duplicate_digest_policy", "keep_all")])
def test_mapping_promotion_rejected(env, capsys, key, bad):
    reg = good_registry()
    reg["mapping_promotion"][key] = bad
    assert env.run(reg, current_v3_like()) == 1
    assert "S7" in _rules(capsys)[0]


def test_mapping_promotion_key_missing(env, capsys):
    reg = good_registry()
    del reg["mapping_promotion"]["sample_window"]
    assert env.run(reg, current_v3_like()) == 1
    assert "S7" in _rules(capsys)[0]


def test_mapping_promotion_absent(env, capsys):
    reg = good_registry()
    del reg["mapping_promotion"]
    assert env.run(reg, current_v3_like()) == 1
    assert "S7" in _rules(capsys)[0]


def test_unknown_fields_allowed(env, capsys):
    reg = good_registry()
    reg["future_block"] = {"anything": 1}
    reg["assets"]["BTC"]["issuers"]["GBTC"]["note_for_later"] = "x"
    assert env.run(reg, current_v3_like()) == 0
    assert "errors=0" in capsys.readouterr().out


def test_issuer_removed_from_candidate(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["FBTC"] = _issuer(False, None,
                                                      lag_key=False)
    assert env.run(good_registry(), cur) == 1
    assert "S11" in _rules(capsys)[0]


def test_enabled_with_null_lag_is_warning_only(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["target_lag_us_business_days"] = None
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["IBIT"]["enabled"] = True
    assert env.run(reg, cur) == 1        # lag 0 -> None is a REAL_CHANGE
    rules = _rules(capsys)[0]
    assert "S9" in rules and "T1" in rules


def test_enabled_null_lag_warning_without_transition(env, capsys):
    reg = good_registry()
    reg["assets"]["BTC"]["issuers"]["IBIT"]["target_lag_us_business_days"] = None
    assert env.run(reg, extra=["--static-only"]) == 0
    rules, out = _rules(capsys)
    assert "S9" in rules and "errors=0" in out


# -------------------------------------------- malformed structure (no crash)

@pytest.mark.parametrize("mangle", [
    lambda r: r.__setitem__("assets", []),
    lambda r: r["assets"].__setitem__("BTC", []),
    lambda r: r["assets"]["BTC"].__setitem__("issuers", []),
    lambda r: r["assets"]["BTC"].pop("issuers"),
    lambda r: r["assets"]["BTC"]["issuers"].__setitem__("GBTC", "bad"),
])
def test_candidate_structure_diagnosed_not_raised(env, capsys, mangle):
    reg = good_registry()
    mangle(reg)
    assert env.run(reg, current_v3_like()) == 1
    rules, out = _rules(capsys)
    assert any(r in ("S13", "S11") for r in rules), out


@pytest.mark.parametrize("mangle", [
    lambda r: r.__setitem__("assets", []),
    lambda r: r["assets"].__setitem__("BTC", []),
    lambda r: r["assets"]["BTC"].__setitem__("issuers", []),
    lambda r: r["assets"]["BTC"].pop("issuers"),
    lambda r: r["assets"]["BTC"]["issuers"].__setitem__("GBTC", "bad"),
])
def test_current_structure_diagnosed_not_raised(env, capsys, mangle):
    cur = current_v3_like()
    mangle(cur)
    assert env.run(good_registry(), cur) == 1
    rules, out = _rules(capsys)
    assert "C1" in rules, out


# ------------------------------------------- current input is fail-closed

def test_current_enabled_truthy_string_is_refused(env, capsys):
    """`enabled: "false"` is truthy to the driver - it must not be read here
    as a satisfied "disabled before the change" proof."""
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["enabled"] = "false"
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 1
    assert env.run(cand, cur) == 1
    assert "C2" in _rules(capsys)[0]


def test_current_lag_malformed_is_refused(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = "BAD"
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 1
    assert env.run(cand, cur) == 1
    assert "C3" in _rules(capsys)[0]


def test_current_asset_enabled_must_be_bool(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["enabled"] = 1
    assert env.run(good_registry(), cur) == 1
    assert "C2" in _rules(capsys)[0]


def test_current_kill_switch_must_be_bool(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["kill_switch_active"] = "false"
    assert env.run(good_registry(), cur) == 1
    assert "C2" in _rules(capsys)[0]


def test_current_ticker_charset_is_refused(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GB TC"] = _issuer(False, None,
                                                       lag_key=False)
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GB TC"] = _issuer(False, None)
    assert env.run(cand, cur) == 1
    rules = _rules(capsys)[0]
    assert "C1" in rules and "S4" in rules


def test_unusable_current_entry_blocks_its_transition(env, capsys):
    """A refused current entry must not fall through as an approved change."""
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["enabled"] = "false"
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 1
    assert env.run(cand, cur) == 1
    rules, out = _rules(capsys)
    assert "C2" in rules and "errors=0" not in out


# ------------------------------------------------------ transition checks

def test_lag_change_while_enabled(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["enabled"] = True
    cur["assets"]["BTC"]["issuers"]["GBTC"]["download_url"] = "https://x/y"
    cur["assets"]["BTC"]["issuers"]["GBTC"]["parser"] = REAL_PARSER
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"] = _issuer(
        True, 2, url="https://x/y", parser=REAL_PARSER)
    assert env.run(cand, cur) == 1
    assert "T1" in _rules(capsys)[0]


def test_lag_change_disabled_without_marker_passes(env, capsys):
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 2
    assert env.run(cand, current_v3_like()) == 0
    assert "errors=0" in capsys.readouterr().out


def test_lag_change_disabled_with_current_marker(env, capsys):
    env.marker(C._expected_as_of(WINDOW, 0), name="etf_gbtc_done.json")
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 2
    assert env.run(cand, current_v3_like()) == 1
    assert "T1" in _rules(capsys)[0]


def test_marker_for_other_window_is_not_current(env, capsys):
    env.marker(C._expected_as_of(WINDOW, 0), window="2026-07-21",
               name="etf_gbtc_done.json")
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = 2
    assert env.run(cand, current_v3_like()) == 0
    assert "errors=0" in capsys.readouterr().out


def test_enable_transition_warns(env, capsys):
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"] = _issuer(
        True, None, url="https://x/y", parser="grayscale_ooxml")
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["target_lag_us_business_days"] = None
    assert env.run(cand, cur) == 0
    rules, out = _rules(capsys)
    assert "T3" in rules and "S9" in rules and "errors=0" in out


def test_transition_runs_unless_static_only(env, capsys):
    cur = current_v3_like()
    cur["assets"]["BTC"]["issuers"]["GBTC"]["enabled"] = True
    cur["assets"]["BTC"]["issuers"]["GBTC"]["download_url"] = "https://x/y"
    cur["assets"]["BTC"]["issuers"]["GBTC"]["parser"] = REAL_PARSER
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["GBTC"] = _issuer(
        True, 2, url="https://x/y", parser=REAL_PARSER)
    assert env.run(cand, cur) == 1                       # default: checked
    capsys.readouterr()
    assert env.run(cand, cur, extra=["--static-only"]) == 0


def test_current_defaults_to_operational_registry():
    args = V.build_parser().parse_args(["--candidate", "x.json"])
    assert args.current == C.REGISTRY


# ---------------------------------------------- materialization exception

def test_ibit_materialization_marker_matches(env, capsys):
    env.marker(C._expected_as_of(WINDOW, 0))
    assert env.run(good_registry(), current_v3_like()) == 0
    assert "errors=0" in capsys.readouterr().out


def test_ibit_materialization_marker_mismatch(env, capsys):
    env.marker("1999-01-04")
    assert env.run(good_registry(), current_v3_like()) == 1
    assert "T1" in _rules(capsys)[0]


def test_ibit_materialization_without_marker(env, capsys):
    assert env.run(good_registry(), current_v3_like()) == 0
    assert "errors=0" in capsys.readouterr().out


def test_ibit_real_lag_change_is_refused(env, capsys):
    """Exemption must not be granted for being IBIT."""
    cand = good_registry()
    cand["assets"]["BTC"]["issuers"]["IBIT"]["target_lag_us_business_days"] = 1
    assert env.run(cand, current_v3_like()) == 1
    assert "T1" in _rules(capsys)[0]


def test_non_ibit_materialization_of_null(env, capsys):
    cur = current_v3_like()
    cand = good_registry()
    assert "target_lag_us_business_days" not in \
        cur["assets"]["BTC"]["issuers"]["GBTC"]
    assert cand["assets"]["BTC"]["issuers"]["GBTC"][
        "target_lag_us_business_days"] is None
    assert env.run(cand, cur) == 0
    assert "errors=0" in capsys.readouterr().out


# ------------------------------------------------------ ledger isolation

def test_ledger_isolation_marker_is_read_from_given_dir(env, capsys):
    """Result must depend on the synthetic ledger, not the operational one."""
    env.marker("1999-01-04")
    assert env.run(good_registry(), current_v3_like()) == 1
    capsys.readouterr()
    os.remove(os.path.join(env.ledger, env.marker_name))
    assert env.run(good_registry(), current_v3_like()) == 0


def test_bound_ledger_rebinds_all_four_globals(tmp_path):
    saved = [getattr(C, n) for n in V._LEDGER_GLOBALS]
    target = str(tmp_path)
    with V._bound_driver_ledger(target):
        assert C.LEDGER == target
        for name in ("DONE_MARKER", "LOCKFILE", "FIRST_SEEN_LOG"):
            value = getattr(C, name)
            assert os.path.dirname(value) == target
            assert os.path.basename(value) == os.path.basename(
                saved[V._LEDGER_GLOBALS.index(name)])
        assert os.path.dirname(C._paths_for("IBIT")[0]) == target
        assert os.path.dirname(C._paths_for("GBTC")[0]) == target
    assert [getattr(C, n) for n in V._LEDGER_GLOBALS] == saved


def test_bound_ledger_restores_after_exception(tmp_path):
    saved = [getattr(C, n) for n in V._LEDGER_GLOBALS]
    with pytest.raises(RuntimeError):
        with V._bound_driver_ledger(str(tmp_path)):
            raise RuntimeError("boom")
    assert [getattr(C, n) for n in V._LEDGER_GLOBALS] == saved


def test_bound_ledger_noop_when_none(tmp_path):
    saved = [getattr(C, n) for n in V._LEDGER_GLOBALS]
    with V._bound_driver_ledger(None):
        assert [getattr(C, n) for n in V._LEDGER_GLOBALS] == saved
    assert [getattr(C, n) for n in V._LEDGER_GLOBALS] == saved


def test_globals_restored_after_full_run(env):
    saved = [getattr(C, n) for n in V._LEDGER_GLOBALS]
    env.marker(C._expected_as_of(WINDOW, 0))
    env.run(good_registry(), current_v3_like())
    assert [getattr(C, n) for n in V._LEDGER_GLOBALS] == saved


# ----------------------------------------------------- writes nothing at all

def test_validator_creates_no_files(env):
    env.marker(C._expected_as_of(WINDOW, 0))
    before = sorted(os.listdir(env.ledger))
    env.run(good_registry(), current_v3_like())
    assert sorted(os.listdir(env.ledger)) == before


def test_validator_never_creates_lockfile(env):
    env.run(good_registry(), current_v3_like())
    assert not os.path.exists(os.path.join(env.ledger, env.lock_name))
    assert not os.path.exists(os.path.join(env.ledger, ".etf_gbtc.lock"))


def test_no_project_bytecode_written(env, tmp_path):
    """Discriminating even though the repo may already hold __pycache__.

    The subprocess runs without PYTHONDONTWRITEBYTECODE and with a fresh
    pycache_prefix, so any bytecode the interpreter writes for a project
    module lands under that prefix where it can be counted.
    """
    prefix = tmp_path / "pyc"
    cand = _write(tmp_path, "cand.json", good_registry())
    cur = _write(tmp_path, "cur.json", current_v3_like())
    environ = dict(os.environ)
    environ.pop("PYTHONDONTWRITEBYTECODE", None)
    before = _pycache_dirs()
    proc = subprocess.run(
        [sys.executable, "-X", "pycache_prefix=" + str(prefix), VALIDATOR,
         "--candidate", cand, "--current", cur, "--ledger", env.ledger,
         "--now-window", WINDOW],
        capture_output=True, text=True, env=environ)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    mirrored = prefix / ROOT.lstrip(os.sep)
    leaked = []
    for dirpath, _dirs, files in os.walk(str(mirrored)):
        leaked += [os.path.join(dirpath, f) for f in files
                   if f.endswith(".pyc")]
    assert leaked == [], leaked
    assert _pycache_dirs() == before


def _pycache_dirs():
    found = []
    for sub in ("scripts", "collectors", "tests"):
        cache = os.path.join(ROOT, sub, "__pycache__")
        found.append((cache, sorted(os.listdir(cache))
                      if os.path.isdir(cache) else None))
    return found


# ------------------------------------------------------------ exit codes

def test_missing_candidate_is_exit_2(env, capsys):
    assert V.main(["--candidate", str(env.tmp / "nope.json"),
                   "--ledger", env.ledger, "--now-window", WINDOW]) == 2
    capsys.readouterr()


def test_malformed_candidate_is_exit_2(env, capsys):
    bad = env.tmp / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert V.main(["--candidate", str(bad), "--ledger", env.ledger,
                   "--now-window", WINDOW]) == 2
    capsys.readouterr()
