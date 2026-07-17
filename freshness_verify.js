// FRESHNESS-P0 — daily freshness judgment (weekday_approx_v1)
// Ratified contract 2026-07-17. Standalone verification BEFORE server patch.
// No external deps. America/New_York via Intl.DateTimeFormat.

"use strict";

// ---- America/New_York helpers ----
// Returns {y,m,d,H,M,S, wday} for an epoch-seconds value, in ET.
function etParts(epochSec) {
  var dt = new Date(epochSec * 1000);
  var fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, weekday: "short"
  });
  var parts = {};
  fmt.formatToParts(dt).forEach(function (p) { parts[p.type] = p.value; });
  var wdayMap = { Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6 };
  var H = parseInt(parts.hour, 10);
  if (H === 24) H = 0; // hour12:false can yield 24 at midnight in some envs
  return {
    y: parseInt(parts.year, 10),
    m: parseInt(parts.month, 10),
    d: parseInt(parts.day, 10),
    H: H,
    M: parseInt(parts.minute, 10),
    S: parseInt(parts.second, 10),
    wday: wdayMap[parts.weekday]
  };
}

function etDateStr(p) {
  function z(n){ return (n<10?"0":"")+n; }
  return p.y + "-" + z(p.m) + "-" + z(p.d);
}

// expected latest session date (YYYY-MM-DD) by weekday_approx_v1, given "now" epoch sec.
function expectedSession(nowSec) {
  var p = etParts(nowSec);
  // build a Date for ET calendar date; step back over weekends / pre-close
  // We work on the ET calendar date components.
  function mkStr(y,m,d){ function z(n){return (n<10?"0":"")+n;} return y+"-"+z(m)+"-"+z(d); }
  // helper: given y,m,d compute weekday via UTC noon of that date (date-only, tz-agnostic for weekday)
  function wdayOf(y,m,d){ return new Date(Date.UTC(y,m-1,d,12,0,0)).getUTCDay(); }
  function prevDay(y,m,d){ var t=new Date(Date.UTC(y,m-1,d,12,0,0)); t.setUTCDate(t.getUTCDate()-1); return {y:t.getUTCFullYear(),m:t.getUTCMonth()+1,d:t.getUTCDate()}; }

  var y=p.y, m=p.m, d=p.d;
  var wd = p.wday; // 0=Sun..6=Sat
  var afterClose = (p.H > 16) || (p.H === 16 && (p.M > 0 || p.S >= 0)); // >=16:00:00 ET

  if (wd === 6) { // Sat -> prev Fri
    var a=prevDay(y,m,d); return mkStr(a.y,a.m,a.d); // Fri
  }
  if (wd === 0) { // Sun -> Fri (two days back)
    var b=prevDay(y,m,d); var c=prevDay(b.y,b.m,b.d); return mkStr(c.y,c.m,c.d);
  }
  // Mon-Fri
  if (afterClose) {
    return mkStr(y,m,d); // today's session
  }
  // before close -> previous weekday
  var pv = prevDay(y,m,d);
  var pwd = wdayOf(pv.y,pv.m,pv.d);
  if (pwd === 0) { // prev is Sunday -> back to Fri
    var e=prevDay(pv.y,pv.m,pv.d); var f=prevDay(e.y,e.m,e.d); return mkStr(f.y,f.m,f.d);
  }
  if (pwd === 6) { // prev is Saturday -> back to Fri
    var g=prevDay(pv.y,pv.m,pv.d); return mkStr(g.y,g.m,g.d);
  }
  return mkStr(pv.y,pv.m,pv.d);
}

var MAX_INGEST_LAG = 3600;      // sec
var MAX_ABSOLUTE_AGE = 96*3600; // sec

// Main judgment. rec = daily file object. nowSec = current epoch.
// returns { state: fresh|stale|unavailable, reason }
function judgeDaily(rec, nowSec) {
  if (!rec || typeof rec !== "object") return { state:"unavailable", reason:"no_record" };
  if (rec.kind !== "daily") return { state:"unavailable", reason:"kind_mismatch" };
  var asOf = rec.as_of;
  if (typeof asOf !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(asOf))
    return { state:"unavailable", reason:"missing_as_of" };
  var barTs = Number(rec.bar_ts);
  if (!Number.isFinite(barTs) || barTs <= 0) return { state:"unavailable", reason:"bar_not_close" };
  var updated = Date.parse(rec.updated);
  if (!Number.isFinite(updated)) return { state:"unavailable", reason:"updated_before_bar" };
  var updatedSec = Math.floor(updated/1000);

  // --- close-bar provenance: bar must be 16:00:00 ET, date == as_of ---
  var bp = etParts(barTs);
  if (etDateStr(bp) !== asOf) return { state:"unavailable", reason:"bar_date_mismatch" };
  if (!(bp.H === 16 && bp.M === 0 && bp.S <= 60))
    return { state:"unavailable", reason:"bar_not_close" }; // covers 13:00 early close, intraday bars

  // --- updated ordering ---
  if (updatedSec < barTs) return { state:"unavailable", reason:"updated_before_bar" };
  if (updatedSec - barTs > MAX_INGEST_LAG) return { state:"unavailable", reason:"ingest_lag_exceeded" };
  if (updatedSec > nowSec + 60) return { state:"unavailable", reason:"future_session" };

  // --- expected weekday session ---
  var exp = expectedSession(nowSec);
  if (asOf > exp) return { state:"unavailable", reason:"future_session" };
  if (asOf < exp) return { state:"stale", reason:"as_of_old" };

  // --- absolute age backstop ---
  var ageSec = nowSec - barTs;
  if (ageSec > MAX_ABSOLUTE_AGE) return { state:"stale", reason:"absolute_age_exceeded" };

  return { state:"fresh", reason:"ok" };
}

// ================= TESTS =================
function ep(iso){ return Math.floor(Date.parse(iso)/1000); }
var fails = 0, passes = 0;
function check(name, got, want) {
  var ok = got === want;
  if (ok) passes++; else fails++;
  console.log((ok?"PASS":"FAIL")+" | "+name+" | got="+got+(ok?"":" want="+want));
}

// 1. July (EDT) 20:00 UTC = 16:00 ET -> fresh. now = Fri 2026-07-17 01:58Z (Thu after close ET)
// bar 2026-07-16 20:00Z. now must make expected session = 2026-07-16.
// Thu 2026-07-16 20:00Z = Thu 16:00 ET (after close) -> expected = 2026-07-16.
var recJul = { kind:"daily", as_of:"2026-07-16", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T20:00:22Z" };
check("1 EDT close fresh", judgeDaily(recJul, ep("2026-07-16T20:05:00Z")).state, "fresh");

// 2. December (EST) 21:00 UTC = 16:00 ET -> fresh. Thu 2026-12-17.
var recDec = { kind:"daily", as_of:"2026-12-17", bar_ts:ep("2026-12-17T21:00:00Z"), updated:"2026-12-17T21:00:20Z" };
check("2 EST close fresh", judgeDaily(recDec, ep("2026-12-17T21:05:00Z")).state, "fresh");

// 3. December 20:00 UTC = 15:00 ET -> not close bar -> unavailable
var recDecEarly = { kind:"daily", as_of:"2026-12-17", bar_ts:ep("2026-12-17T20:00:00Z"), updated:"2026-12-17T20:00:20Z" };
check("3 EST 15:00 not-close unavailable", judgeDaily(recDecEarly, ep("2026-12-17T21:05:00Z")).state, "unavailable");

// 4. kind=intraday -> unavailable
var recIntra = { kind:"intraday", as_of:"2026-07-16", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T20:00:22Z" };
check("4 intraday kind unavailable", judgeDaily(recIntra, ep("2026-07-16T20:05:00Z")).state, "unavailable");

// 5. as_of missing -> unavailable
var recNoAsof = { kind:"daily", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T20:00:22Z" };
check("5 no as_of unavailable", judgeDaily(recNoAsof, ep("2026-07-16T20:05:00Z")).state, "unavailable");

// 6. as_of != bar_ts ET date -> unavailable
var recMismatch = { kind:"daily", as_of:"2026-07-15", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T20:00:22Z" };
check("6 as_of/bar date mismatch unavailable", judgeDaily(recMismatch, ep("2026-07-16T20:05:00Z")).state, "unavailable");

// 7. updated before bar_ts -> unavailable
var recUpdEarly = { kind:"daily", as_of:"2026-07-16", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T19:59:00Z" };
check("7 updated<bar unavailable", judgeDaily(recUpdEarly, ep("2026-07-16T20:05:00Z")).state, "unavailable");

// 8. updated 22s after close -> PASS (fresh) [same as test 1 essentially]
check("8 updated +22s fresh", judgeDaily(recJul, ep("2026-07-16T20:05:00Z")).state, "fresh");

// 9. Saturday, Friday as_of -> fresh. now = Sat 2026-07-18 12:00Z. Fri session = 2026-07-17.
var recFri = { kind:"daily", as_of:"2026-07-17", bar_ts:ep("2026-07-17T20:00:00Z"), updated:"2026-07-17T20:00:20Z" };
check("9 Sat with Fri as_of fresh", judgeDaily(recFri, ep("2026-07-18T12:00:00Z")).state, "fresh");

// 10. weekday after close, previous session as_of -> stale.
// now = Fri 2026-07-17 20:05Z (after close) -> expected = 2026-07-17. rec as_of 2026-07-16 -> stale.
var recPrev = { kind:"daily", as_of:"2026-07-16", bar_ts:ep("2026-07-16T20:00:00Z"), updated:"2026-07-16T20:00:22Z" };
check("10 prev session stale", judgeDaily(recPrev, ep("2026-07-17T20:05:00Z")).state, "stale");

// 11. US holiday, prev session as_of -> stale allowed.
// MLK Mon 2026-01-19 is EST (close 16:00 ET = 21:00 UTC). now must be AFTER close ET.
// now = Mon 2026-01-19 21:05Z = 16:05 ET (after close) -> expected weekday session = 2026-01-19.
// rec as_of = Fri 2026-01-16 (holiday means no new data) -> older than expected -> stale (allowed).
var recHol = { kind:"daily", as_of:"2026-01-16", bar_ts:ep("2026-01-16T21:00:00Z"), updated:"2026-01-16T21:00:20Z" };
check("11 holiday prev session stale-allowed", judgeDaily(recHol, ep("2026-01-19T21:05:00Z")).state, "stale");

// 12. 13:00 ET early close bar -> unavailable
// EDT: 13:00 ET = 17:00 UTC.
var recEarlyClose = { kind:"daily", as_of:"2026-07-16", bar_ts:ep("2026-07-16T17:00:00Z"), updated:"2026-07-16T17:00:20Z" };
check("12 early close 13ET unavailable", judgeDaily(recEarlyClose, ep("2026-07-16T20:05:00Z")).state, "unavailable");

// 13. age small but as_of old -> stale. Construct: valid close bar for old session, now much later same-week.
// bar Mon 2026-07-13 20:00Z, now Wed 2026-07-15 20:05Z after close -> expected 2026-07-15 -> as_of older -> stale
var recOld = { kind:"daily", as_of:"2026-07-13", bar_ts:ep("2026-07-13T20:00:00Z"), updated:"2026-07-13T20:00:22Z" };
check("13 as_of old stale", judgeDaily(recOld, ep("2026-07-15T20:05:00Z")).state, "stale");

// 14. as_of latest but provenance mismatch (bar not 16:00 ET) -> unavailable
var recProv = { kind:"daily", as_of:"2026-07-16", bar_ts:ep("2026-07-16T18:30:00Z"), updated:"2026-07-16T18:30:20Z" };
check("14 latest as_of but bad provenance unavailable", judgeDaily(recProv, ep("2026-07-16T20:05:00Z")).state, "unavailable");

console.log("\n==== "+passes+" passed / "+fails+" failed ====");
process.exit(fails===0 ? 0 : 1);
