#!/usr/bin/env python3
# F29 v7.2 contract patch - brief_contract_v1_1.py
# APPROVED (RATIFIED 2026-07-22): remove body<->meta character cross-checks,
#   raise ready article length ceiling. No new checks, no word-boundary parser.
#
# Removes (per canary1 analysis):
#   [D] body<->tickers two-way char match  (lines 435-440)
#   [A] body<->themes  two-way char match  (lines 453-460)
# Keeps:
#   ticker/theme exact membership (allowed_tickers / allowed_themes),
#   counts, schema, forbidden words, number+unit, provenance(derived fields),
#   absolute-price, digest, SHA/atomic, disclaimer.
# Change:
#   [E] ARTICLE_LEN ready ceiling 2500 -> 3200
#
# Contract: literal anchor + str.replace, count gate, dup guard, backup,
#   py_compile, atomic write, rollback printed. Pure ASCII.

import os, sys, shutil, hashlib, py_compile, tempfile
from datetime import datetime, timezone

TARGET = "/root/moneyflow/brief_contract_v1_1.py"
EXPECT_PRE_SHA = "bdb26c84baea6152cadc406973464a43cc606a7c519b6022971a135135c0315f"
BACKUP_ROOT = "/root/f29-backups"
MARKER = "F29-V72-CONTRACT"

# --- anchor A: ticker body cross-check (remove) ---
ANCHOR_TICKER = (
    "        seen = mentioned_tickers(body, aliases)\n"
    "        for t in sorted(declared - seen):\n"
    "            res.fail(\"sections[%s]: ticker %s declared but not mentioned in body \"\n"
    "                     \"(neither symbol nor name)\" % (sid, t))\n"
    "        for t in sorted(seen - declared):\n"
    "            res.fail(\"sections[%s]: body mentions %s but tickers array omits it\" % (sid, t))\n"
)
REPLACE_TICKER = (
    "        # " + MARKER + " removed body<->tickers char cross-check (canary1 D).\n"
    "        # Exact stock_radar membership below still rejects market proxies.\n"
)

# --- anchor B: theme body cross-check (remove, keep theme_all.add) ---
ANCHOR_THEME = (
    "                dec_th.add(t)\n"
    "                theme_all.add(t)\n"
    "        for t in sorted(dec_th):\n"
    "            if t not in body:\n"
    "                res.fail(\"sections[%s]: theme '%s' declared but not discussed in body\"\n"
    "                         % (sid, t))\n"
    "        if ok_th_all:\n"
    "            for t in sorted(mentioned_themes(body, ok_th_all) - dec_th):\n"
    "                res.fail(\"sections[%s]: body discusses theme '%s' but themes array omits it\"\n"
    "                         % (sid, t))\n"
)
REPLACE_THEME = (
    "                dec_th.add(t)\n"
    "                theme_all.add(t)\n"
    "        # " + MARKER + " removed body<->themes char cross-check (canary1 A).\n"
    "        # themes = section's representative SOURCE tags, not a full body index.\n"
    "        # Exact membership (theme_all - ok_th) below still enforced.\n"
)

# --- anchor C: article length ceiling ---
ANCHOR_LEN = 'ARTICLE_LEN = {"baseline_only": (1000, 1600), "ready": (1500, 2500)}\n'
REPLACE_LEN = (
    'ARTICLE_LEN = {"baseline_only": (1000, 1600), "ready": (1500, 3200)}'
    '  # ' + MARKER + '\n'
)


def sha256_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def die(m):
    print("ABORT: " + m); sys.exit(1)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else TARGET
    if not os.path.isfile(target):
        die("target not found: " + target)
    with open(target, encoding="utf-8") as f:
        src = f.read()
    pre = sha256_file(target)
    print("pre_sha256: " + pre)
    if MARKER in src:
        print("already applied: " + MARKER); return 0
    if target == TARGET and pre != EXPECT_PRE_SHA:
        die("pre SHA mismatch (expected %s)" % EXPECT_PRE_SHA)

    for name, a in (("ticker", ANCHOR_TICKER), ("theme", ANCHOR_THEME),
                    ("length", ANCHOR_LEN)):
        n = src.count(a)
        print("anchor gate: %-7s count==%d" % (name, n))
        if n != 1:
            die("anchor %s count %d != 1" % (name, n))

    out = src.replace(ANCHOR_TICKER, REPLACE_TICKER)
    out = out.replace(ANCHOR_THEME, REPLACE_THEME)
    out = out.replace(ANCHOR_LEN, REPLACE_LEN)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bdir = os.path.join(BACKUP_ROOT, "v72-contract-" + ts)
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(target, os.path.join(bdir, os.path.basename(target)))
    print("backup: " + os.path.join(bdir, os.path.basename(target)))

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".py")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    try:
        py_compile.compile(tmp, doraise=True)
        print("py_compile: PASS")
    except Exception as e:
        os.unlink(tmp); die("py_compile failed: " + str(e)[:200])
    os.chmod(tmp, os.stat(target).st_mode & 0o7777)
    os.replace(tmp, target)

    post = sha256_file(target)
    print("applied. post_sha256: " + post)
    print("post size: %d bytes" % os.path.getsize(target))
    with open(target, encoding="utf-8") as f:
        c = f.read()
    print("marker count: %d" % c.count(MARKER))
    print("residual body-cross checks: %d (expect 0)"
          % (c.count("declared but not mentioned in body")
             + c.count("body discusses theme")
             + c.count("declared but not discussed in body")
             + c.count("body mentions %s but tickers")))
    print("ROLLBACK: cp %s %s"
          % (os.path.join(bdir, os.path.basename(target)), target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
