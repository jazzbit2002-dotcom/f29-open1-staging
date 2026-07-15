#!/usr/bin/env python3
# patch_portal_cachebust.py -- F29 S3 release finalize: bump the portal's
# f29-search.js cache token 20260713c -> 20260715a so browsers pick up the S3
# router. Single query-string change; no markup/logic/other change.
# BASE = post-showcase portal (0e2219d8...). Applying this SUPERSEDES 0e2219d8;
# record the new SHA as Patch B's new BASE.
import os, sys, hashlib, tempfile, datetime

TARGET = '/var/www/f29-portal/index.html'
BACKUP_BASE = '/root/f29-backups'
EXPECT_SHA = '0e2219d8c2616b8f6ec061085b8569c5e809bd435182064e14951e250b60022c'
EXPECT_SIZE = 36307
OLD = '<script src="/assets/f29-search.js?v=20260713c" defer></script>'
NEW = '<script src="/assets/f29-search.js?v=20260715a" defer></script>'

def die(m):
    print('[cache][ABORT] %s'%m,file=sys.stderr); print('[cache][ABORT] source NOT modified.',file=sys.stderr); sys.exit(1)
def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    if not os.path.isfile(TARGET): die('target not found')
    raw=open(TARGET,'rb').read(); src=raw.decode('utf-8')
    print('[cache] before sha   = %s'%sha(raw)); print('[cache] before bytes = %d'%len(raw))
    if sha(raw)!=EXPECT_SHA: die('SHA MISMATCH: %s (expected post-showcase 0e2219d8)'%sha(raw))
    if len(raw)!=EXPECT_SIZE: die('SIZE MISMATCH: %d'%len(raw))
    print('[cache] SHA gate PASS (post-showcase BASE)')
    if '?v=20260715a' in src: die('already applied: 20260715a token present')
    n=src.count(OLD)
    if n!=1: die('anchor count=%d (expected 1)'%n)
    if src.count('?v=20260713c')!=1: die('unexpected 20260713c count=%d'%src.count('?v=20260713c'))
    print('[cache] anchor count=1 (20260713c -> 20260715a)')
    out=src.replace(OLD,NEW,1)
    checks=[
      ('new token ==1', out.count('?v=20260715a')==1),
      ('old token ==0', out.count('?v=20260713c')==0),
      ('script src intact', out.count('<script src="/assets/f29-search.js?v=20260715a" defer></script>')==1),
      ('showcase cards intact', out.count('href="/kr-moneyflow"')==2 and out.count('href="/weight"')==2),
      ('byte delta ==0 (same length token)', len(out.encode('utf-8'))==len(raw)),
    ]
    for name,ok in checks:
        if not ok: die('post-check FAIL: %s'%name)
    print('[cache] post-check gates PASS (%d)'%len(checks))
    ts=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir=os.path.join(BACKUP_BASE,'portal-cache-%s'%ts); os.makedirs(bdir,exist_ok=True)
    bak=os.path.join(bdir,'index.html'); open(bak,'wb').write(raw)
    print('[cache] backup       = %s'%bak)
    d=os.path.dirname(os.path.abspath(TARGET)); mode=os.stat(TARGET).st_mode&0o7777
    fd,tmp=tempfile.mkstemp(dir=d)
    with os.fdopen(fd,'wb') as f: f.write(out.encode('utf-8'))
    os.chmod(tmp,mode); os.replace(tmp,TARGET)
    ra=open(TARGET,'rb').read()
    print('[cache] after sha    = %s'%sha(ra)); print('[cache] after bytes  = %d'%len(ra))
    print('[cache] OK  rollback: cp %s %s'%(bak,TARGET))
    print('[cache] NOTE: 0e2219d8 is now SUPERSEDED. New SHA above = Patch B new BASE.')

if __name__=='__main__': main()
