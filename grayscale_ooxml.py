"""
D2: Grayscale OOXML parser for etf_issuer.py

Insert the block below into collectors/etf_issuer.py.  It is also
importable standalone (isolated unit runs) via the fallback shim at the
bottom of this docstring section.

Audit contract satisfied (2026-07-22):
  - AC-1 worksheet selection is by HEADER, never by part name or index.
         Every worksheet part is scanned; exactly one match is required.
         0 matches or 2+ matches -> ParseError (fail-closed).
  - AC-2 column mapping is by cell coordinate c.attrib["r"], never by
         <c> document order.  OOXML omits empty cells.
  - AC-3 output is sorted ASCENDING by as_of, duplicates rejected.
         (Source file is DESCENDING; unsorted output would invert the
         sign of every delta_shares downstream.)
  - AC-4 namespace-agnostic matching ({*}) - Grayscale uses a default
         namespace, VanEck uses an "x:" prefix.
  - AC-5 fail-closed: missing header, missing required cell, bad date,
         empty sheet, or under-length series all raise ParseError.

Return contract is identical to parse_ishares_spreadsheetml:
    [{"as_of": "YYYY-MM-DD", "nav_per_share": float,
      "shares_outstanding": float}, ...]

MERGE-ONLY FILE.  This is an insertion block for
collectors/etf_issuer.py, not an importable module: it deliberately
relies on ParseError / register_parser / PARSERS already existing in the
host module.  Importing it standalone raises NameError by design, and it
must be DELETED after merging -- a second copy of the implementation
would drift.  tests/test_grayscale_ooxml.py imports the production
module only, so a missing or malformed merge fails loudly.

D1 coupling: this parser declares its own magic bytes as a function
attribute (see PARSER_EXPECTED_PREFIXES / attribute assignment).  It
works unchanged whether or not D1 has landed; once register_parser
grows an expected_prefixes argument, poll_and_collect can read it via
getattr(parser, "expected_prefixes", None).
"""

import math as _gs_math
import re as _gs_re
import zipfile as _gs_zip
from datetime import date as _gs_date
from io import BytesIO as _gs_BytesIO
from xml.etree import ElementTree as _gs_ET



_GS_WORKSHEET_PART = _gs_re.compile(r"^xl/worksheets/[^/]+\.xml$")
_GS_CELL_REF = _gs_re.compile(r"^([A-Z]+)[0-9]+$")

# Header labels that must all be present for a worksheet to be adopted.
_GS_H_DATE = "Date"
_GS_H_SHARES = "Shares Outstanding"
_GS_H_NAV = "NAV Per Share"
_GS_REQUIRED_HEADERS = (_GS_H_DATE, _GS_H_SHARES, _GS_H_NAV)

# compute_creation_redemption drops the first row, so a usable series
# needs at least two data rows.
_GS_MIN_DATA_ROWS = 2

PARSER_EXPECTED_PREFIXES = (b"PK\x03\x04",)  # OOXML is a zip container


def _gs_col(ref):
    """'AB12' -> 'AB'.  AC-2: coordinate is authoritative, not order."""
    m = _GS_CELL_REF.match((ref or "").strip())
    if not m:
        raise ParseError("cell without usable r= coordinate: %r" % (ref,))
    return m.group(1)


def _gs_shared_strings(zf):
    """Return the sharedStrings table, or [] when the part is absent.

    Grayscale files observed on 2026-07-20 carry no sharedStrings part
    (cells are t="str" with an inline <v>), but sibling products may.
    """
    try:
        blob = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = _gs_ET.fromstring(blob)
    out = []
    for si in root.findall("{*}si"):
        # NOTE: Element.iter() treats "{*}t" as a literal tag name - the
        # wildcard is only honoured by find/findall path syntax.
        out.append("".join(t.text or "" for t in si.findall(".//{*}t")))
    return out


def _gs_cell_text(cell, shared):
    """Text of one <c>, honouring the t= encoding.

    Handles: t="str" (formula string), t="s" (sharedStrings index),
    t="inlineStr" (<is><t>), and untyped numeric cells.
    """
    kind = cell.get("t")
    if kind == "inlineStr":
        is_el = cell.find("{*}is")
        if is_el is None:
            return ""
        return "".join(t.text or "" for t in is_el.findall(".//{*}t"))
    v = cell.find("{*}v")
    if v is None or v.text is None:
        return ""
    text = v.text
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            raise ParseError("sharedStrings index out of range: %r" % (text,))
    return text


def _gs_row_map(row, shared):
    """{column_letter: text} for one <row>.  AC-2."""
    out = {}
    for cell in row.findall("{*}c"):
        col = _gs_col(cell.get("r"))
        if col in out:
            raise ParseError("duplicate cell coordinate in row: %s" % col)
        out[col] = _gs_cell_text(cell, shared)
    return out


def _gs_header_columns(row_map):
    """Column letters for the required headers, or None if not a header.

    Returns None (not an error) when the row simply is not the header we
    are looking for -- the caller uses that to skip non-matching sheets.
    Raises only when a header label is genuinely ambiguous.
    """
    label_to_cols = {}
    for col, text in row_map.items():
        label = (text or "").strip()
        if label:
            label_to_cols.setdefault(label, []).append(col)
    for label in _GS_REQUIRED_HEADERS:
        if label not in label_to_cols:
            return None
    picked = {}
    for label in _GS_REQUIRED_HEADERS:
        cols = label_to_cols[label]
        if len(cols) != 1:
            raise ParseError(
                "ambiguous header %r appears in %d columns" % (label, len(cols)))
        picked[label] = cols[0]
    return picked


def _gs_number(text, field, as_of):
    # No comma stripping: the observed <v> payloads carry no thousands
    # separators, and stripping them would turn a malformed "1,2,3" into
    # 123.0.  If a real issuer file ever ships grouped digits, admit them
    # with an explicit format regex rather than by deleting characters.
    try:
        value = float((text or "").strip())
    except ValueError:
        raise ParseError(
            "non-numeric %s at as_of=%s: %r" % (field, as_of, text))
    # float() accepts "nan"/"inf"/"Infinity" and overflows "1e400" to inf.
    # Those are valid floats but invalid data: they would propagate
    # silently through delta_shares and est_creation_usd.  Fail closed.
    if not _gs_math.isfinite(value):
        raise ParseError(
            "non-finite %s at as_of=%s: %r" % (field, as_of, text))
    # Shares outstanding and NAV per share are strictly positive by
    # definition; a zero or negative reading is corruption, not data.
    if field in (_GS_H_SHARES, _GS_H_NAV) and value <= 0:
        raise ParseError(
            "non-positive %s at as_of=%s: %r" % (field, as_of, text))
    return value


@register_parser("grayscale_ooxml")
def parse_grayscale_ooxml(raw):
    """Grayscale daily-performance xlsx -> ascending SO series.

    Same return contract as parse_ishares_spreadsheetml.
    """
    try:
        zf = _gs_zip.ZipFile(_gs_BytesIO(raw))
    except _gs_zip.BadZipFile as e:
        raise ParseError("not a readable OOXML container: %s" % e)

    with zf:
        parts = sorted(n for n in zf.namelist() if _GS_WORKSHEET_PART.match(n))
        if not parts:
            raise ParseError("no worksheet parts in container")
        shared = _gs_shared_strings(zf)

        # AC-1: scan every worksheet, adopt on header match only.
        matches = []
        for part in parts:
            try:
                root = _gs_ET.fromstring(zf.read(part))
            except _gs_ET.ParseError as e:
                raise ParseError("worksheet %s is not well-formed: %s" % (part, e))
            rows = root.findall(".//{*}sheetData/{*}row")
            if not rows:
                continue
            cols = _gs_header_columns(_gs_row_map(rows[0], shared))
            if cols is not None:
                matches.append((part, rows, cols))

        if len(matches) != 1:
            raise ParseError(
                "expected exactly 1 worksheet carrying headers %s, found %d (%s)"
                % (list(_GS_REQUIRED_HEADERS), len(matches),
                   ", ".join(m[0] for m in matches) or "none"))

        part, rows, cols = matches[0]

    c_date, c_shares, c_nav = (
        cols[_GS_H_DATE], cols[_GS_H_SHARES], cols[_GS_H_NAV])

    series = []
    seen = set()
    for row in rows[1:]:
        rm = _gs_row_map(row, shared)
        raw_date = (rm.get(c_date) or "").strip()
        if not raw_date:
            raise ParseError(
                "%s row r=%s: empty Date cell" % (part, row.get("r")))
        try:
            as_of = _gs_date.fromisoformat(raw_date).isoformat()
        except ValueError:
            raise ParseError(
                "%s row r=%s: Date is not ISO-8601: %r"
                % (part, row.get("r"), raw_date))
        if as_of in seen:
            raise ParseError("duplicate as_of in source: %s" % as_of)
        seen.add(as_of)

        shares_txt = rm.get(c_shares)
        nav_txt = rm.get(c_nav)
        if not (shares_txt or "").strip():
            raise ParseError("missing Shares Outstanding at as_of=%s" % as_of)
        if not (nav_txt or "").strip():
            raise ParseError("missing NAV Per Share at as_of=%s" % as_of)

        series.append({
            "as_of": as_of,
            "nav_per_share": _gs_number(nav_txt, "NAV Per Share", as_of),
            "shares_outstanding": _gs_number(
                shares_txt, "Shares Outstanding", as_of),
        })

    if len(series) < _GS_MIN_DATA_ROWS:
        raise ParseError(
            "series too short: %d data rows (min %d)"
            % (len(series), _GS_MIN_DATA_ROWS))

    # AC-3: source is DESCENDING; downstream diffing requires ASCENDING.
    series.sort(key=lambda r: r["as_of"])
    return series


# D1 hand-off: magic bytes travel with the parser, not with the caller.
parse_grayscale_ooxml.expected_prefixes = PARSER_EXPECTED_PREFIXES
