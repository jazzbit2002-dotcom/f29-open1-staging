#!/usr/bin/env python3
# F29 MARKET-CLOSE-SNAPSHOT (2026-07-18)
# Additive only: expose the 16:00 ET close-time snapshot as a separate contract object.
# Scope: mf_server.js market_internals IIFE.
#   - readMI() NOT modified (intraday/daily byte-identical, contracts preserved)
#   - reuses existing _etParts/_etDate/_expSession/MAX_INGEST_LAG/MAX_ABSOLUTE_AGE (no duplication)
#   - adds readCloseSnapshot() + market_close_snapshot in response
# Pure ASCII. Literal anchors + count gates. Backup. node --check. Atomic write.

import os, sys, shutil, subprocess, datetime, hashlib

TARGET = "/root/moneyflow/mf_server.js"
MARKER = "F29-CLOSE-SNAPSHOT v1"

def sha256(path):
    h = hashlib.sha256()
    with open(path,"rb") as f: h.update(f.read())
    return h.hexdigest()

def fail(msg):
    print("HARD_FAIL: " + msg); sys.exit(1)

src = open(TARGET,"r",encoding="utf-8").read()
if MARKER in src:
    fail("marker already present - patch already applied")
if "F29-FRESHNESS-P0" not in src:
    fail("prerequisite FRESHNESS-P0 helpers not found - wrong file state")

# ---- anchor A: call site (avoids the unicode note line) ----
A_CALL = (
    '        var intra = readMI("intraday");\n'
    '        var daily = readMI("daily");\n'
    '        if (!intra && !daily) return null;\n'
)
# ---- anchor B: response object tail ----
A_RESP = (
    '          intraday: intra,\n'
    '          daily: daily\n'
    '        };\n'
)

for name, a in (("CALL", A_CALL), ("RESP", A_RESP)):
    n = src.count(a)
    if n != 1:
        fail("anchor %s count=%d (expected 1)" % (name, n))
print("anchor gate: 2/2 count==1")

# ---- replacement A: insert function + call ----
NEW_CALL = (
    '        // ' + MARKER + '\n'
    '        var CLOSE_REQUIRED = ["spy","qqq","iwm","rsp","vix","tnx"];\n'
    '        function readCloseSnapshot(){\n'
    '          var m;\n'
    '          try { m = JSON.parse(fs.readFileSync("/root/moneyflow/market_internals_intraday.json","utf8")); }\n'
    '          catch(e){ return null; }\n'
    '          var nowSec = Math.floor(Date.now()/1000);\n'
    '          function out(state,reason,asOf,ageSec){\n'
    '            return { kind:"market_close_snapshot", reference_rule:"us_regular_close_16_et",\n'
    '                     updated: m && m.updated, bar_ts: m && m.bar_ts, as_of: asOf || null,\n'
    '                     stale: state !== "fresh", freshness:{ state:state, reason:reason },\n'
    '                     age_min: Number.isFinite(ageSec) ? Math.floor(ageSec/60) : null,\n'
    '                     data: (state === "fresh" && m && m.data) ? m.data : {} };\n'
    '          }\n'
    '          if (!m || typeof m !== "object") return out("unavailable","kind_mismatch",null,null);\n'
    '          if (m.kind !== "intraday") return out("unavailable","kind_mismatch",null,null);\n'
    '          var barTs = Number(m.bar_ts);\n'
    '          if (!Number.isFinite(barTs) || barTs <= 0) return out("unavailable","bar_not_close",null,null);\n'
    '          var upd = Date.parse(m.updated);\n'
    '          if (!Number.isFinite(upd)) return out("unavailable","updated_before_bar",null,null);\n'
    '          var updSec = Math.floor(upd/1000);\n'
    '          var bp = _etParts(barTs);\n'
    '          var asOf = _etDate(bp);\n'
    '          var ageSec = nowSec - barTs;\n'
    '          if (!(bp.H===16 && bp.M===0 && bp.S<=60)) {\n'
    '            if (bp.H===13 && bp.M===0) return out("unavailable","early_close_not_supported",asOf,ageSec);\n'
    '            return out("unavailable","bar_not_close",asOf,ageSec);\n'
    '          }\n'
    '          if (updSec < barTs) return out("unavailable","updated_before_bar",asOf,ageSec);\n'
    '          if (updSec - barTs > MAX_INGEST_LAG) return out("unavailable","ingest_lag_exceeded",asOf,ageSec);\n'
    '          if (updSec > nowSec + 60) return out("unavailable","future_session",asOf,ageSec);\n'
    '          var dd = m.data || {};\n'
    '          for (var ci=0; ci<CLOSE_REQUIRED.length; ci++) {\n'
    '            if (!Number.isFinite(Number(dd[CLOSE_REQUIRED[ci]]))) return out("unavailable","required_field_missing",asOf,ageSec);\n'
    '          }\n'
    '          var expS = _expSession(nowSec);\n'
    '          if (asOf > expS) return out("unavailable","future_session",asOf,ageSec);\n'
    '          if (asOf < expS) return out("stale","as_of_old",asOf,ageSec);\n'
    '          if (ageSec > MAX_ABSOLUTE_AGE) return out("stale","absolute_age_exceeded",asOf,ageSec);\n'
    '          return out("fresh","ok",asOf,ageSec);\n'
    '        }\n'
    + A_CALL +
    '        var closeSnap = readCloseSnapshot();\n'
)

# ---- replacement B: add to response ----
NEW_RESP = (
    '          intraday: intra,\n'
    '          daily: daily,\n'
    '          market_close_snapshot: closeSnap\n'
    '        };\n'
)

out = src.replace(A_CALL, NEW_CALL, 1)
out = out.replace(A_RESP, NEW_RESP, 1)
if out == src: fail("no change produced")
if out.count(MARKER) != 1: fail("marker count != 1 after patch")

# backup
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/close-snapshot-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir,"mf_server.js"))
print("backup: " + bdir + "/mf_server.js")
print("pre_sha256: " + sha256(TARGET))

tmp = TARGET + ".closesnap.tmp.js"
with open(tmp,"w",encoding="utf-8") as f: f.write(out)
r = subprocess.run(["node","--check",tmp], capture_output=True, text=True)
if r.returncode != 0:
    os.remove(tmp); fail("node --check failed:\n" + r.stderr)
print("node --check: PASS")
os.replace(tmp, TARGET)
print("applied. post_sha256: " + sha256(TARGET))
print("post size: %d bytes" % os.path.getsize(TARGET))
print("ROLLBACK: cp %s/mf_server.js %s && pm2 restart moneyflow" % (bdir, TARGET))
print("NEXT: pm2 restart moneyflow, then live verify (intraday/daily unchanged + close snapshot present)")
