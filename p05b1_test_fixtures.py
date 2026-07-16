import importlib.util, json, tempfile, os, sys

spec = importlib.util.spec_from_file_location("frag", os.path.join(os.path.dirname(__file__) or ".", "frag_work.py"))
frag = importlib.util.module_from_spec(spec); spec.loader.exec_module(frag)

def mk(code, state, label, score):
    return {"code": code, "name": "N"+code, "market": "KR", "changeRate": 1.0,
            "shareDeltaPp": 0.1, "priceChangePct": 1.0, "flowLabel": label,
            "flowState": state, "score": score}

def run(ranks, ok):
    tmp = tempfile.mktemp(suffix=".json")
    out = frag.build(ranks, ok, "20260714", 15, tmp)
    return json.load(open(tmp))

STATES6 = ["up_concentration","down_concentration","attention_up","fade_up","neutral","fade_down"]
results = []
def check(name, cond):
    results.append((name, cond)); print(("PASS " if cond else "FAIL ")+name)

# ---- NORMAL: 6 states, attention_up=0, up/down order differs from buy/sell after sort ----
normal = (
    [mk("U1","up_concentration","up",5), mk("U2","up_concentration","up",9), mk("U3","up_concentration","up",1)] +  # sort by -score -> U2,U3,U1 (differs from list order)
    [mk("D1","down_concentration","down",-2), mk("D2","down_concentration","down",-8)] +
    [mk("P1","fade_up","fu",3)] +
    [mk("N1","neutral","nt",0), mk("N2","neutral","nt",0)] +
    [mk("X1","fade_down","fd",-1), mk("X2","fade_down","fd",-1)]
)  # total 10, attention_up=0
try:
    o = run(normal, 10)
    check("normal: stateLists has all 6 keys", tuple(o["stateLists"].keys())==tuple(STATES6))
    check("normal: counts has all 6 keys", tuple(o["counts"].keys())==tuple(STATES6))
    check("normal: attention_up empty list + 0 count", o["stateLists"]["attention_up"]==[] and o["counts"]["attention_up"]==0)
    check("normal: fade_down 2 stocks", len(o["stateLists"]["fade_down"])==2 and o["counts"]["fade_down"]==2)
    check("normal: buyPressure set == stateLists[up]", {r["code"] for r in o["buyPressure"]}=={r["code"] for r in o["stateLists"]["up_concentration"]})
    check("normal: total rows == 10", sum(len(v) for v in o["stateLists"].values())==10)
    check("normal: slim fields only", set(o["stateLists"]["up_concentration"][0].keys())=={"code","name","market","changeRate","shareDeltaPp","priceChangePct","flowLabel"})
    check("normal: buyPressure order != stateLists[up] order (sort applied)", [r["code"] for r in o["buyPressure"]]!=[r["code"] for r in o["stateLists"]["up_concentration"]])
except Exception as e:
    check("normal: no exception", False); print("  err:", e)

# ---- NEGATIVE 1: unknown flowState ----
try:
    run(normal + [mk("Z1","BOGUS","zz",0)], 11); check("neg: unknown flowState raises", False)
except RuntimeError as e:
    check("neg: unknown flowState raises RuntimeError", "unknown flowState" in str(e))
except Exception as e:
    check("neg: unknown flowState raises", False); print("  wrong exc:", type(e), e)

# ---- NEGATIVE 2: duplicate code across states (uniqueness gate) ----
dup = normal + [mk("U1","neutral","nt",0)]  # U1 also in up -> dup code, total 11
try:
    run(dup, 11); check("neg: dup code raises", False)
except RuntimeError as e:
    check("neg: dup code -> uniqueness fail", "uniqueness" in str(e))
except Exception as e:
    check("neg: dup code raises", False); print("  wrong exc:", type(e), e)

# ---- NEGATIVE 3: wrong targetCount (total mismatch) ----
try:
    run(normal, 999); check("neg: wrong ok raises", False)
except RuntimeError as e:
    check("neg: wrong ok -> total mismatch", "targetCount" in str(e) or "total" in str(e))
except AssertionError:
    check("neg: wrong ok -> (assert caught it first)", True)
except Exception as e:
    check("neg: wrong ok raises", False); print("  wrong exc:", type(e), e)

# ---- summary ----
bad = [n for n,c in results if not c]
print("\nSUMMARY: %d/%d passed" % (sum(1 for _,c in results if c), len(results)))
sys.exit(1 if bad else 0)
