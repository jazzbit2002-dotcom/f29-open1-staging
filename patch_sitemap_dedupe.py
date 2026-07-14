#!/usr/bin/env python3
# patch_sitemap_dedupe.py
# F29 D7 prep : remove duplicate '/index.html' from STATIC_URLS (sitemap only).
# LOCK EXEMPTION: build_stock_pages.py is D4 FINAL LOCK. This is a scoped
# exemption for a single SEO-canonicalization defect (duplicate sitemap URL),
# unrelated to any calculation contract. NAV list ('/index.html' as the
# Bitcoin-risk-index nav href) is a DIFFERENT list and is NOT touched.
import hashlib
import os
import py_compile
import sys
import tempfile
import datetime

TARGET = '/root/krx-moneyflow/build_stock_pages.py'
BACKUP_DIR = '/root/f29-backups'
EXPECT_SHA = 'b8fa92ec406d3d0d383581ce1837943bcbc235cf850fbdcdc5ee177c890f3612'
EXPECT_SIZE = 65027

MARKER = '# F29-D7-SITEMAP-DEDUPE v1'


def die(msg):
    print('[patch][ABORT] %s' % msg, file=sys.stderr)
    print('[patch][ABORT] source NOT modified.', file=sys.stderr)
    sys.exit(1)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- read
if not os.path.isfile(TARGET):
    die('target not found: %s' % TARGET)

raw_before = open(TARGET, 'rb').read()
src = raw_before.decode('utf-8')

print('[patch] target       = %s' % TARGET)
print('[patch] before sha   = %s' % sha_bytes(raw_before))
print('[patch] before bytes = %d' % len(raw_before))

# --------------------------------------------------------------- SHA gate
if sha_bytes(raw_before) != EXPECT_SHA:
    die('SHA MISMATCH: expected %s, got %s -- file changed since D4 LOCK, '
        'investigate before patching' % (EXPECT_SHA, sha_bytes(raw_before)))
if len(raw_before) != EXPECT_SIZE:
    die('SIZE MISMATCH: expected %d, got %d' % (EXPECT_SIZE, len(raw_before)))
print('[patch] SHA gate PASS (matches D4 FINAL LOCK)')

# ------------------------------------------- duplicate-application guard
# (checked BEFORE anchor gates: a re-run reports "already applied", not a
#  false "anchor missing" alarm)
if MARKER in src:
    die('already applied: %s marker present' % MARKER)

# -------------------------------------------------- anchor (ASCII literal)
# This substring is unique to the STATIC_URLS definition line. The NAV
# list's '/index.html' entry has different surrounding text
# ("...'\uc704\ud5d8\uc9c0\uc218','/index.html')...") and will NOT match.
ANCHOR_OLD = "'/', '/index.html', '/kr-moneyflow'"
ANCHOR_NEW = "'/', '/kr-moneyflow'"

n = src.count(ANCHOR_OLD)
if n != 1:
    die('anchor count = %d (expected exactly 1)' % n)
print("[patch] anchor count = 1  (STATIC_URLS: dropping '/index.html')")

# guard: make sure we are not about to touch the NAV list by accident
if src.count("'/index.html'") != 2:
    die("safety check failed: expected exactly 2 occurrences of '/index.html' "
        "in source (1 STATIC_URLS + 1 NAV), found %d -- source shape changed, "
        "refusing to guess" % src.count("'/index.html'"))
print('[patch] pre-check: 2 total /index.html occurrences confirmed '
      '(1 STATIC_URLS + 1 NAV)')

# ------------------------------------------------------------- transform
out = src.replace(ANCHOR_OLD, ANCHOR_NEW, 1)
out = MARKER + '\n' + out

# ------------------------------------------------------- post-transform gates
if out.count("'/index.html'") != 1:
    die('post-check: /index.html occurrences != 1 (NAV entry must survive, '
        'STATIC_URLS entry must be gone) -- got %d'
        % out.count("'/index.html'"))
if MARKER not in out:
    die('post-check: marker missing after transform')
if out.count(MARKER) != 1:
    die('post-check: marker duplicated')
if "STATIC_URLS = ['/', '/kr-moneyflow', '/weight', '/moneyflow'," not in out:
    die('post-check: STATIC_URLS transformed line not found in expected shape')
if "write_atomic(SITEMAP, '\\n'.join(lines))" not in out:
    die('post-check: sitemap write_atomic call lost -- protected construct missing')
if "'/lab/', '/lab/match.html', '/precheck/', '/precheck/full/']" not in out:
    die('post-check: STATIC_URLS tail entries lost')

try:
    compile(out, TARGET, 'exec')
except SyntaxError as e:
    die('post-check: syntax error -> %s' % e)
print('[patch] post-check gates PASS')

# ----------------------------------------------------------------- backup
os.makedirs(BACKUP_DIR, exist_ok=True)
bak_dir = os.path.join(BACKUP_DIR, 'd7sitemap-20260715')
os.makedirs(bak_dir, exist_ok=True)
bak = os.path.join(bak_dir, 'build_stock_pages.py.bak')
if os.path.exists(bak):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bak = os.path.join(bak_dir, 'build_stock_pages.py.bak.%s' % ts)
with open(bak, 'wb') as f:
    f.write(raw_before)
print('[patch] backup       = %s' % bak)

# ------------------------------------------------------- atomic write
d = os.path.dirname(os.path.abspath(TARGET))
mode = os.stat(TARGET).st_mode & 0o7777
fd, tmp = tempfile.mkstemp(dir=d)
with os.fdopen(fd, 'wb') as f:
    f.write(out.encode('utf-8'))
os.chmod(tmp, mode)
try:
    py_compile.compile(tmp, cfile=tmp + 'c', doraise=True)
except py_compile.PyCompileError as e:
    os.unlink(tmp)
    die('py_compile FAIL -> %s' % e)
if os.path.exists(tmp + 'c'):
    os.unlink(tmp + 'c')
os.replace(tmp, TARGET)

raw_after = open(TARGET, 'rb').read()
print('[patch] after sha    = %s' % sha_bytes(raw_after))
print('[patch] after bytes  = %d' % len(raw_after))
print('[patch] OK  rollback: cp %s %s' % (bak, TARGET))
print('[patch] NOTE: this changes build_stock_pages.py -- the D4 LOCK SHA')
print('[patch] NOTE: reference (%s) is now SUPERSEDED. Record the new SHA'
      % EXPECT_SHA)
print('[patch] NOTE: as the current LOCK baseline in the next handoff.')
