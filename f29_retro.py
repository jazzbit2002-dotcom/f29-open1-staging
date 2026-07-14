#!/usr/bin/env python3
# f29_retro.py — F29 소급/diff 공용 판정 엔진 v1 (2026-07-13)
# 계약: 판정 로직을 복제하지 않는다. build_weight.py의 원본 함수를 import해
#       "시계열을 T 시점에서 자른 뒤 같은 함수에 통과"시킨다.
#       → 소급(retro)·전일(diff)·라이브가 코드 구조상 동일 엔진임이 보장된다.
# 계약: 미래 데이터 참조 금지. T 시점 판정은 bars[:T+1]만 사용한다.

import os, sys, json

BASE = '/root/krx-moneyflow'
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 원본 엔진 (복제 금지 — import만)
from build_weight import (
    flow_state, window_ratio, window_change,
    avg_head, avg_tail, market_total_tv, PRICE_EPS, AVG_N,
)

_MKT_CACHE = None


def market_total():
    """점유율 분모. OHLCV 전량 스캔이므로 빌드당 1회만 계산해 캐시."""
    global _MKT_CACHE
    if _MKT_CACHE is None:
        _MKT_CACHE = market_total_tv()
    return _MKT_CACHE

WINDOWS = (15, 30, 60, 90)
RAW_DIR = os.path.join(BASE, 'data/stocks')

# 상태 severity: 재방문 서사에서 "개선/악화" 판정에 사용
# up_concentration(강) > attention_up > fade_up > neutral > fade_down > down_concentration(약)
STATE_RANK = {
    'up_concentration': 3,
    'attention_up': 2,
    'fade_up': 1,
    'neutral': 0,
    'fade_down': -1,
    'down_concentration': -2,
}


def load_raw(code):
    """data/stocks/{code}.json — bars(date, close, tradingValue, marketCap, changeRate)"""
    p = os.path.join(RAW_DIR, f'{code}.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def build_series(bars, mkt_total):
    """bars → (dates, close_raw, shares). build_weight 190~196행과 동일 산식."""
    dates, close_raw, shares = [], [], []
    for b in bars:
        date = str(b.get('date', ''))
        close = float(b.get('close') or 0)
        tv = float(b.get('tradingValue') or 0)
        mt = float(mkt_total.get(date, 0) or 0)
        if close <= 0:
            continue
        dates.append(date)
        close_raw.append(close)
        shares.append(round((tv / mt * 100.0) if mt > 0 else 0.0, 4))
    return dates, close_raw, shares


def judge_at(close_raw, shares, upto, windows=WINDOWS):
    """T=upto 시점의 창별 판정. 미래 데이터 미참조(슬라이스로 절단).
    반환: {'15': {state,label,priceChangePct,shareDeltaPp}, ...}"""
    cr = close_raw[:upto + 1]
    sh = shares[:upto + 1]
    if len(cr) < AVG_N * 2:
        return {}
    out = {}
    for w in windows:
        if len(cr) < w:
            continue
        seg = cr[-w:]
        p_then, p_now = avg_head(seg), avg_tail(seg)
        price_chg = round((p_now / p_then - 1) * 100, 2) if p_then > 0 else 0.0
        sr = window_ratio(sh, w)
        sd = window_change(sh, w)
        state, label = flow_state(sr, price_chg)
        out[str(w)] = {
            'flowState': state, 'flowLabel': label,
            'priceChangePct': price_chg, 'shareDeltaPp': round(sd, 3),
        }
    return out


def history(close_raw, shares, dates, n=20, window=15):
    """최근 n거래일 판정 이력 (소급). 각 원소는 그날까지의 데이터만으로 판정."""
    out = []
    start = max(0, len(close_raw) - n)
    for t in range(start, len(close_raw)):
        j = judge_at(close_raw, shares, t, windows=(window,))
        s = j.get(str(window))
        if not s:
            continue
        nxt = None
        if t + 1 < len(close_raw):
            nxt = round((close_raw[t + 1] / close_raw[t] - 1) * 100, 2)
        out.append({
            'date': dates[t],
            'flowState': s['flowState'], 'flowLabel': s['flowLabel'],
            'priceChangePct': s['priceChangePct'],
            'shareDeltaPp': s['shareDeltaPp'],
            'nextDayReturn': nxt,   # 다음 거래일 실제 종가 등락 (마지막 날은 None)
        })
    return out


def diff_prev(close_raw, shares, windows=WINDOWS):
    """전일 대비 변화. 오늘(T)과 전일(T-1)을 같은 엔진으로 판정 후 비교.
    반환: [{'window','field','prev','curr','kind'}] — 상태 변화 우선."""
    n = len(close_raw)
    if n < 2:
        return []
    cur = judge_at(close_raw, shares, n - 1, windows)
    prv = judge_at(close_raw, shares, n - 2, windows)
    changes = []
    for w in windows:
        k = str(w)
        c, p = cur.get(k), prv.get(k)
        if not c or not p:
            continue
        if c['flowState'] != p['flowState']:
            changes.append({
                'window': w, 'field': 'state', 'kind': 'state',
                'prev': p['flowLabel'], 'curr': c['flowLabel'],
                'delta': STATE_RANK.get(c['flowState'], 0) - STATE_RANK.get(p['flowState'], 0),
            })
        ds = round(c['shareDeltaPp'] - p['shareDeltaPp'], 3)
        if abs(ds) >= 0.1:
            changes.append({
                'window': w, 'field': 'share', 'kind': 'metric',
                'prev': p['shareDeltaPp'], 'curr': c['shareDeltaPp'], 'delta': ds,
            })
        dp = round(c['priceChangePct'] - p['priceChangePct'], 2)
        if abs(dp) >= 0.5:
            changes.append({
                'window': w, 'field': 'price', 'kind': 'metric',
                'prev': p['priceChangePct'], 'curr': c['priceChangePct'], 'delta': dp,
            })
    # 상태 변화 우선 → 짧은 창 우선 → 변화폭 큰 순
    changes.sort(key=lambda x: (0 if x['kind'] == 'state' else 1, x['window'], -abs(x['delta'])))
    return changes


def analyze(code, mkt_total=None):
    """종목 1개의 소급/diff 전체 산출. builder가 호출하는 단일 진입점."""
    if mkt_total is None:
        mkt_total = market_total()
    raw = load_raw(code)
    if not raw or not raw.get('bars'):
        return None
    bars = raw['bars']
    dates, close_raw, shares = build_series(bars, mkt_total)
    if len(close_raw) < AVG_N * 2:
        return None
    last = bars[-1]
    return {
        'quote': {   # 헤더 시세 (현재 페이지 결손분)
            'date': str(last.get('date', '')),
            'close': last.get('close'),
            'changeRate': last.get('changeRate'),
            'tradingValue': last.get('tradingValue'),
            'marketCap': last.get('marketCap'),
        },
        'today': judge_at(close_raw, shares, len(close_raw) - 1),
        'diff': diff_prev(close_raw, shares),
        'history': history(close_raw, shares, dates, n=20, window=15),
        'bars': len(close_raw),
    }
