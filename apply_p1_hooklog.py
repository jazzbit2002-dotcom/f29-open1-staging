#!/usr/bin/env python3
# apply_p1_hooklog.py -- F29-P1-HOOKLOG v1
# Scope: /root/f29/server.js -- ONE line only.
#   the startup log that prints the webhook secret is replaced by a
#   configured/missing indicator. No other log, route, auth or response
#   behaviour is touched. No pm2 restart is performed.
#
# Anchor is a predicate (line contains both console.log and HOOK_SECRET),
# not a literal, because the original line contains non-ASCII text and this
# script must stay pure ASCII.
#
# Gates (abort on any failure):
#   G1 target path exact (override --file only for fixtures)
#   G2 pre-image SHA-256 equals --expect-sha
#   G3 anchor line count == 1
#   G4 marker count == 0 (not already applied)
#   G5 diff shape: removed 1 / added 1
#   G6 node --check passes on the candidate BEFORE it replaces the target
#   G7 backup written and re-read byte-identical
#
# Default mode is dry-run. Use --apply to write.

import argparse, difflib, hashlib, os, shutil, stat, subprocess, sys, tempfile, time

TARGET = "/root/f29/server.js"
EXPECT_SHA = "cb752754277f3446220442026bf19e234d6c391631789a528dbffbc7d427c890"
MARKER = "F29-P1-HOOKLOG"
NEWLINE = ("console.log(HOOK_SECRET ? '[webhook] endpoint configured' : "
           "'[webhook] secret missing'); // F29-P1-HOOKLOG v1")


def die(msg):
    print("ABORT: %s" % msg)
    sys.exit(2)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    with open(p, "rb") as f:
        return sha256_bytes(f.read())


def is_anchor(line):
    return ("console.log" in line) and ("HOOK_SECRET" in line)


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
    pre_sha = sha256_bytes(raw)
    print("PRE  file        %s" % target)
    print("PRE  sha256      %s" % pre_sha)
    print("PRE  bytes       %d" % len(raw))

    if a.expect_sha and pre_sha != a.expect_sha:
        die("G2 SHA mismatch -- file changed since baseline. expected %s" % a.expect_sha)

    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)

    n_marker = text.count(MARKER)
    hits = [i for i, ln in enumerate(lines) if is_anchor(ln)]
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
                                     fromfile="a/server.js", tofile="b/server.js", n=2))
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
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".p1hooklog.", suffix=".js")
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
        cand_sha = sha256_file(tmp)
        cand_bytes = os.path.getsize(tmp)

        if not a.apply:
            os.unlink(tmp)
            print("\nCANDIDATE sha256 %s" % cand_sha)
            print("CANDIDATE bytes  %d" % cand_bytes)
            print("\nDRY-RUN ONLY. Nothing written. Re-run with --apply to write.")
            return

        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = os.path.join(a.backup_root, "p1hooklog-%s" % ts)
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, "server.js")
        shutil.copy2(target, bpath)
        if sha256_file(bpath) != pre_sha:
            os.unlink(tmp)
            die("G7 backup mismatch")
        with open(os.path.join(bdir, "manifest.txt"), "w") as m:
            m.write("source      %s\n" % target)
            m.write("sha256      %s\n" % pre_sha)
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
    print("POST sha256      %s" % sha256_bytes(post))
    print("POST bytes       %d" % len(post))
    print("POST marker      %d" % ptext.count(MARKER))
    print("POST anchor_old  %d" % sum(1 for ln in ptext.splitlines() if is_anchor(ln)
                                      and MARKER not in ln))
    print("\nROLLBACK: cp %s %s" % (bpath, target))
    print("NOTE: pm2 NOT restarted. runtime activation = PENDING_RESTART")


if __name__ == "__main__":
    main()
