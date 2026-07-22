#!/usr/bin/env python3
"""validate_registry.py - registry v4 static and transition validator (D5a-1).

Read-only.  Creates and modifies nothing: no registry write, no DB
connection, no network, no bytecode cache.  The done marker is a file, so
the DB is never opened.

Contracts are NOT reimplemented here.  Ticker path derivation, the expected
as-of formula, marker recognition and lag interpretation are all taken from
the operational driver, so this tool cannot drift away from what actually
runs (D2 and D3 both failed by checking a replica instead of the real
thing).

Operational form:
    python3 -B scripts/validate_registry.py --candidate PATH

Diagnostic line format: "LEVEL RULE scope: detail".  The rule id sits at a
fixed token position so the report stays machine-readable even when a scope
has to be quoted.  Rule namespaces: S* candidate static, C* current
transition input, T* transition verdict.

Exit codes: 0 = PASS (WARN allowed), 1 = at least one ERROR, 2 = usage/IO.
"""
import sys

# Must precede every project import: the guard is what makes "writes
# nothing" true for the bytecode cache as well (-B covers the CLI, this
# covers in-process import by the test suite).
sys.dont_write_bytecode = True

import argparse    # noqa: E402
import contextlib  # noqa: E402
import json        # noqa: E402
import os          # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import scripts.collect_etf_ibit as C           # noqa: E402
from collectors.etf_issuer import PARSERS      # noqa: E402

SCHEMA_VERSION = "etf-issuer-registry-v4"
LAG_KEY = "target_lag_us_business_days"

# Rebound as one group: _paths_for() returns C.LEDGER-derived paths for
# every ticker EXCEPT the legacy one, which returns these globals verbatim.
# Rebinding LEDGER alone would leave IBIT reading the operational ledger.
_LEDGER_GLOBALS = ("LEDGER", "DONE_MARKER", "LOCKFILE", "FIRST_SEEN_LOG")

_MP_ENUMS = {
    "sample_key": ("latest_as_of",),
    "sample_window": ("first_observed_window",),
    "duplicate_digest_policy": ("collapse_and_flag_revision",),
}
_MP_INTS = {"required_valid_samples": 1, "holiday_crossing_min": 0}


class Diagnostics(object):
    def __init__(self):
        self.items = []

    def add(self, level, scope, rule, detail):
        self.items.append((level, scope, rule, detail))

    def error(self, scope, rule, detail):
        self.add("ERROR", scope, rule, detail)

    def warn(self, scope, rule, detail):
        self.add("WARN", scope, rule, detail)

    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    def emit(self, stream):
        for level, scope, rule, detail in self.items:
            stream.write("%s %s %s: %s\n"
                         % (level, rule, _safe_scope(scope), detail))


def _safe_scope(scope):
    """Ticker text is untrusted input: a ticker containing a newline would
    otherwise inject a fake diagnostic line into the report."""
    if scope and not any(ch.isspace() for ch in scope):
        return scope
    return json.dumps(scope)


def _is_bool(v):
    return isinstance(v, bool)


def _is_int_ge(v, low):
    # bool is a subclass of int - reject it explicitly (same rule the
    # driver applies to the lag value).
    return isinstance(v, int) and not isinstance(v, bool) and v >= low


def _is_nonempty_str(v):
    return isinstance(v, str) and v != ""


@contextlib.contextmanager
def _bound_driver_ledger(ledger_dir):
    """Temporarily point the driver's ledger globals at ledger_dir.

    Basenames are taken from the operational values, so the derived names
    stay identical to what the driver would use.  Restoration happens in
    finally, on the exception path as well.
    """
    if ledger_dir is None:
        yield
        return
    saved = dict((n, getattr(C, n)) for n in _LEDGER_GLOBALS)
    try:
        C.LEDGER = ledger_dir
        for name in ("DONE_MARKER", "LOCKFILE", "FIRST_SEEN_LOG"):
            setattr(C, name,
                    os.path.join(ledger_dir, os.path.basename(saved[name])))
        yield
    finally:
        for name, value in saved.items():
            setattr(C, name, value)


def _as_object(value):
    return value if isinstance(value, dict) else None


def _issuer_map(cfg):
    """issuers mapping of an asset config, or None when malformed/absent."""
    if not isinstance(cfg, dict):
        return None
    return _as_object(cfg.get("issuers"))


def _effective_lag(ticker, meta):
    """(lag, error_text) - delegates value validation to the driver."""
    try:
        return C._target_lag_for(ticker, meta), None
    except ValueError as exc:
        return None, str(exc)


def _current_marker(ticker, window, ledger_dir):
    """Marker dict when a CURRENT-window marker exists, else None.

    Only element [0] of _paths_for is used.  Element [1] is the lockfile,
    which the driver opens with mode "w" - this tool never touches it.
    """
    with _bound_driver_ledger(ledger_dir):
        done_marker = C._paths_for(ticker)[0]
        if not C._done_today(window, done_marker):
            return None
        try:
            with open(done_marker, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
    return data if isinstance(data, dict) else {}


def check_mapping_promotion(reg, diags):
    promo = reg.get("mapping_promotion")
    if not isinstance(promo, dict):
        diags.error("-", "S7", "mapping_promotion missing or not an object")
        return
    for key, allowed in _MP_ENUMS.items():
        if key not in promo:
            diags.error("-", "S7", "mapping_promotion.%s missing" % key)
        elif promo[key] not in allowed:
            diags.error("-", "S7",
                        "mapping_promotion.%s=%r not in %r"
                        % (key, promo[key], list(allowed)))
    for key, low in _MP_INTS.items():
        if key not in promo:
            diags.error("-", "S7", "mapping_promotion.%s missing" % key)
        elif not _is_int_ge(promo[key], low):
            diags.error("-", "S7",
                        "mapping_promotion.%s=%r must be int >= %d "
                        "(bool rejected)" % (key, promo[key], low))


def check_static(reg, diags):
    if reg.get("schema_version") != SCHEMA_VERSION:
        diags.error("-", "S1",
                    "schema_version=%r expected %r"
                    % (reg.get("schema_version"), SCHEMA_VERSION))

    fresh = reg.get("freshness", {})
    if not isinstance(fresh, dict) or "max_lag_business_days" not in fresh:
        diags.error("-", "S8", "freshness.max_lag_business_days missing")
    elif not _is_int_ge(fresh.get("max_lag_business_days"), 0):
        diags.error("-", "S8",
                    "freshness.max_lag_business_days=%r must be int >= 0 "
                    "(bool rejected)" % (fresh.get("max_lag_business_days"),))

    check_mapping_promotion(reg, diags)

    assets = reg.get("assets")
    if not isinstance(assets, dict):
        diags.error("-", "S13", "assets=%s is not an object" % type(assets).__name__)
        return
    for asset, cfg in sorted(assets.items()):
        if not isinstance(cfg, dict):
            diags.error(asset, "S13", "asset config is not an object")
            continue
        if not _is_bool(cfg.get("enabled")):
            diags.error(asset, "S12",
                        "assets.%s.enabled=%r must be bool"
                        % (asset, cfg.get("enabled")))
        issuers = _issuer_map(cfg)
        if issuers is None:
            diags.error(asset, "S13", "issuers missing or not an object")
            continue
        for ticker, meta in sorted(issuers.items()):
            _check_issuer(asset, ticker, meta, diags)


def _check_issuer(asset, ticker, meta, diags):
    scope = "%s/%s" % (asset, ticker)

    try:
        C._paths_for(ticker)
    except ValueError as exc:
        diags.error(scope, "S4", str(exc))

    if not isinstance(meta, dict):
        diags.error(scope, "S13", "issuer entry is not an object")
        return

    enabled = meta.get("enabled")
    if not _is_bool(enabled):
        diags.error(scope, "S12", "enabled=%r must be bool" % (enabled,))
    if not _is_bool(meta.get("kill_switch_active")):
        diags.error(scope, "S12",
                    "kill_switch_active=%r must be bool"
                    % (meta.get("kill_switch_active"),))

    url = meta.get("download_url")
    if url is not None and not _is_nonempty_str(url):
        diags.error(scope, "S5", "download_url must be null or non-empty str")
    parser = meta.get("parser")
    if parser is not None and not _is_nonempty_str(parser):
        diags.error(scope, "S5", "parser must be null or non-empty str")
    elif _is_nonempty_str(parser) and parser not in PARSERS:
        diags.error(scope, "S6",
                    "parser=%r not registered in PARSERS %r"
                    % (parser, sorted(PARSERS)))

    if enabled is True:
        if not _is_nonempty_str(url):
            diags.error(scope, "S5", "enabled issuer needs download_url")
        if not _is_nonempty_str(parser):
            diags.error(scope, "S5", "enabled issuer needs parser")

    if LAG_KEY not in meta:
        diags.error(scope, "S2", "%s key missing" % LAG_KEY)
        return
    lag, err = _effective_lag(ticker, meta)
    if err is not None:
        diags.error(scope, "S3", err)
    elif lag is None and enabled is True:
        diags.warn(scope, "S9",
                   "enabled with null lag - observation-only collection")


def check_current_inputs(current, diags):
    """Fail-closed validation of the fields a transition verdict rests on.

    current is not required to be a v4 file, but every field the T-rules
    read must be exactly what the driver would act on.  An unchecked
    current is a fail-open hole: `enabled: "false"` is truthy to the
    driver and would otherwise be read here as disabled, silently
    satisfying the "disabled before the change" proof D5-1 depends on.

    Returns the set of (asset, ticker) pairs safe to use as input; anything
    excluded has already produced an ERROR.
    """
    safe = set()
    assets = current.get("assets")
    if not isinstance(assets, dict):
        diags.error("current", "C1",
                    "assets=%s is not an object" % type(assets).__name__)
        return safe
    for asset, cfg in sorted(assets.items()):
        scope_a = "current/%s" % asset
        if not isinstance(cfg, dict):
            diags.error(scope_a, "C1", "asset config is not an object")
            continue
        if not _is_bool(cfg.get("enabled")):
            diags.error(scope_a, "C2",
                        "assets.%s.enabled=%r must be bool"
                        % (asset, cfg.get("enabled")))
        issuers = _issuer_map(cfg)
        if issuers is None:
            diags.error(scope_a, "C1", "issuers missing or not an object")
            continue
        for ticker, meta in sorted(issuers.items()):
            scope = "current/%s/%s" % (asset, ticker)
            if not isinstance(meta, dict):
                diags.error(scope, "C1", "issuer entry is not an object")
                continue
            usable = True
            if not _is_bool(meta.get("enabled")):
                diags.error(scope, "C2",
                            "enabled=%r must be bool" % (meta.get("enabled"),))
                usable = False
            if not _is_bool(meta.get("kill_switch_active")):
                diags.error(scope, "C2",
                            "kill_switch_active=%r must be bool"
                            % (meta.get("kill_switch_active"),))
                usable = False
            try:
                C._paths_for(ticker)
            except ValueError as exc:
                diags.error(scope, "C1", str(exc))
                usable = False
            _lag, err = _effective_lag(ticker, meta)
            if err is not None:
                diags.error(scope, "C3", err)
                usable = False
            if usable:
                safe.add((asset, ticker))
    return safe


def check_transition(current, candidate, window, ledger_dir, diags):
    safe = check_current_inputs(current, diags)
    cur_assets = _as_object(current.get("assets")) or {}
    cand_assets = _as_object(candidate.get("assets")) or {}

    for asset, cur_cfg in sorted(cur_assets.items()):
        cur_issuers = _issuer_map(cur_cfg)
        if cur_issuers is None:
            continue
        cand_issuers = _issuer_map(cand_assets.get(asset)) or {}
        for ticker in sorted(cur_issuers):
            if ticker not in cand_issuers:
                diags.error("%s/%s" % (asset, ticker), "S11",
                            "issuer present in current registry is missing "
                            "from candidate")

    for asset, cand_cfg in sorted(cand_assets.items()):
        cand_issuers = _issuer_map(cand_cfg)
        if cand_issuers is None:
            continue
        cur_issuers = _issuer_map(cur_assets.get(asset)) or {}
        for ticker, new_meta in sorted(cand_issuers.items()):
            if not isinstance(new_meta, dict):
                continue
            if (asset, ticker) not in safe:
                continue        # unusable current input - ERROR already filed
            old_meta = cur_issuers.get(ticker)
            if not isinstance(old_meta, dict):
                continue
            _check_one_transition(asset, ticker, old_meta, new_meta,
                                  window, ledger_dir, diags)


def _check_one_transition(asset, ticker, old_meta, new_meta,
                          window, ledger_dir, diags):
    scope = "%s/%s" % (asset, ticker)
    try:
        C._paths_for(ticker)
    except ValueError:
        return  # already reported by S4; path derivation impossible

    old_lag, old_err = _effective_lag(ticker, old_meta)
    new_lag, new_err = _effective_lag(ticker, new_meta)
    if old_err is not None or new_err is not None:
        return  # already reported: candidate by S3, current by C3

    old_enabled = old_meta.get("enabled") is True
    new_enabled = new_meta.get("enabled") is True

    if new_enabled and not old_enabled:
        diags.warn(scope, "T3",
                   "enabled false->true; rights fields are declarative only "
                   "and the runtime gate is unwired - separate preflight "
                   "required")

    key_moved = (LAG_KEY in old_meta) != (LAG_KEY in new_meta)

    if old_lag == new_lag and not key_moved:
        return                                            # NO_CHANGE

    if old_lag == new_lag and key_moved:                  # MATERIALIZATION
        if _materialization_ok(ticker, old_lag, new_lag, window, ledger_dir):
            return
        # falls through to the REAL_CHANGE rules deliberately

    _require_real_change_conditions(scope, ticker, old_lag, new_lag,
                                    old_enabled, new_enabled,
                                    window, ledger_dir, diags)


def _materialization_ok(ticker, old_lag, new_lag, window, ledger_dir):
    """No-op materialization of an already-effective lag.

    Deliberately blind to the ticker name: an issuer is not exempt for
    being IBIT, it is exempt for the value being provably unchanged.
    """
    if old_lag is None or new_lag != old_lag:
        return False
    marker = _current_marker(ticker, window, ledger_dir)
    if marker is None:
        return True     # no stale marker exists, so B-2 cannot be misled
    return marker.get("expected_issuer_as_of") == C._expected_as_of(window,
                                                                    new_lag)


def _require_real_change_conditions(scope, ticker, old_lag, new_lag,
                                    old_enabled, new_enabled,
                                    window, ledger_dir, diags):
    detail = "lag %r -> %r" % (old_lag, new_lag)
    if old_enabled:
        diags.error(scope, "T1",
                    "%s while enabled=true before the change" % detail)
    if new_enabled:
        diags.error(scope, "T1",
                    "%s with enabled=true after the change" % detail)
    if _current_marker(ticker, window, ledger_dir) is not None:
        diags.error(scope, "T1",
                    "%s with a current-window marker present (window=%s)"
                    % (detail, window))


def _load(path, diags_label):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise SystemExit2("%s: %s" % (diags_label, exc))
    except ValueError as exc:
        raise SystemExit2("%s: invalid JSON: %s" % (diags_label, exc))
    if not isinstance(data, dict):
        raise SystemExit2("%s: top level is not an object" % diags_label)
    return data


class SystemExit2(Exception):
    pass


def build_parser():
    ap = argparse.ArgumentParser(
        description="Validate an etf-issuer-registry-v4 candidate.")
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--current", default=C.REGISTRY)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--now-window", dest="now_window", default=None)
    ap.add_argument("--static-only", dest="static_only", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    diags = Diagnostics()
    try:
        candidate = _load(args.candidate, "candidate")
        current = None if args.static_only else _load(args.current, "current")
    except SystemExit2 as exc:
        sys.stderr.write("FATAL %s\n" % exc)
        return 2

    window = args.now_window or C._kst_window_date()
    check_static(candidate, diags)
    if not args.static_only:
        check_transition(current, candidate, window, args.ledger, diags)

    diags.emit(sys.stdout)
    failures = len(diags.errors())
    sys.stdout.write("window=%s errors=%d warnings=%d\n"
                     % (window, failures, len(diags.items) - failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
