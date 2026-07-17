// FRESHNESS-P0 server-ready module + dual-contract wrapper + integration tests
// Ratified contract 2026-07-17. Verify BEFORE server patch.

"use strict";

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
  var H = parseInt(parts.hour, 10); if (H === 24) H = 0;
  return { y:parseInt(parts.year,10), m:parseInt(parts.month,10), d:parseInt(parts.day,10),
           H:H, M:parseInt(parts.minute,10), S:parseInt(parts.second,10), wday:wdayMap[parts.weekday] };
}
function etDateStr(p){ function z(n){return (n<10?"0":"")+n;} return p.y+"-"+z(p.m)+"-"+z(p.d); }

function expectedWeekdaySession(nowSec) {
  var p = etParts(nowSec);
  function mkStr(y,m,d){ function z(n){return (n<10?"0":"")+n;} return y+"-"+z(m)+"-"+z(d); }
  function wdayOf(y,m,d){ return new Date(Date.UTC(y,m-1,d,12,0,0)).getUTCDay(); }
  function prevDay(y,m,d){ var t=new Date(Date.UTC(y,m-1,d,12,0,0)); t.setUTCDate(t.getUTCDate()-1);
    return {y:t.getUTCFullYear(),m:t.getUTCMonth()+1,d:t.getUTCDate()}; }
  var y=p.y,m=p.m,d=p.d,wd=p.wday;
  var afterClose = (p.H > 16) || (p.H === 16 && (p.M > 0 || p.S >= 0));
  if (wd === 6){ var a=prevDay(y,m,d); return mkStr(a.y,a.m,a.d); }
  if (wd === 0){ var b=prevDay(y,m,d); var c=prevDay(b.y,b.m,b.d); return mkStr(c.y,c.m,c.d); }
  if (afterClose) return mkStr(y,m,d);
  var pv=prevDay(y,m,d), pwd=wdayOf(pv.y,pv.m,pv.d);
  if (pwd===0){ var e=prevDay(pv.y,pv.m,pv.d); var f=prevDay(e.y,e.m,e.d); return mkStr(f.y,f.m,f.d); }
  if (pwd===6){ var g=prevDay(pv.y,pv.m,pv.d); return mkStr(g.y,g.m,g.d); }
  return mkStr(pv.y,pv.m,pv.d);
}

var MAX_INGEST_LAG = 3600;
var MAX_ABSOLUTE_AGE = 96*3600;

function judgeDaily(rec, nowMs) {
  var nowSec = Math.floor(nowMs/1000);
  if (!rec || typeof rec !== "object") return { state:"unavailable", reason:"kind_mismatch" };
  if (rec.kind !== "daily") return { state:"unavailable", reason:"kind_mismatch" };
  var asOf = rec.as_of;
  if (typeof asOf !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(asOf))
    return { state:"unavailable", reason:"missing_as_of" };
  var barTs = Number(rec.bar_ts);
  if (!Number.isFinite(barTs) || barTs <= 0) return { state:"unavailable", reason:"bar_not_close" };
  var updated = Date.parse(rec.updated);
  if (!Number.isFinite(updated)) return { state:"unavailable", reason:"updated_before_bar" };
  var updatedSec = Math.floor(updated/1000);

  var bp = etParts(barTs);
  if (etDateStr(bp) !== asOf) return { state:"unavailable", reason:"bar_date_mismatch" };
  // close-bar must be 16:00 ET. 13:00 ET early close -> distinct reason.
  if (!(bp.H === 16 && bp.M === 0 && bp.S <= 60)) {
    if (bp.H === 13 && bp.M === 0) return { state:"unavailable", reason:"early_close_not_supported" };
    return { state:"unavailable", reason:"bar_not_close" };
  }
  if (updatedSec < barTs) return { state:"unavailable", reason:"updated_before_bar" };
  if (updatedSec - barTs > MAX_INGEST_LAG) return { state:"unavailable", reason:"ingest_lag_exceeded" };
  if (updatedSec > nowSec + 60) return { state:"unavailable", reason:"future_session" };

  var exp = expectedWeekdaySession(nowSec);
  if (asOf > exp) return { state:"unavailable", reason:"future_session" };
  if (asOf < exp) return { state:"stale", reason:"as_of_old" };

  if (nowSec - barTs > MAX_ABSOLUTE_AGE) return { state:"stale", reason:"absolute_age_exceeded" };
  return { state:"fresh", reason:"ok" };
}

// ---- dual-contract readMI wrapper (daily branch) ----
function makeDailyReturn(record, nowMs) {
  var ageSec = Math.floor(nowMs/1000) - Number(record.bar_ts||0);
  var freshness = judgeDaily(record, nowMs);
  return Object.assign({}, record, {
    ageSec: ageSec,
    stale: freshness.state !== "fresh",   // fail-closed: stale AND unavailable -> true
    freshness: freshness
  });
}
function isDailyUsable(miDaily) {
  if (!miDaily) return false;
  if (miDaily.freshness && miDaily.freshness.state) return miDaily.freshness.state === "fresh";
  return miDaily.stale === false; // legacy fallback
}

// ================= INTEGRATION TESTS =================
function ep(iso){ return Date.parse(iso); }
var fails=0,passes=0;
function check(n,got,want){ var ok=got===want; if(ok)passes++;else fails++;
  console.log((ok?"PASS":"FAIL")+" | "+n+" | got="+got+(ok?"":" want="+want)); }

var freshRec = { kind:"daily", as_of:"2026-07-16", bar_ts:Math.floor(ep("2026-07-16T20:00:00Z")/1000), updated:"2026-07-16T20:00:22Z", data:{s5th:64.61} };
var staleRec = { kind:"daily", as_of:"2026-07-13", bar_ts:Math.floor(ep("2026-07-13T20:00:00Z")/1000), updated:"2026-07-13T20:00:22Z", data:{s5th:65} };
var unavailRec = { kind:"daily", as_of:"2026-07-16", bar_ts:Math.floor(ep("2026-07-16T18:30:00Z")/1000), updated:"2026-07-16T18:30:22Z", data:{s5th:99} };

// daily fresh -> stale=false, freshness=fresh, usable
var r1 = makeDailyReturn(freshRec, ep("2026-07-16T20:05:00Z"));
check("INT daily fresh: stale=false", r1.stale, false);
check("INT daily fresh: state", r1.freshness.state, "fresh");
check("INT daily fresh: usable", isDailyUsable(r1), true);

// daily stale -> stale=true, freshness=stale, NOT usable
var r2 = makeDailyReturn(staleRec, ep("2026-07-15T20:05:00Z"));
check("INT daily stale: stale=true", r2.stale, true);
check("INT daily stale: state", r2.freshness.state, "stale");
check("INT daily stale: not usable", isDailyUsable(r2), false);

// daily unavailable -> stale=true (fail-closed), freshness=unavailable, NOT usable
var r3 = makeDailyReturn(unavailRec, ep("2026-07-16T20:05:00Z"));
check("INT daily unavail: stale=true (fail-closed)", r3.stale, true);
check("INT daily unavail: state", r3.freshness.state, "unavailable");
check("INT daily unavail: not usable", isDailyUsable(r3), false);

// legacy response: no freshness, stale=false -> fallback usable
check("INT legacy stale=false usable", isDailyUsable({ stale:false, data:{} }), true);
check("INT legacy stale=true not usable", isDailyUsable({ stale:true, data:{} }), false);

// raw record preserved (data/as_of/bar_ts/updated still present)
check("INT raw data preserved", r1.data.s5th, 64.61);
check("INT raw as_of preserved", r1.as_of, "2026-07-16");

// early close distinct reason
var ec = judgeDaily({ kind:"daily", as_of:"2026-07-16", bar_ts:Math.floor(ep("2026-07-16T17:00:00Z")/1000), updated:"2026-07-16T17:00:22Z" }, ep("2026-07-16T20:05:00Z"));
check("INT early close reason", ec.reason, "early_close_not_supported");

console.log("\n==== INTEGRATION: "+passes+" passed / "+fails+" failed ====");
process.exit(fails===0?0:1);
