"""
D1 test - per-parser container signature declaration.

Tested against the production module.  No network: every test that
reaches poll_and_collect monkeypatches collectors.ephemeral
.fetch_extract_discard and inspects the arguments it received.

D1 moves the magic-byte gate from a hard-coded literal inside
poll_and_collect to a declaration carried by each parser, so that
non-XML containers (Grayscale OOXML, Fidelity OLE2, Bitwise HTML) can be
admitted without weakening the gate for anyone else.

Run from the repo root:  python3 -m pytest -q
"""

from datetime import datetime, timezone

import pytest

import collectors.ephemeral as EPH
import collectors.etf_issuer as E


def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()


@pytest.fixture
def capture_fetch(monkeypatch):
    """Replace the network call; record what poll_and_collect passed."""
    seen = {}

    def fake(url, extractor, timeout=30, max_bytes=None,
             expected_prefixes=None):
        seen["url"] = url
        seen["extractor"] = extractor
        seen["expected_prefixes"] = expected_prefixes
        today = _today_iso()
        return {"result": [
            {"as_of": "2026-01-01", "nav_per_share": 10.0,
             "shares_outstanding": 100.0},
            {"as_of": today, "nav_per_share": 11.0,
             "shares_outstanding": 110.0},
        ], "input_digest": "d" * 64, "persistence_mode": "ephemeral_memory"}

    monkeypatch.setattr(EPH, "fetch_extract_discard", fake)
    return seen


# ---------------------------------------------------- declarations
def test_ishares_declares_xml_signature():
    assert E.parse_ishares_spreadsheetml.expected_prefixes == (b"<?xml",)


def test_grayscale_declares_ooxml_signature():
    assert E.parse_grayscale_ooxml.expected_prefixes == (b"PK\x03\x04",)


def test_declarations_are_tuples_of_bytes():
    for name, fn in E.PARSERS.items():
        prefixes = getattr(fn, "expected_prefixes", None)
        assert prefixes is not None, "parser %r declares nothing" % name
        assert isinstance(prefixes, tuple), name
        assert all(isinstance(p, bytes) and p for p in prefixes), name


# ---------------------------------------------------- register_parser
def test_register_parser_still_accepts_one_argument():
    """Backward compatibility: the decorator must not become mandatory
    two-arg, or any parser registered the old way breaks at import."""
    @E.register_parser("d1_probe_onearg")
    def _p(raw):
        return []
    assert E.PARSERS["d1_probe_onearg"] is _p
    del E.PARSERS["d1_probe_onearg"]


def test_register_parser_sets_declaration_from_argument():
    @E.register_parser("d1_probe_declared", expected_prefixes=(b"%PDF",))
    def _p(raw):
        return []
    assert _p.expected_prefixes == (b"%PDF",)
    del E.PARSERS["d1_probe_declared"]


def test_register_parser_normalises_list_to_tuple():
    @E.register_parser("d1_probe_list", expected_prefixes=[b"AB", b"CD"])
    def _p(raw):
        return []
    assert _p.expected_prefixes == (b"AB", b"CD")
    del E.PARSERS["d1_probe_list"]


# ---------------------------------------------------- wiring
def test_poll_forwards_ooxml_declaration(capture_fetch):
    E.poll_and_collect("GBTC", "http://example.invalid/x", "grayscale_ooxml")
    assert capture_fetch["expected_prefixes"] == (b"PK\x03\x04",)
    assert capture_fetch["extractor"] is E.parse_grayscale_ooxml


def test_poll_forwards_xml_declaration(capture_fetch):
    """Regression: the iShares path must be byte-identical to pre-D1."""
    E.poll_and_collect("IBIT", "http://example.invalid/x",
                       "ishares_spreadsheetml")
    assert capture_fetch["expected_prefixes"] == (b"<?xml",)


def test_poll_no_longer_hardcodes_a_single_signature(capture_fetch):
    """Two parsers, two different gates, same call site."""
    E.poll_and_collect("IBIT", "http://example.invalid/a",
                       "ishares_spreadsheetml")
    first = capture_fetch["expected_prefixes"]
    E.poll_and_collect("GBTC", "http://example.invalid/b", "grayscale_ooxml")
    second = capture_fetch["expected_prefixes"]
    assert first != second


# ---------------------------------------------------- fail-closed
def test_undeclared_parser_is_refused_before_any_fetch(monkeypatch):
    called = []
    monkeypatch.setattr(EPH, "fetch_extract_discard",
                        lambda *a, **k: called.append(1))

    @E.register_parser("d1_probe_undeclared")
    def _p(raw):
        return []
    try:
        with pytest.raises(ValueError) as e:
            E.poll_and_collect("X", "http://example.invalid/x",
                               "d1_probe_undeclared")
        assert "expected_prefixes" in str(e.value)
        assert called == [], "fetch must not run without a signature gate"
    finally:
        del E.PARSERS["d1_probe_undeclared"]


def test_unregistered_parser_still_raises(monkeypatch):
    called = []
    monkeypatch.setattr(EPH, "fetch_extract_discard",
                        lambda *a, **k: called.append(1))
    with pytest.raises(ValueError):
        E.poll_and_collect("X", "http://example.invalid/x", "no_such_parser")
    assert called == []
