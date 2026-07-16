#!/usr/bin/env python3
# P0-5B-2: state selector + statePanel (renderRank reuse, openStockSheet loop). 2-file, count-gated, atomic.
import hashlib, os, shutil, sys
from datetime import datetime, timezone

WJS = os.environ.get("WJS", "/root/krx-moneyflow/web/weight.js")
WHT = os.environ.get("WHT", "/root/krx-moneyflow/web/weight.html")

# ---- Anchor A: globals + helpers after THEME_OF ----
A_OLD = 'var THEME_OF = {};'
A_NEW = (
    'var THEME_OF = {};\n'
    'var _openState = null;\n'
    'var _stateBound = false;\n'
    '// STATE_META labels mirror build_weight.py flow_state() (backend=SSOT; fallback for 0-count buttons)\n'
    'var STATE_META = Object.freeze([\n'
    '  {state:"up_concentration",   label:"\uc0c1\uc2b9 \uac70\ub798\ub300\uae08 \uc9d1\uc911"},\n'
    '  {state:"attention_up",       label:"\uac70\ub798\ub300\uae08 \uad00\uc2ec \uc99d\uac00"},\n'
    '  {state:"fade_up",            label:"\uc587\uc740 \uc0c1\uc2b9"},\n'
    '  {state:"neutral",            label:"\ub69c\ub837\ud55c \ubc29\ud5a5 \uc5c6\uc74c"},\n'
    '  {state:"fade_down",          label:"\uad00\uc2ec\u00b7\uac00\uaca9 \ub3d9\ubc18 \uc704\ucd95"},\n'
    '  {state:"down_concentration", label:"\ud558\ub77d \uac70\ub798\ub300\uae08 \uc9d1\uc911"}\n'
    ']);\n'
    'function getStateLabel(meta){\n'
    '  var lists = WEIGHT && WEIGHT.stateLists;\n'
    '  var rows = lists && Array.isArray(lists[meta.state]) ? lists[meta.state] : null;\n'
    '  var dataLabel = rows && rows.length ? rows[0].flowLabel : "";\n'
    '  if(dataLabel && dataLabel !== meta.label){ console.warn("state label drift:", meta.state, "backend="+dataLabel, "frontend="+meta.label); }\n'
    '  return dataLabel || meta.label;\n'
    '}\n'
    'function renderStateControls(){\n'
    '  var c = WEIGHT.counts || {};\n'
    '  var btns = STATE_META.map(function(meta){\n'
    '    var count = Number(c[meta.state] || 0);\n'
    '    var dis = count === 0;\n'
    '    return \'<button type="button" class="wstate-btn" data-state="\'+meta.state+\'" aria-controls="statePanel" aria-expanded="false"\'+(dis?\' disabled\':\'\')+\'>\'+esc(getStateLabel(meta))+\' <span>\'+count+\'</span></button>\';\n'
    '  }).join("");\n'
    '  return \'<div class="wstate-sel">\'+btns+\'</div><div id="statePanel" hidden></div>\';\n'
    '}\n'
    'function _stateDelegate(e){\n'
    '  var b = e.target.closest("button[data-state]");\n'
    '  if(!b || b.disabled) return;\n'
    '  toggleStatePanel(b.dataset.state);\n'
    '}\n'
    'function toggleStatePanel(state){\n'
    '  var lists = WEIGHT && WEIGHT.stateLists;\n'
    '  var rows = lists && Array.isArray(lists[state]) ? lists[state] : null;\n'
    '  if(!rows){ console.warn("stateLists unavailable:", state); return; }\n'
    '  var panel = document.getElementById("statePanel");\n'
    '  var btns = document.querySelectorAll(".wstate-sel button[data-state]");\n'
    '  if(_openState === state){\n'
    '    panel.hidden = true; _openState = null;\n'
    '    btns.forEach(function(b){ b.setAttribute("aria-expanded","false"); });\n'
    '    return;\n'
    '  }\n'
    '  btns.forEach(function(b){ b.setAttribute("aria-expanded", b.dataset.state===state ? "true" : "false"); });\n'
    '  renderRank("statePanel", rows, "state", THEME_OF);\n'
    '  panel.hidden = false; _openState = state;\n'
    '}'
)

# ---- Anchor B: summaryCard render -> append controls + reset + bind once ----
B_OLD = '  document.getElementById("summaryCard").innerHTML = html;'
B_NEW = (
    '  html += renderStateControls();\n'
    '  document.getElementById("summaryCard").innerHTML = html;\n'
    '  _openState = null;\n'
    '  if(!_stateBound){ _stateBound = true; document.getElementById("summaryCard").addEventListener("click", _stateDelegate); }'
)

# ---- Anchor C: renderRank note -> omit for state ----
C_OLD = '  document.getElementById(cardId).innerHTML=rows+\'<div class="card-note">\'+note+\'</div>\';'
C_NEW = (
    '  var noteHtml = kind==="state" ? "" : \'<div class="card-note">\'+note+\'</div>\';\n'
    '  document.getElementById(cardId).innerHTML=rows+noteHtml;'
)

# ---- Anchor D: CSS before </style> ----
D_OLD = '</style>'
D_NEW = (
    '.wstate-sel{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}\n'
    '.wstate-sel button{font:inherit;font-size:12px;padding:7px 10px;border-radius:8px;background:var(--card2);border:1px solid var(--line);color:var(--txt2);cursor:pointer;display:flex;align-items:center;gap:5px}\n'
    '.wstate-sel button span{color:var(--txt);font-weight:600;font-variant-numeric:tabular-nums}\n'
    '.wstate-sel button[disabled]{opacity:.38;cursor:default}\n'
    '.wstate-sel button:focus-visible{outline:1px solid var(--teal);outline-offset:1px}\n'
    '.wstate-sel button[aria-expanded="true"]{border-color:var(--teal);color:var(--txt)}\n'
    '#statePanel{max-height:340px;overflow-y:auto;margin-top:10px}\n'
    '</style>'
)

def sha_b(p):
    d = open(p, "rb").read(); return hashlib.sha256(d).hexdigest(), len(d)
def read(p):
    return open(p, "r", encoding="utf-8").read()

for p in (WJS, WHT):
    if not os.path.isfile(p): sys.exit("ABORT: missing " + p)
js = read(WJS); ht = read(WHT)

# double-apply guard
if "STATE_META" in js or "wstate-sel" in js or "wstate-sel" in ht:
    sys.exit("ABORT: STATE_META/wstate-sel already present (already applied?)")

for name, anc, src in [("A", A_OLD, "js"), ("B", B_OLD, "js"), ("C", C_OLD, "js"), ("D", D_OLD, "ht")]:
    hay = js if src == "js" else ht
    c = hay.count(anc)
    if c != 1:
        sys.exit("ABORT: anchor %s count %d (expect 1)" % (name, c))

js2 = js.replace(A_OLD, A_NEW, 1).replace(B_OLD, B_NEW, 1).replace(C_OLD, C_NEW, 1)
ht2 = ht.replace(D_OLD, D_NEW, 1)

checks_js = [
    ('var STATE_META = Object.freeze(', 1),
    ('function toggleStatePanel(state)', 1),
    ('function getStateLabel(meta)', 1),
    ('function renderStateControls()', 1),
    ('kind==="state" ? "" :', 1),
    ('addEventListener("click", _stateDelegate)', 1),
    ('renderRank("statePanel", rows, "state", THEME_OF)', 1),
]
for needle, want in checks_js:
    if js2.count(needle) != want:
        sys.exit("ABORT: js post-check '%s' = %d (expect %d)" % (needle, js2.count(needle), want))
if ht2.count('.wstate-sel button') < 1 or ht2.count('#statePanel{') != 1:
    sys.exit("ABORT: html css post-check failed")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = os.environ.get("BK_DIR", "/root/f29-backups/p05b2-" + ts)
os.makedirs(bdir, exist_ok=False)
shutil.copy2(WJS, os.path.join(bdir, "weight.js"))
shutil.copy2(WHT, os.path.join(bdir, "weight.html"))
sj0, bj0 = sha_b(WJS); sh0, bh0 = sha_b(WHT)
open(os.path.join(bdir, "manifest.txt"), "w").write(
    "weight.js sha=%s bytes=%d\nweight.html sha=%s bytes=%d\nutc=%s\n" % (sj0, bj0, sh0, bh0, ts))

tj = WJS + ".tmp." + ts; th = WHT + ".tmp." + ts
open(tj, "w", encoding="utf-8").write(js2)
open(th, "w", encoding="utf-8").write(ht2)
os.replace(tj, WJS); os.replace(th, WHT)
sj1, bj1 = sha_b(WJS); sh1, bh1 = sha_b(WHT)
print("OK")
print("backup_dir=" + bdir)
print("weight.js  before=%s/%d after=%s/%d" % (sj0, bj0, sj1, bj1))
print("weight.html before=%s/%d after=%s/%d" % (sh0, bh0, sh1, bh1))
