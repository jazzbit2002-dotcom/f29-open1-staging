#!/usr/bin/env python3
"""make_registry_v4.py - build an etf-issuer-registry-v4 candidate (D5a-2).

Reads the operational registry, applies ONLY the declared deltas, and writes
the candidate to a path outside the repository.  The input file is never
modified: the atomic swap is a separate, later step.

Fail-closed by construction:
  * the input must hash to --expect-sha, or the run aborts
  * after building, every changed path is compared against an allowlist;
    anything else - including an accidental enabled flip - aborts with no
    output written
  * the four invariants the audit requires are checked explicitly and
    printed, so the transition evidence does not depend on reading a diff

Pure ASCII.  The registry's CJK notes are carried through untouched by
loading and dumping with ensure_ascii=False.

    python3 -B tools/make_registry_v4.py \
        --expect-sha <sha256 of the live registry> \
        --gbtc-url '<reconnaissance URL>' \
        --out /tmp/etf_issuer_registry_v4.json
"""
import sys

sys.dont_write_bytecode = True

import argparse   # noqa: E402
import hashlib    # noqa: E402
import json       # noqa: E402
import os         # noqa: E402

SCHEMA_V4 = "etf-issuer-registry-v4"
LAG_KEY = "target_lag_us_business_days"
ASSET = "BTC"
LAG_BY_TICKER = {"IBIT": 0}          # every other issuer is observation-only
DROP_FROM_BASKET = ("ARKB",)         # Sky judgment: basket exclusion only,
                                     # the issuer entry itself is preserved
MAPPING_PROMOTION = [
    ("required_valid_samples", 10),
    ("sample_key", "latest_as_of"),
    ("sample_window", "first_observed_window"),
    ("duplicate_digest_policy", "collapse_and_flag_revision"),
    ("holiday_crossing_min", 1),
]

ALLOWED_CHANGES = None      # built at runtime, needs the ticker list


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _walk(node, prefix=""):
    """Flatten to {path: leaf} so a structural diff needs no assumptions."""
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_walk(value, "%s.%s" % (prefix, key) if prefix else key))
    elif isinstance(node, list):
        out[prefix] = json.dumps(node, ensure_ascii=False, sort_keys=False)
    else:
        out[prefix] = node
    return out


def _diff(before, after):
    flat_a, flat_b = _walk(before), _walk(after)
    changed = []
    for path in sorted(set(flat_a) | set(flat_b)):
        old = flat_a.get(path, "<absent>")
        new = flat_b.get(path, "<absent>")
        if old != new:
            changed.append((path, old, new))
    return changed


def _allowed_paths(tickers):
    allowed = {"schema_version", "assets.%s.core_basket" % ASSET}
    for ticker in tickers:
        allowed.add("assets.%s.issuers.%s.%s" % (ASSET, ticker, LAG_KEY))
    allowed.add("assets.%s.issuers.GBTC.download_url" % ASSET)
    allowed.add("assets.%s.issuers.GBTC.parser" % ASSET)
    for key, _value in MAPPING_PROMOTION:
        allowed.add("mapping_promotion.%s" % key)
    return allowed


def build(reg, gbtc_url, gbtc_parser):
    out = json.loads(json.dumps(reg))          # deep copy, order preserved
    out["schema_version"] = SCHEMA_V4

    asset = out["assets"][ASSET]
    asset["core_basket"] = [t for t in asset["core_basket"]
                            if t not in DROP_FROM_BASKET]

    for ticker, meta in asset["issuers"].items():
        meta[LAG_KEY] = LAG_BY_TICKER.get(ticker)

    gbtc = asset["issuers"]["GBTC"]
    gbtc["download_url"] = gbtc_url
    gbtc["parser"] = gbtc_parser

    out["mapping_promotion"] = dict(MAPPING_PROMOTION)
    return out


def invariants(before, after):
    """The four comparisons the audit requires, reported as data."""
    a_before = before["assets"][ASSET]
    a_after = after["assets"][ASSET]
    i_before, i_after = a_before["issuers"], a_after["issuers"]
    lines = []
    ok = True

    added = sorted(set(i_after) - set(i_before))
    removed = sorted(set(i_before) - set(i_after))
    lines.append("new issuers: %s" % (added or 0))
    lines.append("removed issuers: %s" % (removed or 0))
    ok = ok and not added and not removed

    same_asset = a_before.get("enabled") == a_after.get("enabled")
    lines.append("asset enabled changes: %d (%r -> %r)"
                 % (0 if same_asset else 1,
                    a_before.get("enabled"), a_after.get("enabled")))
    ok = ok and same_asset

    enabled_changes, kill_changes = [], []
    for ticker in sorted(set(i_before) & set(i_after)):
        if i_before[ticker].get("enabled") != i_after[ticker].get("enabled"):
            enabled_changes.append(ticker)
        if (i_before[ticker].get("kill_switch_active")
                != i_after[ticker].get("kill_switch_active")):
            kill_changes.append(ticker)
    lines.append("issuer enabled changes: %d %s"
                 % (len(enabled_changes), enabled_changes or ""))
    lines.append("kill_switch_active changes: %d %s"
                 % (len(kill_changes), kill_changes or ""))
    ok = ok and not enabled_changes and not kill_changes

    lines.append("enabled state after: %s"
                 % json.dumps({t: i_after[t].get("enabled")
                               for t in sorted(i_after)}))
    lines.append("core_basket: %s -> %s"
                 % (a_before["core_basket"], a_after["core_basket"]))
    return ok, lines


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src",
                    default="config/etf_issuer_registry.json")
    ap.add_argument("--out", default="/tmp/etf_issuer_registry_v4.json")
    ap.add_argument("--expect-sha", dest="expect_sha", required=True)
    ap.add_argument("--gbtc-url", dest="gbtc_url", required=True)
    ap.add_argument("--gbtc-parser", dest="gbtc_parser",
                    default="grayscale_ooxml")
    args = ap.parse_args(argv)

    raw = open(args.src, "rb").read()
    actual = _sha(raw)
    print("input      : %s" % args.src)
    print("input bytes: %d" % len(raw))
    print("input sha  : %s" % actual)
    if actual != args.expect_sha:
        print("ABORT: input sha does not match --expect-sha %s"
              % args.expect_sha)
        return 1
    if not args.gbtc_url.startswith("https://"):
        print("ABORT: --gbtc-url must be https")
        return 1

    before = json.loads(raw.decode("utf-8"))
    after = build(before, args.gbtc_url, args.gbtc_parser)

    changed = _diff(before, after)
    allowed = _allowed_paths(sorted(before["assets"][ASSET]["issuers"]))
    unexpected = [c for c in changed if c[0] not in allowed]

    print("")
    print("--- changed paths (%d) ---" % len(changed))
    for path, old, new in changed:
        print("  %-52s %r -> %r" % (path, old, new))

    ok, lines = invariants(before, after)
    print("")
    print("--- invariants ---")
    for line in lines:
        print("  %s" % line)

    if unexpected:
        print("")
        print("ABORT: change outside the declared delta:")
        for path, old, new in unexpected:
            print("  %s %r -> %r" % (path, old, new))
        return 1
    if not ok:
        print("")
        print("ABORT: invariant violation")
        return 1

    body = (json.dumps(after, ensure_ascii=False, indent=2) + "\n").encode()
    with open(args.out, "wb") as handle:
        handle.write(body)
    print("")
    print("output      : %s" % args.out)
    print("output bytes: %d" % len(body))
    print("output sha  : %s" % _sha(body))
    print("input untouched: %s" % (_sha(open(args.src, "rb").read()) == actual))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
