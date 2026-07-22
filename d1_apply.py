#!/usr/bin/env python3
"""
D1 patch applier for collectors/etf_issuer.py.

Three hunks, each matched by exact string and asserted to occur exactly
once.  Anything unexpected aborts before writing, so a mismatched source
fails loudly instead of being mangled.

  usage:  python3 d1_apply.py [--check]

  --check   report what would change and exit without writing

Idempotent: re-running on an already-patched file reports NOOP.

D1 scope only.  Does not touch the driver, the registry, cron, or the
D2 parser block.
"""

import hashlib
import os
import sys

TARGET = os.path.join("collectors", "etf_issuer.py")

HUNKS = [
    (
        "register_parser accepts a signature declaration",
        '''def register_parser(name):
    def deco(fn):
        PARSERS[name] = fn
        return fn
    return deco''',
        '''def register_parser(name, expected_prefixes=None):
    """Register a parser and, optionally, the magic bytes it accepts.

    D1: the container signature belongs to the parser, not to the caller.
    Passing expected_prefixes here is equivalent to setting the attribute
    on the function afterwards; both are read by poll_and_collect.
    """
    def deco(fn):
        if expected_prefixes is not None:
            fn.expected_prefixes = tuple(expected_prefixes)
        PARSERS[name] = fn
        return fn
    return deco''',
    ),
    (
        "iShares declares its own signature (behaviour unchanged)",
        '@register_parser("ishares_spreadsheetml")',
        '@register_parser("ishares_spreadsheetml", expected_prefixes=(b"<?xml",))',
    ),
    (
        "poll_and_collect reads the declaration instead of hard-coding",
        '''    fx = fetch_extract_discard(download_url, extractor=parser,
                               expected_prefixes=(b"<?xml",))''',
        '''    expected_prefixes = getattr(parser, "expected_prefixes", None)
    if expected_prefixes is None:
        raise ValueError(
            "parser %r declares no expected_prefixes - refusing to fetch "
            "without a signature gate" % parser_name)

    fx = fetch_extract_discard(download_url, extractor=parser,
                               expected_prefixes=expected_prefixes)''',
    ),
]


def main():
    check_only = "--check" in sys.argv[1:]

    if not os.path.isfile(TARGET):
        sys.exit("not found: %s (run from the repo root)" % TARGET)

    src = open(TARGET, encoding="utf-8").read()
    before = hashlib.sha256(src.encode()).hexdigest()
    print("target : %s" % TARGET)
    print("bytes  : %d" % len(src.encode()))
    print("sha256 : %s" % before)
    print()

    applied, already = 0, 0
    for label, old, new in HUNKS:
        n_old, n_new = src.count(old), src.count(new)
        if n_old == 0 and n_new >= 1:
            print("  NOOP  %s (already applied)" % label)
            already += 1
            continue
        if n_old != 1:
            sys.exit("  ABORT %s: expected 1 match, found %d" % (label, n_old))
        src = src.replace(old, new)
        applied += 1
        print("  OK    %s" % label)

    print()
    if already == len(HUNKS):
        print("nothing to do - file already patched")
        return
    if applied != len(HUNKS):
        sys.exit("ABORT: partial match (%d applied, %d already)"
                 % (applied, already))

    after = hashlib.sha256(src.encode()).hexdigest()
    if check_only:
        print("--check: would write %d bytes, sha256 %s"
              % (len(src.encode()), after))
        return

    open(TARGET, "w", encoding="utf-8").write(src)
    print("written: %d bytes" % len(src.encode()))
    print("sha256 : %s" % after)


if __name__ == "__main__":
    main()
