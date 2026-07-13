import io, os, sys, hashlib, tempfile

TARGET = sys.argv[1] if len(sys.argv) > 1 else '/var/www/f29/assets/f29-search.js'
DRYRUN = '--apply' not in sys.argv
MARKER = 'v1.9.1+D1+S1+S2'

A1_OLD = "/* f29-search.js \u2014 v1.9.1+D1+S1 (\uc2e4\uc2dc\uac04 \uc811\ub450 \uc790\ub3d9\uc644\uc131 \ubcf5\uc6d0 2026-07-13). \uc758\uc874: f29-metrics.js (F29M.track) */"
A1_NEW = "/* f29-search.js \u2014 v1.9.1+D1+S1+S2 (\uc2e4\uc2dc\uac04 \uc790\ub3d9\uc644\uc131 + \uc815\uc2dd\uba85 \ubd80\ubd84\uc77c\uce58 \ud68c\uadc0 \ubcf5\uad6c 2026-07-13). \uc758\uc874: f29-metrics.js (F29M.track) */"

# --- anchor 2: route() tail (US/crypto/fail) ---
A2_OLD = """    const usKey = q.trim().toUpperCase();                        // \u2464 \ubbf8\uad6d \u2014 \ubcc4\uce6d\uc740 \ud2f0\ucee4\ub85c \ubcc0\ud658
    if (US_ALIAS.has(usKey)) return { type: 'us', ticker: US_ALIAS.get(usKey) };
    if (CRYPTO[usKey] || CRYPTO[q.trim()])                       // \u2465 \ud06c\ub9bd\ud1a0
      return { type: 'crypto', asset: CRYPTO[usKey] || CRYPTO[q.trim()] };
    return { type: 'fail' };                                     // \u2466 \uc2e4\ud328
  }"""

A2_NEW = """    const usKey = q.trim().toUpperCase();                        // \u2464 \ubbf8\uad6d \u2014 \ubcc4\uce6d\uc740 \ud2f0\ucee4\ub85c \ubcc0\ud658
    if (US_ALIAS.has(usKey)) return { type: 'us', ticker: US_ALIAS.get(usKey) };
    if (CRYPTO[usKey] || CRYPTO[q.trim()])                       // \u2465 \ud06c\ub9bd\ud1a0
      return { type: 'crypto', asset: CRYPTO[usKey] || CRYPTO[q.trim()] };
    const con = containsMatch(m);                               // \u2466 \uc815\uc2dd\uba85 \ud55c\uae00 \ubd80\ubd84\uc77c\uce58 (S2 \u2014 US/crypto \ub4a4)
    if (con.length === 1) return { type: 'kr_partial', stock: con[0] };
    if (con.length >= 2)  return { type: 'kr_partial', list: rankCandidates(con).slice(0, 10) };
    return { type: 'fail' };                                     // \u2467 \uc2e4\ud328
  }

  // S2: \uc815\uc2dd\uba85 \ubd80\ubd84\uc77c\uce58 \u2014 \uc815\uaddc\ud654 2\uc790 \uc774\uc0c1 + \ud55c\uae00 \ud3ec\ud568 \uc9c8\uc758\ub9cc. \ud1b5\uce6d \ubd80\ubd84\uc77c\uce58 \uae08\uc9c0
  function containsMatch(m) {
    if (!m || m.length < 2 || !/[\uac00-\ud7a3]/.test(m)) return [];
    return IDX.stocks.filter(s => s.m.includes(m) && !s.m.startsWith(m));
  }"""

# --- anchor 3: suggest() body ---
A3_OLD = """    const seen = new Set(), out = [];
    for (const s of IDX.stocks) {
      if (s.m.startsWith(m) && !seen.has(s.c)) { seen.add(s.c); out.push(s); }
    }
    for (const a in IDX.aliases) {                               // \ud1b5\uce6d \uc811\ub450 \u2192 \uc885\ubaa9
      if (!a.startsWith(m)) continue;
      const code = IDX.aliases[a];
      if (seen.has(code)) continue;
      const hit = IDX.stocks.find(s => s.c === code);
      if (hit) { seen.add(code); out.push(hit); }
    }
    if (!out.length) { box.innerHTML = ''; box.hidden = true; return; }
    renderCandidates(rankCandidates(out).slice(0, 10), 'kr_partial');"""

A3_NEW = """    const seen = new Set(), pre = [], con = [];
    for (const s of IDX.stocks) {                               // \u2460 \uc815\uc2dd\uba85 \uc811\ub450
      if (s.m.startsWith(m) && !seen.has(s.c)) { seen.add(s.c); pre.push(s); }
    }
    for (const a in IDX.aliases) {                               // \ud1b5\uce6d \uc811\ub450 \u2192 \uc885\ubaa9 (\uc644\uc804 \uc544\ub2cc \uc811\ub450 \ud5c8\uc6a9 \u2014 S1 \uae30\uc874)
      if (!a.startsWith(m)) continue;
      const code = IDX.aliases[a];
      if (seen.has(code)) continue;
      const hit = IDX.stocks.find(s => s.c === code);
      if (hit) { seen.add(code); pre.push(hit); }
    }
    for (const s of containsMatch(m)) {                          // \u2461 \uc815\uc2dd\uba85 \ud55c\uae00 \ubd80\ubd84\uc77c\uce58 (S2)
      if (!seen.has(s.c)) { seen.add(s.c); con.push(s); }
    }
    const out = rankCandidates(pre).concat(rankCandidates(con)); // \uc811\ub450 \uc6b0\uc120 \u2192 \ubd80\ubd84\uc77c\uce58
    if (!out.length) { box.innerHTML = ''; box.hidden = true; return; }
    renderCandidates(out.slice(0, 10), 'kr_partial');"""

src = io.open(TARGET, encoding='utf-8').read()
if MARKER in src:
    print('SKIP: marker already present'); sys.exit(0)

fails = []
for name, old in (('A1_header', A1_OLD), ('A2_route', A2_OLD), ('A3_suggest', A3_OLD)):
    n = src.count(old)
    if n != 1:
        fails.append('%s count=%d (expected 1)' % (name, n))
if fails:
    print('HARD_FAIL:')
    for f in fails: print('  ' + f)
    sys.exit(1)

out = src.replace(A1_OLD, A1_NEW).replace(A2_OLD, A2_NEW).replace(A3_OLD, A3_NEW)
b = out.encode('utf-8')
print('anchors OK  bytes %d -> %d  sha %s' % (len(src.encode('utf-8')), len(b), hashlib.sha256(b).hexdigest()))
if DRYRUN:
    print('DRY-RUN: not written'); sys.exit(0)

st = os.stat(TARGET); d = os.path.dirname(TARGET)
fd, tmp = tempfile.mkstemp(dir=d)
with os.fdopen(fd, 'wb') as f: f.write(b)
os.chmod(tmp, st.st_mode & 0o7777); os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, TARGET)
print('APPLIED')
