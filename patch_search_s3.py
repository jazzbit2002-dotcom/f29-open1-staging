#!/usr/bin/env python3
# patch_search_s3.py -- F29 S3 : add optional onStockSelect(stock, queryType) callback
# to the shared search router. Unifies the 4 KR selection paths (direct result,
# autocomplete click, Enter confirm, alias/partial confirm) into a single
# selectStock(stock, qtype, opts) entry point. Options are bound per init instance
# (no global state). Callback missing -> existing /stock/{c}/?ref=search move, 100%.
# US/crypto/fail paths unchanged. Object signature only (no (code,name), no data-name).
#
# Pure ASCII source. All anchors are ASCII-only -> Korean bytes in the target are
# never touched. Literal anchor str.replace + per-anchor count gate (exactly 1) +
# SHA gate + dup guard + backup (non-public) + node --check + atomic write + post gates.
import os
import sys
import hashlib
import subprocess
import tempfile
import datetime

TARGET = '/var/www/f29/assets/f29-search.js'
BACKUP_BASE = '/root/f29-backups'
EXPECT_SHA = '5979f8f9daee3f8cac391cc248e8a0e3b96d8860d00ddcfb0ad660149b0e860e'
EXPECT_SIZE = 8481


def die(msg):
    print('[s3][ABORT] %s' % msg, file=sys.stderr)
    print('[s3][ABORT] source NOT modified.', file=sys.stderr)
    sys.exit(1)


def sha(b):
    return hashlib.sha256(b).hexdigest()


# (label, old, new) -- each old must appear exactly once
EDITS = [
    ('header-version',
     'v1.9.1+D1+S1+S2',
     'v1.9.1+D1+S1+S2+S3'),
    ('header-note',
     '(F29M.track) */',
     '(F29M.track). S3: optional onStockSelect(stock,queryType) callback, instance-bound. */'),
    ('go-block+selectStock',
     "  function go(res, qtype) {\n"
     "    track('search_submit', { query_type: qtype });\n"
     "    if (res.stock) {\n"
     "      track('search_result_click', { code: res.stock.c, query_type: qtype });\n"
     "      location.href = `/stock/${res.stock.c}/?ref=search`;\n"
     "    }\n"
     "  }",
     "  // S3: single KR selection entry point. All 4 KR paths (direct result,\n"
     "  // autocomplete click, Enter confirm, alias/partial confirm) funnel here.\n"
     "  // opts are bound per init instance (no global state).\n"
     "  function selectStock(stock, qtype, opts) {\n"
     "    track('search_result_click', { code: stock.c, query_type: qtype });\n"
     "    if (opts && typeof opts.onStockSelect === 'function') {\n"
     "      opts.onStockSelect(stock, qtype);   // callback present -> no location.href fallback (even on throw)\n"
     "      return;\n"
     "    }\n"
     "    location.href = `/stock/${stock.c}/?ref=search`;\n"
     "  }\n"
     "\n"
     "  function go(res, qtype, opts) {\n"
     "    track('search_submit', { query_type: qtype });\n"
     "    if (res.stock) selectStock(res.stock, qtype, opts);\n"
     "  }"),
    ('submit-sig',
     '  function submit(q) {',
     '  function submit(q, opts) {'),
    ('submit-go-call',
     '        if (res.stock) return go(res, res.type);',
     '        if (res.stock) return go(res, res.type, opts);'),
    ('submit-cand-call',
     '        return renderCandidates(res.list, res.type);',
     '        return renderCandidates(res.list, res.type, opts);'),
    ('renderCandidates-block',
     "  function renderCandidates(list, qtype) {\n"
     "    const box = document.getElementById('f29-search-results');\n"
     "    box.innerHTML = list.map(s =>\n"
     "      `<button class=\"f29-cand\" data-code=\"${s.c}\">${esc(s.n)}</button>`).join('');\n"
     "    box.hidden = false;\n"
     "    box.querySelectorAll('.f29-cand').forEach(b => b.addEventListener('click', () => {\n"
     "      track('search_result_click', { code: b.dataset.code, query_type: qtype });\n"
     "      location.href = `/stock/${b.dataset.code}/?ref=search`;\n"
     "    }));\n"
     "  }",
     "  function renderCandidates(list, qtype, opts) {\n"
     "    const box = document.getElementById('f29-search-results');\n"
     "    box.innerHTML = list.map(s =>\n"
     "      `<button class=\"f29-cand\" data-code=\"${s.c}\">${esc(s.n)}</button>`).join('');\n"
     "    box.hidden = false;\n"
     "    const btns = box.querySelectorAll('.f29-cand');\n"
     "    Array.prototype.forEach.call(btns, (b, i) => {\n"
     "      const s = list[i];   // full stock object via closure (name from object, no extra button attr)\n"
     "      b.addEventListener('click', () => selectStock(s, qtype, opts));\n"
     "    });\n"
     "  }"),
    ('suggest-sig',
     '  function suggest(q) {',
     '  function suggest(q, opts) {'),
    ('suggest-cand-call',
     "    renderCandidates(out.slice(0, 10), 'kr_partial');",
     "    renderCandidates(out.slice(0, 10), 'kr_partial', opts);"),
    ('init-sig',
     '    async init(inputEl) {\n'
     '      await loadIndex();',
     '    async init(inputEl, options) {\n'
     '      const opts = options || {};\n'
     '      await loadIndex();'),
    ('init-submit-call',
     "if (e.key === 'Enter' && inputEl.value.trim()) submit(inputEl.value); });",
     "if (e.key === 'Enter' && inputEl.value.trim()) submit(inputEl.value, opts); });"),
    ('init-suggest-compend',
     "inputEl.addEventListener('compositionend', () => { composing = false; suggest(inputEl.value); });",
     "inputEl.addEventListener('compositionend', () => { composing = false; suggest(inputEl.value, opts); });"),
    ('init-suggest-timer',
     'timer = setTimeout(() => suggest(inputEl.value), 80);',
     'timer = setTimeout(() => suggest(inputEl.value, opts), 80);'),
]


def main():
    if not os.path.isfile(TARGET):
        die('target not found: %s' % TARGET)
    raw_before = open(TARGET, 'rb').read()
    src = raw_before.decode('utf-8')
    print('[s3] target       = %s' % TARGET)
    print('[s3] before sha   = %s' % sha(raw_before))
    print('[s3] before bytes = %d' % len(raw_before))

    # SHA gate (BASE identity)
    if sha(raw_before) != EXPECT_SHA:
        die('SHA MISMATCH: expected %s got %s -- live not at S3 BASE, investigate'
            % (EXPECT_SHA, sha(raw_before)))
    if len(raw_before) != EXPECT_SIZE:
        die('SIZE MISMATCH expected %d got %d' % (EXPECT_SIZE, len(raw_before)))
    print('[s3] SHA gate PASS (S1+S2 BASE)')

    # dup guard BEFORE anchor gates
    if 'v1.9.1+D1+S1+S2+S3' in src:
        die('already applied: +S3 version marker present')
    if 'function selectStock(' in src:
        die('already applied: selectStock present')

    # apply edits with per-anchor count gate
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        if n != 1:
            die('anchor [%s] count=%d (expected exactly 1)' % (label, n))
        out = out.replace(old, new, 1)
        print('[s3] anchor [%s] count=1 applied' % label)

    # ---- post-transform gates ----
    checks = [
        ('function selectStock( == 1', out.count('function selectStock(') == 1),
        ('selectStock( total == 3 (1 def + 2 calls)', out.count('selectStock(') == 3),
        ('stock stock nav == 1', out.count('`/stock/${stock.c}/?ref=search`') == 1),
        ('old candidate nav gone', out.count('${b.dataset.code}') == 0),
        ('no data-name added', out.count('data-name') == 0),
        ('onStockSelect invocation == 1', out.count('opts.onStockSelect(stock, qtype)') == 1),
        ('version +S3 == 1', out.count('v1.9.1+D1+S1+S2+S3') == 1),
        ('init options sig == 1', out.count('async init(inputEl, options)') == 1),
        ('old go sig gone', out.count('function go(res, qtype) {') == 0),
        ('old submit sig gone', out.count('function submit(q) {') == 0),
        ('old suggest sig gone', out.count('function suggest(q) {') == 0),
        ('US path unchanged', out.count('/moneyflow/#stock-') == 1),
        ('crypto path unchanged', out.count('?asset=') == 1),
        ('no accidental global SEL', ' SEL ' not in out and 'let SEL' not in out and 'var SEL' not in out),
    ]
    for name, ok in checks:
        if not ok:
            die('post-check FAIL: %s' % name)
    print('[s3] post-check gates PASS (%d checks)' % len(checks))

    # ---- backup (non-public) ----
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_BASE, 's3-%s' % ts)
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, 'f29-search.js')
    with open(bak, 'wb') as f:
        f.write(raw_before)
    # manifest
    st = os.stat(TARGET)
    with open(os.path.join(bdir, 'manifest.txt'), 'w') as f:
        f.write('orig_path=%s\nowner_uid=%d\nmode=%o\nsize=%d\nsha256_before=%s\n'
                % (TARGET, st.st_uid, st.st_mode & 0o7777, len(raw_before), sha(raw_before)))
    print('[s3] backup       = %s' % bak)

    # ---- atomic write via temp in same dir, node --check, then replace ----
    d = os.path.dirname(os.path.abspath(TARGET))
    mode = os.stat(TARGET).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, 'wb') as f:
        f.write(out.encode('utf-8'))
    os.chmod(tmp, mode)
    try:
        r = subprocess.run(['node', '--check', tmp],
                           capture_output=True, text=True)
    except FileNotFoundError:
        os.unlink(tmp)
        die('node not found -- cannot validate JS syntax')
    if r.returncode != 0:
        os.unlink(tmp)
        die('node --check FAIL:\n%s' % (r.stderr.strip()))
    print('[s3] node --check PASS')
    os.replace(tmp, TARGET)

    raw_after = open(TARGET, 'rb').read()
    print('[s3] after sha    = %s' % sha(raw_after))
    print('[s3] after bytes  = %d' % len(raw_after))
    print('[s3] OK  rollback: cp %s %s' % (bak, TARGET))


if __name__ == '__main__':
    main()
