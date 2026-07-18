#!/usr/bin/env python3
# F29 MONEYFLOW-DIGEST (2026-07-18)
# Additive only: expose F29's own theme ranking / horizon strength / value chain /
# strength quality / rotation / stock radar as a compact digest for briefing.
# Scope: mf_server.js briefing-context response object.
#   - built ONLY from already-loaded S (score_output) and P (positions_output)
#   - no new collector, no new file, no DB, no cron
#   - market_internals / intraday / daily / market_close_snapshot: UNTOUCHED
# Pure ASCII. Literal anchor + count gate. Backup. node --check. Atomic write.

import os, sys, shutil, subprocess, datetime, hashlib

TARGET = "/root/moneyflow/mf_server.js"
MARKER = "F29-MONEYFLOW-DIGEST v1"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f: h.update(f.read())
    return h.hexdigest()

def fail(msg):
    print("HARD_FAIL: " + msg); sys.exit(1)

src = open(TARGET, "r", encoding="utf-8").read()
if MARKER in src:
    fail("marker already present - patch already applied")
if "F29-CLOSE-SNAPSHOT" not in src:
    fail("prerequisite CLOSE-SNAPSHOT not found - wrong file state")

A = (
    '      volatility: volLabels,\n'
    '      market_internals: (function(){\n'
)
if src.count(A) != 1:
    fail("anchor count=%d (expected 1)" % src.count(A))
print("anchor gate: 1/1 count==1")

NEW = (
    '      volatility: volLabels,\n'
    '      // ' + MARKER + '\n'
    '      moneyflow_digest: (function(){\n'
    '        var out = {};\n'
    '        var rk = Array.isArray(S.ranking) ? S.ranking : [];\n'
    '        function slim(x){ return { theme:x.theme, score:x.score, direction:x.direction,\n'
    '                                   d_score:x.d_score, d_rank:x.d_rank }; }\n'
    '        function nz(v){ var n = Number(v); return Number.isFinite(n) ? n : 0; }\n'
    '        out.theme_ranking = {\n'
    '          top: rk.slice(0,5).map(slim),\n'
    '          fast_risers: rk.slice().sort(function(a,b){\n'
    '            return (nz(b.d_rank)-nz(a.d_rank)) || (nz(b.d_score)-nz(a.d_score)); })\n'
    '            .slice(0,3).map(slim),\n'
    '          fast_fallers: rk.slice().sort(function(a,b){\n'
    '            return (nz(a.d_rank)-nz(b.d_rank)) || (nz(a.d_score)-nz(b.d_score)); })\n'
    '            .slice(0,3).map(slim)\n'
    '        };\n'
    '        var ps = S.period_strength || {};\n'
    '        out.horizon_leaders = { d7: (ps["7\\uc77c"]||[]).slice(0,3),\n'
    '                                d30: (ps["30\\uc77c"]||[]).slice(0,3),\n'
    '                                d90: (ps["90\\uc77c"]||[]).slice(0,3) };\n'
    '        out.value_chains = (Array.isArray(S.value_chain) ? S.value_chain : [])\n'
    '          .slice(0,4).map(function(v){\n'
    '            return { group:v.group, lead:v.lead, gap:v.gap,\n'
    '                     members:(v.members||[]).map(function(m){\n'
    '                       return { theme:m.theme, score:m.score }; }) }; });\n'
    '        out.strength_quality = S.quality || null;\n'
    '        var rg2 = S.rotation_regime || {};\n'
    '        out.rotation = { confirmed:rg2.final, candidate:rg2.candidate,\n'
    '                         detail:rg2.detail, pos:rg2.pos, neg:rg2.neg, lead:rg2.lead };\n'
    '        var pa = P.positions || [];\n'
    '        function pick(r){\n'
    '          return { ticker:r.ticker, name:r.name_ko, theme:r.theme_group,\n'
    '                   axis:r.axis_state, lifecycle:r.lifecycle,\n'
    '                   rs:{ sector_20:r.RS_sector_20, market_20:r.RS_market_20,\n'
    '                        sector_60:r.RS_sector_60, market_60:r.RS_market_60 } };\n'
    '        }\n'
    '        function byMkt(desc){ return function(a,b){\n'
    '          var x=nz(a.RS_market_20), y=nz(b.RS_market_20);\n'
    '          return desc ? (y-x) : (x-y); }; }\n'
    '        out.stock_radar = {\n'
    '          dual_axis_winners: pa.filter(function(r){ return r.axis_state==="\\uc591\\ucd95\\uc6b0\\uc704"; })\n'
    '            .sort(byMkt(true)).slice(0,3).map(pick),\n'
    '          mixed: pa.filter(function(r){ return r.axis_state==="\\ud63c\\uc870"; })\n'
    '            .sort(byMkt(true)).slice(0,3).map(pick),\n'
    '          dual_axis_laggards: pa.filter(function(r){ return r.axis_state==="\\uc591\\ucd95\\uc5f4\\uc704"; })\n'
    '            .sort(byMkt(false)).slice(0,3).map(pick),\n'
    '          watching: pa.filter(function(r){ return r.watch; }).slice(0,2).map(function(r){\n'
    '            var o = pick(r); o.watch = r.watch; return o; })\n'
    '        };\n'
    '        out.note = "\\ud14c\\ub9c8 \\uc21c\\uc704\\u00b7\\uae30\\uac04\\ubcc4 \\uac15\\uc138'
    '\\u00b7\\ubc38\\ub958\\uccb4\\uc778\\u00b7\\uc885\\ubaa9 \\uc0c1\\ub300\\uac15\\ub3c4 \\uc694\\uc57d. '
    'score\\ub294 \\uad00\\uc2ec\\ub3c4 \\uc810\\uc218\\uc774\\uba70 \\uac00\\uaca9\\uc774 \\uc544\\ub2c8\\uace0, '
    'rs\\ub294 %p \\uc0c1\\ub300\\uac15\\ub3c4\\uc774\\uba70 \\uc790\\uae08 \\uaddc\\ubaa8\\uac00 \\uc544\\ub2d9\\ub2c8\\ub2e4.";\n'
    '        return out;\n'
    '      })(),\n'
    '      market_internals: (function(){\n'
)

out = src.replace(A, NEW, 1)
if out == src: fail("no change produced")
if out.count(MARKER) != 1: fail("marker count != 1")

ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/mf-digest-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir, "mf_server.js"))
print("backup: " + bdir + "/mf_server.js")
print("pre_sha256: " + sha256(TARGET))

tmp = TARGET + ".digest.tmp.js"
with open(tmp, "w", encoding="utf-8") as f: f.write(out)
r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
if r.returncode != 0:
    os.remove(tmp); fail("node --check failed:\n" + r.stderr)
print("node --check: PASS")
os.replace(tmp, TARGET)
print("applied. post_sha256: " + sha256(TARGET))
print("post size: %d bytes" % os.path.getsize(TARGET))
print("ROLLBACK: cp %s/mf_server.js %s && pm2 restart moneyflow" % (bdir, TARGET))
print("NEXT: pm2 restart moneyflow, then verify digest + market_internals unchanged")
