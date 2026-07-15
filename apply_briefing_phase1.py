#!/usr/bin/env python3
# F29 BRIEFING PHASE 1 v2 - explicit routes via URL object (2026-07-15)
# Revised per external feedback: no staticMap mutation, no manual "?" split.
# Scope: mf_server.js routing only. NO changes to positions/score/hook/stale/internals/staticMap.
#   1. GET /moneyflow/briefing[/ | /index.html]  -> MF_DIR/briefing/index.html
#   2. GET /moneyflow/api/briefing/latest?type=daily|weekly (URL-parsed, 400 on bad type)
#   3. ensure /root/moneyflow/briefings/archive + /root/moneyflow/briefing exist
# Pure ASCII. Single literal anchor + count gate. Backup. node --check. Atomic write.

import os, sys, shutil, subprocess, datetime, hashlib

TARGET = "/root/moneyflow/mf_server.js"
MARKER = "F29-BRIEFING-PHASE1 v2"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def fail(msg):
    print("HARD_FAIL: " + msg)
    sys.exit(1)

src = open(TARGET, "r", encoding="utf-8").read()

if "F29-BRIEFING-PHASE1" in src:
    fail("a BRIEFING-PHASE1 marker already present - patch already applied")

# ---- single anchor: crypto route block. New routes inserted immediately before it. ----
A_CRYPTO = '  if (req.url === "/moneyflow/crypto" || req.url === "/crypto") {'
n = src.count(A_CRYPTO)
if n != 1:
    fail("anchor CRYPTO count=%d (expected 1)" % n)
print("anchor gate: 1/1 count==1")

# ---- inserted block: explicit page route + explicit API route ----
BLOCK = (
    '  // ' + MARKER + '\n'
    '  var _bu = new URL(req.url, "http://127.0.0.1");\n'
    '  var _bp = _bu.pathname;\n'
    '  if (req.method === "GET" && (_bp === "/moneyflow/briefing" ||\n'
    '      _bp === "/moneyflow/briefing/" || _bp === "/moneyflow/briefing/index.html")) {\n'
    '    try {\n'
    '      var _bhtml = fs.readFileSync(path.join(MF_DIR, "briefing", "index.html"), "utf8");\n'
    '      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });\n'
    '      res.end(_bhtml);\n'
    '    } catch (e) { res.writeHead(404); res.end("not found"); }\n'
    '    return;\n'
    '  }\n'
    '  if (req.method === "GET" && (_bp === "/moneyflow/api/briefing/latest" ||\n'
    '      _bp === "/api/briefing/latest")) {\n'
    '    var _bt = _bu.searchParams.get("type");\n'
    '    if (_bt !== "daily" && _bt !== "weekly") {\n'
    '      res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });\n'
    '      res.end(JSON.stringify({ status: "error", error: "invalid_type" }));\n'
    '      return;\n'
    '    }\n'
    '    var _bd = readJson("briefings/latest_" + _bt + ".json");\n'
    '    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8",\n'
    '                         "Cache-Control": "no-store" });\n'
    '    res.end(JSON.stringify(_bd || { status: "pending", type: _bt }));\n'
    '    return;\n'
    '  }\n'
    + A_CRYPTO
)

out = src.replace(A_CRYPTO, BLOCK, 1)

if out == src:
    fail("no changes produced")
if out.count(MARKER) != 1:
    fail("marker count after patch != 1")

# ---- backup ----
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/briefing-phase1-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir, "mf_server.js"))
pre_sha = sha256(TARGET)
print("backup: " + bdir + "/mf_server.js")
print("pre_sha256: " + pre_sha)

# ---- write temp, node --check, atomic replace ----
tmp = TARGET + ".briefing.tmp.js"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(out)

r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
if r.returncode != 0:
    os.remove(tmp)
    fail("node --check failed:\n" + r.stderr)
print("node --check: PASS")

os.replace(tmp, TARGET)

# ---- ensure dirs ----
os.makedirs("/root/moneyflow/briefings/archive", exist_ok=True)
os.makedirs("/root/moneyflow/briefing", exist_ok=True)
print("dirs ready: /root/moneyflow/briefings/archive , /root/moneyflow/briefing")

print("applied. post_sha256: " + sha256(TARGET))
print("post size: %d bytes" % os.path.getsize(TARGET))
print("ROLLBACK: cp %s/mf_server.js %s && pm2 restart moneyflow" % (bdir, TARGET))
print("NEXT: place briefing/index.html, pm2 restart moneyflow, then curl checks")
