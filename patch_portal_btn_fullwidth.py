#!/usr/bin/env python3
# patch_portal_btn_fullwidth.py -- F29 portal: force search button full-width on
# mobile so it sits on its own row BELOW the input (instead of wrapping to a short
# left-aligned box). Adds ONE media rule; does not touch the input basis, markup,
# search logic, or f29-search.js.
#
# Why flex-basis:100% (not another basis tweak): with flex-wrap:wrap already on,
# a 100% flex-basis guarantees the button occupies its own line at full width,
# independent of viewport/content width estimation. Deterministic.
#
# Pure ASCII source; ASCII-only anchor -> Korean bytes untouched. Literal anchor
# str.replace + count gate + SHA gate + dup guard + backup (non-public) + atomic
# write + post gates. HTML: no node --check (per handoff); CSS-block grep instead.
import os
import sys
import hashlib
import tempfile
import datetime

TARGET = '/var/www/f29-portal/index.html'
BACKUP_BASE = '/root/f29-backups'
EXPECT_SHA = '06459ef13381fb3619b83d1139a517b8774d41294631a8def6ac4898080d5bfb'
EXPECT_SIZE = 31800

ANCHOR_OLD = ('  @media (max-width:390px){#stockSearchWrap{max-width:100%}'
              '#f29-search-results{max-width:100%}}')
NEW_RULE = '  @media (max-width:480px){#searchBtn{flex:1 1 100%}}'
ANCHOR_NEW = ANCHOR_OLD + '\n' + NEW_RULE


def die(msg):
    print('[portal2][ABORT] %s' % msg, file=sys.stderr)
    print('[portal2][ABORT] source NOT modified.', file=sys.stderr)
    sys.exit(1)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.isfile(TARGET):
        die('target not found: %s' % TARGET)
    raw_before = open(TARGET, 'rb').read()
    src = raw_before.decode('utf-8')
    print('[portal2] target       = %s' % TARGET)
    print('[portal2] before sha   = %s' % sha(raw_before))
    print('[portal2] before bytes = %d' % len(raw_before))

    if sha(raw_before) != EXPECT_SHA:
        die('SHA MISMATCH expected %s got %s' % (EXPECT_SHA, sha(raw_before)))
    if len(raw_before) != EXPECT_SIZE:
        die('SIZE MISMATCH expected %d got %d' % (EXPECT_SIZE, len(raw_before)))
    print('[portal2] SHA gate PASS')

    # dup guard before anchor gate
    if 'max-width:480px){#searchBtn{flex:1 1 100%}' in src:
        die('already applied: 480px button-fullwidth rule present')

    n = src.count(ANCHOR_OLD)
    if n != 1:
        die('anchor count = %d (expected exactly 1)' % n)
    # do not accidentally already have a 480 media block for searchBtn
    if src.count('@media (max-width:480px)') != 0:
        die('unexpected existing 480px media block(s): %d -- investigate'
            % src.count('@media (max-width:480px)'))
    print('[portal2] anchor count = 1  (append 480px button rule after 390px block)')

    out = src.replace(ANCHOR_OLD, ANCHOR_NEW, 1)

    expected_delta = len(('\n' + NEW_RULE).encode('utf-8'))
    checks = [
        ('new rule present == 1', out.count('@media (max-width:480px){#searchBtn{flex:1 1 100%}}') == 1),
        ('390px block intact == 1', out.count(ANCHOR_OLD) == 1),
        ('base searchBtn rule intact (PC side-by-side)', out.count('#searchBtn{flex:0 0 auto;') == 1),
        ('input basis 160 untouched', out.count('#stockSearch{flex:1 1 160px;') == 1),
        ('wrap rule intact', out.count('#stockSearchWrap{position:relative;display:flex;flex-wrap:wrap;') == 1),
        ('input markup intact', out.count('<input id="stockSearch"') == 1),
        ('button markup intact', out.count('<button id="searchBtn"') == 1),
        ('router wiring intact', out.count('/assets/f29-search.js?v=20260713c') == 1),
        ('byte delta == +new rule', len(out.encode('utf-8')) == len(raw_before) + expected_delta),
        ('exactly one 480px media block', out.count('@media (max-width:480px)') == 1),
    ]
    for name, ok in checks:
        if not ok:
            die('post-check FAIL: %s' % name)
    print('[portal2] post-check gates PASS (%d checks)' % len(checks))

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_BASE, 'portal-btnfull-%s' % ts)
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, 'index.html')
    with open(bak, 'wb') as f:
        f.write(raw_before)
    st = os.stat(TARGET)
    with open(os.path.join(bdir, 'manifest.txt'), 'w') as f:
        f.write('orig_path=%s\nowner_uid=%d\nmode=%o\nsize=%d\nsha256_before=%s\n'
                % (TARGET, st.st_uid, st.st_mode & 0o7777, len(raw_before), sha(raw_before)))
    print('[portal2] backup       = %s' % bak)

    d = os.path.dirname(os.path.abspath(TARGET))
    mode = os.stat(TARGET).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, 'wb') as f:
        f.write(out.encode('utf-8'))
    os.chmod(tmp, mode)
    os.replace(tmp, TARGET)

    raw_after = open(TARGET, 'rb').read()
    print('[portal2] after sha    = %s' % sha(raw_after))
    print('[portal2] after bytes  = %d' % len(raw_after))
    print('[portal2] OK  rollback: cp %s %s' % (bak, TARGET))


if __name__ == '__main__':
    main()
