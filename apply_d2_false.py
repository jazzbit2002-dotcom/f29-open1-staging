#!/usr/bin/env python3
# apply_d2_false.py -- F29-D2-FALSE v1
# Scope: /var/www/f29/assets/f29-recent.js -- ONE line.
#   adds prev_visit_date to the same_stock:false branch so both branches
#   satisfy the D-2 contract (ledger 0-1: false branch value = most recent
#   record's last_visit_date, i.e. list[0].last_visit_date).
#
# Not changed: event name, same_stock predicate, date computation,
#              localStorage schema, metrics.js, chip rendering.
# No restart, no rebuild (static asset).
#
# Gates (abort on any failure):
#   G1 target path exact (override --file only for fixtures)
#   G2 --expect-sha REQUIRED for --apply; must match pre-image
#      (dry-run prints the value to pin)
#   G3 anchor count == 1
#   G4 marker count == 0
#   G5 diff shape: removed 1 / added 1
#   G6 node --check passes on the candidate BEFORE it replaces the target
#   G7 backup written and re-read byte-identical

import argparse, difflib, hashlib, os, shutil, stat, subprocess, sys, tempfile, time

TARGET = "/var/www/f29/assets/f29-recent.js"
MARKER = "F29-D2-FALSE"
ANCHOR = "F29M.track('next_day_return', { same_stock: false, code, ref: F29M.ref() });"
NEWLINE = ("F29M.track('next_day_return', { same_stock: false, code, "
           "prev_visit_date: list[0].last_visit_date, ref: F29M.ref() }); "
           "// F29-D2-FALSE v1")


def die(msg):
    print("ABORT: %s" % msg)
    sys.exit(2)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    with open(p, "rb") as f:
        return sha_bytes(f.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=TARGET)
    ap.add_argument("--expect-sha", default=None)
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
    pre = sha_bytes(raw)
    print("PRE  file        %s" % target)
    print("PRE  sha256      %s" % pre)
    print("PRE  bytes       %d" % len(raw))

    if a.apply and not a.expect_sha:
        die("G2 --expect-sha is required for --apply. Pin the PRE sha256 above.")
    if a.expect_sha and pre != a.expect_sha:
        die("G2 SHA mismatch -- expected %s" % a.expect_sha)

    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)

    n_marker = text.count(MARKER)
    hits = [i for i, ln in enumerate(lines) if ln.strip() == ANCHOR]
    print("PRE  anchor      %d  (line %s)"
          % (len(hits), ",".join(str(i + 1) for i in hits) or "-"))
    print("PRE  marker      %d" % n_marker)

    if n_marker != 0:
        die("G4 marker '%s' already present (%d)" % (MARKER, n_marker))
    if len(hits) != 1:
        die("G3 anchor count = %d (expected exactly 1)" % len(hits))

    i = hits[0]
    src = lines[i]
    indent = src[: len(src) - len(src.lstrip())]
    eol = "\r\n" if src.endswith("\r\n") else ("\n" if src.endswith("\n") else "")
    new_lines = list(lines)
    new_lines[i] = indent + NEWLINE + eol
    new_text = "".join(new_lines)

    diff = list(difflib.unified_diff(lines, new_lines,
                                     fromfile="a/f29-recent.js",
                                     tofile="b/f29-recent.js", n=3))
    added = [d for d in diff if d.startswith("+") and not d.startswith("+++")]
    removed = [d for d in diff if d.startswith("-") and not d.startswith("---")]

    print("\n--- DRY-RUN DIFF ---")
    sys.stdout.write("".join(diff))
    print("--- END DIFF ---")
    print("PLAN removed_lines %d" % len(removed))
    print("PLAN added_lines   %d" % len(added))

    if len(removed) != 1 or len(added) != 1:
        die("G5 unexpected diff shape (removed=%d added=%d, expected 1/1)"
            % (len(removed), len(added)))

    node = shutil.which("node")
    if node is None:
        die("G6 node not found in PATH")

    d = os.path.dirname(target)
    st = os.stat(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".d2false.", suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as t:
            t.write(new_text)
            t.flush()
            os.fsync(t.fileno())
        chk = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        if chk.returncode != 0:
            print(chk.stderr.strip()[:400])
            die("G6 node --check FAILED on candidate -- target untouched")
        print("G6 node --check   PASS (candidate)")
        cand = sha_file(tmp)
        cbytes = os.path.getsize(tmp)

        if not a.apply:
            os.unlink(tmp)
            print("\nCANDIDATE sha256 %s" % cand)
            print("CANDIDATE bytes  %d" % cbytes)
            print("\nDRY-RUN ONLY. Nothing written.")
            print("To apply:  --apply --expect-sha %s" % pre)
            return

        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = os.path.join(a.backup_root, "d2false-%s" % ts)
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, "f29-recent.js")
        shutil.copy2(target, bpath)
        if sha_file(bpath) != pre:
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
    ptext = post.decode("utf-8")
    print("POST sha256      %s" % sha_bytes(post))
    print("POST bytes       %d" % len(post))
    print("POST marker      %d" % ptext.count(MARKER))
    print("POST prev_field  %d" % ptext.count("prev_visit_date"))
    print("POST event_name  %d" % ptext.count("'next_day_return'"))
    print("\nROLLBACK: cp %s %s" % (bpath, target))
    print("NOTE: static asset. no restart, no rebuild. cache max-age=300.")


if __name__ == "__main__":
    main()
