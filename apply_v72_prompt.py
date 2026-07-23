#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# F29 macro_prompt_v7.txt -> v7.2 patch
# APPROVED SCOPE (Sky 2026-07-23): P-1 themes / P-2 tickers / P-3 length only.
# All else unchanged: section structure, data-input desc, comparison/digest,
#   relative-return, forbidden/metaphor/absolute-price, social/email/key_points,
#   disclaimer, output JSON schema.
#
# Contract: literal anchor + str.replace, count gate, dup guard, backup,
#   UTF-8 write, byte report, forbidden-token(2,500) residual check, rollback.
# NOTE: contains Korean -> must be delivered via GitHub raw, not SSH paste.

import os, sys, shutil, hashlib, tempfile

TARGET = "/root/moneyflow/macro_prompt_v7.txt"
EXPECT_PRE_SHA = "5f4d65cb6366bf7616a00e6a7c8207269adf92ea165ac00c397efca14db4b2f3"
BACKUP_ROOT = "/root/f29-backups"
MARKER = "v7.2"   # not written into file; internal label only

# --- P-2 tickers (anchor: 3 lines) ---
ANCHOR_TICKER = (
    "- tickers \ub294 \uadf8 body \uc5d0\uc11c \uc2e4\uc81c\ub85c \uc5b8\uae09\ud55c \uc885\ubaa9\uc758 \ub300\ubb38\uc790 \ud2f0\ucee4 \ubc30\uc5f4\uc785\ub2c8\ub2e4. \ucd5c\ub300 4\uac1c.\n"
    "  body \uc5d0 \ub4f1\uc7a5\ud558\uc9c0 \uc54a\ub294 \ud2f0\ucee4\ub97c \ub123\uc9c0 \uc54a\uace0, body \uc5d0\uc11c \uc5b8\uae09\ud55c \uc885\ubaa9\uc744 \ube60\ub728\ub9ac\uc9c0\ub3c4 \uc54a\uc2b5\ub2c8\ub2e4.\n"
    "  \ud2f0\ucee4\ub294 \uc81c\uacf5\ub41c \ub370\uc774\ud130\uc5d0 \uc2e4\uc7ac\ud558\ub294 \uac12\ub9cc \uc501\ub2c8\ub2e4. \ud55c\uae00 \uc885\ubaa9\uba85\uc744 body \uc5d0 \uc4f0\ub354\ub77c\ub3c4 tickers \uc5d0\ub294 \ud2f0\ucee4\ub97c \ub123\uc2b5\ub2c8\ub2e4.\n"
)
REPLACE_TICKER = (
    "- tickers \uc5d0\ub294 stock_radar \ud5c8\uc6a9 \uc720\ub2c8\ubc84\uc2a4\uc5d0 \uc18d\ud558\ub294 \uac1c\ubcc4 \uae30\uc5c5 \uc885\ubaa9 \uc911, \uadf8 \uc808\uc758 \ub300\uc2dc\ubcf4\ub4dc \ub9c1\ud06c \ub300\uc0c1\uc73c\ub85c \uc120\ud0dd\ud55c \ud2f0\ucee4\ub9cc \ub123\uc2b5\ub2c8\ub2e4. \ucd5c\ub300 4\uac1c.\n"
    "  \uc9c0\uc218\u00b7ETF\u00b7\uc120\ubb3c\u00b7\ud658\uc728\u00b7\uc6d0\uc790\uc7ac\u00b7\ud68c\uc0ac\ucc44\u00b7\uc2dc\uc7a5 \ud504\ub85d\uc2dc\ub294 \ub123\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. \uc608: SPY, QQQ, IWM, DXY, VIX, NQ1, CL1, BRN1, HYG, LQD.\n"
    "  \ud574\ub2f9 \uc808\uc5d0 \ub9c1\ud06c\ud560 \uac1c\ubcc4 \uae30\uc5c5 \uc885\ubaa9\uc774 \uc5c6\uc73c\uba74 \ube48 \ubc30\uc5f4\ub85c \ub461\ub2c8\ub2e4. \ubcf8\ubb38\uc5d0 \uc5b8\uae09\ub41c \ubaa8\ub4e0 \uae30\ud638\ub97c tickers \uc5d0 \uc62e\uae38 \ud544\uc694\ub294 \uc5c6\uc2b5\ub2c8\ub2e4.\n"
)

# --- P-1 themes (anchor: 2 lines) ---
ANCHOR_THEME = (
    "- themes \ub294 \uadf8 body \uc5d0\uc11c \ub2e4\ub8ec \ud14c\ub9c8\uba85 \ubc30\uc5f4\uc785\ub2c8\ub2e4. \ucd5c\ub300 6\uac1c.\n"
    "  \uc81c\uacf5\ub41c \ub370\uc774\ud130\uc5d0 \uc788\ub294 \ud14c\ub9c8\uba85\uacfc \uc644\uc804\ud788 \uac19\uc740 \ubb38\uc790\uc5f4\ub9cc \uc501\ub2c8\ub2e4. \uc0c8 \uc774\ub984\uc744 \ub9cc\ub4e4\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.\n"
)
REPLACE_THEME = (
    "- \uac01 \uc808\uc758 themes \uc5d0\ub294 \uadf8 \uc808\uc758 \ud575\uc2ec \ub17c\uc9c0\ub97c \ub300\ud45c\ud558\ub294 SOURCE THEMES \ud0dc\uadf8\ub9cc \ub123\uc2b5\ub2c8\ub2e4. \ucd5c\ub300 6\uac1c.\n"
    "  \ubcf8\ubb38\uc5d0 \ub4f1\uc7a5\ud55c \ubaa8\ub4e0 \ud14c\ub9c8\uc5b4\ub97c \ube60\uc9d0\uc5c6\uc774 \uc0c9\uc778\ud560 \ud544\uc694\ub294 \uc5c6\uc2b5\ub2c8\ub2e4.\n"
    "  \uac01 \ud0dc\uadf8\ub294 SOURCE THEMES \uc5d0 \uc874\uc7ac\ud558\ub294 \uc815\ud655\ud55c \ubb38\uc790\uc5f4\uc774\uc5b4\uc57c \ud569\ub2c8\ub2e4.\n"
    "  \uadf8\ub8f9\uba85\u00b7\uacc4\uc5f4\uba85\u00b7\ubd80\ubd84\ubb38\uc790\uc5f4\uc744 \uc784\uc758\ub85c \ud0dc\uadf8\ub85c \ub9cc\ub4e4\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.\n"
)

# --- P-3 length: ready 2500 -> 3200 (anchor unique) ---
ANCHOR_READY = "- \uc804\uccb4 \uc0b0\ubb38 \ubd84\ub7c9 \ud569\uacc4\ub294 1,500\uc790\uc5d0\uc11c 2,500\uc790\uc785\ub2c8\ub2e4.\n"
REPLACE_READY = "- \uc804\uccb4 \uc0b0\ubb38 \ubd84\ub7c9 \ud569\uacc4\ub294 1,500\uc790\uc5d0\uc11c 3,200\uc790\uc785\ub2c8\ub2e4.\n"

# --- P-3 length: baseline 1600 -> 1800 (anchor unique) ---
ANCHOR_BASE = "- \uc804\uccb4 \uc0b0\ubb38 \ubd84\ub7c9 \ud569\uacc4\ub294 1,000\uc790\uc5d0\uc11c 1,600\uc790\uc785\ub2c8\ub2e4.\n"
REPLACE_BASE = "- \uc804\uccb4 \uc0b0\ubb38 \ubd84\ub7c9 \ud569\uacc4\ub294 1,000\uc790\uc5d0\uc11c 1,800\uc790\uc785\ub2c8\ub2e4.\n"

ANCHORS = [("tickers", ANCHOR_TICKER, REPLACE_TICKER),
           ("themes", ANCHOR_THEME, REPLACE_THEME),
           ("ready_len", ANCHOR_READY, REPLACE_READY),
           ("base_len", ANCHOR_BASE, REPLACE_BASE)]


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
    print("pre_sha256 : " + pre)
    print("pre_bytes  : %d" % os.path.getsize(target))

    if REPLACE_TICKER in src:
        print("already applied (P-2 present)"); return 0
    if target == TARGET and pre != EXPECT_PRE_SHA:
        die("pre SHA mismatch (expected %s)" % EXPECT_PRE_SHA)

    for name, a, _ in ANCHORS:
        n = src.count(a)
        print("anchor gate: %-9s count==%d" % (name, n))
        if n != 1:
            die("anchor %s count %d != 1" % (name, n))

    out = src
    for name, a, r in ANCHORS:
        out = out.replace(a, r)

    # residual forbidden token check: no "2,500" article-length line may remain
    if "1,500\uc790\uc5d0\uc11c 2,500\uc790" in out:
        die("residual 2,500 length phrase remains")
    if "1,000\uc790\uc5d0\uc11c 1,600\uc790" in out:
        die("residual 1,600 length phrase remains")

    ts = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bdir = os.path.join(BACKUP_ROOT, "v72-prompt-" + ts)
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(target, os.path.join(bdir, os.path.basename(target)))
    print("backup     : " + os.path.join(bdir, os.path.basename(target)))

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".tmp")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.chmod(tmp, os.stat(target).st_mode & 0o7777)
    os.replace(tmp, target)

    post = sha256_file(target)
    print("post_sha256: " + post)
    print("post_bytes : %d" % os.path.getsize(target))
    with open(target, encoding="utf-8") as f:
        c = f.read()
    print("P-1 present: %s" % ("SOURCE THEMES \ud0dc\uadf8\ub9cc" in c))
    print("P-2 present: %s" % ("stock_radar \ud5c8\uc6a9 \uc720\ub2c8\ubc84\uc2a4" in c))
    print("P-3 ready  : %s" % ("1,500\uc790\uc5d0\uc11c 3,200\uc790" in c))
    print("P-3 base   : %s" % ("1,000\uc790\uc5d0\uc11c 1,800\uc790" in c))
    print("residual 2,500: %d (expect 0)" % c.count("1,500\uc790\uc5d0\uc11c 2,500\uc790"))
    print("ROLLBACK: cp %s %s"
          % (os.path.join(bdir, os.path.basename(target)), target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
