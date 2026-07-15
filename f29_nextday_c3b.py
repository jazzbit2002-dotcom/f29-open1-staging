#!/usr/bin/env python3
# f29_nextday_c3b.py -- F29 NEXT-DAY-RETURN  C-3b : leave-one-outcome-date robustness
#                       + fade_down 7/13 single-day carry check.
#
# READ-ONLY. Same engine / same evaluated set as C-1/C-2/C-3. Never writes to any
# protected path. Does NOT modify build_weight.py, f29_retro.py, stocks_public,
# stock pages, cron. Output = stdout + one /tmp JSON.
#
# Method: daily-cluster dMean of each (regime,label) is the mean over active days of
# the per-day mean relative return (each DATE weight 1). Per-date benchmarks are
# self-contained (each date's excess mean = 0), so leave-one-outcome-date = drop that
# date's per-day mean from the cluster average; no re-benchmarking.
#
# Usage: python3 f29_nextday_c3b.py <C-3 json path>
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
TOL = 1e-9
CMP_TOL = 1e-6
EXPECT_RETRO_SHA = '8e15d6e7418502fe0bbd777a864cf7c87739546dc6b85c5d690a80c3d85777bd'
EXPECT_BW_SHA = '6902ccbd94468e282c17fd9ee177da8715284456d55a7dae43ba4c04469b7966'
RETRO_PATH = os.path.join(BASE, 'f29_retro.py')
BW_PATH = os.path.join(BASE, 'build_weight.py')
FOCUS_DATE = '20260713'   # the n=95 fade_down down-day flagged in C-3

if BASE not in sys.path:
    sys.path.insert(0, BASE)
import f29_retro as retro  # noqa: E402

ORDER = ['up_concentration', 'attention_up', 'fade_up',
         'neutral', 'fade_down', 'down_concentration']


def die(msg, code=2):
    print('[c3b][FAIL] %s' % msg, file=sys.stderr)
    sys.exit(code)


def sha_file(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def pct(xs, q):
    n = len(xs)
    if n == 0:
        return None
    if n == 1:
        return xs[0]
    rank = (q / 100.0) * (n - 1)
    lo = int(math.floor(rank)); hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    f = rank - lo
    return xs[lo] * (1 - f) + xs[hi] * f


def build_obs():
    codes = sorted(os.path.basename(p)[:-5]
                   for p in glob.glob(os.path.join(STOCKS_PUBLIC, '*.json')))
    mkt = retro.market_total()
    sessions = sorted(mkt.keys())
    mpos = {d: i for i, d in enumerate(sessions)}
    excl = {'no_next_session': 0, 'suspended_or_missing_next_session': 0,
            'signal_date_not_in_market_calendar': 0}
    cand = ev = 0
    obs = []
    for code in codes:
        raw = retro.load_raw(code)
        if not raw or not raw.get('bars'):
            continue
        dates, close_raw, shares = retro.build_series(raw['bars'], mkt)
        if len(close_raw) < retro.AVG_N * 2:
            continue
        cbd = dict(zip(dates, close_raw))
        for t in range(len(close_raw)):
            j = retro.judge_at(close_raw, shares, t, windows=(WINDOW,))
            s = j.get(str(WINDOW))
            if not s:
                continue
            cand += 1
            sd = dates[t]; i = mpos.get(sd)
            if i is None:
                excl['signal_date_not_in_market_calendar'] += 1; continue
            if i + 1 >= len(sessions):
                excl['no_next_session'] += 1; continue
            od = sessions[i + 1]; oc = cbd.get(od); csd = close_raw[t]
            if oc is None or csd <= 0:
                excl['suspended_or_missing_next_session'] += 1; continue
            obs.append({'out': od, 'state': s['flowState'],
                        'abs': round((oc / csd - 1.0) * 100.0, 2)})
            ev += 1
    return obs, cand, ev, excl


def main():
    if len(sys.argv) < 2:
        die('usage: python3 f29_nextday_c3b.py <C-3 json path>')
    c3 = json.load(open(sys.argv[1], encoding='utf-8'))

    rsha, bsha = sha_file(RETRO_PATH), sha_file(BW_PATH)
    if rsha != EXPECT_RETRO_SHA or bsha != EXPECT_BW_SHA:
        die('engine SHA changed since C-0 -- input not identical to C-1/2/3')
    ii = c3.get('input_identity', {})
    if ii.get('f29_retro_sha256') != rsha or ii.get('build_weight_sha256') != bsha:
        die('engine SHA differs from C-3 record')

    obs, cand, ev, excl = build_obs()
    excluded_total = sum(excl.values())
    if ev != ii.get('evaluated') or excluded_total != ii.get('excluded_total'):
        die('gate: evaluated/excluded differ from C-3')

    bucket = {}
    for o in obs:
        bucket.setdefault(o['out'], []).append(o['abs'])
    benchmark = {d: sum(v) / len(v) for d, v in bucket.items()}
    regime_of = {d: ('up' if m > 0 else ('down' if m < 0 else 'flat'))
                 for d, m in benchmark.items()}
    for o in obs:
        o['rel'] = o['abs'] - benchmark[o['out']]
        o['reg'] = regime_of[o['out']]
    n_out = len(bucket)
    if n_out != ii.get('outcome_dates'):
        die('gate: outcome_dates differ from C-3')

    # per (reg,label) -> {date: (day_mean_rel, day_n)}
    daily = {}
    for o in obs:
        for reg in ('ALL', o['reg']):
            daily.setdefault((reg, o['state']), {}) \
                 .setdefault(o['out'], []).append(o['rel'])
    per_day = {}
    for k, dd in daily.items():
        per_day[k] = {d: (sum(v) / len(v), len(v)) for d, v in dd.items()}

    # reproduce C-3 daily_mean_mean (gate)
    c3dc = c3.get('daily_cluster', {})
    for (reg, st), pd in per_day.items():
        means = [m for m, _ in pd.values()]
        dm = sum(means) / len(means)
        stored = c3dc.get('%s|%s' % (reg, st), {}).get('daily_mean_mean')
        if stored is not None and abs(round(dm, 4) - stored) > CMP_TOL:
            die('gate: daily dMean %s|%s recompute %.4f != C-3 %.4f'
                % (reg, st, dm, stored))

    # -------- leave-one-outcome-date on each (reg,label) daily cluster --------
    def loo_row(reg, st):
        pd = per_day.get((reg, st))
        if not pd:
            return None
        rows = sorted(pd.items())            # (date,(mean,n))
        means = [m for _, (m, _) in rows]
        D = len(means)
        orig = sum(means) / D
        if D < 2:
            return {'reg': reg, 'label': st, 'days': D, 'orig': round(orig, 4),
                    'loo_min': None, 'loo_max': None, 'flip': None,
                    'max_infl_date': None, 'loo_at_max': None, 'delta_at_max': None}
        loos = []
        for k in range(D):
            v = (sum(means) - means[k]) / (D - 1)
            loos.append((rows[k][0], v, rows[k][1][1]))   # (date, loo_dMean, day_n)
        lmin = min(v for _, v, _ in loos)
        lmax = max(v for _, v, _ in loos)
        # sign flip vs original
        if orig > 0:
            flip = lmin < 0
        elif orig < 0:
            flip = lmax > 0
        else:
            flip = (lmin < 0) or (lmax > 0)
        # max-influence date = removal that moves dMean farthest from orig
        mdate, mval, mn = max(loos, key=lambda x: abs(x[1] - orig))
        return {'reg': reg, 'label': st, 'days': D, 'orig': round(orig, 4),
                'loo_min': round(lmin, 4), 'loo_max': round(lmax, 4),
                'flip': bool(flip), 'max_infl_date': mdate, 'max_infl_n': mn,
                'loo_at_max': round(mval, 4), 'delta_at_max': round(mval - orig, 4)}

    loo = {}
    for st in ORDER:
        for reg in ('ALL', 'up', 'down'):
            r = loo_row(reg, st)
            if r:
                loo['%s|%s' % (reg, st)] = r

    # -------- fade_down DOWN focus: with vs without FOCUS_DATE --------
    fd_down = [o for o in obs if o['state'] == 'fade_down' and o['reg'] == 'down']

    def pooled(sel):
        if not sel:
            return {'n': 0}
        r = sorted(o['rel'] for o in sel)
        n = len(r)
        return {'n': n, 'rel_mean': round(sum(r) / n, 4),
                'rel_median': round(pct(r, 50), 4),
                'exceed_rate': round(sum(1 for x in r if x > 0) / n * 100, 2)}

    def cluster(sel):
        pd = {}
        for o in sel:
            pd.setdefault(o['out'], []).append(o['rel'])
        means = sorted(sum(v) / len(v) for v in pd.values())
        D = len(means)
        if D == 0:
            return {'active_days': 0}
        return {'active_days': D, 'dMean': round(sum(means) / D, 4),
                'dMed': round(pct(means, 50), 4),
                'posDay_rate': round(sum(1 for m in means if m > 0) / D * 100, 2)}

    fd_pool_with = pooled(fd_down)
    fd_pool_wo = pooled([o for o in fd_down if o['out'] != FOCUS_DATE])
    fd_clu_with = cluster(fd_down)
    fd_clu_wo = cluster([o for o in fd_down if o['out'] != FOCUS_DATE])
    focus_n = sum(1 for o in fd_down if o['out'] == FOCUS_DATE)

    # verdict flags (Sky's rule applied to numbers)
    fd_down_loo = loo.get('down|fade_down', {})
    fd_sign_flip_daily = fd_down_loo.get('flip')
    pool_shrink = None
    if fd_pool_with.get('n') and fd_pool_with['rel_mean'] not in (0, None):
        pool_shrink = round((1 - fd_pool_wo['rel_mean'] / fd_pool_with['rel_mean']) * 100, 1)

    doc = {
        'script': 'f29_nextday_c3b.py', 'window': WINDOW,
        'generated_utc': datetime.datetime.now(datetime.timezone.utc)
                                  .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'c3_source': sys.argv[1],
        'input_identity': {'f29_retro_sha256': rsha, 'build_weight_sha256': bsha,
                           'evaluated': ev, 'excluded_total': excluded_total,
                           'outcome_dates': n_out},
        'leave_one_outcome_date': loo,
        'fade_down_down_focus': {
            'focus_date': FOCUS_DATE, 'focus_day_n': focus_n,
            'pooled_with': fd_pool_with, 'pooled_without': fd_pool_wo,
            'daily_with': fd_clu_with, 'daily_without': fd_clu_wo,
            'daily_sign_flip_on_any_single_removal': fd_sign_flip_daily,
            'pooled_rel_mean_shrink_pct_when_focus_removed': pool_shrink,
        },
    }
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outpath = '/tmp/f29_nextday_c3b_%s.json' % stamp
    blob = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
    open(outpath, 'wb').write(blob)
    sha = hashlib.sha256(blob).hexdigest()

    P = print
    P('=' * 96)
    P('F29 NEXT-DAY-RETURN  C-3b  leave-one-outcome-date + fade_down %s carry' % FOCUS_DATE)
    P('=' * 96)
    P('input  f29_retro=%s.. build_weight=%s..  evaluated=%d excluded=%d outcome_dates=%d'
      % (rsha[:8], bsha[:8], ev, excluded_total, n_out))
    P('gate   evaluated/excluded/outcome_dates = C-3 PASS | daily dMean reproduces C-3 PASS')
    P('\n[ LOO ] leave-one-outcome-date on daily dMean  (each date weight 1)')
    P('  %-19s %-4s %4s | %8s %8s %8s %5s | %-14s %8s'
      % ('label', 'reg', 'days', 'orig', 'loo_min', 'loo_max', 'flip',
         'maxInfl(n)', 'delta'))
    for st in ORDER:
        for reg in ('ALL', 'up', 'down'):
            r = loo.get('%s|%s' % (reg, st))
            if not r:
                continue
            md = (r['max_infl_date'][4:] + '(%d)' % r.get('max_infl_n', 0)
                  if r['max_infl_date'] else '-')
            P('  %-19s %-4s %4d | %8.3f %8.3f %8.3f %5s | %-14s %8.3f'
              % (st, reg, r['days'], r['orig'],
                 r['loo_min'] if r['loo_min'] is not None else float('nan'),
                 r['loo_max'] if r['loo_max'] is not None else float('nan'),
                 'Y' if r['flip'] else 'n', md,
                 r['delta_at_max'] if r['delta_at_max'] is not None else float('nan')))
        P('  ' + '-' * 88)
    P('\n[ fade_down DOWN focus ]  %s day_n=%d' % (FOCUS_DATE, focus_n))
    P('  pooled  (n=95 day actually weighted here)')
    P('    with %s : n=%d rel_mn=%.3f rel_md=%.3f exc%%=%.1f'
      % (FOCUS_DATE, fd_pool_with['n'], fd_pool_with['rel_mean'],
         fd_pool_with['rel_median'], fd_pool_with['exceed_rate']))
    P('    w/o  %s : n=%d rel_mn=%.3f rel_md=%.3f exc%%=%.1f   (rel_mn shrink %s%%)'
      % (FOCUS_DATE, fd_pool_wo['n'], fd_pool_wo['rel_mean'],
         fd_pool_wo['rel_median'], fd_pool_wo['exceed_rate'],
         pool_shrink if pool_shrink is not None else 'na'))
    P('  daily   (each date weight 1 -- 95-day already down-weighted to 1/37)')
    P('    with %s : days=%d dMean=%.4f dMed=%.4f posDay%%=%.1f'
      % (FOCUS_DATE, fd_clu_with['active_days'], fd_clu_with['dMean'],
         fd_clu_with['dMed'], fd_clu_with['posDay_rate']))
    P('    w/o  %s : days=%d dMean=%.4f dMed=%.4f posDay%%=%.1f'
      % (FOCUS_DATE, fd_clu_wo['active_days'], fd_clu_wo['dMean'],
         fd_clu_wo['dMed'], fd_clu_wo['posDay_rate']))
    P('    daily sign flip on ANY single-date removal: %s'
      % ('Y' if fd_sign_flip_daily else 'n'))
    P('\njson  %s' % outpath)
    P('sha   %s' % sha)


if __name__ == '__main__':
    main()
