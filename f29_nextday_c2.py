#!/usr/bin/env python3
# f29_nextday_c2.py -- F29 NEXT-DAY-RETURN  C-2 : absolute + market-relative.
#
# READ-ONLY. Same engine, same evaluated set as C-1. Never writes to any
# protected path. Does NOT modify build_weight.py, f29_retro.py, stocks_public,
# stock pages, or cron. Output = stdout + one /tmp JSON.
#
# Contract (Sky 2026-07-15):
#   - window = 15 fixed.
#   - relative_return_pp = stock_return_pct
#       - equal-weight mean of ALL evaluable universe on the SAME outcome_date.
#   - benchmark universe is DYNAMIC per date; NO 201/202 hardcoded in the math.
#   - NOT a KOSPI/KOSDAQ index, NOT leave-one-out. Plain same-date equal-weight mean.
#   - absolute and relative printed side by side, per label.
#   - relative positive_rate = share EXCEEDING same-date universe mean (NOT up-prob).
#   - C-2 does not establish significance/selection skill: equal-weight removes the
#     common LEVEL only, not sector/theme correlation or the daily cluster effect.
#
# Usage: python3 f29_nextday_c2.py /tmp/f29_nextday_c1_XXXXXX.json
#   The C-1 json is required and used to cross-check identical input/evaluated set.
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

# Engine SHAs audited at C-0 (2026-07-15). C-2 MUST run on the same engine as C-1,
# else absolute numbers would not reproduce. These are verification targets, not
# universe constants.
EXPECT_RETRO_SHA = '8e15d6e7418502fe0bbd777a864cf7c87739546dc6b85c5d690a80c3d85777bd'
EXPECT_BW_SHA = '6902ccbd94468e282c17fd9ee177da8715284456d55a7dae43ba4c04469b7966'
RETRO_PATH = os.path.join(BASE, 'f29_retro.py')
BW_PATH = os.path.join(BASE, 'build_weight.py')

if BASE not in sys.path:
    sys.path.insert(0, BASE)
import f29_retro as retro  # noqa: E402

REL_POS_MEANING = ('share of observations whose next-day return EXCEEDS the '
                   'same outcome_date equal-weight universe mean '
                   '(market-relative out-performance rate, NOT an up-probability)')
BIAS_NOTICE = (
    'Equal-weight same-date relativization removes the common market LEVEL only. '
    'It does NOT remove sector/theme correlation or the daily cluster effect. '
    'Do not read significance or selection skill from C-2 alone; that needs C-3 '
    'regime split + daily cluster validation. Survivorship/selection bias of the '
    'current stocks_public universe still applies.')


def die(msg, code=2):
    print('[c2][FAIL] %s' % msg, file=sys.stderr)
    sys.exit(code)


def sha_file(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def pct(xs_sorted, q):
    n = len(xs_sorted)
    if n == 0:
        return None
    if n == 1:
        return xs_sorted[0]
    rank = (q / 100.0) * (n - 1)
    lo = int(math.floor(rank)); hi = int(math.ceil(rank))
    if lo == hi:
        return xs_sorted[lo]
    frac = rank - lo
    return xs_sorted[lo] * (1 - frac) + xs_sorted[hi] * frac


def summarize(vals, pos_is_exceed=False):
    xs = sorted(vals)
    n = len(xs)
    if n == 0:
        return {'n': 0}
    mean = sum(xs) / n
    pos = sum(1 for r in xs if r > 0)
    d = {
        'n': n,
        'mean': round(mean, 4),
        'median': round(pct(xs, 50), 4),
        'positive_rate': round(pos / n * 100.0, 2),
        'positive_count': pos,
        'p10': round(pct(xs, 10), 4),
        'p25': round(pct(xs, 25), 4),
        'p75': round(pct(xs, 75), 4),
        'p90': round(pct(xs, 90), 4),
        'min': round(xs[0], 4),
        'max': round(xs[-1], 4),
    }
    if pos_is_exceed:
        d['positive_rate_meaning'] = REL_POS_MEANING
    return d


def main():
    if len(sys.argv) < 2:
        die('usage: python3 f29_nextday_c2.py <C-1 json path>')
    c1_path = sys.argv[1]
    try:
        c1 = json.load(open(c1_path, encoding='utf-8'))
    except Exception as e:
        die('cannot read C-1 json (%s): %s' % (c1_path, e))
    if c1.get('window') != WINDOW:
        die('C-1 window %r != %d' % (c1.get('window'), WINDOW))

    # ---- engine identity (gate 8) ----
    rsha, bsha = sha_file(RETRO_PATH), sha_file(BW_PATH)
    if rsha != EXPECT_RETRO_SHA:
        die('f29_retro.py SHA changed since C-0 (%s) -- input not identical to C-1' % rsha)
    if bsha != EXPECT_BW_SHA:
        die('build_weight.py SHA changed since C-0 (%s) -- input not identical to C-1' % bsha)

    if not os.path.isdir(STOCKS_PUBLIC):
        die('stocks_public not found')
    codes = sorted(os.path.basename(p)[:-5]
                   for p in glob.glob(os.path.join(STOCKS_PUBLIC, '*.json')))
    if not codes:
        die('stocks_public empty')

    mkt_total = retro.market_total()
    sessions = sorted(mkt_total.keys())
    mpos = {d: i for i, d in enumerate(sessions)}

    stocks_total = len(codes)
    stocks_no_data = 0
    stocks_too_short = 0
    stocks_contributing = 0
    candidate = 0
    evaluated = 0
    excl = {'no_next_session': 0,
            'suspended_or_missing_next_session': 0,
            'signal_date_not_in_market_calendar': 0}

    obs = []   # each: {code, sig, out, state, label, abs}
    for code in codes:
        raw = retro.load_raw(code)
        if not raw or not raw.get('bars'):
            stocks_no_data += 1
            continue
        dates, close_raw, shares = retro.build_series(raw['bars'], mkt_total)
        if len(close_raw) < retro.AVG_N * 2:
            stocks_too_short += 1
            continue
        close_by_date = dict(zip(dates, close_raw))
        labeled_here = 0
        for t in range(len(close_raw)):
            j = retro.judge_at(close_raw, shares, t, windows=(WINDOW,))
            s = j.get(str(WINDOW))
            if not s:
                continue
            candidate += 1
            labeled_here += 1
            sd = dates[t]
            i = mpos.get(sd)
            if i is None:
                excl['signal_date_not_in_market_calendar'] += 1
                continue
            if i + 1 >= len(sessions):
                excl['no_next_session'] += 1
                continue
            od = sessions[i + 1]
            oc = close_by_date.get(od)
            csd = close_raw[t]
            if oc is None or csd <= 0:
                excl['suspended_or_missing_next_session'] += 1
                continue
            ret = round((oc / csd - 1.0) * 100.0, 2)
            obs.append({'code': code, 'sig': sd, 'out': od,
                        'state': s['flowState'], 'label': s['flowLabel'], 'abs': ret})
            evaluated += 1
        if labeled_here:
            stocks_contributing += 1
        else:
            stocks_too_short += 1

    excluded_total = sum(excl.values())

    # ---------------------------------------------------- internal reconciliation
    if candidate != evaluated + excluded_total:
        die('recon: candidate(%d) != evaluated(%d)+excluded(%d)'
            % (candidate, evaluated, excluded_total))

    # ---------------------------------------------------- benchmark per outcome_date
    bucket = {}
    for o in obs:
        bucket.setdefault(o['out'], []).append(o['abs'])
    benchmark = {d: (sum(v) / len(v)) for d, v in bucket.items()}
    benchmark_n = {d: len(v) for d, v in bucket.items()}

    # gate 3: benchmark_n each == that day's evaluated count (by construction);
    #         verify totals + positivity.
    if sum(benchmark_n.values()) != evaluated:
        die('gate3: sum(benchmark_n)=%d != evaluated=%d'
            % (sum(benchmark_n.values()), evaluated))
    if any(nn <= 0 for nn in benchmark_n.values()):
        die('gate3: a benchmark_n is <= 0')
    n_out_dates = len(bucket)
    n_sig_dates = len({o['sig'] for o in obs})
    if n_out_dates != n_sig_dates:
        die('gate2: distinct outcome dates %d != distinct signal dates %d'
            % (n_out_dates, n_sig_dates))

    # ---------------------------------------------------- relative + per-date mean-zero
    per_date_excess = {}
    for o in obs:
        ex = o['abs'] - benchmark[o['out']]     # raw (unrounded) for gate checks
        o['rel'] = ex
        per_date_excess.setdefault(o['out'], []).append(ex)
    # gate 5: each date's excess mean ~ 0
    worst = 0.0
    for d, exs in per_date_excess.items():
        m = sum(exs) / len(exs)
        worst = max(worst, abs(m))
        if abs(m) > TOL:
            die('gate5: outcome_date %s excess mean %.3e exceeds tol %.1e' % (d, m, TOL))
    all_excess = [o['rel'] for o in obs]
    all_excess_mean = sum(all_excess) / len(all_excess) if all_excess else 0.0
    if abs(all_excess_mean) > TOL:                # gate 6
        die('gate6: ALL excess mean %.3e exceeds tol %.1e' % (all_excess_mean, TOL))

    # ---------------------------------------------------- group + cross-check vs C-1
    order = ['up_concentration', 'attention_up', 'fade_up',
             'neutral', 'fade_down', 'down_concentration']
    abs_g, rel_g, gn = {}, {}, {}
    for st in order:
        a = [o['abs'] for o in obs if o['state'] == st]
        r = [o['rel'] for o in obs if o['state'] == st]
        if not a:
            continue
        abs_g[st] = summarize(a)
        abs_g[st]['label'] = next(o['label'] for o in obs if o['state'] == st)
        rel_g[st] = summarize(r, pos_is_exceed=True)
        gn[st] = len(a)
    abs_all = dict(summarize([o['abs'] for o in obs]), label='(all evaluated)')
    rel_all = summarize(all_excess, pos_is_exceed=True)

    # cross-checks against C-1 json (gates 1,4,7 + input identity for gate 8)
    c1o = c1.get('observations', {})
    if evaluated != c1o.get('evaluated'):
        die('gate1: evaluated %d != C-1 %s' % (evaluated, c1o.get('evaluated')))
    if candidate != c1o.get('candidate'):
        die('gate7: candidate %d != C-1 %s' % (candidate, c1o.get('candidate')))
    if excluded_total != c1o.get('excluded_total'):
        die('gate7: excluded_total %d != C-1 %s' % (excluded_total, c1o.get('excluded_total')))
    if excl != c1o.get('excluded_by_reason'):
        die('gate7: excluded_by_reason %r != C-1 %r' % (excl, c1o.get('excluded_by_reason')))
    c1g = c1.get('groups', {})
    c1_gn = {k: v['n'] for k, v in c1g.items() if k != '__ALL__' and v.get('n', 0) > 0}
    if gn != c1_gn:
        die('gate4: per-label n %r != C-1 %r' % (gn, c1_gn))
    # gate 8: same universe count + spans as C-1
    if stocks_total != c1.get('universe', {}).get('stocks_public_total'):
        die('gate8: stocks_public_total %d != C-1 %s'
            % (stocks_total, c1.get('universe', {}).get('stocks_public_total')))
    sig_first = min(o['sig'] for o in obs); sig_last = max(o['sig'] for o in obs)
    out_first = min(o['out'] for o in obs); out_last = max(o['out'] for o in obs)
    if (c1.get('signal_date_span', {}).get('first') != sig_first or
            c1.get('signal_date_span', {}).get('last') != sig_last or
            c1.get('outcome_date_span', {}).get('first') != out_first or
            c1.get('outcome_date_span', {}).get('last') != out_last):
        die('gate8: date span mismatch vs C-1')

    # ---------------------------------------------------- write json
    doc = {
        'script': 'f29_nextday_c2.py',
        'generated_utc': datetime.datetime.now(datetime.timezone.utc)
                                  .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'window': WINDOW,
        'c1_source': c1_path,
        'input_identity': {
            'f29_retro_sha256': rsha,
            'build_weight_sha256': bsha,
            'stocks_public_total': stocks_total,
            'signal_date_span': {'first': sig_first, 'last': sig_last},
            'outcome_date_span': {'first': out_first, 'last': out_last},
            'outcome_dates': n_out_dates,
        },
        'relative_definition': ('stock_return_pct - equal-weight mean of ALL '
                                'evaluated stocks sharing the same outcome_date'),
        'relative_positive_rate_meaning': REL_POS_MEANING,
        'bias_notice': BIAS_NOTICE,
        'observations': {
            'candidate': candidate, 'evaluated': evaluated,
            'excluded_total': excluded_total, 'excluded_by_reason': excl,
        },
        'gates': {
            'g1_evaluated_matches_c1': True,
            'g2_outcome_dates': n_out_dates,
            'g3_benchmark_n_sum_matches_evaluated': True,
            'g4_per_label_n_matches_c1': True,
            'g5_per_date_excess_mean_zero_max_abs': worst,
            'g6_all_excess_mean': all_excess_mean,
            'g7_exclusions_match_c1': True,
            'g8_input_identity_matches_c1': True,
        },
        'benchmark_n_by_date': dict(sorted(benchmark_n.items())),
        'groups_absolute': dict(abs_g, __ALL__=abs_all),
        'groups_relative': dict(rel_g, __ALL__=rel_all),
    }
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outpath = '/tmp/f29_nextday_c2_%s.json' % stamp
    blob = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
    open(outpath, 'wb').write(blob)
    sha = hashlib.sha256(blob).hexdigest()

    # ---------------------------------------------------- stdout
    P = print
    P('=' * 84)
    P('F29 NEXT-DAY-RETURN  C-2  (window=%d)   absolute | market-relative' % WINDOW)
    P('=' * 84)
    P('input     f29_retro=%s..  build_weight=%s..' % (rsha[:8], bsha[:8]))
    P('          stocks_public=%d  signal %s..%s  outcome %s..%s  outcome_dates=%d'
      % (stocks_total, sig_first, sig_last, out_first, out_last, n_out_dates))
    P('signals   candidate=%d  evaluated=%d  excluded=%d  (matches C-1)'
      % (candidate, evaluated, excluded_total))
    P('gates     g1 eval=C1 PASS | g2 out_dates=%d | g3 bench_n_sum=eval PASS |'
      % n_out_dates)
    P('          g4 label_n=C1 PASS | g5 per-date excess max|mean|=%.2e | '
      'g6 ALL excess mean=%.2e | g7 excl=C1 PASS | g8 input=C1 PASS'
      % (worst, all_excess_mean))
    P('-' * 84)
    P('%-19s %6s | %7s %7s %6s | %8s %8s %6s'
      % ('label', 'n', 'abs_med', 'abs_mn', 'pos%', 'rel_med', 'rel_mn', 'exc%'))
    P('%-19s %6s | %7s %7s %6s | %8s %8s %6s'
      % ('', '', '', '', '', '(vs same-day univ mean)', '', ''))
    for st in order + ['__ALL__']:
        a = abs_g.get(st) if st != '__ALL__' else abs_all
        r = rel_g.get(st) if st != '__ALL__' else rel_all
        if not a or a.get('n', 0) == 0:
            continue
        P('%-19s %6d | %7.2f %7.2f %6.1f | %8.2f %8.2f %6.1f'
          % (st, a['n'], a['median'], a['mean'], a['positive_rate'],
             r['median'], r['mean'], r['positive_rate']))
    P('-' * 84)
    P('abs_* = absolute next-day return %%.  rel_* = return minus same-outcome-date '
      'equal-weight universe mean.')
    P('exc%% = share exceeding that same-day mean (out-performance rate, NOT up-prob).')
    P('json  %s' % outpath)
    P('sha   %s' % sha)
    P('NOTE  equal-weight relativization removes common level only; sector/theme + '
      'cluster remain -> C-3.')


if __name__ == '__main__':
    main()
