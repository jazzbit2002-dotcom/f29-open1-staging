#!/usr/bin/env python3
# apply_hook_redact.py -- F29-HOOK-REDACT v1 (P0)
# Scope: /etc/nginx/nginx.conf ONLY. Single anchor. No generalized patcher.
#
# Change:
#   insert  map $request_uri $req_safe {...}  + log_format hookredact '...'
#   replace access_log /var/log/nginx/access.log;
#      ->   access_log /var/log/nginx/access.log hookredact;
#
# Gates (abort on any failure):
#   G1 target path is exactly /etc/nginx/nginx.conf (override with --file for fixtures)
#   G2 anchor line count == 1
#   G3 existing marker count == 0
#   G4 backup written and re-read byte-identical
#   G5 dry-run diff contains only the planned block + the one anchor line change
#
# Default mode is dry-run. Use --apply to write.
# Does NOT run nginx -t and does NOT reload. Operator does that separately.

import argparse, difflib, hashlib, os, shutil, stat, sys, tempfile, time

ANCHOR = "access_log /var/log/nginx/access.log;"
NEWLINE_TAIL = "access_log /var/log/nginx/access.log hookredact;"
MARKER = "F29-HOOK-REDACT"

BLOCK = """# --- F29-HOOK-REDACT v1 (2026-07-21) ---
# Masks the secret path segment of POST /hook/<SECRET> in access logs.
# Field layout is identical to the stock 'combined' format; only the
# request-URI portion is substituted when the URI starts with /hook/.
map $request_uri $req_safe {
    ~^/hook/   "/hook/[REDACTED]";
    default    $request_uri;
}
log_format hookredact '$remote_addr - $remote_user [$time_local] '
                      '"$request_method $req_safe $server_protocol" '
                      '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
# --- end F29-HOOK-REDACT v1 ---
"""


def die(msg):
    print("ABORT: %s" % msg)
    sys.exit(2)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_new(lines):
    hits = [i for i, ln in enumerate(lines) if ln.strip() == ANCHOR]
    if len(hits) != 1:
        die("G2 anchor count = %d (expected exactly 1)" % len(hits))
    i = hits[0]
    raw = lines[i]
    indent = raw[: len(raw) - len(raw.lstrip())]
    block = "".join(indent + b + "\n" for b in BLOCK.rstrip("\n").split("\n"))
    out = list(lines[:i])
    out.append(block)
    out.append(indent + NEWLINE_TAIL + "\n")
    out.extend(lines[i + 1:])
    return "".join(out), i + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="/etc/nginx/nginx.conf")
    ap.add_argument("--backup-root", default="/root/f29-backups")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-nonstandard-path", action="store_true")
    a = ap.parse_args()

    target = os.path.abspath(a.file)

    if target != "/etc/nginx/nginx.conf" and not a.allow_nonstandard_path:
        die("G1 target is %s (expected /etc/nginx/nginx.conf)" % target)
    if not os.path.isfile(target):
        die("G1 file not found: %s" % target)

    with open(target, "r") as f:
        original = f.read()
    lines = original.splitlines(keepends=True)

    n_marker = original.count(MARKER)
    if n_marker != 0:
        die("G3 marker '%s' already present (%d) -- already applied?" % (MARKER, n_marker))

    n_anchor = sum(1 for ln in lines if ln.strip() == ANCHOR)
    print("PRE  file        %s" % target)
    print("PRE  sha256      %s" % sha256(target))
    print("PRE  bytes       %d" % len(original.encode()))
    print("PRE  anchor      %d" % n_anchor)
    print("PRE  marker      %d" % n_marker)

    new_text, anchor_line = build_new(lines)

    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile="a/nginx.conf", tofile="b/nginx.conf", n=3))
    added = [d for d in diff if d.startswith("+") and not d.startswith("+++")]
    removed = [d for d in diff if d.startswith("-") and not d.startswith("---")]

    print("\n--- DRY-RUN DIFF ---")
    sys.stdout.write("".join(diff))
    print("--- END DIFF ---")
    print("PLAN added_lines   %d" % len(added))
    print("PLAN removed_lines %d" % len(removed))
    print("PLAN anchor_at     line %d" % anchor_line)

    expected_added = len(BLOCK.rstrip("\n").split("\n")) + 1
    if len(removed) != 1 or len(added) != expected_added:
        die("G5 unexpected diff shape (removed=%d expected 1, added=%d expected %d)"
            % (len(removed), len(added), expected_added))
    if removed[0].strip().lstrip("-").strip() != ANCHOR:
        die("G5 removed line is not the anchor")

    if not a.apply:
        print("\nDRY-RUN ONLY. Nothing written. Re-run with --apply to write.")
        return

    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    bdir = os.path.join(a.backup_root, "hookredact-%s" % ts)
    os.makedirs(bdir, exist_ok=True)
    bpath = os.path.join(bdir, "nginx.conf")
    shutil.copy2(target, bpath)
    if sha256(bpath) != sha256(target):
        die("G4 backup mismatch")
    st = os.stat(target)
    with open(os.path.join(bdir, "manifest.txt"), "w") as m:
        m.write("source      %s\n" % target)
        m.write("sha256      %s\n" % sha256(target))
        m.write("bytes       %d\n" % st.st_size)
        m.write("mode        %s\n" % oct(stat.S_IMODE(st.st_mode)))
        m.write("uid_gid     %d:%d\n" % (st.st_uid, st.st_gid))
        m.write("backed_up   %s\n" % ts)
    print("\nBACKUP  %s" % bpath)

    d = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".hookredact.")
    try:
        with os.fdopen(fd, "w") as t:
            t.write(new_text)
            t.flush()
            os.fsync(t.fileno())
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print("POST sha256      %s" % sha256(target))
    with open(target) as f:
        after = f.read()
    print("POST bytes       %d" % len(after.encode()))
    print("POST marker      %d" % after.count(MARKER))
    print("POST old_anchor  %d" % sum(1 for ln in after.splitlines() if ln.strip() == ANCHOR))
    print("POST new_anchor  %d" % sum(1 for ln in after.splitlines() if ln.strip() == NEWLINE_TAIL))
    print("\nROLLBACK: cp %s %s   then: nginx -t && systemctl reload nginx" % (bpath, target))
    print("NEXT: nginx -t   (do NOT restart)")


if __name__ == "__main__":
    main()
