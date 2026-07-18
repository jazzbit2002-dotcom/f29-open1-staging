#!/usr/bin/env python3
# F29 PREFLIGHT 2 - Anthropic API auth / model access check (2026-07-18)
# Proves: key loads from .env, auth succeeds, model reachable, usage returned.
# Does NOT print the key, headers, or .env contents. Minimal call only.

import json, os, re, sys, urllib.request, urllib.error

ENV = "/root/moneyflow/.env"
MODEL = "claude-opus-4-8"

try:
    env = open(ENV, encoding="utf-8").read()
except Exception as e:
    print("FAIL: cannot read .env:", type(e).__name__); sys.exit(1)
m = re.search(r"^ANTHROPIC_API_KEY=(.+)$", env, re.M)
if not m:
    print("FAIL: ANTHROPIC_API_KEY not found in .env"); sys.exit(1)
key = m.group(1).strip()
print("key loaded: yes (value not shown), length_class=%s" % ("ok" if len(key) > 20 else "SUSPICIOUS"))

st = os.stat(ENV)
print("env perms: %o" % (st.st_mode & 0o777))

body = json.dumps({
    "model": MODEL,
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "Reply with exactly: ok"}]
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=body,
    headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as r:
        status = r.status
        d = json.loads(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    detail = e.read().decode("utf-8", "replace")[:400]
    print("FAIL: HTTP %d" % e.code)
    print("error body:", detail)
    sys.exit(1)
except Exception as e:
    print("FAIL:", type(e).__name__, str(e)[:300]); sys.exit(1)

txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
u = d.get("usage", {})
print("HTTP:", status)
print("model:", d.get("model"))
print("stop_reason:", d.get("stop_reason"))
print("input_tokens:", u.get("input_tokens"))
print("output_tokens:", u.get("output_tokens"))
print("cache_creation_input_tokens:", u.get("cache_creation_input_tokens"))
print("cache_read_input_tokens:", u.get("cache_read_input_tokens"))
print("text:", txt.strip()[:50])
print("API_PREFLIGHT: PASS")
