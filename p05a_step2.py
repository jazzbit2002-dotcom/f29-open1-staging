#!/usr/bin/env python3
# P0-5A step2: weight search wiring. 2-file atomic, count-gated, ASCII script (CJK via \u escapes).
import hashlib, os, shutil, sys
from datetime import datetime, timezone

WJS = "/root/krx-moneyflow/web/weight.js"
WHT = "/root/krx-moneyflow/web/weight.html"

# ---- Anchors (exact, each must appear 1x) ----
A_OLD = '  <div class="label">\uc624\ub298\uc758 \ub3c8\uc758 \ubb34\uac8c</div>'
A_NEW = (
    '  <div class="card mystock-card" id="myStockCard">\n'
    '    <div class="mystock-label">\ub0b4 \uc885\ubaa9 \uac80\uc0c9</div>\n'
    '    <input id="myStockSearch" type="text" inputmode="search" autocomplete="off"\n'
    '       placeholder="\uc885\ubaa9\uba85 \ub610\ub294 6\uc790\ub9ac \ucf54\ub4dc (\uc608: \uc0bc\uc131\uc804\uc790 \u00b7 005930)">\n'
    '    <div id="f29-search-results" hidden></div>\n'
    '  </div>\n'
    '  <div class="label">\uc624\ub298\uc758 \ub3c8\uc758 \ubb34\uac8c</div>'
)

B_OLD = '<script src="/weight/weight.js?v=202607151200"></script>'
B_NEW = (
    '<script src="/assets/f29-search.js?v=20260715a" defer></script>\n'
    '<script src="/weight/weight.js?v=20260715b"></script>'
)

C_OLD = 'document.addEventListener("DOMContentLoaded", bootWeight);'
C_NEW = (
    'document.addEventListener("DOMContentLoaded", function(){\n'
    '  bootWeight();\n'
    '  var _si = document.getElementById("myStockSearch");\n'
    '  if (_si && window.F29Search && !_si.dataset.wired) {\n'
    '    _si.dataset.wired = "1";\n'
    '    F29Search.init(_si, {\n'
    '      onStockSelect: function(stock, queryType){\n'
    '        openStockSheet(stock.c, stock.n || stock.c);\n'
    '      }\n'
    '    });\n'
    '  }\n'
    '});'
)

D_OLD = '</style>'
D_NEW = (
    '.mystock-card{padding:14px 16px}\n'
    '.mystock-label{display:block;font-size:13px;color:var(--txt2);margin-bottom:8px}\n'
    '#myStockSearch{width:100%;box-sizing:border-box;padding:11px 13px;background:var(--card2);border:1px solid var(--line);border-radius:10px;color:var(--txt);font-size:15px;outline:none}\n'
    '#myStockSearch:focus{border-color:var(--teal)}\n'
    '#f29-search-results{margin-top:8px}\n'
    '#f29-search-results .f29-cand{display:block;width:100%;text-align:left;padding:10px 12px;background:var(--card2);border:1px solid var(--line);border-radius:8px;color:var(--txt);font-size:14px;margin-top:6px;cursor:pointer}\n'
    '#f29-search-results .f29-cand:hover{border-color:var(--teal)}\n'
    '#f29-search-results .f29-fail{padding:12px;color:var(--txt2);font-size:13px}\n'
    '</style>'
)

def sha_b(p):
    d = open(p, "rb").read()
    return hashlib.sha256(d).hexdigest(), len(d)
def read(p):
    return open(p, "r", encoding="utf-8").read()

for p in (WJS, WHT):
    if not os.path.isfile(p): sys.exit("ABORT: missing " + p)

js = read(WJS)
ht = read(WHT)

# ---- Gate: each anchor exactly 1x ----
for name, anc, src in [("A", A_OLD, "ht"), ("B", B_OLD, "ht"), ("D", D_OLD, "ht"), ("C", C_OLD, "js")]:
    haystack = ht if src == "ht" else js
    c = haystack.count(anc)
    if c != 1:
        sys.exit("ABORT: anchor %s count %d (expect 1)" % (name, c))

# guard: no double-apply
if "myStockSearch" in ht or "myStockSearch" in js:
    sys.exit("ABORT: myStockSearch already present (already applied?)")

# ---- Apply in memory ----
ht2 = ht.replace(A_OLD, A_NEW, 1).replace(B_OLD, B_NEW, 1).replace(D_OLD, D_NEW, 1)
js2 = js.replace(C_OLD, C_NEW, 1)

# ---- Post-check in memory ----
assert_pairs = [
    (ht2, 'id="myStockSearch"', 1),
    (ht2, 'id="f29-search-results"', 1),
    (ht2, '/assets/f29-search.js?v=20260715a', 1),
    (ht2, '/weight/weight.js?v=20260715b', 1),
    (ht2, 'weight.js?v=202607151200', 0),
    (js2, "F29Search.init(_si", 1),
    (js2, "openStockSheet(stock.c", 1),
]
for h, needle, want in assert_pairs:
    got = h.count(needle)
    if got != want:
        sys.exit("ABORT: post-check '%s' = %d (expect %d)" % (needle, got, want))

# ---- Backup ----
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = "/root/f29-backups/p05a-step2-" + ts
os.makedirs(bdir, exist_ok=False)
shutil.copy2(WJS, os.path.join(bdir, "weight.js"))
shutil.copy2(WHT, os.path.join(bdir, "weight.html"))
sha_j0, b_j0 = sha_b(WJS)
sha_h0, b_h0 = sha_b(WHT)
open(os.path.join(bdir, "manifest.txt"), "w").write(
    "weight.js  sha256_before=%s bytes=%d\nweight.html sha256_before=%s bytes=%d\nutc=%s\n" % (sha_j0, b_j0, sha_h0, b_h0, ts)
)

# ---- Atomic write both ----
tmp_j = WJS + ".tmp." + ts
tmp_h = WHT + ".tmp." + ts
open(tmp_j, "w", encoding="utf-8").write(js2)
open(tmp_h, "w", encoding="utf-8").write(ht2)
os.replace(tmp_j, WJS)
os.replace(tmp_h, WHT)

sha_j1, b_j1 = sha_b(WJS)
sha_h1, b_h1 = sha_b(WHT)
print("OK")
print("backup_dir=" + bdir)
print("weight.js  before=%s/%d after=%s/%d" % (sha_j0, b_j0, sha_j1, b_j1))
print("weight.html before=%s/%d after=%s/%d" % (sha_h0, b_h0, sha_h1, b_h1))
