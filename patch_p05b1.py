#!/usr/bin/env python3
# P0-5B-1: add stateLists (6-key fixed) + normalize counts (6-key) + require() gates to build_weight.py
# ASCII-only (CJK via \u), literal-anchor str.replace, count-gated, atomic, backup.
import hashlib, os, shutil, sys
from datetime import datetime, timezone

TARGET = os.environ.get("BW_TARGET", "/root/krx-moneyflow/build_weight.py")

A_OLD = '    buy = [r for r in ranks if r["flowState"] == "up_concentration"]'
A_NEW = (
    '    STATE_ORDER = ("up_concentration", "down_concentration", "attention_up", "fade_up", "neutral", "fade_down")\n'
    '    def require(cond, msg):\n'
    '        if not cond:\n'
    '            raise RuntimeError(msg)\n'
    '    buy = [r for r in ranks if r["flowState"] == "up_concentration"]'
)

B_OLD = (
    '    # \uc0c1\ud0dc\ubcc4 \uac1c\uc218 (\uc694\uc57d \uce74\ub4dc\uc6a9)\n'
    '    counts = {}\n'
    '    for r in ranks:\n'
    '        st = r["flowState"]\n'
    '        counts[st] = counts.get(st, 0) + 1'
)
B_NEW = (
    '    # state counts + per-state stock lists (6-key normalized)\n'
    '    state_lists = {st: [] for st in STATE_ORDER}\n'
    '    counts = {st: 0 for st in STATE_ORDER}\n'
    '    for r in ranks:\n'
    '        _st = r["flowState"]\n'
    '        if _st not in state_lists:\n'
    '            raise RuntimeError("unknown flowState: " + str(_st))\n'
    '        state_lists[_st].append(slim(r))\n'
    '        counts[_st] += 1'
)

C_OLD = (
    '        "buyPressure": [slim(r) for r in buy],\n'
    '        "sellPressure": [slim(r) for r in sell]\n'
    '    }'
)
C_NEW = (
    '        "buyPressure": [slim(r) for r in buy],\n'
    '        "sellPressure": [slim(r) for r in sell],\n'
    '        "stateLists": state_lists\n'
    '    }'
)

D_OLD = '    assert sum(counts.values()) == ok, f"counts sum {sum(counts.values())} != targetCount {ok}"'
D_NEW = (
    D_OLD + '\n'
    '    require(tuple(state_lists.keys()) == STATE_ORDER, "stateLists key order drift")\n'
    '    for _st in STATE_ORDER:\n'
    '        require(len(state_lists[_st]) == counts[_st], "stateLists[" + _st + "] len != counts")\n'
    '    require(sum(len(v) for v in state_lists.values()) == ok, "stateLists total != targetCount")\n'
    '    _allc = [r["code"] for rows in state_lists.values() for r in rows]\n'
    '    require(len(_allc) == ok, "stateLists row total mismatch")\n'
    '    require(len(set(_allc)) == ok, "stateLists code uniqueness fail")\n'
    '    require({r["code"] for r in out["buyPressure"]} == {r["code"] for r in state_lists["up_concentration"]}, "buyPressure/stateLists set mismatch")\n'
    '    require({r["code"] for r in out["sellPressure"]} == {r["code"] for r in state_lists["down_concentration"]}, "sellPressure/stateLists set mismatch")'
)

def sha_b(p):
    d = open(p, "rb").read()
    return hashlib.sha256(d).hexdigest(), len(d)

if not os.path.isfile(TARGET): sys.exit("ABORT: missing " + TARGET)
src = open(TARGET, "r", encoding="utf-8").read()

# double-apply guard
if "STATE_ORDER" in src or "stateLists" in src:
    sys.exit("ABORT: STATE_ORDER/stateLists already present (already applied?)")

# gate: each anchor exactly 1x
for name, anc in [("A", A_OLD), ("B", B_OLD), ("C", C_OLD), ("D", D_OLD)]:
    c = src.count(anc)
    if c != 1:
        sys.exit("ABORT: anchor %s count %d (expect 1)" % (name, c))

out = src.replace(A_OLD, A_NEW, 1).replace(B_OLD, B_NEW, 1).replace(C_OLD, C_NEW, 1).replace(D_OLD, D_NEW, 1)

# post-check
checks = [
    ('STATE_ORDER = (', 1),
    ('def require(cond, msg):', 1),
    ('state_lists = {st: [] for st in STATE_ORDER}', 1),
    ('counts = {st: 0 for st in STATE_ORDER}', 1),
    ('"stateLists": state_lists', 1),
    ('counts = {}', 0),
    ('stateLists code uniqueness fail', 1),
    ('buyPressure/stateLists set mismatch', 1),
    ('sellPressure/stateLists set mismatch', 1),
]
for needle, want in checks:
    got = out.count(needle)
    if got != want:
        sys.exit("ABORT: post-check '%s' = %d (expect %d)" % (needle, got, want))

# compile check on patched content
import py_compile, tempfile
_tmp = TARGET + ".compilecheck.tmp"
open(_tmp, "w", encoding="utf-8").write(out)
try:
    py_compile.compile(_tmp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(_tmp); sys.exit("ABORT: patched content does not compile: %s" % e)
os.remove(_tmp)

# backup
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
bdir = os.environ.get("BW_BACKUP_DIR", "/root/f29-backups/p05b1-" + ts)
os.makedirs(bdir, exist_ok=False)
shutil.copy2(TARGET, os.path.join(bdir, os.path.basename(TARGET)))
sha0, b0 = sha_b(TARGET)
open(os.path.join(bdir, "manifest.txt"), "w").write(
    "%s sha256_before=%s bytes=%d utc=%s\n" % (TARGET, sha0, b0, ts))

# atomic write
tmp = TARGET + ".tmp." + ts
open(tmp, "w", encoding="utf-8").write(out)
os.replace(tmp, TARGET)
sha1, b1 = sha_b(TARGET)
print("OK")
print("backup_dir=" + bdir)
print("build_weight.py before=%s/%d after=%s/%d" % (sha0, b0, sha1, b1))
