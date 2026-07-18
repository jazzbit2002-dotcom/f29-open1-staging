#!/usr/bin/env python3
# F29 US MACRO DELIVERY (2026-07-18)
# fetch -> validate -> store snapshot (as_of keyed) -> T-1 delta -> envelope -> [API probe]
# No new collector, no DB, no cron, no auto-publish. Delivery layer only.
#
# usage:
#   python3 us_macro_delivery.py --store-only   # baseline: fetch/validate/store, no API call
#   python3 us_macro_delivery.py                # full: + comparison + prompt + API + evidence

import json, os, re, sys, time, uuid, hashlib, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone

ENV = "/root/moneyflow/.env"
MODEL = "claude-opus-4-8"
URL = "http://127.0.0.1:3001/api/briefing-context"
PROMPT_FILE = "/root/moneyflow/macro_prompt_v2.txt"
BASE = "/root/moneyflow/briefing_delivery"
SNAPDIR = os.path.join(BASE, "snapshots", "us-close")
EVIDIR = os.path.join(BASE, "evidence")
MAX_TOKENS = 8000
PRICE_IN = 5.0 / 1_000_000
PRICE_OUT = 25.0 / 1_000_000

PRICE_FIELDS = ["spy","qqq","iwm","rsp","es1","nq1","ym1","hyg","lqd","srln",
                "soxx","xlp","xly","xlf","xlk","dxy","cl1","brn1","usdjpy"]
RATE_FIELDS = ["tnx","us02y"]
VOL_FIELDS = ["vix","move"]
RELATIVE = [
    ("large_vs_small", "spy", "iwm"),
    ("capweight_vs_equalweight", "spy", "rsp"),
    ("nasdaq_vs_market", "qqq", "spy"),
    ("semi_vs_tech", "soxx", "xlk"),
    ("cyclical_vs_staples", "xly", "xlp"),
]

STORE_ONLY = "--store-only" in sys.argv

def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def now_iso(): return datetime.now(timezone.utc).isoformat()
def fail(msg):
    print("FAIL: " + msg); sys.exit(1)

os.makedirs(SNAPDIR, exist_ok=True)
os.makedirs(EVIDIR, exist_ok=True)

# ---------- 1. fetch ----------
fetch_started = now_iso(); t0 = time.time()
try:
    raw = subprocess.check_output(["curl", "-fsS", URL], timeout=60)
except Exception as e:
    fail("fetch failed: %s" % type(e).__name__)
t1 = time.time(); fetch_completed = now_iso()
snapshot_sha = sha_bytes(raw)
d = json.loads(raw.decode("utf-8"))
print("fetch_started_at  :", fetch_started)
print("fetch_completed_at:", fetch_completed)
print("source_generated  :", d.get("generated"))
print("fetch_elapsed_sec : %.3f" % (t1 - t0))
print("raw bytes         :", len(raw))

# ---------- 2. validate ----------
try:
    gen_ts = datetime.fromisoformat(str(d.get("generated")).replace("Z", "+00:00")).timestamp()
except Exception:
    fail("generated unparsable")
if not (t0 - 2 <= gen_ts <= t1 + 2):
    fail("transport freshness: generated outside fetch window (cache suspected)")
if (t1 - t0) > 10:
    fail("fetch too slow")

mi = d.get("market_internals") or {}
cs = mi.get("market_close_snapshot") or {}
dy = mi.get("daily") or {}
cs_state = (cs.get("freshness") or {}).get("state")
dy_state = (dy.get("freshness") or {}).get("state")
print("close_snapshot    :", cs_state, "| as_of", cs.get("as_of"), "| fields", len(cs.get("data") or {}))
print("daily             :", dy_state, "| as_of", dy.get("as_of"))
if cs_state != "fresh":
    fail("market_close_snapshot not fresh: %s" % cs_state)
if d.get("as_of") != cs.get("as_of"):
    fail("top-level as_of != close_snapshot as_of")
print("VALIDATION: PASS")

# ---------- 3. store snapshot (as_of keyed) ----------
cur_as_of = cs.get("as_of")
cur_data = cs.get("data") or {}
canon = json.dumps({"as_of": cur_as_of, "bar_ts": cs.get("bar_ts"),
                    "reference_rule": cs.get("reference_rule"), "data": cur_data},
                   sort_keys=True, ensure_ascii=False, separators=(",", ":"))
cur_hash = sha_bytes(canon.encode("utf-8"))
snap = {"as_of": cur_as_of, "bar_ts": cs.get("bar_ts"),
        "source_updated": cs.get("updated"), "reference_rule": cs.get("reference_rule"),
        "data_sha256": cur_hash, "stored_at": now_iso(), "data": cur_data}
path = os.path.join(SNAPDIR, cur_as_of + ".json")

if os.path.exists(path):
    old = json.load(open(path, encoding="utf-8"))
    if old.get("data_sha256") == cur_hash:
        store_status = "noop"
        print("snapshot store    : noop (same as_of, same data hash)")
    else:
        store_status = "conflict"
        cpath = os.path.join(SNAPDIR, cur_as_of + ".conflict." + datetime.now(timezone.utc).strftime("%H%M%SZ") + ".json")
        json.dump({"existing_sha": old.get("data_sha256"), "incoming_sha": cur_hash,
                   "incoming": snap, "detected_at": now_iso()},
                  open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("snapshot store    : CONFLICT (same as_of, different data hash)")
        print("conflict record   :", cpath)
        print("HOLD: existing snapshot NOT overwritten. canary must not proceed.")
        sys.exit(2)
else:
    tmp = path + ".tmp"
    json.dump(snap, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    store_status = "saved"
    print("snapshot store    : saved ->", path)
print("data_sha256       :", cur_hash)

# ---------- 4. load previous (different as_of, latest before current) ----------
prev = None
cands = []
for fn in os.listdir(SNAPDIR):
    if not re.match(r"^\d{4}-\d{2}-\d{2}\.json$", fn):
        continue
    a = fn[:-5]
    if a < cur_as_of:
        cands.append(a)
if cands:
    pa = max(cands)
    prev = json.load(open(os.path.join(SNAPDIR, pa + ".json"), encoding="utf-8"))
print("previous snapshot :", prev.get("as_of") if prev else "none")

# ---------- 5. comparison ----------
def num(x):
    try:
        v = float(x); return v if v == v else None
    except Exception:
        return None

if prev is None:
    comparison = {"market_close_comparison": {
        "status": "baseline_only", "current_as_of": cur_as_of, "previous_as_of": None}}
    print("comparison        : baseline_only (no prior session stored)")
else:
    pd_ = prev.get("data") or {}
    price, rate, vol = {}, {}, {}
    for f in PRICE_FIELDS:
        c, p = num(cur_data.get(f)), num(pd_.get(f))
        if c is not None and p not in (None, 0):
            price[f] = round((c / p - 1) * 100, 3)
    for f in RATE_FIELDS:
        c, p = num(cur_data.get(f)), num(pd_.get(f))
        if c is not None and p is not None:
            rate[f] = round((c - p) * 100, 1)
    for f in VOL_FIELDS:
        c, p = num(cur_data.get(f)), num(pd_.get(f))
        if c is not None and p not in (None, 0):
            vol[f] = {"points": round(c - p, 3), "pct": round((c / p - 1) * 100, 2)}
    rel = {}
    for name, a, b in RELATIVE:
        if a in price and b in price:
            rel[name] = round(price[a] - price[b], 3)
    comparison = {"market_close_comparison": {
        "status": "ready",
        "current_as_of": cur_as_of,
        "previous_as_of": prev.get("as_of"),
        "reference_label": "\uc9c1\uc804 \ubcf4\uc874 \ubbf8\uad6d \uac70\ub798 \uc138\uc158 \ub300\ube44",
        "price_change_pct": price,
        "rate_change_bp": rate,
        "volatility_change": vol,
        "relative_performance_pct": rel}}
    print("comparison        : ready (%s -> %s), price %d / rate %d / vol %d / rel %d"
          % (prev.get("as_of"), cur_as_of, len(price), len(rate), len(vol), len(rel)))

if STORE_ONLY:
    print("STORE_ONLY: done (no API call)")
    sys.exit(0)

# ---------- 6. prompt ----------
try:
    tmpl = open(PROMPT_FILE, encoding="utf-8").read()
except Exception:
    fail("prompt file missing: %s" % PROMPT_FILE)
payload = dict(d); payload.update(comparison)
prompt = tmpl + "\n" + json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
pb = prompt.encode("utf-8"); prompt_sha = sha_bytes(pb)
print("prompt_sha256     :", prompt_sha)
print("prompt bytes      :", len(pb))

# ---------- 7. API ----------
env = open(ENV, encoding="utf-8").read()
m = re.search(r"^ANTHROPIC_API_KEY=(.+)$", env, re.M)
if not m: fail("ANTHROPIC_API_KEY not found")
key = m.group(1).strip()
body = json.dumps({"model": MODEL, "max_tokens": MAX_TOKENS,
                   "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
    headers={"content-type": "application/json", "x-api-key": key,
             "anthropic-version": "2023-06-01"}, method="POST")
c0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.loads(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("FAIL: HTTP %d" % e.code); print(e.read().decode("utf-8", "replace")[:400]); sys.exit(1)
except Exception as e:
    fail("api call: %s %s" % (type(e).__name__, str(e)[:200]))
c1 = time.time()

text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
ob = text.encode("utf-8")
u = resp.get("usage", {})
it = u.get("input_tokens") or 0; ot = u.get("output_tokens") or 0
cost = it * PRICE_IN + ot * PRICE_OUT
print("--- USAGE ---")
print("model             :", resp.get("model"))
print("stop_reason       :", resp.get("stop_reason"))
print("input_tokens      :", it)
print("output_tokens     :", ot)
print("cache_creation    :", u.get("cache_creation_input_tokens"))
print("cache_read        :", u.get("cache_read_input_tokens"))
print("api_elapsed_sec   : %.1f" % (c1 - c0))
print("cost_usd          : %.4f" % cost)
print("output chars      :", len(text))

# ---------- 8. evidence (immutable, no latest) ----------
run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
outdir = os.path.join(EVIDIR, run_id); os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "briefing_context_raw.json"), "wb").write(raw)
open(os.path.join(outdir, "prompt.txt"), "wb").write(pb)
open(os.path.join(outdir, "response.txt"), "wb").write(ob)
json.dump(comparison, open(os.path.join(outdir, "comparison.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
evidence = {"run_id": run_id, "model": MODEL,
    "fetch_started_at": fetch_started, "fetch_completed_at": fetch_completed,
    "source_generated_at": d.get("generated"),
    "snapshot_sha256": snapshot_sha, "prompt_sha256": prompt_sha, "output_sha256": sha_bytes(ob),
    "close_snapshot_data_sha256": cur_hash, "snapshot_store_status": store_status,
    "current_as_of": cur_as_of, "previous_as_of": (prev or {}).get("as_of"),
    "comparison_status": comparison["market_close_comparison"]["status"],
    "input_tokens": it, "output_tokens": ot,
    "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
    "cache_read_input_tokens": u.get("cache_read_input_tokens"),
    "stop_reason": resp.get("stop_reason"), "cost_usd": round(cost, 4),
    "output_chars": len(text), "close_snapshot_state": cs_state, "daily_state": dy_state,
    "status": "draft_saved"}
json.dump(evidence, open(os.path.join(outdir, "evidence.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("evidence dir      :", outdir)
print("DELIVERY: DONE")
