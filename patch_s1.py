import io, os, sys, hashlib, tempfile

TARGET = sys.argv[1] if len(sys.argv) > 1 else '/var/www/f29/assets/f29-search.js'
DRYRUN = '--apply' not in sys.argv

MARKER = 'v1.9.1+D1+S1'

A1_OLD = "/* f29-search.js \u2014 v1.9.1+D1 (D-1 \ucf54\ub4dc \uacc4\uc57d \uac1c\uc815 2026-07-13). \uc758\uc874: f29-metrics.js (F29M.track) */"
A1_NEW = "/* f29-search.js \u2014 v1.9.1+D1+S1 (\uc2e4\uc2dc\uac04 \uc811\ub450 \uc790\ub3d9\uc644\uc131 \ubcf5\uc6d0 2026-07-13). \uc758\uc874: f29-metrics.js (F29M.track) */"

A2_OLD = """  window.F29Search = {
    async init(inputEl) {
      await loadIndex();
      inputEl.addEventListener('focus', () => track('search_focus', {}), { once: true });
      inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && inputEl.value.trim()) submit(inputEl.value); });
    }
  };"""

A2_NEW = """  // S1: \uc2e4\uc2dc\uac04 \uc811\ub450 \ud6c4\ubcf4 \ub80c\ub354. \ud0c0\uc774\ud551\ub9cc\uc73c\ub85c\ub294 \uc808\ub300 \uc774\ub3d9\ud558\uc9c0 \uc54a\ub294\ub2e4(\uc81c\ucd9c \uc804\uc6a9).
  function suggest(q) {
    const box = document.getElementById('f29-search-results');
    if (!box || !IDX) return;
    const m = norm(q);
    if (!m) { box.innerHTML = ''; box.hidden = true; return; }
    const seen = new Set(), out = [];
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
    renderCandidates(rankCandidates(out).slice(0, 10), 'kr_partial');
  }

  window.F29Search = {
    async init(inputEl) {
      await loadIndex();
      inputEl.addEventListener('focus', () => track('search_focus', {}), { once: true });
      inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && inputEl.value.trim()) submit(inputEl.value); });
      let composing = false, timer = null;
      inputEl.addEventListener('compositionstart', () => { composing = true; });
      inputEl.addEventListener('compositionend', () => { composing = false; suggest(inputEl.value); });
      inputEl.addEventListener('input', () => {
        if (composing) return;                                   // IME \uc870\ud569 \uc911: \ubcf4\ub958
        clearTimeout(timer);
        timer = setTimeout(() => suggest(inputEl.value), 80);
      });
    }
  };"""

src = io.open(TARGET, encoding='utf-8').read()
if MARKER in src:
    print('SKIP: marker already present'); sys.exit(0)

fails = []
for name, old in (('A1_header', A1_OLD), ('A2_init', A2_OLD)):
    n = src.count(old)
    if n != 1:
        fails.append('%s count=%d (expected 1)' % (name, n))
if fails:
    print('HARD_FAIL:'); [print('  ' + f) for f in fails]; sys.exit(1)

out = src.replace(A1_OLD, A1_NEW).replace(A2_OLD, A2_NEW)
b = out.encode('utf-8')
print('anchors OK  bytes %d -> %d  sha %s' % (len(src.encode('utf-8')), len(b), hashlib.sha256(b).hexdigest()))
if DRYRUN:
    print('DRY-RUN: not written'); sys.exit(0)

st = os.stat(TARGET)
d = os.path.dirname(TARGET)
fd, tmp = tempfile.mkstemp(dir=d)
with os.fdopen(fd, 'wb') as f:
    f.write(b)
os.chmod(tmp, st.st_mode & 0o7777)
os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, TARGET)
print('APPLIED')
