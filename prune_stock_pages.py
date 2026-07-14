#!/usr/bin/env python3
"""prune_stock_pages.py -- F29 D6-2 : ghost stock page directory pruner.

Contract (Sky-approved 2026-07-14):
  ghost = {ROOT dirs matching [0-9A-Z]{6}} - {stocks_public codes}
  Stage 1 : full verification, ZERO deletion.
            every candidate must satisfy ALL of:
              (a) not in Full universe (stocks_public)
              (b) not in search_index.json
              (c) not in sitemap.xml
              (d) contents == ['index.html'] exactly
            any violation -> HARD_FAIL, exit 1, nothing removed.
  Stage 2 : only after stage 1 passes for ALL candidates.
            all-or-nothing. no partial deletion.
  Safety cap : candidates > MAX_PRUNE -> HARD_FAIL, nothing removed.
  Backup     : tar.gz before deletion, verified by entry count, else abort.
  Idempotent : 0 candidates -> exit 0, still logs one [PRUNE] line.

Runs as 3rd link in the cron chain:
  build_stock_pages.py && build_search_index.py && prune_stock_pages.py
Never touches build_stock_pages.py (D4 FINAL LOCK).
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

STOCKS_DIR = '/root/krx-moneyflow/output/stocks_public'
STOCK_ROOT = '/var/www/f29-stock'
SEARCH_IDX = '/var/www/f29-portal/data/search_index.json'
SITEMAP = '/var/www/f29-portal/sitemap.xml'
BACKUP_BASE = '/root/f29-backups'
MAX_PRUNE = 20

CODE_RE = re.compile(r'[0-9A-Z]{6}')


def log(msg):
    print('[PRUNE] %s' % msg, file=sys.stderr)


def hard_fail(msg):
    print('[PRUNE][HARD_FAIL] %s' % msg, file=sys.stderr)
    print('[PRUNE][HARD_FAIL] removed=0 (nothing deleted)', file=sys.stderr)
    sys.exit(1)


def main():
    # ---------------------------------------------------------- inputs
    if not os.path.isdir(STOCKS_DIR):
        hard_fail('stocks_public not found: %s' % STOCKS_DIR)
    if not os.path.isdir(STOCK_ROOT):
        hard_fail('stock root not found: %s' % STOCK_ROOT)

    full = {os.path.basename(p)[:-5]
            for p in glob.glob(os.path.join(STOCKS_DIR, '*.json'))}
    if not full:
        hard_fail('Full universe is empty -- upstream failure, refusing to prune')

    try:
        idx_doc = json.load(open(SEARCH_IDX, encoding='utf-8'))
        idx = {s['c'] for s in idx_doc['stocks']}
    except Exception as e:
        hard_fail('search_index unreadable (%s) -- refusing to prune' % e)

    try:
        sitemap = open(SITEMAP, encoding='utf-8').read()
    except Exception as e:
        hard_fail('sitemap unreadable (%s) -- refusing to prune' % e)

    entries = os.listdir(STOCK_ROOT)
    dirs = {d for d in entries if os.path.isdir(os.path.join(STOCK_ROOT, d))}

    # non-code-shaped directories are NEVER deletion candidates
    odd = sorted(d for d in dirs if not CODE_RE.fullmatch(d))
    if odd:
        log('WARN non-code dirs ignored: %s' % odd)
    code_dirs = {d for d in dirs if CODE_RE.fullmatch(d)}

    candidates = sorted(code_dirs - full)

    # -------------------------------------------------- idempotent no-op
    if not candidates:
        log('candidates=0 removed=0 landing=%d full=%d' % (len(code_dirs), len(full)))
        return

    # ----------------------------------------------- safety cap (stage 0)
    if len(candidates) > MAX_PRUNE:
        hard_fail('candidates=%d exceeds MAX_PRUNE=%d -- upstream anomaly suspected'
                  % (len(candidates), MAX_PRUNE))

    # ------------------------------------- STAGE 1 : verify all, delete none
    violations = []
    for c in candidates:
        p = os.path.join(STOCK_ROOT, c)
        if c in full:
            violations.append('%s: present in Full universe' % c)
        if c in idx:
            violations.append('%s: present in search_index' % c)
        if '/stock/%s/' % c in sitemap:
            violations.append('%s: present in sitemap' % c)
        contents = sorted(os.listdir(p))
        if contents != ['index.html']:
            violations.append('%s: unexpected contents %s' % (c, contents))
    if violations:
        for v in violations:
            print('[PRUNE][HARD_FAIL] %s' % v, file=sys.stderr)
        hard_fail('stage-1 verification failed (%d violations)' % len(violations))
    log('stage-1 PASS: %d candidates verified, 0 removed' % len(candidates))

    # ------------------------------------------------------------ backup
    day = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
    bdir = os.path.join(BACKUP_BASE, 'prune-%s' % day)
    os.makedirs(bdir, exist_ok=True)
    tarpath = os.path.join(bdir, 'ghosts.tar.gz')
    if os.path.exists(tarpath):
        ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        tarpath = os.path.join(bdir, 'ghosts.%s.tar.gz' % ts)

    with tarfile.open(tarpath, 'w:gz') as tf:
        for c in candidates:
            tf.add(os.path.join(STOCK_ROOT, c), arcname=c)

    # backup verification: every candidate dir + its index.html must be inside
    with tarfile.open(tarpath, 'r:gz') as tf:
        names = set(tf.getnames())
    for c in candidates:
        if c not in names or '%s/index.html' % c not in names:
            os.unlink(tarpath)
            hard_fail('backup verification failed for %s -- aborting before deletion' % c)
    log('backup OK: %s (%d dirs verified)' % (tarpath, len(candidates)))

    # ------------------------------- STAGE 2 : all-or-nothing deletion
    removed = []
    try:
        for c in candidates:
            shutil.rmtree(os.path.join(STOCK_ROOT, c))
            removed.append(c)
    except Exception as e:
        print('[PRUNE][HARD_FAIL] deletion aborted after %d/%d: %s'
              % (len(removed), len(candidates), e), file=sys.stderr)
        print('[PRUNE][HARD_FAIL] RESTORE: tar xzf %s -C %s'
              % (tarpath, STOCK_ROOT), file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------- post-check
    after = len({d for d in os.listdir(STOCK_ROOT)
                 if os.path.isdir(os.path.join(STOCK_ROOT, d))
                 and CODE_RE.fullmatch(d)})
    if after != len(full):
        print('[PRUNE][HARD_FAIL] post-count %d != Full %d -- RESTORE: tar xzf %s -C %s'
              % (after, len(full), tarpath, STOCK_ROOT), file=sys.stderr)
        sys.exit(1)

    log('candidates=%d removed=%d landing=%d full=%d  removed_codes=%s'
        % (len(candidates), len(removed), after, len(full), removed))
    log('rollback: tar xzf %s -C %s' % (tarpath, STOCK_ROOT))


if __name__ == '__main__':
    main()
