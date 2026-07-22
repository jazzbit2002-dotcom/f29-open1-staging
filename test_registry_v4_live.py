"""Operational registry conformance (D5a-2).

Separate file on purpose: tests/test_registry_v4.py carries the ratified
D5a-1 fingerprint (f03e1b0b...) and editing it would break the
"deployed == approved" comparison for no gain.

Static validation only.  The transition rules read the live done marker,
whose contents move with the KST window and the cron slots, so asserting on
them here would make the suite time-dependent.  Transition behaviour is
already locked by the 75 synthetic cases next door.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.collect_etf_ibit as C            # noqa: E402
import scripts.validate_registry as V           # noqa: E402
from collectors.etf_issuer import PARSERS       # noqa: E402

LAG_KEY = "target_lag_us_business_days"


def test_live_registry_is_a_valid_v4_file(capsys):
    assert V.main(["--candidate", C.REGISTRY, "--static-only"]) == 0
    assert "errors=0" in capsys.readouterr().out

    import json
    with open(C.REGISTRY, encoding="utf-8") as handle:
        reg = json.load(handle)

    assert reg["schema_version"] == V.SCHEMA_VERSION
    for asset, cfg in reg["assets"].items():
        for ticker, meta in cfg["issuers"].items():
            where = "%s/%s" % (asset, ticker)
            assert LAG_KEY in meta, where
            lag = meta[LAG_KEY]
            assert lag is None or (isinstance(lag, int)
                                   and not isinstance(lag, bool)
                                   and lag >= 0), where
            if meta.get("enabled") is True:
                assert meta.get("parser") in PARSERS, where
                assert meta.get("download_url"), where
