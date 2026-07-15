#!/usr/bin/env python3
# f29_nextday_c1.py -- F29 NEXT-DAY-RETURN  C-1 : single-period one-off aggregate.
#
# READ-ONLY. Never writes to any protected path. It imports the ratified engine
# (f29_retro -> build_weight) and re-uses judge_at / build_series / market_total;
# it does NOT re-implement any judgment logic and does NOT modify:
#   build_weight.py, f29_retro.py, stocks_public, stock pages, cron.
# Output = stdout summary + one JSON under /tmp (ephemeral, not an operational path).
#
# Contract locked by Sky (2026-07-15):
#   - representative window = 15 trading days, FIXED. (30/60/90 = later sensitivity)
#   - absolute return only. relative (market-excess) is C-2.
#   - G3: outcome_date = signal_date's NEXT session on the MARKET trading-day index.
#         if the stock has no valid close on that session -> DO NOT jump to the next
#         valid close; exclude as suspended_or_missing_next_session.
#   - survivorship/selection bias explicit; candidate/evaluated/excluded reconciled.
import os
import sys
import glob
import json
import math
import hashlib
import datetime

BASE = '/root/krx-moneyflow'
STOCKS_PUBLIC = os.path.join(BASE, 'output/stocks_public')
WINDOW = 15

if BASE not in sys.path:
    sys.path.insert(0, BASE)

# import-only re-use of the ratified engine (no logic duplication)
import f29_retro as retro  # noqa: E402  (imports build_weight; import-safe library)

BIAS_NOTICE = (
    "Retrospective analysis over the CURRENT stocks_public universe. "
    "Delisted/dropped names and names that fail today's quality filter are absent "
    "from the sample (survivorship + selection bias). Distributions describe "
    "survivors under current filters, not a tradable strategy. Absolute return only; "
    "market-excess (relative) is C-2. Same-day observations share market shocks, so "
    "n is not n independent experiments (cluster effect -> C-4 before any public use)."
)


def die(msg, code=2):
    print('[c1][FAIL] %s' % msg, file=sys.stderr)
    sys.exit(code)


def pct(xs_sorted, q):
    """Linear-interpolation percentile (numpy 'linear'/type-7). q in [0,100]."""
    n = len(xs_sorted)
    if n == 0:
        return None
    if n == 1:
        return xs_sorted[0]
    rank = (q / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs_sorted[lo]
    frac = rank - lo
    return xs_sorted[lo] * (1 - frac) + xs_sorted[hi] * frac


def summarize(returns):
    xs = sorted(returns)
    n = len(xs)
    if n == 0:
        return {'n': 0}
    mean = sum(xs) / n
    pos = sum(1 for r in xs if r > 0)
    zero = sum(1 for r in xs if r == 0)
    return {
        'n': n,
        'mean': round(mean, 4),
        'median': round(pct(xs, 50), 4),
        'positive_rate': round(pos / n * 100.0, 2),
        'positive_count': pos,
        'zero_count': zero,
        'p10': round(pct(xs, 10), 4),
        'p25': round(pct(xs, 25), 4),
        'p75': round(pct(xs, 75), 4),
        'p90': round(pct(xs, 90), 4),
        'min': round(xs[0], 4),
        'max': round(xs[-1], 4),
    }


def main():
    if not os.path.isdir(STOCKS_PUBLIC):
        die('stocks_public not found: %s' % STOCKS_PUBLIC)

    codes = sorted(os.path.basename(p)[:-5]
                   for p in glob.glob(os.path.join(STOCKS_PUBLIC, '*.json')))
    if not codes:
        die('stocks_public universe empty -- refusing to aggregate')

    # market trading-day index (authoritative session list = OHLCV date keys)
    mkt_total = retro.market_total()          # cached full OHLCV scan (denominator)
    sessions = sorted(mkt_total.keys())
    if len(sessions) < 2:
        die('market calendar has < 2 sessions')
    mpos = {d: i for i, d in enumerate(sessions)}
    last_session = sessions[-1]

    # accounting
    stocks_total = len(codes)
    stocks_no_data = 0
    stocks_too_short = 0        # has data but never produces a window-15 label
    stocks_contributing = 0

    candidate = 0              # labeled (stock, signal_date) signals
    evaluated = 0
    excl = {
        'no_next_session': 0,
        'suspended_or_missing_next_session': 0,
        'signal_date_not_in_market_calendar': 0,
    }

    groups = {}                # flowState -> {'label':..., 'returns':[...]}
    all_returns = []
    sig_dates_seen = []
    out_dates_seen = []

    for code in codes:
        raw = retro.load_raw(code)
        if not raw or not raw.get('bars'):
            stocks_no_data += 1
            continue
        dates, close_raw, shares = retro.build_series(raw['bars'], mkt_total)
        if len(close_raw) < retro.AVG_N * 2:
            stocks_too_short += 1
            continue
        close_by_date = dict(zip(dates, close_raw))  # valid closes only
        labeled_here = 0
        for t in range(len(close_raw)):
            j = retro.judge_at(close_raw, shares, t, windows=(WINDOW,))
            s = j.get(str(WINDOW))
            if not s:
                continue                     # not classifiable at t (short history)
            candidate += 1
            labeled_here += 1
            sd = dates[t]
            i = mpos.get(sd)
            if i is None:
                excl['signal_date_not_in_market_calendar'] += 1
                continue
            if i + 1 >= len(sessions):
                excl['no_next_session'] += 1   # signal on most recent session
                continue
            od = sessions[i + 1]
            oc = close_by_date.get(od)
            if oc is None:
                excl['suspended_or_missing_next_session'] += 1
                continue
            csd = close_raw[t]
            if csd <= 0:
                excl['suspended_or_missing_next_session'] += 1
                continue
            ret = round((oc / csd - 1.0) * 100.0, 2)
            g = groups.setdefault(s['flowState'],
                                  {'label': s['flowLabel'], 'returns': []})
            g['returns'].append(ret)
            all_returns.append(ret)
            sig_dates_seen.append(sd)
            out_dates_seen.append(od)
            evaluated += 1
        if labeled_here:
            stocks_contributing += 1
        else:
            stocks_too_short += 1

    excluded_total = sum(excl.values())

    # ------------------------------------------------ reconciliation (hard)
    if candidate != evaluated + excluded_total:
        die('reconciliation: candidate(%d) != evaluated(%d)+excluded(%d)'
            % (candidate, evaluated, excluded_total))
    grp_n = sum(len(g['returns']) for g in groups.values())
    if grp_n != evaluated:
        die('reconciliation: sum(group n)=%d != evaluated=%d' % (grp_n, evaluated))

    grp_out = {}
    for state, g in groups.items():
        d = summarize(g['returns'])
        d['label'] = g['label']
        grp_out[state] = d
    grp_out['__ALL__'] = dict(summarize(all_returns), label='(all evaluated)')

    doc = {
        'script': 'f29_nextday_c1.py',
        'generated_utc': datetime.datetime.now(datetime.timezone.utc)
                                  .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'window': WINDOW,
        'return_type': 'absolute',
        'return_definition': '(close[outcome_date]/close[signal_date]-1)*100, per-stock',
        'outcome_rule': "next MARKET session; missing stock close there -> excluded (no jump)",
        'bias_notice': BIAS_NOTICE,
        'engine': {
            'f29_retro': '/root/krx-moneyflow/f29_retro.py',
            'build_weight': '/root/krx-moneyflow/build_weight.py',
            'AVG_N': retro.AVG_N,
        },
        'market_calendar': {
            'sessions': len(sessions),
            'first': sessions[0], 'last': last_session,
        },
        'universe': {
            'stocks_public_total': stocks_total,
            'contributing': stocks_contributing,
            'no_data': stocks_no_data,
            'too_short_or_unlabeled': stocks_too_short,
        },
        'observations': {
            'candidate': candidate,
            'evaluated': evaluated,
            'excluded_total': excluded_total,
            'excluded_by_reason': excl,
            'reconciliation_ok': True,
        },
        'signal_date_span': {
            'first': min(sig_dates_seen) if sig_dates_seen else None,
            'last': max(sig_dates_seen) if sig_dates_seen else None,
        },
        'outcome_date_span': {
            'first': min(out_dates_seen) if out_dates_seen else None,
            'last': max(out_dates_seen) if out_dates_seen else None,
        },
        'groups': grp_out,
    }

    # ---------------------------------------------------- write /tmp json
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outpath = '/tmp/f29_nextday_c1_%s.json' % stamp
    blob = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
    with open(outpath, 'wb') as f:
        f.write(blob)
    sha = hashlib.sha256(blob).hexdigest()

    # ---------------------------------------------------- stdout summary
    P = lambda *a: print(*a)
    P('=' * 68)
    P('F29 NEXT-DAY-RETURN  C-1  (window=%d, absolute)' % WINDOW)
    P('=' * 68)
    P('universe  stocks_public=%d  contributing=%d  no_data=%d  too_short=%d'
      % (stocks_total, stocks_contributing, stocks_no_data, stocks_too_short))
    P('calendar  sessions=%d  %s..%s' % (len(sessions), sessions[0], last_session))
    P('signals   candidate=%d  evaluated=%d  excluded=%d'
      % (candidate, evaluated, excluded_total))
    for k, v in excl.items():
        P('            excl.%-34s %d' % (k, v))
    P('recon     candidate == evaluated + excluded : PASS')
    P('span      signal %s..%s  outcome %s..%s'
      % (doc['signal_date_span']['first'], doc['signal_date_span']['last'],
         doc['outcome_date_span']['first'], doc['outcome_date_span']['last']))
    P('-' * 68)
    order = ['up_concentration', 'attention_up', 'fade_up',
             'neutral', 'fade_down', 'down_concentration', '__ALL__']
    P('%-20s %6s %8s %8s %7s %8s %8s'
      % ('label', 'n', 'mean', 'median', 'pos%', 'p10', 'p90'))
    for st in order:
        if st not in grp_out or grp_out[st].get('n', 0) == 0:
            continue
        d = grp_out[st]
        name = st if st == '__ALL__' else '%s' % st
        P('%-20s %6d %8.2f %8.2f %7.1f %8.2f %8.2f'
          % (name, d['n'], d['mean'], d['median'],
             d['positive_rate'], d['p10'], d['p90']))
    P('-' * 68)
    P('json  %s' % outpath)
    P('sha   %s' % sha)
    P('NOTE  survivorship/selection bias + cluster effect apply -- see json.bias_notice')


if __name__ == '__main__':
    main()
