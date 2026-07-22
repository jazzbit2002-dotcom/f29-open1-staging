"""
D2 test suite - parse_grayscale_ooxml, tested AGAINST THE PRODUCTION
MODULE.

This file deliberately imports collectors.etf_issuer and nothing else.
There is no fallback to a standalone copy: if the merge into
collectors/etf_issuer.py did not happen, or happened incorrectly, these
tests must fail at import time rather than quietly exercising a second
copy of the implementation.

Fixtures are synthesised to mirror the real GBTC container observed on
2026-07-20 (SHA cb7506e4...882a5): default namespace, t="str" cells with
inline <v>, 9-column header, DESCENDING date order, no sharedStrings.

Run from the repo root:  python3 -m pytest -q
"""

import zipfile
from io import BytesIO

import pytest

from collectors.etf_issuer import (PARSERS, ParseError,
                                   parse_grayscale_ooxml)

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

GBTC_HEADERS = ["Product Name", "Product ID", "OTC Ticker", "Date",
                "Shares Outstanding", "NAV Per Share", "NAV / Share 1 Day %",
                "Market Price Per Share", "AUM"]

COLS = "ABCDEFGHI"


# ---------------------------------------------------------------- helpers
def _cell(col, rownum, value, is_text):
    ref = "%s%d" % (col, rownum)
    if is_text:
        return '<c r="%s" t="str"><v>%s</v></c>' % (ref, value)
    return '<c r="%s"><v>%s</v></c>' % (ref, value)


def _row(rownum, values, text_flags, skip=()):
    """Build a <row>.  Columns listed in `skip` are OMITTED entirely -
    this is what OOXML does with empty cells (AC-2 regression)."""
    cells = []
    for i, val in enumerate(values):
        col = COLS[i]
        if col in skip or val is None:
            continue
        cells.append(_cell(col, rownum, val, text_flags[i]))
    return '<row r="%d">%s</row>' % (rownum, "".join(cells))


def _sheet(rows_xml, prefix=None):
    if prefix:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<{p}:worksheet xmlns:{p}="{ns}"><{p}:sheetData>{rows}'
            '</{p}:sheetData></{p}:worksheet>'
        ).format(p=prefix, ns=MAIN, rows=rows_xml).replace(
            "<row ", "<%s:row " % prefix).replace(
            "</row>", "</%s:row>" % prefix).replace(
            "<c ", "<%s:c " % prefix).replace(
            "</c>", "</%s:c>" % prefix).replace(
            "<v>", "<%s:v>" % prefix).replace(
            "</v>", "</%s:v>" % prefix)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>'
        % (MAIN, rows_xml))


def _zip(parts):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        for name, body in parts.items():
            zf.writestr(name, body)
    return buf.getvalue()


def gbtc_rows(dates_so_nav, skip_on_row=None, skip_cols=()):
    """dates_so_nav: list of (date_str, shares, nav) in SOURCE order."""
    text_flags = [True, True, True, True, False, False, False, False, False]
    out = [_row(1, GBTC_HEADERS, [True] * 9)]
    for i, (d, so, nav) in enumerate(dates_so_nav, start=2):
        vals = ["Grayscale Bitcoin Trust ETF",
                "672e88c7-dac6-4fcd-9069-18eef01a2c73", "GBTC",
                d, so, nav, "-0.0018", "49.71", "8642258335.48"]
        sk = skip_cols if (skip_on_row is None or skip_on_row == i) else ()
        out.append(_row(i, vals, text_flags, skip=sk))
    return "".join(out)


def gbtc_file(dates_so_nav, **kw):
    """Realistic 4-sheet container; only sheet1 carries the headers."""
    return _zip({
        "xl/worksheets/sheet1.xml": _sheet(gbtc_rows(dates_so_nav, **kw)),
        "xl/worksheets/sheet2.xml": _sheet(
            _row(1, ["1M", "3M", "6M", "YTD"], [True] * 4)
            + _row(2, ["0.1", "0.2", "0.3", "0.4"], [False] * 4)),
        "xl/worksheets/sheet3.xml": _sheet(
            _row(1, ["Holding", "Quantity"], [True] * 2)
            + _row(2, ["Bitcoin", "16587"], [True, False])),
        "xl/worksheets/sheet4.xml": _sheet(
            _row(1, ["Disclosures"], [True])),
    })


# Real head-of-file values, 2026-07-17 downward (see 07-20 baseline).
REAL_HEAD = [
    ("2026-07-17", "173910100", "49.69"),
    ("2026-07-16", "173910100", "49.78"),
    ("2026-07-15", "173910100", "50.33"),
    ("2026-07-14", "173910100", "50.02"),
    ("2026-07-13", "175010100", "48.23"),
]


# ------------------------------------------------------------------ tests
def test_descending_source_returns_ascending():
    """AC-3 - the whole point.  Source is newest-first."""
    out = parse_grayscale_ooxml(gbtc_file(REAL_HEAD))
    got = [r["as_of"] for r in out]
    assert got == sorted(got)
    assert got[0] == "2026-07-13" and got[-1] == "2026-07-17"


def test_delta_sign_matches_reality():
    """Regression for the inversion bug: SO fell 175,010,100 ->
    173,910,100 on 07-14, so the delta must be NEGATIVE."""
    out = parse_grayscale_ooxml(gbtc_file(REAL_HEAD))
    deltas = {out[i]["as_of"]:
              out[i]["shares_outstanding"] - out[i - 1]["shares_outstanding"]
              for i in range(1, len(out))}
    assert deltas["2026-07-14"] == -1100000.0
    assert all(v == 0.0 for k, v in deltas.items() if k != "2026-07-14")


def test_values_and_types():
    out = parse_grayscale_ooxml(gbtc_file(REAL_HEAD))
    last = out[-1]
    assert last == {"as_of": "2026-07-17",
                    "nav_per_share": 49.69,
                    "shares_outstanding": 173910100.0}
    assert isinstance(last["shares_outstanding"], float)


def test_omitted_empty_cells_do_not_shift_columns():
    """AC-2 - OOXML omits empty cells; <c> order must not drive mapping.
    Column B is dropped from row 3, which would shift D/E/F left by one
    under an order-based parser."""
    out = parse_grayscale_ooxml(
        gbtc_file(REAL_HEAD, skip_on_row=3, skip_cols=("B",)))
    by_date = {r["as_of"]: r for r in out}
    assert by_date["2026-07-16"]["shares_outstanding"] == 173910100.0
    assert by_date["2026-07-16"]["nav_per_share"] == 49.78


def test_prefixed_namespace_is_accepted():
    """AC-4 - Grayscale uses a default ns, VanEck uses x:."""
    blob = _zip({"xl/worksheets/sheet1.xml":
                 _sheet(gbtc_rows(REAL_HEAD), prefix="x")})
    out = parse_grayscale_ooxml(blob)
    assert len(out) == 5 and out[-1]["as_of"] == "2026-07-17"


def test_header_sheet_found_regardless_of_part_name():
    """AC-1 - selection is by header, never by sheet1/index."""
    blob = _zip({
        "xl/worksheets/sheet1.xml": _sheet(_row(1, ["1M", "3M"], [True] * 2)),
        "xl/worksheets/sheet7.xml": _sheet(gbtc_rows(REAL_HEAD)),
    })
    out = parse_grayscale_ooxml(blob)
    assert len(out) == 5


def test_no_matching_header_fails():
    blob = _zip({"xl/worksheets/sheet1.xml":
                 _sheet(_row(1, ["Holding", "Quantity"], [True] * 2)
                        + _row(2, ["Bitcoin", "16587"], [True, False]))})
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(blob)
    assert "found 0" in str(e.value)


def test_two_matching_sheets_fail():
    """AC-1 - ambiguity is fail-closed, not first-wins."""
    blob = _zip({
        "xl/worksheets/sheet1.xml": _sheet(gbtc_rows(REAL_HEAD)),
        "xl/worksheets/sheet2.xml": _sheet(gbtc_rows(REAL_HEAD)),
    })
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(blob)
    assert "found 2" in str(e.value)


def test_duplicate_as_of_fails():
    rows = REAL_HEAD + [("2026-07-17", "173910100", "49.69")]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "duplicate as_of" in str(e.value)


def test_non_iso_date_fails():
    rows = [("Jul 17, 2026", "173910100", "49.69")] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "not ISO-8601" in str(e.value)


def test_missing_shares_cell_fails():
    """Fail-closed: a dropped E cell must not silently become 0."""
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(
            gbtc_file(REAL_HEAD, skip_on_row=2, skip_cols=("E",)))
    assert "Shares Outstanding" in str(e.value)


def test_non_numeric_shares_fails():
    rows = [("2026-07-17", "n/a", "49.69")] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-numeric" in str(e.value)


def test_series_too_short_fails():
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(REAL_HEAD[:1]))
    assert "too short" in str(e.value)


def test_empty_sheetdata_is_skipped_not_crashed():
    blob = _zip({
        "xl/worksheets/sheet1.xml": _sheet(""),
        "xl/worksheets/sheet2.xml": _sheet(gbtc_rows(REAL_HEAD)),
    })
    assert len(parse_grayscale_ooxml(blob)) == 5


def test_shared_strings_encoding_supported():
    """Sibling products may use t="s" instead of t="str"."""
    hdr = "".join('<c r="%s1" t="s"><v>%d</v></c>' % (COLS[i], i)
                  for i in range(9))
    body = ""
    for n, (d, so, nav) in enumerate(REAL_HEAD, start=2):
        body += ('<row r="%d"><c r="D%d" t="s"><v>%d</v></c>'
                 '<c r="E%d"><v>%s</v></c><c r="F%d"><v>%s</v></c></row>'
                 % (n, n, 9 + n - 2, n, so, n, nav))
    sst = ("<sst xmlns=\"%s\">%s</sst>"
           % (MAIN, "".join("<si><t>%s</t></si>" % s
                            for s in GBTC_HEADERS + [d for d, _, _ in REAL_HEAD])))
    blob = _zip({"xl/worksheets/sheet1.xml":
                 _sheet('<row r="1">%s</row>' % hdr + body),
                 "xl/sharedStrings.xml": sst})
    out = parse_grayscale_ooxml(blob)
    assert [r["as_of"] for r in out] == sorted(d for d, _, _ in REAL_HEAD)


def test_inline_string_encoding_supported():
    """t="inlineStr" carries text in <is><t>, not <v>."""
    def icell(col, n, val):
        return ('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>'
                % (col, n, val))
    hdr = "".join(icell(COLS[i], 1, GBTC_HEADERS[i]) for i in range(9))
    body = ""
    for n, (d, so, nav) in enumerate(REAL_HEAD, start=2):
        body += ('<row r="%d">%s<c r="E%d"><v>%s</v></c>'
                 '<c r="F%d"><v>%s</v></c></row>'
                 % (n, icell("D", n, d), n, so, n, nav))
    blob = _zip({"xl/worksheets/sheet1.xml":
                 _sheet('<row r="1">%s</row>' % hdr + body)})
    out = parse_grayscale_ooxml(blob)
    assert [r["as_of"] for r in out] == sorted(d for d, _, _ in REAL_HEAD)
    assert out[-1]["shares_outstanding"] == 173910100.0


def test_rich_text_runs_in_shared_strings():
    """<si> may split text across <r><t> runs; concatenation is required.

    All three mandatory headers are present, and "Shares Outstanding" is
    the one split into runs -- so this test FAILS if run concatenation
    ever regresses, instead of passing on a missing-header technicality.
    """
    sst = (
        '<sst xmlns="%s">'
        '<si><t>Date</t></si>'
        '<si><r><t>Shares </t></r><r><t>Outstan</t></r><r><t>ding</t></r></si>'
        '<si><t>NAV Per Share</t></si>'
        '%s</sst>'
        % (MAIN, "".join("<si><t>%s</t></si>" % d for d, _, _ in REAL_HEAD)))
    rows = ('<row r="1"><c r="D1" t="s"><v>0</v></c>'
            '<c r="E1" t="s"><v>1</v></c>'
            '<c r="F1" t="s"><v>2</v></c></row>')
    for n, (_d, so, nav) in enumerate(REAL_HEAD, start=2):
        rows += ('<row r="%d"><c r="D%d" t="s"><v>%d</v></c>'
                 '<c r="E%d"><v>%s</v></c><c r="F%d"><v>%s</v></c></row>'
                 % (n, n, 3 + n - 2, n, so, n, nav))
    blob = _zip({"xl/sharedStrings.xml": sst,
                 "xl/worksheets/sheet1.xml": _sheet(rows)})
    out = parse_grayscale_ooxml(blob)
    assert [r["as_of"] for r in out] == sorted(d for d, _, _ in REAL_HEAD)
    assert out[-1]["shares_outstanding"] == 173910100.0


def test_no_namespace_is_accepted():
    """AC-4 third case: some producers emit OOXML with no namespace at
    all.  Default-ns and x:-prefixed are covered by other tests."""
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet><sheetData>%s</sheetData></worksheet>'
             % gbtc_rows(REAL_HEAD))
    out = parse_grayscale_ooxml(_zip({"xl/worksheets/sheet1.xml": sheet}))
    assert len(out) == 5
    assert out[-1]["as_of"] == "2026-07-17"
    assert out[-1]["shares_outstanding"] == 173910100.0


@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-inf",
                                 "Infinity", "-Infinity", "1e400"])
def test_non_finite_shares_fails(bad):
    """float() accepts these; they must not reach the series."""
    rows = [("2026-07-17", bad, "49.69")] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-finite" in str(e.value)
    assert "Shares Outstanding" in str(e.value)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "Infinity"])
def test_non_finite_nav_fails(bad):
    rows = [("2026-07-17", "173910100", bad)] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-finite" in str(e.value)
    assert "NAV Per Share" in str(e.value)


def test_non_finite_never_reaches_output():
    """Belt-and-braces: no returned value may be nan or inf."""
    import math
    out = parse_grayscale_ooxml(gbtc_file(REAL_HEAD))
    for row in out:
        assert math.isfinite(row["shares_outstanding"])
        assert math.isfinite(row["nav_per_share"])


# ------------------------------------------------- merge integrity
def test_grayscale_parser_registered_in_production_registry():
    """The decorator must have run inside the production module."""
    assert PARSERS["grayscale_ooxml"] is parse_grayscale_ooxml


def test_parser_lives_in_production_module():
    """Guards against testing a stray standalone copy."""
    assert parse_grayscale_ooxml.__module__ == "collectors.etf_issuer"


def test_existing_registrations_survive_the_merge():
    """If the standalone shim ever fired inside etf_issuer.py it would
    rebind PARSERS to {} and wipe the iShares registration.  It must
    not: ParseError/PARSERS already exist there, so the shim is skipped.
    """
    assert "ishares_spreadsheetml" in PARSERS
    assert len(PARSERS) >= 2


def test_parser_raises_the_production_parse_error():
    """Not a shadowed copy of ParseError defined by the merged block."""
    import collectors.etf_issuer as E
    assert ParseError is E.ParseError
    with pytest.raises(E.ParseError):
        parse_grayscale_ooxml(b"definitely not a zip")


# ------------------------------------------------- numeric guards
@pytest.mark.parametrize("bad", ["1,2,3", "1,234,567"])
def test_grouped_digits_are_rejected_not_silently_stripped(bad):
    """Comma stripping would turn "1,2,3" into 123.0.  Fail closed."""
    rows = [("2026-07-17", bad, "49.69")] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-numeric" in str(e.value)


@pytest.mark.parametrize("bad", ["-173910100", "0", "-0.0"])
def test_non_positive_shares_fails(bad):
    rows = [("2026-07-17", bad, "49.69")] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-positive" in str(e.value)
    assert "Shares Outstanding" in str(e.value)


@pytest.mark.parametrize("bad", ["-49.69", "0"])
def test_non_positive_nav_fails(bad):
    rows = [("2026-07-17", "173910100", bad)] + REAL_HEAD[1:]
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(gbtc_file(rows))
    assert "non-positive" in str(e.value)
    assert "NAV Per Share" in str(e.value)


def test_not_a_zip_fails():
    with pytest.raises(ParseError) as e:
        parse_grayscale_ooxml(b"<?xml version=\"1.0\"?><worksheet/>")
    assert "OOXML container" in str(e.value)


def test_declares_ooxml_magic_bytes():
    """D1 hand-off: the parser carries its own signature."""
    assert parse_grayscale_ooxml.expected_prefixes == (b"PK\x03\x04",)


def test_full_scale_630_rows():
    """Real GBTC is 630 data rows (dimension A1:I631, row 1 = header)."""
    import datetime
    d0 = datetime.date(2026, 7, 17)
    rows = []
    for i in range(630):
        rows.append(((d0 - datetime.timedelta(days=i)).isoformat(),
                     str(173910100 + i * 1000), "49.69"))
    out = parse_grayscale_ooxml(gbtc_file(rows))
    assert len(out) == 630
    got = [r["as_of"] for r in out]
    assert got == sorted(got)
    # SO decreases as dates advance -> every delta must be negative.
    assert all(out[i]["shares_outstanding"] < out[i - 1]["shares_outstanding"]
               for i in range(1, len(out)))
