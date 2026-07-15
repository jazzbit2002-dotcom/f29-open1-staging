#!/usr/bin/env python3
# patch_portal_cardsA.py -- F29 portal patch A: add 2 top showcase cards
# (Korea Money Flow /kr-moneyflow, Weight of Money /weight) and set the visual
# order of all 6 cards via href-based CSS `order` (existing 4 cards untouched).
# New cards use empty id-spans filled by setLang() i18n (ko/en/zh/ja), same as
# existing cards. New mockup graphics: KR = gold sparkline + theme badges;
# Weight = concentric bubbles. Lower feats section is patch B (separate).
#
# Pure ASCII source; CJK values embedded as \uXXXX. All anchors ASCII & unique.
# SHA gate + per-anchor count gate + dup guard + backup + post gates.
# HTML: no node --check (per handoff); structural grep verification instead.
import os, sys, hashlib, tempfile, datetime

TARGET = '/var/www/f29-portal/index.html'
BACKUP_BASE = '/root/f29-backups'
EXPECT_SHA = '2bc1084207cfa57f2feae6e9bc66cad495f7f49d505f42866d803cc192838634'
EXPECT_SIZE = 31854

def die(m):
    print('[cardsA][ABORT] %s' % m, file=sys.stderr); print('[cardsA][ABORT] source NOT modified.', file=sys.stderr); sys.exit(1)
def sha(b): return hashlib.sha256(b).hexdigest()

# ---------- new card markup (ASCII only; text via id + i18n) ----------
KR_CARD = (
'      <!-- Korea Money Flow (patch A) -->\n'
'      <a class="sc-card mk-order-kr" href="/kr-moneyflow" style="text-decoration:none;color:inherit">\n'
'        <div class="sc-head">\n'
'          <span class="sc-name" id="sckrname"></span>\n'
'          <span class="sc-tag mono">KR MONEY FLOW</span>\n'
'        </div>\n'
'        <div class="mk-flow">\n'
'          <div class="mk-badges">\n'
'            <span class="mk-badge b-gold" id="krb1"></span>\n'
'            <span class="mk-badge b-teal" id="krb2"></span>\n'
'            <span class="mk-badge b-purple" id="krb3"></span>\n'
'          </div>\n'
'          <svg viewBox="0 0 320 96" preserveAspectRatio="none" style="width:100%;height:96px">\n'
'            <polyline points="0,78 40,70 80,74 120,56 160,60 200,44 240,50 280,30 320,36" fill="none" stroke="#D8B45F" stroke-width="2.6"/>\n'
'          </svg>\n'
'          <div class="mk-legend">\n'
'            <span><span class="dotm" style="background:#D8B45F"></span><i id="krl1"></i></span>\n'
'          </div>\n'
'        </div>\n'
'        <div class="sc-desc" id="sckrdesc"></div>\n'
'      </a>\n'
)
WT_CARD = (
'      <!-- Weight of Money (patch A) -->\n'
'      <a class="sc-card mk-order-wt" href="/weight" style="text-decoration:none;color:inherit">\n'
'        <div class="sc-head">\n'
'          <span class="sc-name" id="scwtname"></span>\n'
'          <span class="sc-tag mono">WEIGHT</span>\n'
'        </div>\n'
'        <div class="mk-bubble">\n'
'          <svg viewBox="0 0 320 96">\n'
'            <circle cx="70" cy="52" r="34" fill="rgba(61,216,176,.13)" stroke="#3DD8B0" stroke-width="2"/>\n'
'            <circle cx="164" cy="54" r="24" fill="rgba(157,123,234,.13)" stroke="#9D7BEA" stroke-width="2"/>\n'
'            <circle cx="238" cy="56" r="17" fill="rgba(232,93,156,.12)" stroke="#E85D9C" stroke-width="2"/>\n'
'            <circle cx="292" cy="60" r="11" fill="rgba(90,107,132,.14)" stroke="#5A6B84" stroke-width="2"/>\n'
'          </svg>\n'
'          <div class="mk-bublbl">\n'
'            <span id="wtb1"></span><span id="wtb2"></span><span id="wtb3"></span>\n'
'          </div>\n'
'        </div>\n'
'        <div class="sc-desc" id="scwtdesc"></div>\n'
'      </a>\n'
)

# ---------- CSS: order (href-based) + new mockup classes ----------
CSS_ADD = (
'  /* patch A: 6-card order + KR/Weight mockups */\n'
'  .showcase a[href="/kr-moneyflow"]{order:1}\n'
'  .showcase a[href="/weight"]{order:2}\n'
'  .showcase a[href="/moneyflow"]{order:3}\n'
'  .showcase a[href="/index.html"]{order:4}\n'
'  .showcase a[href="/lab/"]{order:5}\n'
'  .showcase a[href="/precheck/"]{order:6}\n'
'  .b-gold{background:rgba(216,180,95,.14);color:var(--gold)}\n'
'  .mk-bubble{padding:4px 0}\n'
'  .mk-bubble svg{width:100%;height:96px}\n'
'  .mk-bublbl{display:flex;gap:8px;margin-top:10px;font-size:.6rem;color:var(--txt2);flex-wrap:wrap}\n'
'  .mk-bublbl span{padding:3px 8px;border-radius:20px;background:rgba(61,216,176,.12);color:var(--txt2);font-weight:700}\n'
)

# ---------- i18n keys per language (values as \u escapes -> pure ASCII source) ----------
I18N = {
 'ko': (
  '    sckrname:"\ud55c\uad6d\uc8fc\uc2dd \ub3c8\uc758 \ud750\ub984", sckrdesc:"\uad6d\ub0b4 \uc2dc\uc7a5\uc758 \uac70\ub798\ub300\uae08\uc774 \uc5b4\ub290 \ud14c\ub9c8\ub85c \ubab0\ub9ac\ub294\uc9c0 \ucd94\uc801\ud569\ub2c8\ub2e4.",\n'
  '    krb1:"\ubc18\ub3c4\uccb4 \uc8fc\ub3c4", krb2:"2\ucc28\uc804\uc9c0 \ud655\uc0b0", krb3:"\ubc14\uc774\uc624 \uad00\uc2ec", krl1:"\uac70\ub798\ub300\uae08 \uc9d1\uc911",\n'
  '    scwtname:"\ub3c8\uc758 \ubb34\uac8c", scwtdesc:"\uc885\ubaa9\ubcc4 \uac70\ub798\ub300\uae08 \uc810\uc720\uc728\ub85c \uc790\uae08\uc774 \uc5b4\ub514\uc5d0 \uc2e4\ub9ac\ub294\uc9c0 \ube44\uad50\ud569\ub2c8\ub2e4.",\n'
  '    wtb1:"1\uc704", wtb2:"2\uc704", wtb3:"3\uc704",\n'
 ),
 'en': (
  '    sckrname:"Korea Money Flow", sckrdesc:"Tracks which themes Korean market turnover is flowing into.",\n'
  '    krb1:"Semis leading", krb2:"Battery spread", krb3:"Bio interest", krl1:"Turnover focus",\n'
  '    scwtname:"Weight of Money", scwtdesc:"Compares where capital concentrates by each stock\'s turnover share.",\n'
  '    wtb1:"#1", wtb2:"#2", wtb3:"#3",\n'
 ),
 'zh': (
  '    sckrname:"\u97e9\u56fd\u80a1\u5e02\u8d44\u91d1\u6d41\u5411", sckrdesc:"\u8ffd\u8e2a\u97e9\u56fd\u5e02\u573a\u6210\u4ea4\u989d\u6d41\u5411\u54ea\u4e9b\u4e3b\u9898\u3002",\n'
  '    krb1:"\u534a\u5bfc\u4f53\u4e3b\u5bfc", krb2:"\u7535\u6c60\u6269\u6563", krb3:"\u751f\u7269\u5173\u6ce8", krl1:"\u6210\u4ea4\u989d\u96c6\u4e2d",\n'
  '    scwtname:"\u8d44\u91d1\u7684\u91cd\u91cf", scwtdesc:"\u4ee5\u4e2a\u80a1\u6210\u4ea4\u989d\u5360\u6bd4\u6bd4\u8f83\u8d44\u91d1\u96c6\u4e2d\u5728\u4f55\u5904\u3002",\n'
  '    wtb1:"\u7b2c1", wtb2:"\u7b2c2", wtb3:"\u7b2c3",\n'
 ),
 'ja': (
  '    sckrname:"\u97d3\u56fd\u682a\u30de\u30cd\u30fc\u30d5\u30ed\u30fc", sckrdesc:"\u97d3\u56fd\u5e02\u5834\u306e\u58f2\u8cb7\u4ee3\u91d1\u304c\u3069\u306e\u30c6\u30fc\u30de\u306b\u5411\u304b\u3046\u304b\u8ffd\u8de1\u3057\u307e\u3059\u3002",\n'
  '    krb1:"\u534a\u5c0e\u4f53\u4e3b\u5c0e", krb2:"\u96fb\u6c60\u62e1\u6563", krb3:"\u30d0\u30a4\u30aa\u95a2\u5fc3", krl1:"\u58f2\u8cb7\u4ee3\u91d1\u96c6\u4e2d",\n'
  '    scwtname:"\u8cc7\u91d1\u306e\u91cd\u307f", scwtdesc:"\u9298\u67c4\u5225\u306e\u58f2\u8cb7\u4ee3\u91d1\u30b7\u30a7\u30a2\u3067\u8cc7\u91d1\u306e\u96c6\u4e2d\u5148\u3092\u6bd4\u8f03\u3057\u307e\u3059\u3002",\n'
  '    wtb1:"1\u4f4d", wtb2:"2\u4f4d", wtb3:"3\u4f4d",\n'
 ),
}

# ---------- set() wiring for new ids ----------
SET_ADD = (
'  set("sckrname",t.sckrname); set("sckrdesc",t.sckrdesc); set("krb1",t.krb1); set("krb2",t.krb2); set("krb3",t.krb3); set("krl1",t.krl1);\n'
'  set("scwtname",t.scwtname); set("scwtdesc",t.scwtdesc); set("wtb1",t.wtb1); set("wtb2",t.wtb2); set("wtb3",t.wtb3);\n'
)

# forbidden compliance tokens (must be 0 in any new text)
FORBIDDEN = ['\ub9e4\uc218','\ub9e4\ub3c4','\uc9c4\uc785','\uc190\uc808','\uccad\uc0b0','\uc608\uce21','\uc801\uc911','\uc2e0\ub8b0\ub3c4','\uc801\uc911\ub960']

EDITS = [
 ('showcase-insert', '<div class="showcase">', '<div class="showcase">\n' + KR_CARD + WT_CARD),
 ('css-order-mockup',
  '  .showcase{margin:52px 0 20px;display:grid;grid-template-columns:1fr 1fr;gap:18px}\n',
  '  .showcase{margin:52px 0 20px;display:grid;grid-template-columns:1fr 1fr;gap:18px}\n' + CSS_ADD),
 ('i18n-ko', '\n  ko:{\n', '\n  ko:{\n' + I18N['ko']),
 ('i18n-en', '\n  en:{\n', '\n  en:{\n' + I18N['en']),
 ('i18n-zh', '\n  zh:{\n', '\n  zh:{\n' + I18N['zh']),
 ('i18n-ja', '\n  ja:{\n', '\n  ja:{\n' + I18N['ja']),
 ('set-wiring',
  '  set("sc4name",t.sc4name); set("sc4desc",t.sc4desc);\n',
  '  set("sc4name",t.sc4name); set("sc4desc",t.sc4desc);\n' + SET_ADD),
]

def main():
    if not os.path.isfile(TARGET): die('target not found')
    raw = open(TARGET,'rb').read(); src = raw.decode('utf-8')
    print('[cardsA] before sha   = %s' % sha(raw)); print('[cardsA] before bytes = %d' % len(raw))
    if sha(raw)!=EXPECT_SHA: die('SHA MISMATCH: %s' % sha(raw))
    if len(raw)!=EXPECT_SIZE: die('SIZE MISMATCH: %d' % len(raw))
    print('[cardsA] SHA gate PASS')
    if 'href="/kr-moneyflow"' in src or 'sckrname' in src: die('already applied: kr card present')

    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        if n!=1: die('anchor [%s] count=%d (expected 1)' % (label,n))
        out = out.replace(old,new,1); print('[cardsA] anchor [%s] applied' % label)

    checks = [
      ('kr card anchor ==1', out.count('class="sc-card mk-order-kr" href="/kr-moneyflow"')==1),
      ('wt card anchor ==1', out.count('class="sc-card mk-order-wt" href="/weight"')==1),
      ('kr href total ==2 (card+css)', out.count('href="/kr-moneyflow"')==2),
      ('wt href total ==2 (card+css)', out.count('href="/weight"')==2),
      ('order rules ==6', sum(out.count('.showcase a[href="%s"]'%h) for h in
                              ['/kr-moneyflow','/weight','/moneyflow','/index.html','/lab/','/precheck/'])==6),
      ('sckrname id ==1', out.count('id="sckrname"')==1),
      ('scwtname id ==1', out.count('id="scwtname"')==1),
      ('sckrname i18n x4', sum(('sckrname:' in v) for v in I18N.values())==4),
      ('set sckrname ==1', out.count('set("sckrname"')==1),
      ('set scwtname ==1', out.count('set("scwtname"')==1),
      ('existing 4 cards intact',
        all(out.count('href="%s" style="text-decoration:none;color:inherit"'%h)==1
            for h in ['/index.html','/moneyflow','/lab/','/precheck/'])),
      ('ko/en/zh/ja openers intact', all(out.count('\n  %s:{\n'%l)==1 for l in ['ko','en','zh','ja'])),
      ('mk-bubble css ==1', out.count('.mk-bubble{padding:4px 0}')==1),
      ('b-gold css ==1', out.count('.b-gold{')==1),
    ]
    for name,ok in checks:
        if not ok: die('post-check FAIL: %s' % name)
    # compliance: forbidden tokens must not appear in the NEW inserted text only
    added = KR_CARD+WT_CARD+CSS_ADD+''.join(I18N.values())+SET_ADD
    for tok in FORBIDDEN:
        if tok in added: die('compliance FAIL: forbidden token in new copy: %s' % tok)
    print('[cardsA] post-check gates PASS (%d) + compliance PASS' % len(checks))

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(BACKUP_BASE,'portal-cardsA-%s'%ts); os.makedirs(bdir,exist_ok=True)
    bak = os.path.join(bdir,'index.html'); open(bak,'wb').write(raw)
    st=os.stat(TARGET)
    open(os.path.join(bdir,'manifest.txt'),'w').write(
      'orig=%s\nmode=%o\nsize=%d\nsha_before=%s\n'%(TARGET,st.st_mode&0o7777,len(raw),sha(raw)))
    print('[cardsA] backup       = %s' % bak)

    d=os.path.dirname(os.path.abspath(TARGET)); mode=os.stat(TARGET).st_mode&0o7777
    fd,tmp=tempfile.mkstemp(dir=d)
    with os.fdopen(fd,'wb') as f: f.write(out.encode('utf-8'))
    os.chmod(tmp,mode); os.replace(tmp,TARGET)
    ra=open(TARGET,'rb').read()
    print('[cardsA] after sha    = %s' % sha(ra)); print('[cardsA] after bytes  = %d' % len(ra))
    print('[cardsA] OK  rollback: cp %s %s' % (bak,TARGET))

if __name__=='__main__': main()
