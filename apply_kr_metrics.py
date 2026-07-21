#!/usr/bin/env python3
# apply_kr_metrics.py -- F29-KR-METRICS v1
# Scope: /root/krx-moneyflow/build_stock_pages.py -- ONE insertion.
#   adds f29-metrics.js + f29-recent.js loads and a single
#   F29Recent.record() call to the generated KR stock page head.
#   No judgment logic, no data, no card structure, no cron, no portal.
#
# The anchor line lives inside an f''' block, so every literal JS brace in
# the inserted text is doubled. Values are injected with json.dumps so the
# stock name becomes a valid JS string literal (html.escape would emit
# &#39; which does not decode inside <script>).
#
# Gates (abort on any failure):
#   G1 target path exact (override --file only for fixtures)
#   G2 pre-image SHA-256 equals --expect-sha
#   G3 anchor count == 1
#   G4 marker count == 0
#   G5 diff shape: removed 0 / added 3
#   G6 py_compile passes on the candidate BEFORE it replaces the target
#   G7 backup written and re-read byte-identical
#
# Default mode is dry-run. Use --apply to write.

import argparse, difflib, hashlib, os, py_compile, shutil, stat, sys, tempfile, time

TARGET = "/root/krx-moneyflow/build_stock_pages.py"
EXPECT_SHA = "fc7a6db5dd033899a2cab4106f0419eb07a3422118045902e29bd22eaca713a4"
MARKER = "F29-KR-METRICS"
ANCHOR = '<script src="/shared/f29-chrome.js?v=20260709b" data-active="" defer></script>'

INSERT_LINES = [
    '<script src="/assets/f29-metrics.js" defer></script>\n',
    '<script src="/assets/f29-recent.js" defer></script>\n',
    ("<script>document.addEventListener('DOMContentLoaded',function(){{"
     "if(window.F29Recent)F29Recent.record("
     '{json.dumps(code)},{json.dumps(name).replace("<","\\\\u003c")},'
     "'full');}});</script>  <!-- F29-KR-METRICS v1 -->\n"),
]


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
    pre = sha_bytes(raw)
    print("PRE  file        %s" % target)
    print("PRE  sha256      %s" % pre)
    print("PRE  bytes       %d" % len(raw))

    if a.expect_sha and pre != a.expect_sha:
        die("G2 SHA mismatch -- file changed since baseline. expected %s" % a.expect_sha)

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
    new_lines = list(lines)
    new_lines[i + 1:i + 1] = INSERT_LINES
    new_text = "".join(new_lines)

    diff = list(difflib.unified_diff(lines, new_lines,
                                     fromfile="a/build_stock_pages.py",
                                     tofile="b/build_stock_pages.py", n=2))
    added = [d for d in diff if d.startswith("+") and not d.startswith("+++")]
    removed = [d for d in diff if d.startswith("-") and not d.startswith("---")]

    print("\n--- DRY-RUN DIFF ---")
    sys.stdout.write("".join(diff))
    print("--- END DIFF ---")
    print("PLAN removed_lines %d" % len(removed))
    print("PLAN added_lines   %d" % len(added))

    if len(removed) != 0 or len(added) != 3:
        die("G5 unexpected diff shape (removed=%d added=%d, expected 0/3)"
            % (len(removed), len(added)))

    d = os.path.dirname(target)
    st = os.stat(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".krmetrics.", suffix=".py")
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

        cand = sha_file(tmp)
        cbytes = os.path.getsize(tmp)

        if not a.apply:
            os.unlink(tmp)
            print("\nCANDIDATE sha256 %s" % cand)
            print("CANDIDATE bytes  %d" % cbytes)
            print("\nDRY-RUN ONLY. Nothing written. Re-run with --apply to write.")
            return

        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = os.path.join(a.backup_root, "krmetrics-%s" % ts)
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, "build_stock_pages.py")
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
    print("POST metrics_ref %d" % ptext.count("f29-metrics.js"))
    print("POST recent_ref  %d" % ptext.count("f29-recent.js"))
    print("POST record_call %d" % ptext.count("F29Recent.record("))
    print("\nROLLBACK: cp %s %s" % (bpath, target))
    print("NEXT: rebuild once, then verify one generated page.")


if __name__ == "__main__":
    main()
