#!/usr/bin/env python3
"""
collect_etf_ibit.py — IBIT 일일 폴링 (P1-a1, cron 진입점).

감리 반영:
- B-2/B-16: 완료 조건 = **오늘 목표 도달** (latest_as_of >= expected_issuer_as_of,
       expected = KST 창 날짜의 직전 미국 영업일). "DB보다 새로움(advanced)"이 아님 —
       뒤처진 DB 에서 target 미달 파일은 저장하되 marker 금지·폴링 계속.
       휴장일에 전일 창 digest 라도 target 충족이면 오늘 marker 작성(반복 취득 차단).
       done marker(ledger/etf_ibit_done.json) 후속 cron 은 네트워크 호출 전 종료.
       fcntl.flock 으로 중복 프로세스 차단.
- B-12: effective_trade_date 는 증거 확정 전 NULL + alignment_status=provisional 저장.
- B-5: canonical 은 신규 날짜만 INSERT. 기존 날짜 값 변경은 revisions 에 append.
       같은 파일 digest 재실행 = no-op (etf_collect_log).
- B-6: enabled(true=수집 대상) / kill_switch_active(true=즉시 중지) 분리 해석.
- 비차단: stdout 에 정확한 추정 금액 미출력(행수·날짜·digest 접두만).
          persistence_mode 실측값 저장. source_health / pipeline_runs 갱신.
"""
import fcntl
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from collectors import etf_issuer as E              # noqa: E402
from collectors.us_calendar import prev_us_business_day  # noqa: E402

DB = os.path.join(BASE, "data", "recovery_core.sqlite")
REGISTRY = os.path.join(BASE, "config", "etf_issuer_registry.json")
LEDGER = os.path.join(BASE, "ledger")
DONE_MARKER = os.path.join(LEDGER, "etf_ibit_done.json")
LOCKFILE = os.path.join(LEDGER, ".etf_ibit.lock")
FIRST_SEEN_LOG = os.path.join(LEDGER, "ibit_first_seen.log")


def _now_utc():
    return datetime.now(timezone.utc)


def _kst_window_date(now_utc=None) -> str:
    """현재 KST 날짜 (폴링 창 식별자)."""
    now = now_utc or _now_utc()
    return (now + timedelta(hours=9)).strftime("%Y-%m-%d")


def _done_today(window_date: str, done_marker: str = None) -> bool:
    done_marker = DONE_MARKER if done_marker is None else done_marker
    if not os.path.exists(done_marker):
        return False
    try:
        with open(done_marker, encoding="utf-8") as f:
            m = json.load(f)
        return m.get("window_date_kst") == window_date
    except (json.JSONDecodeError, OSError):
        return False


def _write_done(window_date: str, expected_issuer_as_of: str, as_of: str, digest: str,
                done_marker: str = None):
    """비차단: tmp 작성 후 os.replace 원자 교체."""
    os.makedirs(LEDGER, exist_ok=True)
    done_marker = DONE_MARKER if done_marker is None else done_marker
    tmp = done_marker + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"window_date_kst": window_date,
                   "expected_issuer_as_of": expected_issuer_as_of,
                   "as_of": as_of, "digest": digest,
                   "done_at": _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}, f)
    os.replace(tmp, done_marker)


def _log_first_seen(window_date: str, as_of: str, first_seen_log: str = None):
    """IBIT 갱신 최초 관측 시각 로그 — candidate_window → 확정용 5영업일 근거 (B-3)."""
    os.makedirs(LEDGER, exist_ok=True)
    first_seen_log = FIRST_SEEN_LOG if first_seen_log is None else first_seen_log
    with open(first_seen_log, "a", encoding="utf-8") as f:
        f.write(f"{_now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}\twindow={window_date}\tas_of={as_of}\n")


def store_new_and_revisions(con, asset, ticker, source_id, digest,
                            persistence_mode, creation_series):
    """B-5: 신규 날짜만 canonical INSERT. 기존 날짜 값 상이 → revisions append. 반환 (added, revised)."""
    now = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    added = revised = 0
    for rec in creation_series:
        iso = rec["as_of"]
        row = con.execute(
            "SELECT delta_shares, nav_per_share, est_creation_usd FROM etf_daily "
            "WHERE asset=? AND ticker=? AND issuer_as_of_date=?",
            (asset, ticker, iso)).fetchone()
        if row is None:
            # B-12 경로 B: 증거 확정 전 effective_trade_date=NULL, alignment_status='provisional'.
            # prev_us_business_day 규칙은 증거(digest 포함 대조) 확보 후 backfill 에서 적용.
            con.execute(
                """INSERT INTO etf_daily
                   (asset, ticker, issuer_as_of_date, effective_trade_date,
                    delta_shares, nav_per_share, est_creation_usd,
                    source_id, input_digest, first_seen_at, last_seen_at,
                    persistence_mode, alignment_status)
                   VALUES (?,?,?,NULL,?,?,?,?,?,?,?,?, 'provisional')""",
                (asset, ticker, iso, rec["delta_shares"], rec["nav_per_share"],
                 rec["est_creation_usd"], source_id, digest, now, now, persistence_mode))
            added += 1
        else:
            same = (abs(row[0] - rec["delta_shares"]) < 1e-9 and
                    abs(row[1] - rec["nav_per_share"]) < 1e-9 and
                    abs(row[2] - rec["est_creation_usd"]) < 1e-6)
            if same:
                con.execute(
                    "UPDATE etf_daily SET last_seen_at=? WHERE asset=? AND ticker=? AND issuer_as_of_date=?",
                    (now, asset, ticker, iso))
            else:
                # canonical 무접촉 — revisions append-only
                cur = con.execute(
                    """INSERT OR IGNORE INTO etf_daily_revisions
                       (asset, ticker, issuer_as_of_date, delta_shares, nav_per_share,
                        est_creation_usd, source_revision_digest, seen_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (asset, ticker, iso, rec["delta_shares"], rec["nav_per_share"],
                     rec["est_creation_usd"], digest, now))
                revised += cur.rowcount  # OR IGNORE 무시분 미계상 (비차단 3)
    con.commit()
    return added, revised


def _update_health(con, source_id, status, ok: bool):
    now = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute(
        """INSERT INTO source_health (source_id, last_success_at, last_status, consecutive_failures)
           VALUES (?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET
             last_success_at = CASE WHEN ? THEN excluded.last_success_at ELSE last_success_at END,
             last_status = excluded.last_status,
             consecutive_failures = CASE WHEN ? THEN 0 ELSE consecutive_failures + 1 END""",
        (source_id, now if ok else None, status, 0 if ok else 1, ok, ok))
    con.commit()


def _run_log(con, step, status, notes=""):
    now = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("INSERT INTO pipeline_runs (run_id, started_at, finished_at, step, status, notes) "
                "VALUES (?,?,?,?,?,?)",
                (uuid.uuid4().hex[:12], now, now, step, status, notes))
    con.commit()


_LEGACY_TICKER = "IBIT"
# fullmatch, not match: Python's "$" also matches immediately before a
# trailing newline character, so a match()-based guard accepts a ticker
# with one appended and leaks it into the derived filenames.
_SAFE_TICKER = re.compile(r"[A-Za-z0-9]+")


def _paths_for(ticker):
    """D4-1: per-ticker ledger artefacts.

    IBIT returns the module globals verbatim so that existing tests
    monkeypatching DONE_MARKER / LOCKFILE / FIRST_SEEN_LOG keep working
    and the live IBIT ledger keeps its filenames (migration-free).
    Every other ticker derives its own set, which is what keeps
    _done_today from being shared across issuers.

    The ticker lands in a filesystem path and is read before the
    registry is consulted, so it is charset-guarded here.
    """
    if not _SAFE_TICKER.fullmatch(ticker or ""):
        raise ValueError("unsafe ticker for path derivation: %r" % (ticker,))
    t = ticker.lower()
    if t == _LEGACY_TICKER.lower():
        return DONE_MARKER, LOCKFILE, FIRST_SEEN_LOG, "etf_ibit"
    return (os.path.join(LEDGER, "etf_%s_done.json" % t),
            os.path.join(LEDGER, ".etf_%s.lock" % t),
            os.path.join(LEDGER, "%s_first_seen.log" % t),
            "etf_%s" % t)


def _expected_as_of(window_date, target_lag_us_business_days):
    """Completion target for a window.

    Lag 0 is the previous U.S. business day - the rule IBIT was ratified
    on.  Each additional unit steps one further business day back, so the
    holiday calendar is honoured at every step rather than only the first.
    """
    d = date.fromisoformat(window_date)
    for _ in range(target_lag_us_business_days + 1):
        d = prev_us_business_day(d)
    return d.isoformat()


def _target_lag_for(ticker, meta):
    """Return a ratified U.S.-business-day lag, or None for observation-only."""
    if "target_lag_us_business_days" not in meta:
        raise ValueError(
            "target_lag_us_business_days key missing for %s "
            "(observation-only must be an explicit null)" % (ticker,))
    lag = meta["target_lag_us_business_days"]
    if lag is None:
        return None
    # bool is a subclass of int, so reject it explicitly.
    if isinstance(lag, bool) or not isinstance(lag, int) or lag < 0:
        raise ValueError(
            "invalid target_lag_us_business_days for %s: %r" % (ticker, lag))
    return lag


def main(asset="BTC", ticker="IBIT"):
    os.makedirs(LEDGER, exist_ok=True)
    done_marker, lockfile, first_seen_log, runlog_tag = _paths_for(ticker)
    # flock — 중복 프로세스 차단 (B-2)
    lock_fd = open(lockfile, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[lock] 다른 수집 프로세스 실행 중 — 종료")
        return 0

    window = _kst_window_date()
    # B-16: 오늘 목표 = KST 창 날짜의 직전 미국 영업일
    if _done_today(window, done_marker):
        print(f"[done] {window} 창 이미 완료 — 네트워크 호출 없이 종료 (B-2)")
        return 0

    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    asset_cfg = reg["assets"].get(asset, {})
    meta = asset_cfg.get("issuers", {}).get(ticker, {})

    # D3: the completion target belongs to the issuer, not to the driver.
    # An issuer whose lag is not ratified runs observation-only - it
    # collects and stores, but never claims a window complete, so neither
    # the done marker nor the first_seen ledger is touched.  That blank is
    # the intended state; the lag evidence is the first-observation row
    # each new digest leaves in etf_collect_log.
    target_lag = _target_lag_for(ticker, meta)
    observation_only = target_lag is None
    expected = None if observation_only else _expected_as_of(window, target_lag)

    # B-6: enabled / kill_switch_active 분리
    if not asset_cfg.get("enabled") or not meta.get("enabled"):
        print(f"[skip] {asset}/{ticker} enabled=false")
        return 0
    if meta.get("kill_switch_active"):
        print(f"[stop] {ticker} kill_switch_active=true — 수집 중지")
        return 0

    url, parser_name = meta.get("download_url"), meta.get("parser")
    if not url:
        print(f"[skip] {ticker} download_url 미설정")
        return 0

    source_id = f"etf_issuer_{ticker.lower()}"
    max_lag = reg.get("freshness", {}).get("max_lag_business_days", 5)
    con = sqlite3.connect(DB)
    try:
        try:
            result = E.poll_and_collect(ticker, url, parser_name,
                                        max_lag_business_days=max_lag)
        except Exception as e:
            _update_health(con, source_id, f"error: {type(e).__name__}", ok=False)
            _run_log(con, runlog_tag, "FAIL", str(e)[:200])
            print(f"[fail] {ticker}: {type(e).__name__}: {e}")
            return 1

        digest = result["input_digest"]

        # B-13: stale → canonical 기록·done marker 금지
        if result.get("freshness") == "stale":
            _update_health(con, source_id, "stale", ok=False)
            _run_log(con, runlog_tag, "STALE", f"latest={result['latest_as_of']}")
            print(f"[stale] latest_as_of={result['latest_as_of']} 허용 lag 초과 — 기록 안 함")
            return 0

        # B-10: digest 판정이 날짜 판정보다 먼저 — 같은 digest = 완전 NOOP
        dup = con.execute(
            "SELECT window_date_kst, latest_as_of, completed FROM etf_collect_log "
            "WHERE source_id=? AND input_digest=?", (source_id, digest)).fetchone()
        if dup:
            dup_window, dup_latest, dup_completed = dup
            # B-16: 완료 판정 = 오늘 target 도달 (dup_latest >= expected).
            #  - 같은 창(B-15 crash 복구): marker 복구 + first_seen 보충(원 실행이 못 남김)
            #  - 다른 창(휴장일 등): target 충족이면 오늘 marker 작성(반복 취득 차단).
            #    first_seen 은 해당 as_of 최초 관측 창에서 이미 기록 — 중복 기록 금지
            #  - target 미달: marker 금지, 폴링 계속
            if observation_only or not dup_completed:
                # Two cases collapse into a plain no-op, and neither may
                # touch collect_log, the marker or first_seen:
                #  - observation_only: no ratified target exists, so nothing
                #    can claim completion.
                #  - not dup_completed: this row was written while the issuer
                #    was still unratified.  Promoting it in place is unsafe,
                #    because window_date_kst has to keep the FIRST
                #    observation window for lag calculation - which leaves
                #    "settled this window then crashed" and "old completed
                #    digest reused across a holiday" indistinguishable.
                #    Ratification takes effect from the next new digest.
                _run_log(con, runlog_tag, "NOOP",
                         "digest=%s no-op observation_only=%s completed=%s"
                         % (digest[:12], observation_only, dup_completed))
                print("[noop] %s digest unchanged - no marker, no first_seen"
                      % ticker)
            elif dup_latest >= expected and not _done_today(window, done_marker):
                _write_done(window, expected, dup_latest, digest, done_marker)
                if dup_window == window:
                    _log_first_seen(window, dup_latest, first_seen_log)
                _run_log(con, runlog_tag, "NOOP",
                         f"digest={digest[:12]} target 도달 marker (dup_window={dup_window})")
                print(f"[noop] 동일 digest — target({expected}) 도달, marker 작성 (window={window})")
            else:
                _run_log(con, runlog_tag, "NOOP", f"digest={digest[:12]} target 미달")
                print(f"[noop] 동일 digest, target({expected}) 미달(latest={dup_latest}) — 폴링 계속")
            _update_health(con, source_id, "noop_same_digest", ok=True)
            return 0

        # digest 다름 → 전체 비교: 신규행 추가 + 과거 revision append (latest 동일해도 수행)
        added, revised = store_new_and_revisions(
            con, asset, ticker, source_id, digest,
            result["persistence_mode"], result["creation_series"])
        latest = result["latest_as_of"]
        # B-16: 완료 = 오늘 목표 도달(latest >= expected). target 미달 파일은 저장하되 폴링 계속.
        target_reached = (not observation_only) and latest >= expected
        con.execute("INSERT INTO etf_collect_log (source_id, input_digest, processed_at, rows_added, "
                    "revisions_added, window_date_kst, latest_as_of, completed) VALUES (?,?,?,?,?,?,?,?)",
                    (source_id, digest, _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), added, revised,
                     window, latest, 1 if target_reached else 0))
        con.commit()
        _update_health(con, source_id, "ok", ok=True)
        _run_log(con, runlog_tag, "OK", f"added={added} revised={revised} target_reached={target_reached}")

        if target_reached:
            _write_done(window, expected, latest, digest, done_marker)
            _log_first_seen(window, latest, first_seen_log)
        print(f"[ok] {ticker} as_of={latest} 신규 {added}행 revision {revised}건 "
              f"digest={digest[:12]}… target({expected}) 도달={target_reached} "
              f"(원문 비영속: {result['persistence_mode']})")
        return 0
    finally:
        con.close()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="BTC")
    ap.add_argument("--ticker", default="IBIT")
    args = ap.parse_args()
    raise SystemExit(main(args.asset, args.ticker))
