#!/usr/bin/env python3
# F29 PREFLIGHT 3 - real token / cost probe (2026-07-18)
# Measurement only. No cron, no auto-publish, no latest, no archive operations.
# Fetch localhost -> validate -> build prompt -> API call -> save evidence under /tmp.

import json, os, re, sys, time, uuid, hashlib, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone

ENV = "/root/moneyflow/.env"
MODEL = "claude-opus-4-8"
URL = "http://127.0.0.1:3001/api/briefing-context"
PROMPT_FILE = "/root/moneyflow/preflight_macro_prompt.txt"
MAX_TOKENS = 8000
PRICE_IN = 5.0 / 1_000_000
PRICE_OUT = 25.0 / 1_000_000

def sha(b):
    return hashlib.sha256(b).hexdigest()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def fail(msg):
    print("FAIL: " + msg); sys.exit(1)

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
outdir = "/tmp/f29_preflight3/" + run_id
os.makedirs(outdir, exist_ok=True)

# ---- 1. fetch (transport freshness measured) ----
fetch_started = now_iso()
t0 = time.time()
try:
    raw = subprocess.check_output(["curl", "-fsS", URL], timeout=60)
except Exception as e:
    fail("fetch failed: %s" % type(e).__name__)
t1 = time.time()
fetch_completed = now_iso()
snapshot_sha = sha(raw)
open(os.path.join(outdir, "briefing_context_raw.json"), "wb").write(raw)

d = json.loads(raw.decode("utf-8"))
src_generated = d.get("generated")
print("fetch_started_at  :", fetch_started)
print("fetch_completed_at:", fetch_completed)
print("source_generated  :", src_generated)
print("fetch_elapsed_sec : %.3f" % (t1 - t0))
print("snapshot_sha256   :", snapshot_sha)
print("raw bytes         :", len(raw))

# ---- 2. validate (transport + market data layers) ----
gen_ts = None
try:
    gen_ts = datetime.fromisoformat(src_generated.replace("Z", "+00:00")).timestamp()
except Exception:
    fail("generated unparsable")
if not (t0 - 2 <= gen_ts <= t1 + 2):
    fail("transport freshness: generated outside fetch window (cache suspected)")
if (t1 - t0) > 10:
    fail("fetch took too long")

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

# ---- 3. build prompt ----
try:
    tmpl = open(PROMPT_FILE, encoding="utf-8").read()
except Exception as e:
    fail("prompt file missing: %s" % PROMPT_FILE)
prompt = tmpl + "\n" + json.dumps(d, ensure_ascii=False, indent=1) + "\n"
pb = prompt.encode("utf-8")
prompt_sha = sha(pb)
open(os.path.join(outdir, "prompt.txt"), "wb").write(pb)
print("prompt_sha256     :", prompt_sha)
print("prompt bytes      :", len(pb))

# ---- 4. API call ----
env = open(ENV, encoding="utf-8").read()
m = re.search(r"^ANTHROPIC_API_KEY=(.+)$", env, re.M)
if not m:
    fail("ANTHROPIC_API_KEY not found")
key = m.group(1).strip()

body = json.dumps({
    "model": MODEL,
    "max_tokens": MAX_TOKENS,
    "messages": [{"role": "user", "content": prompt}]
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=body,
    headers={"content-type": "application/json", "x-api-key": key,
             "anthropic-version": "2023-06-01"},
    method="POST",
)
call_started = now_iso()
c0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.loads(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("FAIL: HTTP %d" % e.code)
    print(e.read().decode("utf-8", "replace")[:400]); sys.exit(1)
except Exception as e:
    fail("api call: %s %s" % (type(e).__name__, str(e)[:200]))
c1 = time.time()

text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
ob = text.encode("utf-8")
open(os.path.join(outdir, "response.txt"), "wb").write(ob)
u = resp.get("usage", {})
it = u.get("input_tokens") or 0
ot = u.get("output_tokens") or 0
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
print("output_sha256     :", sha(ob))

evidence = {
    "run_id": run_id, "model": MODEL,
    "fetch_started_at": fetch_started, "fetch_completed_at": fetch_completed,
    "source_generated_at": src_generated,
    "call_started_at": call_started,
    "snapshot_sha256": snapshot_sha, "prompt_sha256": prompt_sha, "output_sha256": sha(ob),
    "input_tokens": it, "output_tokens": ot,
    "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
    "cache_read_input_tokens": u.get("cache_read_input_tokens"),
    "stop_reason": resp.get("stop_reason"),
    "cost_usd": round(cost, 4), "output_chars": len(text),
    "close_snapshot_state": cs_state, "daily_state": dy_state,
    "as_of": d.get("as_of"), "status": "probe_only",
}
open(os.path.join(outdir, "evidence.json"), "w", encoding="utf-8").write(
    json.dumps(evidence, ensure_ascii=False, indent=2))
print("evidence dir      :", outdir)
print("PROBE: DONE")
