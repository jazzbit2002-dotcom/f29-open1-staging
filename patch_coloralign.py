#!/usr/bin/env python3
# KR-STATE-COLOR-ALIGN: fade_down sheet badge bg-out(red) -> bg-fade(gold). down unchanged. no new hex.
import hashlib, os, shutil, sys
from datetime import datetime, timezone
WJS = os.environ.get("WJS", "/root/krx-moneyflow/web/weight.js")
WHT = os.environ.get("WHT", "/root/krx-moneyflow/web/weight.html")

A_OLD = '  if(state==="fade_down") return "bg-out";'
A_NEW = '  if(state==="fade_down") return "bg-fade";'
B_OLD = '  .bg-mix{background:#1A2332;color:var(--neu)} .bg-lead{background:#2A2410;color:var(--mid)} .bg-few{background:#20202A;color:var(--txt3)}'
B_NEW = '  .bg-mix{background:#1A2332;color:var(--neu)} .bg-lead{background:#2A2410;color:var(--mid)} .bg-few{background:#20202A;color:var(--txt3)} .bg-fade{background:#2A2410;color:var(--gold)}'

def sha_b(p):
    d=open(p,"rb").read(); return hashlib.sha256(d).hexdigest(), len(d)
def read(p): return open(p,"r",encoding="utf-8").read()
for p in (WJS,WHT):
    if not os.path.isfile(p): sys.exit("ABORT: missing "+p)
js=read(WJS); ht=read(WHT)
if "bg-fade" in js or "bg-fade" in ht:
    sys.exit("ABORT: bg-fade already present (already applied?)")
if js.count(A_OLD)!=1: sys.exit("ABORT: js anchor count %d"%js.count(A_OLD))
if ht.count(B_OLD)!=1: sys.exit("ABORT: html anchor count %d"%ht.count(B_OLD))
# down must stay bg-out (unique down line unchanged)
if js.count('if(state==="down_concentration") return "bg-out";')!=1:
    sys.exit("ABORT: down_concentration anchor missing/changed")
js2=js.replace(A_OLD,A_NEW,1)
ht2=ht.replace(B_OLD,B_NEW,1)
# post-check
if js2.count('fade_down") return "bg-fade"')!=1: sys.exit("ABORT: fade_down not rerouted")
if js2.count('down_concentration") return "bg-out"')!=1: sys.exit("ABORT: down changed!")
if js2.count('fade_down") return "bg-out"')!=0: sys.exit("ABORT: fade_down still bg-out")
if ht2.count('.bg-fade{background:#2A2410;color:var(--gold)}')!=1: sys.exit("ABORT: bg-fade css missing")
if ht2.count('.bg-out{background:#2A1A17;color:var(--down)}')!=1: sys.exit("ABORT: bg-out changed!")
# no new hex: #2A2410 already existed in original
if '#2A2410' not in ht: sys.exit("ABORT: bg-fade uses hex not pre-existing")
ts=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir=os.environ.get("BK_DIR","/root/f29-backups/coloralign-"+ts)
os.makedirs(bdir,exist_ok=False)
shutil.copy2(WJS,os.path.join(bdir,"weight.js")); shutil.copy2(WHT,os.path.join(bdir,"weight.html"))
sj0,bj0=sha_b(WJS); sh0,bh0=sha_b(WHT)
open(os.path.join(bdir,"manifest.txt"),"w").write("js %s %d\nhtml %s %d\n%s\n"%(sj0,bj0,sh0,bh0,ts))
tj=WJS+".tmp."+ts; th=WHT+".tmp."+ts
open(tj,"w",encoding="utf-8").write(js2); open(th,"w",encoding="utf-8").write(ht2)
os.replace(tj,WJS); os.replace(th,WHT)
sj1,bj1=sha_b(WJS); sh1,bh1=sha_b(WHT)
print("OK"); print("backup_dir="+bdir)
print("weight.js  before=%s/%d after=%s/%d"%(sj0,bj0,sj1,bj1))
print("weight.html before=%s/%d after=%s/%d"%(sh0,bh0,sh1,bh1))
