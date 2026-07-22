#!/usr/bin/env python3
# apply_us_minbars.py -- F29-US-MINBARS v1
# Scope: /root/moneyflow/build_us_stock_pages.py -- TWO functions only.
#   (1) load_pattern_judgments(): stop discarding rows whose top1 is null
#       when status == "insufficient_bars". Without this the entry never
#       reaches card_pattern() and any card-side patch is a no-op.
#   (2) card_pattern(): render the approved "preparing" card for those rows.
#
# Numbers come from the judgment entry, never hardcoded:
#   current sessions   -> bars
#   required sessions  -> min_bars_required
# Render only when ALL hold (bool is excluded explicitly: bool subclasses int):
#   status == "insufficient_bars"
#   isinstance(bars, int) and not isinstance(bars, bool)
#   isinstance(required, int) and not isinstance(required, bool)
#   bars >= 0 and required > 0 and bars < required
# Otherwise return None (existing non-render behaviour).
#
# Unchanged: top1 dict render path, other statuses, pattern logic,
#            Pattern Lab files, US P1 chart code, cron/nginx/pm2.
#
# Gates (abort on any failure):
#   G1 target path exact       G2 pre SHA == --expect-sha
#   G3 each anchor count == 1  G4 marker count == 0
#   G5 diff shape exact        G6 py_compile on candidate BEFORE replace
#   G7 backup re-read identical
# Default mode is dry-run. Use --apply to write. Pure ASCII source.

import argparse, difflib, hashlib, os, py_compile, shutil, stat, sys, tempfile, time

TARGET = "/root/moneyflow/build_us_stock_pages.py"
EXPECT_SHA = "13c0c9fd116eafb835c6ba38b9b2085c0f81c80d5009fd550152d3880fda8b50"
MARKER = "F29-US-MINBARS"

KO_TITLE = "\ucc28\ud2b8 \ud615\ud0dc"
KO_L1 = "\ucc28\ud2b8 \ud615\ud0dc \ud310\uc815\uc744 \uc900\ube44 \uc911\uc785\ub2c8\ub2e4. "
KO_L2A = "\ud604\uc7ac "
KO_L2B = "\uac70\ub798\uc77c\uc774\uba70 "
KO_L2C = "\uac70\ub798\uc77c\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."

A1_OLD = "if t and isinstance(r.get('top1'), dict):"
A1_NEW = ("if t and (isinstance(r.get('top1'), dict)"
          " or r.get('status') == 'insufficient_bars'):  # F29-US-MINBARS v1")

A2 = "t1 = r.get('top1') or {}"

A2_BLOCK = [
    "if r.get('status') == 'insufficient_bars':  # F29-US-MINBARS v1",
    "    _b = r.get('bars')",
    "    _m = r.get('min_bars_required')",
    "    if (isinstance(_b, int) and not isinstance(_b, bool)",
    "            and isinstance(_m, int) and not isinstance(_m, bool)",
    "            and _b >= 0 and _m > 0 and _b < _m):",
    "        return (f'<section class=\"card\"><h2>\ucc28\ud2b8 \ud615\ud0dc</h2>'",
    "                f'<p class=\"hint\">\ucc28\ud2b8 \ud615\ud0dc \ud310\uc815\uc744 \uc900\ube44 \uc911\uc785\ub2c8\ub2e4. '",
    "                f'\ud604\uc7ac {esc(_b)}\uac70\ub798\uc77c\uc774\uba70 {esc(_m)}\uac70\ub798\uc77c\uc774 \ud544\uc694\ud569\ub2c8\ub2e4.</p>'",
    "                f'</section>')",
    "    return None",
]


def die(msg):
    print("ABORT: %s" % msg)
    sys.exit(2)


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def sha_f(p):
    with open(p, "rb") as f:
        return sha_b(f.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=TARGET)
    ap.add_argument("--expect-sha", default=EXPECT_SHA)
    ap.add_argument("--backup-root", default="/root/f29-backups")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-nonstandard-path", action="store_true")
    a = ap.parse_args()

    target = os.path.abspath(a.file)
    if target != TARGET and not a.allow_nonstandard_path:
        die("G1 target is %s (expected %s)" % (target, TARGET))
    if not os.path.isfile(target):
        die("G1 file not found: %s" % target)

    with open(target, "rb") as f:
        raw = f.read()
    pre = sha_b(raw)
    print("PRE  file        %s" % target)
    print("PRE  sha256      %s" % pre)
    print("PRE  bytes       %d" % len(raw))

    if a.expect_sha and pre != a.expect_sha:
        die("G2 SHA mismatch -- expected %s" % a.expect_sha)

    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)

    if text.count(MARKER) != 0:
        die("G4 marker '%s' already present (%d)" % (MARKER, text.count(MARKER)))

    h1 = [i for i, ln in enumerate(lines) if ln.strip() == A1_OLD]
    h2 = [i for i, ln in enumerate(lines) if ln.strip() == A2]
    print("PRE  anchor1     %d  (line %s)" % (len(h1), ",".join(str(i + 1) for i in h1) or "-"))
    print("PRE  anchor2     %d  (line %s)" % (len(h2), ",".join(str(i + 1) for i in h2) or "-"))
    if len(h1) != 1:
        die("G3 anchor1 count = %d (expected 1)" % len(h1))
    if len(h2) != 1:
        die("G3 anchor2 count = %d (expected 1)" % len(h2))

    new_lines = list(lines)

    i2 = h2[0]
    src2 = new_lines[i2]
    ind2 = src2[: len(src2) - len(src2.lstrip())]
    eol2 = "\r\n" if src2.endswith("\r\n") else "\n"
    block = [ind2 + b + eol2 for b in A2_BLOCK]
    new_lines[i2:i2 + 1] = block + [src2]

    i1 = h1[0]
    src1 = new_lines[i1]
    ind1 = src1[: len(src1) - len(src1.lstrip())]
    eol1 = "\r\n" if src1.endswith("\r\n") else "\n"
    new_lines[i1] = ind1 + A1_NEW + eol1

    new_text = "".join(new_lines)

    diff = list(difflib.unified_diff(lines, new_lines,
                                     fromfile="a/build_us_stock_pages.py",
                                     tofile="b/build_us_stock_pages.py", n=3))
    added = [d for d in diff if d.startswith("+") and not d.startswith("+++")]
    removed = [d for d in diff if d.startswith("-") and not d.startswith("---")]

    print("\n--- DRY-RUN DIFF ---")
    sys.stdout.write("".join(diff))
    print("--- END DIFF ---")
    print("PLAN removed_lines %d" % len(removed))
    print("PLAN added_lines   %d" % len(added))

    exp_add = 1 + len(A2_BLOCK)
    if len(removed) != 1 or len(added) != exp_add:
        die("G5 unexpected diff shape (removed=%d expected 1, added=%d expected %d)"
            % (len(removed), len(added), exp_add))

    d = os.path.dirname(target)
    st = os.stat(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".usminbars.", suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as t:
            t.write(new_text)
            t.flush()
            os.fsync(t.fileno())
        try:
            py_compile.compile(tmp, cfile=tmp + "c", doraise=True)
            print("G6 py_compile     PASS (candidate)")
        except py_compile.PyCompileError as e:
            print(str(e)[:400])
            die("G6 py_compile FAILED on candidate -- target untouched")
        finally:
            if os.path.exists(tmp + "c"):
                os.unlink(tmp + "c")

        cand = sha_f(tmp)
        cbytes = os.path.getsize(tmp)

        if not a.apply:
            os.unlink(tmp)
            print("\nCANDIDATE sha256 %s" % cand)
            print("CANDIDATE bytes  %d" % cbytes)
            print("\nDRY-RUN ONLY. Nothing written. Re-run with --apply to write.")
            return

        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = os.path.join(a.backup_root, "usminbars-%s" % ts)
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, "build_us_stock_pages.py")
        shutil.copy2(target, bpath)
        if sha_f(bpath) != pre:
            os.unlink(tmp)
            die("G7 backup mismatch")
        with open(os.path.join(bdir, "manifest.txt"), "w") as m:
            m.write("source      %s\n" % target)
            m.write("sha256      %s\n" % pre)
            m.write("bytes       %d\n" % len(raw))
            m.write("mode        %s\n" % oct(stat.S_IMODE(st.st_mode)))
            m.write("uid_gid     %d:%d\n" % (st.st_uid, st.st_gid))
            m.write("backed_up   %s\n" % ts)
        print("\nBACKUP  %s" % bpath)

        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    post = open(target, "rb").read()
    pt = post.decode("utf-8")
    print("POST sha256      %s" % sha_b(post))
    print("POST bytes       %d" % len(post))
    print("POST marker      %d" % pt.count(MARKER))
    print("POST old_anchor1 %d" % sum(1 for ln in pt.splitlines() if ln.strip() == A1_OLD))
    print("POST min_bars_ref %d" % pt.count("min_bars_required"))
    print("\nROLLBACK: cp %s %s" % (bpath, target))
    print("NEXT: rebuild once, then verify SPCX and one 60-bar ticker.")


if __name__ == "__main__":
    main()
