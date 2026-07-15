#!/usr/bin/env python3
# f29_nextday_c3.py -- F29 NEXT-DAY-RETURN  C-3 : regime split + daily cluster view.
#
# READ-ONLY. Same engine / same evaluated set as C-1/C-2. Never writes to any
# protected path. Does NOT modify build_weight.py, f29_retro.py, stocks_public,
# stock pages, or cron. Output = stdout + one /tmp JSON.
#
# Contract (Sky 2026-07-15):
#   1. window=15, input/exclusions/label-n identical to C-2.
#   2. regime = sign of the same outcome_date equal-weight universe mean return.
#   3. 0 kept as separate 'flat'; never merged into up/down.
#   4. per regime x label: absolute AND relative -> n, outcome_dates, mean, median,
#      positive/exceed rate, p10/p25/p75/p90.
#   5. daily cluster: compute per (outcome_date x label) daily-mean relative FIRST,
#      then aggregate across dates with EACH DATE AS ONE EQUAL-WEIGHT UNIT
#      (a day with more stocks is NOT up-weighted).
#   6. cluster min output: active_days, daily_mean's mean/median, positive_day_rate,
#      p10/p25/p75/p90.
#   7. highest/lowest contributing day + that day's label n (does a few days carry it).
#   8. raw observation n is NOT a count of independent samples / significance basis.
#   9. no writes to protected paths.
#  10. /tmp one-off only. append-only analytics decided AFTER C-3 verdict.
#
# Usage: python3 f29_nextday_c3.py <C-2 json path>
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
EXPECT_RETRO_SHA = '8e15d6e7418502fe0bbd777a864cf7c87739546dc6b85c5d690a80c3d85777bd'
EXPECT_BW_SHA = '6902ccbd94468e282c17fd9ee177da8715284456d55a7dae43ba4c04469b7966'
RETRO_PATH = os.path.join(BASE, 'f29_retro.py')
BW_PATH = os.path.join(BASE, 'build_weight.py')

if BASE not in sys.path:
    sys.path.insert(0, BASE)
import f29_retro as retro  # noqa: E402

ORDER = ['up_concentration', 'attention_up', 'fade_up',
         'neutral', 'fade_down', 'down_concentration']
REGIMES = ['ALL', 'up', 'down', 'flat']
NOTE = ('C-3 does NOT remove sector/theme correlation; it splits regime and reweights '
        'days equally to expose cluster illusion. Not a proof of judgment skill. '
        'raw observation n is not independent-sample count.')


def die(msg, code=2):
    print('[c3][FAIL] %s' % msg, file=sys.stderr)
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


def summ(vals):
    xs = sorted(vals)
    n = len(xs)
    if n == 0:
        return {'n': 0}
    mean = sum(xs) / n
    pos = sum(1 for r in xs if r > 0)
    return {'n': n, 'mean': round(mean, 4), 'median': round(pct(xs, 50), 4),
            'positive_rate': round(pos / n * 100.0, 2),
            'p10': round(pct(xs, 10), 4), 'p25': round(pct(xs, 25), 4),
            'p75': round(pct(xs, 75), 4), 'p90': round(pct(xs, 90), 4)}


def main():
    if len(sys.argv) < 2:
        die('usage: python3 f29_nextday_c3.py <C-2 json path>')
    c2 = json.load(open(sys.argv[1], encoding='utf-8'))
    if c2.get('window') != WINDOW:
        die('C-2 window mismatch')

    rsha, bsha = sha_file(RETRO_PATH), sha_file(BW_PATH)
    if rsha != EXPECT_RETRO_SHA or bsha != EXPECT_BW_SHA:
        die('engine SHA changed since C-0 -- input not identical to C-1/C-2')
    if c2.get('input_identity', {}).get('f29_retro_sha256') != rsha or \
       c2.get('input_identity', {}).get('build_weight_sha256') != bsha:
        die('engine SHA differs from C-2 record')

    codes = sorted(os.path.basename(p)[:-5]
                   for p in glob.glob(os.path.join(STOCKS_PUBLIC, '*.json')))
    mkt_total = retro.market_total()
    sessions = sorted(mkt_total.keys())
    mpos = {d: i for i, d in enumerate(sessions)}

    excl = {'no_next_session': 0, 'suspended_or_missing_next_session': 0,
            'signal_date_not_in_market_calendar': 0}
    candidate = evaluated = 0
    obs = []
    for code in codes:
        raw = retro.load_raw(code)
        if not raw or not raw.get('bars'):
            continue
        dates, close_raw, shares = retro.build_series(raw['bars'], mkt_total)
        if len(close_raw) < retro.AVG_N * 2:
            continue
        cbd = dict(zip(dates, close_raw))
        for t in range(len(close_raw)):
            j = retro.judge_at(close_raw, shares, t, windows=(WINDOW,))
            s = j.get(str(WINDOW))
            if not s:
                continue
            candidate += 1
            sd = dates[t]
            i = mpos.get(sd)
            if i is None:
                excl['signal_date_not_in_market_calendar'] += 1
                continue
            if i + 1 >= len(sessions):
                excl['no_next_session'] += 1
                continue
            od = sessions[i + 1]
            oc = cbd.get(od); csd = close_raw[t]
            if oc is None or csd <= 0:
                excl['suspended_or_missing_next_session'] += 1
                continue
            obs.append({'out': od, 'state': s['flowState'], 'label': s['flowLabel'],
                        'abs': round((oc / csd - 1.0) * 100.0, 2)})
            evaluated += 1
    excluded_total = sum(excl.values())

    # ---- benchmark + regime tag + relative ----
    bucket = {}
    for o in obs:
        bucket.setdefault(o['out'], []).append(o['abs'])
    benchmark = {d: sum(v) / len(v) for d, v in bucket.items()}
    regime_of = {}
    for d, m in benchmark.items():
        regime_of[d] = 'up' if m > 0 else ('down' if m < 0 else 'flat')
    for o in obs:
        o['rel'] = o['abs'] - benchmark[o['out']]
        o['reg'] = regime_of[o['out']]

    outcome_dates = sorted(bucket.keys())
    n_out = len(outcome_dates)

    # ---- cross-check vs C-2 (gates) ----
    c2o = c2.get('observations', {})
    if evaluated != c2o.get('evaluated'):
        die('gate: evaluated %d != C-2 %s' % (evaluated, c2o.get('evaluated')))
    if excluded_total != c2o.get('excluded_total') or excl != c2o.get('excluded_by_reason'):
        die('gate: exclusions differ from C-2')
    if n_out != c2.get('input_identity', {}).get('outcome_dates'):
        die('gate: outcome_dates %d != C-2 %s'
            % (n_out, c2.get('input_identity', {}).get('outcome_dates')))
    c2_label_n = {k: v['n'] for k, v in c2.get('groups_absolute', {}).items()
                  if k != '__ALL__'}

    # per-date excess mean zero
    worst = 0.0
    for d in outcome_dates:
        exs = [o['rel'] for o in obs if o['out'] == d]
        worst = max(worst, abs(sum(exs) / len(exs)))
    if worst > TOL:
        die('gate: per-date excess mean %.2e exceeds tol' % worst)

    # regime day partition
    reg_days = {'up': set(), 'down': set(), 'flat': set()}
    for d in outcome_dates:
        reg_days[regime_of[d]].add(d)
    if sum(len(v) for v in reg_days.values()) != n_out:
        die('gate: regime day counts do not sum to outcome_dates')
    if (reg_days['up'] | reg_days['down'] | reg_days['flat']) != set(outcome_dates):
        die('gate: regime day sets do not partition outcome_dates')

    # ---- (regime x label) pooled abs+rel  (item 4) ----
    cells = {}
    for reg in REGIMES:
        for st in ORDER:
            sel = [o for o in obs if o['state'] == st and (reg == 'ALL' or o['reg'] == reg)]
            if not sel:
                continue
            cells[(reg, st)] = {
                'n': len(sel),
                'outcome_dates': len({o['out'] for o in sel}),
                'absolute': summ([o['abs'] for o in sel]),
                'relative': summ([o['rel'] for o in sel]),
                'label': sel[0]['label'],
            }
    # gate: per label, up+down+flat n == C-2 label n  (and ALL == same)
    for st in ORDER:
        parts = sum(cells[(r, st)]['n'] for r in ('up', 'down', 'flat')
                    if (r, st) in cells)
        allc = cells.get(('ALL', st), {}).get('n', 0)
        if st in c2_label_n:
            if parts != c2_label_n[st] or allc != c2_label_n[st]:
                die('gate: label %s regime-n sum %d/all %d != C-2 %d'
                    % (st, parts, allc, c2_label_n[st]))

    # ---- daily cluster view (items 5-7) ----
    # per (regime, label): date -> daily mean rel, daily n
    daily = {}
    for o in obs:
        for reg in ('ALL', o['reg']):
            daily.setdefault((reg, o['state']), {}).setdefault(o['out'], []).append(o['rel'])
    cluster = {}
    for (reg, st), per_day in daily.items():
        rows = [(d, sum(r) / len(r), len(r)) for d, r in per_day.items()]
        means = sorted(m for _, m, _ in rows)
        active = len(rows)
        posd = sum(1 for m in means if m > 0)
        best = max(rows, key=lambda x: x[1])   # (date, mean, n)
        wrst = min(rows, key=lambda x: x[1])
        cluster[(reg, st)] = {
            'active_days': active,
            'min_label_n_per_day': min(n for _, _, n in rows),
            'max_label_n_per_day': max(n for _, _, n in rows),
            'daily_mean_mean': round(sum(means) / active, 4),
            'daily_mean_median': round(pct(means, 50), 4),
            'positive_day_rate': round(posd / active * 100.0, 2),
            'p10': round(pct(means, 10), 4), 'p25': round(pct(means, 25), 4),
            'p75': round(pct(means, 75), 4), 'p90': round(pct(means, 90), 4),
            'best_day': {'date': best[0], 'daily_mean': round(best[1], 4), 'label_n': best[2]},
            'worst_day': {'date': wrst[0], 'daily_mean': round(wrst[1], 4), 'label_n': wrst[2]},
        }

    # ---- json ----
    def cellkey(m):
        return {'%s|%s' % (r, s): v for (r, s), v in m.items()}
    doc = {
        'script': 'f29_nextday_c3.py', 'window': WINDOW,
        'generated_utc': datetime.datetime.now(datetime.timezone.utc)
                                  .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'c2_source': sys.argv[1],
        'input_identity': {'f29_retro_sha256': rsha, 'build_weight_sha256': bsha,
                           'evaluated': evaluated, 'excluded_total': excluded_total,
                           'outcome_dates': n_out},
        'regime_rule': 'sign of same outcome_date equal-weight universe mean return; '
                       '0 kept separate as flat',
        'regime_days': {r: len(reg_days[r]) for r in ('up', 'down', 'flat')},
        'gates': {'evaluated_eq_c2': True, 'outcome_dates_eq_c2': True,
                  'exclusions_eq_c2': True, 'label_regime_n_eq_c2': True,
                  'per_date_excess_max_abs': worst,
                  'regime_days_sum': sum(len(reg_days[r]) for r in ('up', 'down', 'flat'))},
        'note': NOTE,
        'regime_x_label': cellkey(cells),
        'daily_cluster': cellkey(cluster),
    }
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outpath = '/tmp/f29_nextday_c3_%s.json' % stamp
    blob = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
    open(outpath, 'wb').write(blob)
    sha = hashlib.sha256(blob).hexdigest()

    # ---- stdout ----
    P = print
    P('=' * 92)
    P('F29 NEXT-DAY-RETURN  C-3  regime split + daily cluster  (window=%d)' % WINDOW)
    P('=' * 92)
    P('input   f29_retro=%s.. build_weight=%s..  evaluated=%d excluded=%d outcome_dates=%d'
      % (rsha[:8], bsha[:8], evaluated, excluded_total, n_out))
    ud, dd, fd = len(reg_days['up']), len(reg_days['down']), len(reg_days['flat'])
    P('regime  up_days=%d  down_days=%d  flat_days=%d  sum=%d  (=%d PASS)'
      % (ud, dd, fd, ud + dd + fd, n_out))
    P('gates   eval=C2 | out_dates=C2 | excl=C2 | label_regime_n=C2 | '
      'per-date excess max|mean|=%.1e' % worst)

    P('\n[ item4 ] REGIME x LABEL  pooled   (rel = vs same-day equal-weight universe mean)')
    for reg in ['ALL', 'up', 'down', 'flat']:
        rows = [(st, cells[(reg, st)]) for st in ORDER if (reg, st) in cells]
        if not rows:
            continue
        dd_ = {'ALL': 'ALL (%d days)' % n_out, 'up': 'UP (%d days)' % ud,
               'down': 'DOWN (%d days)' % dd, 'flat': 'FLAT (%d days)' % fd}[reg]
        P('  --- %s ---' % dd_)
        P('  %-19s %6s %5s | %7s %7s %5s | %7s %7s %5s'
          % ('label', 'n', 'dts', 'abs_mn', 'abs_md', 'pos%', 'rel_mn', 'rel_md', 'exc%'))
        for st, c in rows:
            a, r = c['absolute'], c['relative']
            P('  %-19s %6d %5d | %7.2f %7.2f %5.1f | %7.2f %7.2f %5.1f'
              % (st, c['n'], c['outcome_dates'], a['mean'], a['median'],
                 a['positive_rate'], r['mean'], r['median'], r['positive_rate']))

    P('\n[ items5-7 ] DAILY CLUSTER  (each date = 1 equal-weight unit; more stocks NOT up-weighted)')
    P('  %-19s %-5s %4s %5s | %8s %8s %7s | %-16s %-16s'
      % ('label', 'reg', 'days', 'minN', 'dMean', 'dMed', 'posDay%', 'worst_day(n)', 'best_day(n)'))
    for st in ORDER:
        for reg in ['ALL', 'up', 'down']:
            k = (reg, st)
            if k not in cluster:
                continue
            c = cluster[k]
            P('  %-19s %-5s %4d %5d | %8.3f %8.3f %7.1f | %-16s %-16s'
              % (st, reg, c['active_days'], c['min_label_n_per_day'],
                 c['daily_mean_mean'], c['daily_mean_median'], c['positive_day_rate'],
                 '%s(%d)' % (c['worst_day']['date'][4:], c['worst_day']['label_n']),
                 '%s(%d)' % (c['best_day']['date'][4:], c['best_day']['label_n'])))
        P('  ' + '-' * 86)
    P('json  %s' % outpath)
    P('sha   %s' % sha)
    P('NOTE  %s' % NOTE)


if __name__ == '__main__':
    main()
