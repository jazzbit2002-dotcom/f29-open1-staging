const vm = require("vm");
const fs = require("fs");
const src = fs.readFileSync("weight.js", "utf8");

let warns = [];
function makeEl(){ return { innerHTML:"", hidden:false, _aria:{}, setAttribute(k,v){this._aria[k]=v;}, getAttribute(k){return this._aria[k];}, addEventListener(){}, dataset:{} }; }
const els = {};
function mkDoc(){
  return {
    getElementById(id){ return els[id] || (els[id]=makeEl()); },
    querySelectorAll(){ const a=[]; a.forEach=Array.prototype.forEach; return a; }
  };
}
const ctx = {
  WEIGHT: null,
  console: { warn:(...a)=>warns.push(a.join(" ")), log:()=>{} },
  document: mkDoc(),
  window: {},
  Array, Object, Number, String, JSON
};
vm.createContext(ctx);
vm.runInContext(src, ctx);

let pass=0, fail=0;
function ck(name, cond){ (cond?pass++:fail++); console.log((cond?"PASS ":"FAIL ")+name); }

// ---- Case set 1: mixed counts, some 0 ----
ctx.WEIGHT = {
  counts: {up_concentration:2, down_concentration:1, attention_up:0, fade_up:0, neutral:0, fade_down:3},
  stateLists: {
    up_concentration:[{code:"A",name:"AA",market:"KR",changeRate:5,flowLabel:"상승 거래대금 집중"},{code:"B",name:"BB",market:"KR",changeRate:2,flowLabel:"상승 거래대금 집중"}],
    down_concentration:[{code:"C",name:"CC",market:"KR",changeRate:-4,flowLabel:"하락 거래대금 집중"}],
    attention_up:[], fade_up:[], neutral:[],
    fade_down:[{code:"D",name:"DD",market:"KR",changeRate:-1,flowLabel:"관심·가격 동반 위축"},{code:"E",name:"EE",market:"KR",changeRate:-2,flowLabel:"관심·가격 동반 위축"},{code:"F",name:"FF",market:"KR",changeRate:-3,flowLabel:"관심·가격 동반 위축"}]
  }
};
warns=[];
const html = ctx.renderStateControls();
const btnStates = [...html.matchAll(/data-state="([^"]+)"/g)].map(m=>m[1]);
ck("6 buttons generated", (html.match(/<button/g)||[]).length===6);
ck("STATE_META order preserved", btnStates.join(",")==="up_concentration,attention_up,fade_up,neutral,fade_down,down_concentration");
// disabled on 0-count: attention_up, fade_up, neutral
const disabledStates = [...html.matchAll(/data-state="([^"]+)"[^>]*disabled/g)].map(m=>m[1]);
ck("0-count states disabled (3)", disabledStates.sort().join(",")==="attention_up,fade_up,neutral");
ck("nonzero states NOT disabled", !/data-state="up_concentration"[^>]*disabled/.test(html));
// label: up uses backend flowLabel; attention_up(0) uses fallback
ck("backend flowLabel shown for up", html.includes("상승 거래대금 집중"));
ck("fallback label shown for 0-count attention_up", html.includes("거래대금 관심 증가"));
ck("fallback label shown for 0-count neutral", html.includes("뚜렷한 방향 없음"));
ck("counts rendered in span", html.includes("<span>2</span>") && html.includes("<span>3</span>") && html.includes("<span>0</span>"));
ck("statePanel div present", html.includes('id="statePanel" hidden'));
ck("no drift warn (labels match)", warns.length===0);

// ---- Case 2: label drift ----
warns=[];
ctx.WEIGHT.stateLists.up_concentration[0].flowLabel = "엉뚱한라벨";
const html2 = ctx.renderStateControls();
ck("drift -> backend label displayed", html2.includes("엉뚱한라벨"));
ck("drift -> console.warn fired", warns.some(w=>w.includes("state label drift")));
ck("drift -> function keeps working (6 buttons)", (html2.match(/<button/g)||[]).length===6);

// ---- Case 3: renderRank kind=state -> no card-note ----
const stateRows = ctx.WEIGHT.stateLists.fade_down;
ctx.renderRank("statePanel", stateRows, "state", {});
const panelHtml = els["statePanel"].innerHTML;
ck("kind=state -> NO card-note DOM", !panelHtml.includes("card-note"));
ck("kind=state -> rows rendered (prow)", (panelHtml.match(/prow/g)||[]).length===3);
ck("kind=state -> openStockSheet in rows", panelHtml.includes("openStockSheet("));
// vs buy keeps note
ctx.renderRank("buyCard", stateRows, "buy", {});
ck("kind=buy -> card-note kept", els["buyCard"].innerHTML.includes("card-note"));

// ---- Case 4: toggleStatePanel open/close ----
els["statePanel"]=makeEl();
ctx.toggleStatePanel("fade_down");
ck("toggle open -> panel visible + _openState set", els["statePanel"].hidden===false);
ctx.toggleStatePanel("fade_down");  // same -> close
ck("toggle same -> panel hidden (close)", els["statePanel"].hidden===true);
ctx.toggleStatePanel("up_concentration");
ck("toggle other -> panel visible again", els["statePanel"].hidden===false);
// unavailable state guard
warns=[];
ctx.toggleStatePanel("nonexistent");
ck("unavailable state -> warn + no crash", warns.some(w=>w.includes("stateLists unavailable")));

console.log("\nSUMMARY: "+pass+" passed, "+fail+" failed");
process.exit(fail?1:0);
