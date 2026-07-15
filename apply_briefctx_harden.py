#!/usr/bin/env python3
# F29 BRIEFING-CONTRACT-HARDENING v1 (2026-07-15)
# Scope: mf_server.js briefing-context response only.
#   A-1: universe classified counts + excluded status distribution
#   A-2: compliance forbidden 6 -> 12
# Forbidden scope: positions logic, lifecycle/axis calc, leaders/exits/watching,
#   theme_flow sort, stale thresholds, market_internals, hook/Pine.
# Pure ASCII. Literal anchors + count gates. Backup. node --check. Atomic write.

import os, sys, shutil, subprocess, datetime, hashlib

TARGET = "/root/moneyflow/mf_server.js"
MARKER = "F29-BRIEFCTX-HARDEN v1"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def fail(msg):
    print("HARD_FAIL: " + msg)
    sys.exit(1)

src = open(TARGET, "r", encoding="utf-8").read()

# duplicate-application guard
if MARKER in src:
    fail("marker already present - patch already applied")

# ---- anchors (must each appear exactly once) ----

A_INSERT = "    const volLabels = {};"

A_UNIVERSE_OLD = (
    "      universe: { total: arr.length, lifecycle_distribution: lifecycleDist,\n"
    "                  axis_distribution: axisDist },"
)

A_FORBIDDEN_OLD = (
    '        forbidden: ["\\ub9e4\\uc218 \\ucd94\\ucc9c", "\\ub9e4\\ub3c4 \\uc2e0\\ud638", '
    '"\\ubaa9\\ud45c\\uac00", "\\uc190\\uc808", "\\uc21c\\uc720\\uc785", "\\uc21c\\uc720\\ucd9c"],'
)

for name, a in (("INSERT", A_INSERT), ("UNIVERSE", A_UNIVERSE_OLD), ("FORBIDDEN", A_FORBIDDEN_OLD)):
    n = src.count(a)
    if n != 1:
        fail("anchor %s count=%d (expected 1)" % (name, n))
print("anchor gate: 3/3 count==1")

# ---- replacements ----

INSERT_NEW = (
    "    // " + MARKER + "\n"
    "    var lifecycleClassified = 0, axisClassified = 0;\n"
    "    var excludedStatusDist = {};\n"
    "    for (const r of arr) {\n"
    "      if (r.lifecycle) lifecycleClassified++;\n"
    "      if (r.axis_state) axisClassified++;\n"
    "      if (r.lifecycle && r.axis_state) continue;\n"
    "      var xst = r.status || \"unknown\";\n"
    "      excludedStatusDist[xst] = (excludedStatusDist[xst] || 0) + 1;\n"
    "    }\n"
    + A_INSERT
)

# distribution_note: "gag bunpoNeun haedang panjeonggabi inneun jongmongman jipgye"
UNIVERSE_NEW = (
    "      universe: { total: arr.length,\n"
    "                  lifecycle_classified: lifecycleClassified,\n"
    "                  axis_classified: axisClassified,\n"
    "                  excluded_status_distribution: excludedStatusDist,\n"
    "                  distribution_note: \"\\uac01 \\ubd84\\ud3ec\\ub294 \\ud574\\ub2f9 "
    "\\ud310\\uc815\\uac12\\uc774 \\uc788\\ub294 \\uc885\\ubaa9\\ub9cc \\uc9d1\\uacc4\",\n"
    "                  lifecycle_distribution: lifecycleDist,\n"
    "                  axis_distribution: axisDist },"
)

# forbidden 12: existing 6 + jinip / cheongsan / yecheuk / jeokjung / silloedo / jeokjungnyul
FORBIDDEN_NEW = (
    '        forbidden: ["\\ub9e4\\uc218 \\ucd94\\ucc9c", "\\ub9e4\\ub3c4 \\uc2e0\\ud638", '
    '"\\ubaa9\\ud45c\\uac00", "\\uc190\\uc808", "\\uc21c\\uc720\\uc785", "\\uc21c\\uc720\\ucd9c", '
    '"\\uc9c4\\uc785", "\\uccad\\uc0b0", "\\uc608\\uce21", "\\uc801\\uc911", '
    '"\\uc2e0\\ub8b0\\ub3c4", "\\uc801\\uc911\\ub960"],'
)

out = src.replace(A_INSERT, INSERT_NEW, 1)
out = out.replace(A_UNIVERSE_OLD, UNIVERSE_NEW, 1)
out = out.replace(A_FORBIDDEN_OLD, FORBIDDEN_NEW, 1)

if out == src:
    fail("no changes produced")
if out.count(MARKER) != 1:
    fail("marker count after patch != 1")

# ---- backup ----
ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/briefctx-harden-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir, "mf_server.js"))
pre_sha = sha256(TARGET)
print("backup: " + bdir + "/mf_server.js")
print("pre_sha256: " + pre_sha)

# ---- write temp, node --check, atomic replace ----
tmp = TARGET + ".briefctx.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(out)

r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
if r.returncode != 0:
    os.remove(tmp)
    fail("node --check failed:\n" + r.stderr)
print("node --check: PASS")

os.replace(tmp, TARGET)
print("applied. post_sha256: " + sha256(TARGET))
print("post size (wc -c equivalent): %d bytes" % os.path.getsize(TARGET))
print("ROLLBACK: cp %s/mf_server.js %s && pm2 restart moneyflow" % (bdir, TARGET))
print("NEXT: pm2 restart moneyflow, then run contract verification curl")
