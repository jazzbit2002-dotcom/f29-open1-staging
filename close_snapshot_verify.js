// MARKET-CLOSE-SNAPSHOT — judgment + tests (2026-07-18)
// Reuses the same ET helpers as FRESHNESS-P0 (replicated here ONLY for standalone testing;
// the server patch reuses the existing in-scope helpers and does NOT duplicate them).
"use strict";

function _etParts(epochSec){
  var dt = new Date(epochSec*1000);
  var fmt = new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",
    year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false,weekday:"short"});
  var pp={}; fmt.formatToParts(dt).forEach(function(x){pp[x.type]=x.value;});
  var wm={Sun:0,Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6}; var H=parseInt(pp.hour,10); if(H===24)H=0;
  return {y:parseInt(pp.year,10),m:parseInt(pp.month,10),d:parseInt(pp.day,10),H:H,M:parseInt(pp.minute,10),S:parseInt(pp.second,10),wday:wm[pp.weekday]};
}
function _etDate(p){function z(n){return (n<10?"0":"")+n;} return p.y+"-"+z(p.m)+"-"+z(p.d);}
function _expSession(nowSec){
  var p=_etParts(nowSec);
  function mk(y,m,d){function z(n){return (n<10?"0":"")+n;} return y+"-"+z(m)+"-"+z(d);}
  function wd(y,m,d){return new Date(Date.UTC(y,m-1,d,12,0,0)).getUTCDay();}
  function pd(y,m,d){var t=new Date(Date.UTC(y,m-1,d,12,0,0));t.setUTCDate(t.getUTCDate()-1);return {y:t.getUTCFullYear(),m:t.getUTCMonth()+1,d:t.getUTCDate()};}
  var y=p.y,m=p.m,d=p.d,w=p.wday,ac=(p.H>16)||(p.H===16&&(p.M>0||p.S>=0));
  if(w===6){var a=pd(y,m,d);return mk(a.y,a.m,a.d);}
  if(w===0){var b=pd(y,m,d);var c=pd(b.y,b.m,b.d);return mk(c.y,c.m,c.d);}
  if(ac)return mk(y,m,d);
  var pv=pd(y,m,d),pw=wd(pv.y,pv.m,pv.d);
  if(pw===0){var e=pd(pv.y,pv.m,pv.d);var f=pd(e.y,e.m,e.d);return mk(f.y,f.m,f.d);}
  if(pw===6){var g=pd(pv.y,pv.m,pv.d);return mk(g.y,g.m,g.d);}
  return mk(pv.y,pv.m,pv.d);
}
var MAX_INGEST_LAG=3600, MAX_ABSOLUTE_AGE=96*3600;
var CLOSE_REQUIRED=["spy","qqq","iwm","rsp","vix","tnx"];

// rec = raw intraday file object. Returns close-snapshot view or null-ish judgment.
function judgeCloseSnapshot(rec, nowMs){
  var nowSec=Math.floor(nowMs/1000);
  function out(state,reason,asOf,ageSec){
    return {kind:"market_close_snapshot", reference_rule:"us_regular_close_16_et",
            updated: rec && rec.updated, bar_ts: rec && rec.bar_ts, as_of: asOf||null,
            stale: state!=="fresh", freshness:{state:state,reason:reason},
            age_min: Number.isFinite(ageSec)?Math.floor(ageSec/60):null,
            data: (state==="fresh" && rec && rec.data) ? rec.data : {}};
  }
  if(!rec||typeof rec!=="object") return out("unavailable","kind_mismatch",null,null);
  if(rec.kind!=="intraday") return out("unavailable","kind_mismatch",null,null);
  var barTs=Number(rec.bar_ts);
  if(!Number.isFinite(barTs)||barTs<=0) return out("unavailable","bar_not_close",null,null);
  var upd=Date.parse(rec.updated);
  if(!Number.isFinite(upd)) return out("unavailable","updated_before_bar",null,null);
  var updSec=Math.floor(upd/1000);
  var bp=_etParts(barTs);
  var asOf=_etDate(bp);                    // as_of derived from bar_ts ET date
  var ageSec=nowSec-barTs;
  // close-bar provenance: must be 16:00 ET
  if(!(bp.H===16&&bp.M===0&&bp.S<=60)){
    if(bp.H===13&&bp.M===0) return out("unavailable","early_close_not_supported",asOf,ageSec);
    return out("unavailable","bar_not_close",asOf,ageSec);
  }
  if(updSec<barTs) return out("unavailable","updated_before_bar",asOf,ageSec);
  if(updSec-barTs>MAX_INGEST_LAG) return out("unavailable","ingest_lag_exceeded",asOf,ageSec);
  if(updSec>nowSec+60) return out("unavailable","future_session",asOf,ageSec);
  var data=rec.data||{};
  for(var i=0;i<CLOSE_REQUIRED.length;i++){
    if(!Number.isFinite(Number(data[CLOSE_REQUIRED[i]]))) return out("unavailable","required_field_missing",asOf,ageSec);
  }
  var exp=_expSession(nowSec);
  if(asOf>exp) return out("unavailable","future_session",asOf,ageSec);
  if(asOf<exp) return out("stale","as_of_old",asOf,ageSec);
  if(ageSec>MAX_ABSOLUTE_AGE) return out("stale","absolute_age_exceeded",asOf,ageSec);
  return out("fresh","ok",asOf,ageSec);
}

// ================= TESTS =================
function ep(iso){ return Date.parse(iso); }
function sec(iso){ return Math.floor(Date.parse(iso)/1000); }
var full={spy:743.23,qqq:696.42,iwm:294.125,rsp:213.47,vix:18.46,tnx:4.542,move:68.16,dxy:100.726,cl1:81.42};
var fails=0,passes=0;
function check(n,got,want){var ok=got===want;if(ok)passes++;else fails++;
  console.log((ok?"PASS":"FAIL")+" | "+n+" | got="+got+(ok?"":" want="+want));}

// 1. latest expected session, 16:00 ET -> fresh
// Fri 2026-07-17 20:00Z = 16:00 ET. now = Fri 20:05Z (after close) -> expected 2026-07-17
var r1=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T20:00:26Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("1 close 16:00ET fresh", r1.freshness.state, "fresh");
check("1 as_of derived", r1.as_of, "2026-07-17");
check("1 data exposed", Object.keys(r1.data).length>0, true);

// 2. 15:45 ET (=19:45Z EDT) -> bar_not_close
var r2=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T19:45:00Z"),updated:"2026-07-17T19:45:20Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("2 15:45ET unavailable", r2.freshness.state, "unavailable");
check("2 reason", r2.freshness.reason, "bar_not_close");

// 3. 16:15 ET (=20:15Z) -> bar_not_close
var r3=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:15:00Z"),updated:"2026-07-17T20:15:20Z",data:full}, ep("2026-07-17T20:30:00Z"));
check("3 16:15ET unavailable", r3.freshness.state, "unavailable");
check("3 reason", r3.freshness.reason, "bar_not_close");

// 4. past as_of -> stale/as_of_old  (Wed close, now Fri after close)
var r4=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-15T20:00:00Z"),updated:"2026-07-15T20:00:20Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("4 past session stale", r4.freshness.state, "stale");
check("4 reason", r4.freshness.reason, "as_of_old");
check("4 data withheld", Object.keys(r4.data).length, 0);

// 5. future as_of -> unavailable/future_session (bar Fri close, now Thu before close)
var r5=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T20:00:20Z"
  ,data:full}, ep("2026-07-16T18:00:00Z"));
check("5 future session unavailable", r5.freshness.state, "unavailable");
check("5 reason", r5.freshness.reason, "future_session");

// 6. updated < bar_ts -> unavailable
var r6=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T19:00:00Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("6 updated<bar unavailable", r6.freshness.state, "unavailable");
check("6 reason", r6.freshness.reason, "updated_before_bar");

// 7. ingest lag > 3600 -> unavailable
var r7=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T21:30:00Z",data:full}, ep("2026-07-17T22:00:00Z"));
check("7 ingest lag unavailable", r7.freshness.state, "unavailable");
check("7 reason", r7.freshness.reason, "ingest_lag_exceeded");

// 8. required field missing -> unavailable
var partial={spy:743.23,qqq:696.42,vix:18.46};  // iwm/rsp/tnx missing
var r8=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T20:00:26Z",data:partial}, ep("2026-07-17T20:05:00Z"));
check("8 missing field unavailable", r8.freshness.state, "unavailable");
check("8 reason", r8.freshness.reason, "required_field_missing");

// 9. 13:00 ET early close (=17:00Z EDT) -> early_close_not_supported
var r9=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T17:00:00Z"),updated:"2026-07-17T17:00:20Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("9 early close unavailable", r9.freshness.state, "unavailable");
check("9 reason", r9.freshness.reason, "early_close_not_supported");

// EST season check: Dec close 16:00 ET = 21:00Z
var rEst=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-12-17T21:00:00Z"),updated:"2026-12-17T21:00:20Z",data:full}, ep("2026-12-17T21:05:00Z"));
check("EST 16:00ET fresh", rEst.freshness.state, "fresh");
var rEstBad=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-12-17T20:00:00Z"),updated:"2026-12-17T20:00:20Z",data:full}, ep("2026-12-17T21:05:00Z"));
check("EST 15:00ET unavailable", rEstBad.freshness.state, "unavailable");

// Saturday: Friday close still fresh (next-day validity)
var rSat=judgeCloseSnapshot({kind:"intraday",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T20:00:26Z",data:full}, ep("2026-07-18T07:00:00Z"));
check("SAT fri-close fresh", rSat.freshness.state, "fresh");
check("SAT age_min large but fresh", rSat.age_min>600, true);

// kind mismatch
var rK=judgeCloseSnapshot({kind:"daily",bar_ts:sec("2026-07-17T20:00:00Z"),updated:"2026-07-17T20:00:26Z",data:full}, ep("2026-07-17T20:05:00Z"));
check("kind mismatch unavailable", rK.freshness.state, "unavailable");

console.log("\n==== CLOSE-SNAPSHOT: "+passes+" passed / "+fails+" failed ====");
process.exit(fails===0?0:1);
