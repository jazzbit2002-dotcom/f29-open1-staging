#!/usr/bin/env python3
# patch_portal_search_basis.py -- F29 portal mobile search-button wrap fix.
# Single CSS value change: #stockSearch flex-basis 220px -> 160px, so on
# ~360-420px phones the input + button stay on one row (button no longer wraps
# to a new line / left-aligns). No markup, no search logic, no f29-search.js change.
#
# Pure ASCII source; the anchor is ASCII-only so Korean bytes in the target are
# untouched. Literal anchor str.replace + count gate (exactly 1) + SHA gate +
# dup guard + backup (non-public) + atomic write + post gates. HTML: no node --check
# (per handoff rule); integrity verified by CSS-block grep instead.
import os
import sys
import hashlib
import tempfile
import datetime

TARGET = '/var/www/f29-portal/index.html'
BACKUP_BASE = '/root/f29-backups'
EXPECT_SHA = '5b2fa2feac336309f5f4946e25739010237a00be91f69b0c8a1deb5ca11ab803'
EXPECT_SIZE = 31800

ANCHOR_OLD = '#stockSearch{flex:1 1 220px;'
ANCHOR_NEW = '#stockSearch{flex:1 1 160px;'


def die(msg):
    print('[portal][ABORT] %s' % msg, file=sys.stderr)
    print('[portal][ABORT] source NOT modified.', file=sys.stderr)
    sys.exit(1)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.isfile(TARGET):
        die('target not found: %s' % TARGET)
    raw_before = open(TARGET, 'rb').read()
    src = raw_before.decode('utf-8')
    print('[portal] target       = %s' % TARGET)
    print('[portal] before sha   = %s' % sha(raw_before))
    print('[portal] before bytes = %d' % len(raw_before))

    if sha(raw_before) != EXPECT_SHA:
        die('SHA MISMATCH expected %s got %s -- file changed, investigate'
            % (EXPECT_SHA, sha(raw_before)))
    if len(raw_before) != EXPECT_SIZE:
        die('SIZE MISMATCH expected %d got %d' % (EXPECT_SIZE, len(raw_before)))
    print('[portal] SHA gate PASS')

    # dup guard before anchor gate
    if ANCHOR_NEW in src:
        die('already applied: 160px basis present')

    # anchor uniqueness
    n = src.count(ANCHOR_OLD)
    if n != 1:
        die('anchor count = %d (expected exactly 1)' % n)
    # safety: full 220px token must be exactly this one occurrence
    if src.count('flex:1 1 220px') != 1:
        die('flex:1 1 220px appears %d times (expected 1) -- shape changed'
            % src.count('flex:1 1 220px'))
    print('[portal] anchor count = 1  (#stockSearch flex-basis 220px -> 160px)')

    out = src.replace(ANCHOR_OLD, ANCHOR_NEW, 1)

    # ---- post-transform gates ----
    checks = [
        ('new basis present == 1', out.count('#stockSearch{flex:1 1 160px;') == 1),
        ('old basis gone', out.count('#stockSearch{flex:1 1 220px;') == 0),
        ('no stray 220px basis', out.count('flex:1 1 220px') == 0),
        ('searchBtn rule intact', out.count('#searchBtn{flex:0 0 auto;') == 1),
        ('wrap rule intact', out.count('#stockSearchWrap{position:relative;display:flex;flex-wrap:wrap;') == 1),
        ('router container intact', out.count('#f29-search-results{position:absolute;') == 1),
        ('router wiring intact', out.count('/assets/f29-search.js?v=20260713c') == 1),
        ('input markup intact', out.count('<input id="stockSearch"') == 1),
        ('button markup intact', out.count('<button id="searchBtn"') == 1),
        ('byte delta == 0 (220 vs 160 same length)', len(out.encode('utf-8')) == len(raw_before)),
    ]
    for name, ok in checks:
        if not ok:
            die('post-check FAIL: %s' % name)
    print('[portal] post-check gates PASS (%d checks)' % len(checks))

    # ---- backup (non-public) ----
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_BASE, 'portal-searchbasis-%s' % ts)
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, 'index.html')
    with open(bak, 'wb') as f:
        f.write(raw_before)
    st = os.stat(TARGET)
    with open(os.path.join(bdir, 'manifest.txt'), 'w') as f:
        f.write('orig_path=%s\nowner_uid=%d\nmode=%o\nsize=%d\nsha256_before=%s\n'
                % (TARGET, st.st_uid, st.st_mode & 0o7777, len(raw_before), sha(raw_before)))
    print('[portal] backup       = %s' % bak)

    # ---- atomic write ----
    d = os.path.dirname(os.path.abspath(TARGET))
    mode = os.stat(TARGET).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, 'wb') as f:
        f.write(out.encode('utf-8'))
    os.chmod(tmp, mode)
    os.replace(tmp, TARGET)

    raw_after = open(TARGET, 'rb').read()
    print('[portal] after sha    = %s' % sha(raw_after))
    print('[portal] after bytes  = %d' % len(raw_after))
    print('[portal] OK  rollback: cp %s %s' % (bak, TARGET))


if __name__ == '__main__':
    main()
