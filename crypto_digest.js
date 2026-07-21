#!/usr/bin/env node
/**
 * F29 crypto_daily_context — 계산 모듈 v1 (2026-07-21 설계 차수)
 *
 * 스펙: CRYPTO_CONTEXT_SPEC_v1.md
 * 원천: /root/f29/history.json, /root/f29/state.json  ← 읽기 전용. 절대 쓰지 않는다.
 * 소비: mf_server.js  GET /api/crypto-daily-context
 *
 * 배포 전 검증 (CLI):
 *   node crypto_digest.js --date 2026-07-18   → dwell R5≈84 R2≈12 R4≈3 R3≈1, transitions 11
 *   node crypto_digest.js --date 2026-07-13   → data_state.state = "insufficient"
 *
 * 계약 (스펙 §5):
 *   C-1 체류 비율은 시간가중으로만. 개수비율 금지
 *   C-2 일자 경계 앵커 필수 (D 00:00 / D+1 00:00)
 *   C-3 공백은 직전 등급 유지. 등급이 바뀐 공백은 ambiguous_gap_min 에 합산 노출
 *   C-4 dwell_pct 는 정수
 *   C-5 커버리지 게이트 ok / sparse / insufficient
 *   §6  gates·risk·market·s2pend·release·rebound·Disp 전면 제외. prem/cvd 는 부호만
 */

"use strict";

const fs = require("fs");

const HISTORY_FILE = process.env.F29_CRYPTO_HISTORY || "/root/f29/history.json";
const STATE_FILE = process.env.F29_CRYPTO_STATE || "/root/f29/state.json";

const EXPECTED_SAMPLES = 96;        // 15분 × 24h
const GAP_THRESHOLD_MIN = 45;       // 조사 기준 (정상 주기 15분의 3배)
const COVERAGE_OK = 80;
const COVERAGE_SPARSE = 60;
const MAX_TRANSITIONS_DETAIL = 6;

// ---------------------------------------------------------------- helpers

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function ms(iso) {
  return Date.parse(iso);
}

/** UTC 일자 문자열 → [start, end) epoch ms */
function dayBounds(dateStr) {
  const start = Date.parse(dateStr + "T00:00:00.000Z");
  if (Number.isNaN(start)) throw new Error("bad date: " + dateStr);
  return [start, start + 86400000];
}

function sign(v) {
  if (typeof v !== "number" || Number.isNaN(v)) return null;
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "flat";
}

function pickNum(o, k) {
  const v = o && o[k];
  return typeof v === "number" && !Number.isNaN(v) ? v : null;
}

/**
 * 정수 반올림 후 합이 100이 되도록 보정 (최대 잔차를 최다 체류 등급에 귀속).
 * C-4: 소수점은 애매 공백 왜곡(최대 3.75%p) 대비 무의미하다.
 */
function toIntPct(dwellMs) {
  const total = Object.values(dwellMs).reduce((a, b) => a + b, 0);
  if (total <= 0) return {};
  const entries = Object.entries(dwellMs).sort((a, b) => b[1] - a[1]);
  const out = {};
  let acc = 0;
  entries.forEach(([code, v], i) => {
    if (i === entries.length - 1) {
      out[code] = 100 - acc;
    } else {
      const p = Math.round((v / total) * 100);
      out[code] = p;
      acc += p;
    }
  });
  // 잔차가 음수가 되는 극단(0% 항목 다수)에서는 최다 항목에 흡수
  for (const k of Object.keys(out)) {
    if (out[k] < 0) {
      out[entries[0][0]] += out[k];
      out[k] = 0;
    }
  }
  return out;
}

// ---------------------------------------------------------------- core

/**
 * 하루치 프로파일. 시간가중 체류·전환·공백·범위.
 * rows = 전체 history (ts 오름차순 정렬 가정)
 */
function buildProfile(rows, dateStr) {
  const [start, end] = dayBounds(dateStr);

  const inDay = rows.filter((r) => {
    const t = ms(r.ts);
    return t >= start && t < end;
  });

  // C-2 경계 앵커: D 00:00 의 등급 = D 이전 마지막 샘플의 등급
  let priorCode = null;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (ms(rows[i].ts) < start) { priorCode = rows[i].code; break; }
  }

  if (inDay.length === 0) {
    return {
      empty: true,
      samples: 0,
      profile: null,
      priorCode,
    };
  }

  const seq = [];
  if (priorCode) seq.push({ t: start, code: priorCode, anchor: true });
  for (const r of inDay) seq.push({ t: ms(r.ts), code: r.code });
  seq.push({ t: end, code: seq[seq.length - 1].code, anchor: true });

  const dwellMs = {};
  let gapsOver = 0;
  let ambiguousMs = 0;
  let transitions = 0;

  for (let i = 0; i < seq.length - 1; i++) {
    const a = seq[i], b = seq[i + 1];
    const dur = b.t - a.t;
    if (dur <= 0) continue;

    // C-3 공백은 직전 등급 유지
    dwellMs[a.code] = (dwellMs[a.code] || 0) + dur;

    if (dur > GAP_THRESHOLD_MIN * 60000) {
      gapsOver++;
      if (a.code !== b.code) ambiguousMs += dur;   // 공백 중 전환 = 시점 불명
    }
    if (a.code !== b.code) transitions++;
  }

  const codes = Object.keys(dwellMs);
  const dominant = codes.sort((x, y) => dwellMs[y] - dwellMs[x])[0] || null;

  const btcVals = inDay.map((r) => pickNum(r, "btc")).filter((v) => v !== null);
  const ethVals = inDay.map((r) => pickNum(r, "eth")).filter((v) => v !== null);
  const last = inDay[inDay.length - 1];

  const coverage = Math.round((inDay.length / EXPECTED_SAMPLES) * 100);

  return {
    empty: false,
    samples: inDay.length,
    coverage,
    gapsOver,
    ambiguousMin: Math.round(ambiguousMs / 60000),
    last,
    profile: {
      dwell_pct: toIntPct(dwellMs),
      dominant,
      open_code: seq[0].code,
      close_code: last.code,
      transitions,
      distinct_codes: Object.keys(dwellMs).sort(),
    },
    range: {
      btc: btcVals.length
        ? { low: Math.min(...btcVals), high: Math.max(...btcVals), close: pickNum(last, "btc") }
        : null,
      eth: ethVals.length
        ? { low: Math.min(...ethVals), high: Math.max(...ethVals), close: pickNum(last, "eth") }
        : null,
    },
    transitions_detail: (() => {
      const out = [];
      for (let i = 0; i < seq.length - 1; i++) {
        const a = seq[i], b = seq[i + 1];
        if (a.code !== b.code && !b.anchor) {
          out.push({ ts: new Date(b.t).toISOString(), from: a.code, to: b.code });
        }
      }
      return out.slice(0, MAX_TRANSITIONS_DETAIL);
    })(),
  };
}

/** §6 컴플라이언스 필터. 화이트리스트 방식 — 신규 필드가 자동 노출되지 않는다. */
function buildIndicators(last, prevLast) {
  if (!last) return null;
  return {
    btc_pos: pickNum(last, "btcPos"),
    eth_pos: pickNum(last, "ethPos"),
    btc_bucket: last.btcBucket || null,
    eth_bucket: last.ethBucket || null,
    flow_btc: last.flowBtc || null,
    flow_eth: last.flowEth || null,
    atr_btc: pickNum(last, "atrBtc"),
    atr_eth: pickNum(last, "atrEth"),
    atr_btc_prev: prevLast ? pickNum(prevLast, "atrBtc") : null,
    atr_eth_prev: prevLast ? pickNum(prevLast, "atrEth") : null,
    prem_btc_sign: sign(pickNum(last, "premBtc")),
    prem_eth_sign: sign(pickNum(last, "premEth")),
    cvd_btc_sign: sign(pickNum(last, "cvdBtc")),
    cvd_eth_sign: sign(pickNum(last, "cvdEth")),
  };
}

function coverageState(pct) {
  if (pct >= COVERAGE_OK) return "ok";
  if (pct >= COVERAGE_SPARSE) return "sparse";
  return "insufficient";
}

/** 대상 UTC 일자의 컨텍스트를 만든다. dateStr 생략 시 = 어제(UTC). */
function buildCryptoContext(dateStr) {
  const rows = readJson(HISTORY_FILE)
    .filter((r) => r && r.ts && r.code)
    .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));

  if (!dateStr) {
    dateStr = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  }
  const prevDate = new Date(dayBounds(dateStr)[0] - 86400000)
    .toISOString().slice(0, 10);

  const cur = buildProfile(rows, dateStr);
  const prev = buildProfile(rows, prevDate);

  let state = null;
  try { state = readJson(STATE_FILE); } catch (e) { state = null; }

  let current = null;
  if (state && state.code) {
    const since = state.codeSince ? ms(state.codeSince) : null;
    current = {
      code: state.code,
      code_since: state.codeSince || null,
      duration_min: since ? Math.round((Date.now() - since) / 60000) : null,
      as_of: state.updated || null,
    };
  }

  const coverage = cur.empty ? 0 : cur.coverage;

  return {
    as_of: dateStr,
    generated: new Date().toISOString(),
    profile: cur.empty ? null : cur.profile,
    prev_profile: prev.empty ? null : {
      dwell_pct: prev.profile.dwell_pct,
      dominant: prev.profile.dominant,
      transitions: prev.profile.transitions,
    },
    range: cur.empty ? null : {
      btc: cur.range.btc,
      eth: cur.range.eth,
      prev_close: prev.empty ? null : {
        btc: prev.range.btc ? prev.range.btc.close : null,
        eth: prev.range.eth ? prev.range.eth.close : null,
      },
    },
    transitions_detail: cur.empty ? [] : cur.transitions_detail,
    indicators: cur.empty ? null
      : buildIndicators(cur.last, prev.empty ? null : prev.last),
    current,
    data_state: {
      samples: cur.empty ? 0 : cur.samples,
      expected: EXPECTED_SAMPLES,
      coverage_pct: coverage,
      gaps_over_45min: cur.empty ? 0 : cur.gapsOver,
      ambiguous_gap_min: cur.empty ? 0 : cur.ambiguousMin,
      state: coverageState(coverage),
    },
  };
}

module.exports = { buildCryptoContext, buildProfile, toIntPct };

// ---------------------------------------------------------------- CLI

if (require.main === module) {
  const i = process.argv.indexOf("--date");
  const d = i >= 0 ? process.argv[i + 1] : null;
  try {
    console.log(JSON.stringify(buildCryptoContext(d), null, 1));
  } catch (e) {
    console.error("ERROR:", e.message);
    process.exit(1);
  }
}
