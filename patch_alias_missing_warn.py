#!/usr/bin/env python3
# patch_alias_missing_warn.py
# F29 D5 : build_search_index.py  alias hard-fail -> WARN demotion.
# Scope: 3 anchors only. No schema change, no new JSON field, no OK-log change.
# Pure ASCII source. Korean WARN text injected as \uXXXX escapes.
import hashlib
import os
import py_compile
import sys
import tempfile
import datetime

TARGET = '/root/krx-moneyflow/build_search_index.py'
BACKUP_DIR = '/root/f29-backups/d5idx-20260714'


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

# ------------------------------------------- duplicate-application guard
# (runs BEFORE anchor gates so a re-run reports "already applied",
#  not a false "anchor missing" alarm)
if 'ALIAS_MISSING' in src:
    die('already applied: ALIAS_MISSING marker present')
if '- len(missing)' in src:
    die('already applied: alias assert already corrected')

# -------------------------------------------------- anchor A (ASCII lit)
A_OLD = "            missing.append('%s->%s' % (alias, code))\n"
A_NEW = ("            missing.append('%s->%s' % (alias, code))\n"
         "            continue\n")
n_a = src.count(A_OLD)
if n_a != 1:
    die('anchor A count = %d (expected exactly 1)' % n_a)
print('[patch] anchor A count = 1  (missing.append -> +continue)')

# -------------------------------------------------- anchor C (ASCII lit)
C_OLD = "assert len(out['aliases']) == len(aliases),"
C_NEW = "assert len(out['aliases']) == len(aliases) - len(missing),"
n_c = src.count(C_OLD)
if n_c != 1:
    die('anchor C count = %d (expected exactly 1)' % n_c)
print('[patch] anchor C count = 1  (alias self-check corrected)')

# ------------------------------- anchor B (structural: target line has CJK)
lines = src.split('\n')
b_hits = [i for i, ln in enumerate(lines)
          if ln.strip() == 'if missing:' and not ln.strip().startswith('#')]
if len(b_hits) != 1:
    die('anchor B count = %d (expected exactly 1)' % len(b_hits))
bi = b_hits[0]
if bi + 1 >= len(lines):
    die('anchor B: no line after "if missing:"')
nxt = lines[bi + 1]
if 'fail(' not in nxt or 'missing' not in nxt:
    die('anchor B: next line is not the fail() call -> %r' % nxt)
indent = lines[bi][:len(lines[bi]) - len(lines[bi].lstrip())]
print('[patch] anchor B count = 1  (line %d: fail -> WARN)' % (bi + 1))

# Korean via escapes so this patch script stays pure ASCII:
#   \uac74 = KUN(count), \uc81c\uc678 = EXCLUDED
WARN_LIT = r"'[search_index][WARN][ALIAS_MISSING] %d\uac74 \uc81c\uc678: %s'"
b_new = [
    indent + 'if missing:',
    indent + '    print(' + WARN_LIT + ' % (len(missing), missing),',
    indent + '          file=sys.stderr)',
]

# ------------------------------------------------------------- transform
out_lines = lines[:bi] + b_new + lines[bi + 2:]
out = '\n'.join(out_lines)
out = out.replace(A_OLD, A_NEW, 1)
out = out.replace(C_OLD, C_NEW, 1)

# ------------------------------------------------------- post-transform gates
if out.count('            continue\n') != 1:
    die('post-check: continue count != 1')
if out.count('ALIAS_MISSING') != 1:
    die('post-check: ALIAS_MISSING count != 1')
if out.count('- len(missing)') != 1:
    die('post-check: corrected assert count != 1')
if out.count('fail(') != src.count('fail(') - 1:
    die('post-check: fail() count delta != -1 (other hard-fails must survive)')
for keep in ("os.replace(tmp, a.out)",
             "tempfile.mkstemp(dir=d)",
             "open_codes = set(src) & land",
             "b1 += 1; fail("):
    if keep not in out:
        die('post-check: protected construct lost -> %s' % keep)
try:
    compile(out, TARGET, 'exec')
except SyntaxError as e:
    die('post-check: syntax error -> %s' % e)
print('[patch] post-check gates PASS')

# ----------------------------------------------------------------- backup
os.makedirs(BACKUP_DIR, exist_ok=True)
bak = os.path.join(BACKUP_DIR, 'build_search_index.py.bak')
if os.path.exists(bak):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bak = os.path.join(BACKUP_DIR, 'build_search_index.py.bak.%s' % ts)
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
