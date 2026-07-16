#!/usr/bin/env python3
# KR-GOLD-SWEEP-r1: replace 5 tradingvalue-gold #D8B45F -> #f0c674 in /kr-moneyflow.
# EXCLUDE 2 (TREND_COLORS palette, .st-slow state color) -> keep #D8B45F. + app.js cache bump.
import hashlib, os, shutil, sys
from datetime import datetime, timezone
APP = os.environ.get("APP", "/root/krx-moneyflow/web/app.js")
IDX = os.environ.get("IDX", "/root/krx-moneyflow/web/index.html")
OLD_VER = os.environ.get("OLDVER", "app.js?v=202607140331")
NEW_VER = os.environ.get("NEWVER", "app.js?v=20260716c")

# --- app.js: 3 tradingvalue-gold anchors (NOT the TREND_COLORS palette line) ---
APP_ANCHORS = [
    ('chartLine(shareSeries, sr, "#D8B45F", true)', 'chartLine(shareSeries, sr, "#f0c674", true)'),
    ('style="background:#D8B45F"', 'style="background:#f0c674"'),
    ('stroke="#D8B45F" stroke-width="2.2"', 'stroke="#f0c674" stroke-width="2.2"'),
]
# EXCLUDED (must stay): TREND_COLORS line contains #D8B45F -> untouched
APP_EXCLUDE = 'var TREND_COLORS=["#3DD8B0","#7BA7EA","#9D7BEA","#D8B45F"];'

# --- index.html: token + axis (NOT .st-slow) ---
IDX_ANCHORS = [
    ('--gold:#D8B45F;', '--gold:#f0c674;'),
    ('.chart-axis .ax-r{fill:#D8B45F;opacity:.75}', '.chart-axis .ax-r{fill:#f0c674;opacity:.75}'),
]
IDX_EXCLUDE = '.st-slow{background:#2A2412;color:#D8B45F}'

def sha_b(p):
    d=open(p,"rb").read(); return hashlib.sha256(d).hexdigest(), len(d)
def read(p): return open(p,"r",encoding="utf-8").read()
for p in (APP,IDX):
    if not os.path.isfile(p): sys.exit("ABORT: missing "+p)
app=read(APP); idx=read(IDX)

# double-apply guard
if '#f0c674' in app or app.count('#D8B45F')!=4:
    sys.exit("ABORT: app.js pre-state unexpected (#f0c674 present or #D8B45F != 4)")
if idx.count('#D8B45F')!=3:
    sys.exit("ABORT: index pre-state unexpected (#D8B45F != 3)")

# anchor count gates
for old,_ in APP_ANCHORS:
    if app.count(old)!=1: sys.exit("ABORT: app anchor !=1: %s"%old)
for old,_ in IDX_ANCHORS:
    if idx.count(old)!=1: sys.exit("ABORT: idx anchor !=1: %s"%old)
if app.count(APP_EXCLUDE)!=1: sys.exit("ABORT: app exclude anchor !=1")
if idx.count(IDX_EXCLUDE)!=1: sys.exit("ABORT: idx exclude anchor !=1")
if idx.count(OLD_VER)!=1: sys.exit("ABORT: cache anchor !=1: %s"%OLD_VER)

app2=app
for old,new in APP_ANCHORS: app2=app2.replace(old,new,1)
idx2=idx
for old,new in IDX_ANCHORS: idx2=idx2.replace(old,new,1)
idx2=idx2.replace(OLD_VER,NEW_VER,1)

# post-check: exact residuals
if app2.count('#D8B45F')!=1: sys.exit("ABORT: app #D8B45F != 1 (got %d)"%app2.count('#D8B45F'))
if app2.count('#f0c674')!=3: sys.exit("ABORT: app #f0c674 != 3 (got %d)"%app2.count('#f0c674'))
if idx2.count('#D8B45F')!=1: sys.exit("ABORT: idx #D8B45F != 1 (got %d)"%idx2.count('#D8B45F'))
if idx2.count('#f0c674')!=2: sys.exit("ABORT: idx #f0c674 != 2 (got %d)"%idx2.count('#f0c674'))
# excluded lines intact
if app2.count(APP_EXCLUDE)!=1: sys.exit("ABORT: TREND_COLORS changed!")
if idx2.count(IDX_EXCLUDE)!=1: sys.exit("ABORT: .st-slow changed!")
if idx2.count(NEW_VER)!=1 or OLD_VER in idx2: sys.exit("ABORT: cache bump failed")

ts=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir=os.environ.get("BK_DIR","/root/f29-backups/goldsweep-r1-"+ts)
os.makedirs(bdir,exist_ok=False)
shutil.copy2(APP,os.path.join(bdir,"app.js")); shutil.copy2(IDX,os.path.join(bdir,"index.html"))
sa0,ba0=sha_b(APP); si0,bi0=sha_b(IDX)
open(os.path.join(bdir,"manifest.txt"),"w").write("app.js %s %d\nindex.html %s %d\n%s\n"%(sa0,ba0,si0,bi0,ts))
ta=APP+".tmp."+ts; ti=IDX+".tmp."+ts
open(ta,"w",encoding="utf-8").write(app2); open(ti,"w",encoding="utf-8").write(idx2)
os.replace(ta,APP); os.replace(ti,IDX)
sa1,ba1=sha_b(APP); si1,bi1=sha_b(IDX)
print("OK"); print("backup_dir="+bdir)
print("app.js  before=%s/%d after=%s/%d"%(sa0,ba0,sa1,ba1))
print("index.html before=%s/%d after=%s/%d"%(si0,bi0,si1,bi1))
print("cache: %s -> %s"%(OLD_VER,NEW_VER))
