#!/usr/bin/env python3
# F29 FRESHNESS-P0 (2026-07-17)
# Replace age-only daily freshness with weekday_approx_v1 dual-contract judgment.
# Scope: mf_server.js market_internals IIFE only. intraday branch UNCHANGED (C-2 preserved).
#   - inject etParts / expectedWeekdaySession / judgeDaily + constants at IIFE top
#   - readMI daily branch -> judgeDaily + dual contract (stale bool kept fail-closed + freshness obj)
#   - raw record fields (updated/bar_ts/as_of/age_min/data) preserved
# Pure ASCII. Literal anchor + count gate. Backup. node --check. Atomic write.

import os, sys, shutil, subprocess, datetime, hashlib

TARGET = "/root/moneyflow/mf_server.js"
MARKER = "F29-FRESHNESS-P0 v1"

def sha256(path):
    h = hashlib.sha256()
    with open(path,"rb") as f: h.update(f.read())
    return h.hexdigest()

def fail(msg):
    print("HARD_FAIL: " + msg); sys.exit(1)

src = open(TARGET,"r",encoding="utf-8").read()
if MARKER in src:
    fail("marker already present - patch already applied")

# ---- anchor: exact readMI function block (215-224) ----
A_READMI = (
    '        function readMI(kind){\n'
    '          try {\n'
    '            var m = JSON.parse(fs.readFileSync("/root/moneyflow/market_internals_"+kind+".json","utf8"));\n'
    '            var ageSec = Math.floor(Date.now()/1000) - Number(m.bar_ts||0);\n'
    '            return { updated: m.updated, bar_ts: m.bar_ts,                     as_of: m.as_of || null,\n'
    '                     stale: kind==="intraday" ? ageSec > 1800 : ageSec > 129600,\n'
    '                     age_min: Math.floor(ageSec/60),\n'
    '                     data: m.data || {} };\n'
    '          } catch(e){ return null; }\n'
    '        }\n'
)

if src.count(A_READMI) != 1:
    fail("anchor READMI count=%d (expected 1)" % src.count(A_READMI))
print("anchor gate: 1/1 count==1")

# ---- replacement: helpers + new readMI (daily dual-contract, intraday unchanged) ----
NEW = (
    '        // ' + MARKER + '\n'
    '        var MAX_INGEST_LAG = 3600, MAX_ABSOLUTE_AGE = 96*3600;\n'
    '        function _etParts(epochSec){\n'
    '          var dt = new Date(epochSec*1000);\n'
    '          var fmt = new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",\n'
    '            year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false,weekday:"short"});\n'
    '          var pp={}; fmt.formatToParts(dt).forEach(function(x){pp[x.type]=x.value;});\n'
    '          var wm={Sun:0,Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6}; var H=parseInt(pp.hour,10); if(H===24)H=0;\n'
    '          return {y:parseInt(pp.year,10),m:parseInt(pp.month,10),d:parseInt(pp.day,10),H:H,M:parseInt(pp.minute,10),S:parseInt(pp.second,10),wday:wm[pp.weekday]};\n'
    '        }\n'
    '        function _etDate(p){function z(n){return (n<10?"0":"")+n;} return p.y+"-"+z(p.m)+"-"+z(p.d);}\n'
    '        function _expSession(nowSec){\n'
    '          var p=_etParts(nowSec);\n'
    '          function mk(y,m,d){function z(n){return (n<10?"0":"")+n;} return y+"-"+z(m)+"-"+z(d);}\n'
    '          function wd(y,m,d){return new Date(Date.UTC(y,m-1,d,12,0,0)).getUTCDay();}\n'
    '          function pd(y,m,d){var t=new Date(Date.UTC(y,m-1,d,12,0,0));t.setUTCDate(t.getUTCDate()-1);return {y:t.getUTCFullYear(),m:t.getUTCMonth()+1,d:t.getUTCDate()};}\n'
    '          var y=p.y,m=p.m,d=p.d,w=p.wday,ac=(p.H>16)||(p.H===16&&(p.M>0||p.S>=0));\n'
    '          if(w===6){var a=pd(y,m,d);return mk(a.y,a.m,a.d);}\n'
    '          if(w===0){var b=pd(y,m,d);var c=pd(b.y,b.m,b.d);return mk(c.y,c.m,c.d);}\n'
    '          if(ac)return mk(y,m,d);\n'
    '          var pv=pd(y,m,d),pw=wd(pv.y,pv.m,pv.d);\n'
    '          if(pw===0){var e=pd(pv.y,pv.m,pv.d);var f=pd(e.y,e.m,e.d);return mk(f.y,f.m,f.d);}\n'
    '          if(pw===6){var g=pd(pv.y,pv.m,pv.d);return mk(g.y,g.m,g.d);}\n'
    '          return mk(pv.y,pv.m,pv.d);\n'
    '        }\n'
    '        function _judgeDaily(rec,nowMs){\n'
    '          var nowSec=Math.floor(nowMs/1000);\n'
    '          if(!rec||typeof rec!=="object")return {state:"unavailable",reason:"kind_mismatch"};\n'
    '          if(rec.kind!=="daily")return {state:"unavailable",reason:"kind_mismatch"};\n'
    '          var asOf=rec.as_of;\n'
    '          if(typeof asOf!=="string"||!/^\\d{4}-\\d{2}-\\d{2}$/.test(asOf))return {state:"unavailable",reason:"missing_as_of"};\n'
    '          var barTs=Number(rec.bar_ts);\n'
    '          if(!Number.isFinite(barTs)||barTs<=0)return {state:"unavailable",reason:"bar_not_close"};\n'
    '          var upd=Date.parse(rec.updated);\n'
    '          if(!Number.isFinite(upd))return {state:"unavailable",reason:"updated_before_bar"};\n'
    '          var updSec=Math.floor(upd/1000);\n'
    '          var bp=_etParts(barTs);\n'
    '          if(_etDate(bp)!==asOf)return {state:"unavailable",reason:"bar_date_mismatch"};\n'
    '          if(!(bp.H===16&&bp.M===0&&bp.S<=60)){\n'
    '            if(bp.H===13&&bp.M===0)return {state:"unavailable",reason:"early_close_not_supported"};\n'
    '            return {state:"unavailable",reason:"bar_not_close"};\n'
    '          }\n'
    '          if(updSec<barTs)return {state:"unavailable",reason:"updated_before_bar"};\n'
    '          if(updSec-barTs>MAX_INGEST_LAG)return {state:"unavailable",reason:"ingest_lag_exceeded"};\n'
    '          if(updSec>nowSec+60)return {state:"unavailable",reason:"future_session"};\n'
    '          var exp=_expSession(nowSec);\n'
    '          if(asOf>exp)return {state:"unavailable",reason:"future_session"};\n'
    '          if(asOf<exp)return {state:"stale",reason:"as_of_old"};\n'
    '          if(nowSec-barTs>MAX_ABSOLUTE_AGE)return {state:"stale",reason:"absolute_age_exceeded"};\n'
    '          return {state:"fresh",reason:"ok"};\n'
    '        }\n'
    '        function readMI(kind){\n'
    '          try {\n'
    '            var m = JSON.parse(fs.readFileSync("/root/moneyflow/market_internals_"+kind+".json","utf8"));\n'
    '            var ageSec = Math.floor(Date.now()/1000) - Number(m.bar_ts||0);\n'
    '            if (kind==="daily") {\n'
    '              var fr = _judgeDaily(m, Date.now());\n'
    '              return { updated: m.updated, bar_ts: m.bar_ts, as_of: m.as_of || null,\n'
    '                       stale: fr.state !== "fresh",\n'
    '                       freshness: fr,\n'
    '                       age_min: Math.floor(ageSec/60),\n'
    '                       data: m.data || {} };\n'
    '            }\n'
    '            return { updated: m.updated, bar_ts: m.bar_ts, as_of: m.as_of || null,\n'
    '                     stale: ageSec > 1800,\n'
    '                     age_min: Math.floor(ageSec/60),\n'
    '                     data: m.data || {} };\n'
    '          } catch(e){ return null; }\n'
    '        }\n'
)

out = src.replace(A_READMI, NEW, 1)
if out == src: fail("no change produced")
if out.count(MARKER) != 1: fail("marker count != 1 after patch")

# backup
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/freshness-p0-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir,"mf_server.js"))
print("backup: " + bdir + "/mf_server.js")
print("pre_sha256: " + sha256(TARGET))

# write temp, node --check, atomic
tmp = TARGET + ".freshness.tmp.js"
with open(tmp,"w",encoding="utf-8") as f: f.write(out)
r = subprocess.run(["node","--check",tmp], capture_output=True, text=True)
if r.returncode != 0:
    os.remove(tmp); fail("node --check failed:\n" + r.stderr)
print("node --check: PASS")
os.replace(tmp, TARGET)
print("applied. post_sha256: " + sha256(TARGET))
print("post size: %d bytes" % os.path.getsize(TARGET))
print("ROLLBACK: cp %s/mf_server.js %s && pm2 restart moneyflow" % (bdir, TARGET))
print("NEXT: pm2 restart moneyflow, then curl briefing-context daily.freshness check + C-1/C-2/C-3 regression")
