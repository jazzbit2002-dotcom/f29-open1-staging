#!/usr/bin/env python3
# P0-5B-2c: state button 3-tone color (control-room req 3.3, tokens only). Increment on colorless live. 2-file atomic.
import hashlib, os, shutil, sys
from datetime import datetime, timezone

WJS = os.environ.get("WJS", "/root/krx-moneyflow/web/weight.js")
WHT = os.environ.get("WHT", "/root/krx-moneyflow/web/weight.html")

# A: STATE_TONE before STATE_META (weight.js)
A_OLD = 'var STATE_META = Object.freeze(['
A_NEW = (
    '// F29 state color contract (control-room request 3.3). Existing CSS tokens only; red-tier = --down (page canonical).\n'
    'var STATE_TONE = Object.freeze({\n'
    '  up_concentration:"teal", attention_up:"teal", fade_up:"teal",\n'
    '  neutral:"gold", fade_down:"gold",\n'
    '  down_concentration:"down"\n'
    '});\n'
    'var STATE_META = Object.freeze(['
)

# B: button class injection (weight.js)
B_OLD = 'class="wstate-btn" data-state="\'+meta.state+\'"'
B_NEW = 'class="wstate-btn wstate-\'+STATE_TONE[meta.state]+\'" data-state="\'+meta.state+\'"'

# C: CSS active rule (teal-only) -> 3-tone, specificity-scoped (weight.html)
C_OLD = '.wstate-sel button[aria-expanded="true"]{border-color:var(--teal);color:var(--txt)}'
C_NEW = (
    '.wstate-sel button.wstate-teal{border-color:var(--teal)}\n'
    '.wstate-sel button.wstate-gold{border-color:var(--gold)}\n'
    '.wstate-sel button.wstate-down{border-color:var(--down)}\n'
    '.wstate-sel button.wstate-teal[aria-expanded="true"]{color:var(--teal)}\n'
    '.wstate-sel button.wstate-gold[aria-expanded="true"]{color:var(--gold)}\n'
    '.wstate-sel button.wstate-down[aria-expanded="true"]{color:var(--down)}'
)

def sha_b(p):
    d = open(p, "rb").read(); return hashlib.sha256(d).hexdigest(), len(d)
def read(p):
    return open(p, "r", encoding="utf-8").read()

for p in (WJS, WHT):
    if not os.path.isfile(p): sys.exit("ABORT: missing " + p)
js = read(WJS); ht = read(WHT)

if "STATE_TONE" in js or "wstate-teal" in ht:
    sys.exit("ABORT: STATE_TONE/wstate-teal already present (already applied?)")

for name, anc, src in [("A", A_OLD, "js"), ("B", B_OLD, "js"), ("C", C_OLD, "ht")]:
    hay = js if src == "js" else ht
    if hay.count(anc) != 1:
        sys.exit("ABORT: anchor %s count %d (expect 1)" % (name, hay.count(anc)))

js2 = js.replace(A_OLD, A_NEW, 1).replace(B_OLD, B_NEW, 1)
ht2 = ht.replace(C_OLD, C_NEW, 1)

# post-check
if js2.count('var STATE_TONE = Object.freeze(') != 1: sys.exit("ABORT: STATE_TONE missing")
if js2.count('wstate-\'+STATE_TONE[meta.state]+\'"') != 1: sys.exit("ABORT: button tone class missing")
for needle in ['button.wstate-teal{border-color:var(--teal)}',
               'button.wstate-gold{border-color:var(--gold)}',
               'button.wstate-down{border-color:var(--down)}']:
    if ht2.count(needle) != 1: sys.exit("ABORT: css '%s' missing" % needle)
if '--red' in ht2 and ht2.count('--red') != ht.count('--red'):
    sys.exit("ABORT: --red introduced")
# no new hex in inserted CSS block (C_NEW uses only var())
import re
if re.search(r'#[0-9A-Fa-f]{6}', C_NEW):
    sys.exit("ABORT: new hex in CSS")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = os.environ.get("BK_DIR", "/root/f29-backups/p05b2c-" + ts)
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
