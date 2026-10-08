"""
GLB · начално състояние от историята (08.10.2026). Хистерезисът (4б, пуснат на 08.10) започна с ПРАЗНО състояние: вход само при close >= линията ×1.01 В ДЕНЯ на първия run → списъкът падна от 9 на 3 (SNX, WCC, WSM), а
"GLB от" показваше 08.10 (WCC — реално над линията от седмици). Сега при първия run с тази версия състоянието се гради ЕДНОКРАТНО от историята: ден по ден същият apply_hysteresis върху последните GLB_SEED_SESSIONS (40) сесии,
с линията, дългия период и overlay-а към всяка дата; белегът "seed" е в data/glb_state.json; следващите дни — обикновеният хистерезис.

РЕАЛНО: tests/fixtures/glb_seed_2026-10-07.json — РЕАЛНИ данни от Yahoo за FAST, ETN, ADI, NVT, CVX, QLYS, SNX, WCC, WSM (месечни close-ове за цялата история + дневни бар-ове за 90 сесии до 07.10.2026 вкл., split-only
корекция като в производството). Затварянията на 07.10 са тези, които видя брифът на 08.10 (9 кандидата на 07.10, 3 на 08.10). СИНТЕТИЧНО (маркирано): състоянието "преди" (3-те събития от 08.10 без белег за seed),
изключеният seed (GLB_SEED_SESSIONS=0), версията на белега. Мрежата е подменена (yf.download връща РЕАЛНИТЕ данни от fixture-а; името на компанията — идентичност).
Пускане: python test_glb_seed.py
"""
import sys, json, pathlib, tempfile, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import glb_screener as g

g._verified_company_name = lambda s: {"name": s, "verified": True}
g.time = type("T", (), {"sleep": staticmethod(lambda s: None)})
FX = json.loads((ROOT / "tests" / "fixtures" / "glb_seed_2026-10-07.json").read_text(encoding="utf-8"))["tickers"]
TK = list(FX)
LAST = "2026-10-07"
ENTRY, EXIT = 1 + config.GLB_ENTRY_MARGIN_PCT / 100, 1 - config.GLB_EXIT_MARGIN_PCT / 100


def hist_of(s, with_actions=False):
    f = FX[s]
    m = pd.DataFrame({"Close": f["monthly"]["close"]}, index=pd.to_datetime(f["monthly"]["dates"]))
    m["Open"] = m["High"] = m["Low"] = m["Close"]
    m["Volume"] = 0
    d = f["daily"]
    dd = pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))
    h = pd.concat([m[["Open", "High", "Low", "Close", "Volume"]], dd]).sort_index()
    if with_actions:
        h["Stock Splits"] = 0.0
    return h


print("── 1. независим еталон: линия, вход ≥ ×1.01, оставане ≥ ×0.97 — прост цикъл върху РЕАЛНИТЕ цени ──")


def independent(s, n=config.GLB_SEED_SESSIONS):
    """Не ползва нищо от glb_screener: за всяка от последните n сесии — линията = най-високият месечен close преди месеца; ≥3 месеца без пробив; вход при close ≥ линията×1.01; оставане до close < линията×0.97."""
    h = hist_of(s)["Close"]
    mc = h.resample("ME").last().dropna()
    held = None
    for d in h.index[-n:]:
        prior = mc[mc.index.to_period("M") < d.to_period("M")]
        line = float(prior.max())
        months_between = len(prior) - 1 - int(np.argmax(prior.values))
        px = float(h.loc[d])
        if held is not None:
            if px < held["line"] * EXIT:
                held = None
        if held is None and months_between >= config.GLB_MIN_MONTHS_UNPENETRATED and px >= line * ENTRY:
            held = {"since": d.date().isoformat(), "line": round(line, 2)}
    return held


EXPECT = {s: independent(s) for s in TK}
assert all(EXPECT[s] is not None for s in TK)
print("  ✓ еталон (независим цикъл): " + ", ".join(f"{s} от {v['since'][8:10]}.{v['since'][5:7]}" for s, v in sorted(EXPECT.items(), key=lambda x: x[1]["since"])))

print()
print("── 2. replay_observations + replay_state = еталона ──")
replays = {s: g.replay_observations(s, hist_of(s), config.GLB_SEED_SESSIONS, config.GLB_ENTRY_MARGIN_PCT) for s in TK}
events, rows, ch = g.replay_state(replays)
assert len(next(iter(replays.values()))) == 40 and max(next(iter(replays.values()))) == LAST
assert {s: {"since": e["since"], "line": e["line"]} for s, e in events.items()} == EXPECT, ({s: (e["since"], e["line"]) for s, e in events.items()}, EXPECT)
assert {r["ticker"] for r in rows} == set(TK) and all(r["pct_vs_line"] >= -3.0 for r in rows)
byt = {r["ticker"]: r["pct_vs_line"] for r in rows}
assert (byt["FAST"], byt["ETN"], byt["WCC"], byt["WSM"], byt["SNX"]) == (0.3, -0.4, 1.4, 3.2, 1.6)                          # затварянията на 07.10 спрямо линията (като в брифа на 08.10)
print("  ✓ събитията и 'GLB от' = еталона; на 07.10 всичките 9 са в списъка (FAST +0.3%, ETN −0.4%, ADI −0.9%, NVT −1.1%, CVX −0.8%, QLYS −0.8% — в рамките на ×0.97); WCC от 23.09, не от 08.10")

print()
print("── 3. старото поведение (празно състояние) върху същите данни = живият бриф на 08.10 ──")
last_obs = {s: r[LAST] for s, r in replays.items()}
ev0, rows0, ch0 = g.apply_hysteresis({}, last_obs, LAST)
assert sorted(ev0) == ["SNX", "WCC", "WSM"] and sorted(r["ticker"] for r in rows0) == ["SNX", "WCC", "WSM"]
print("  ✓ с празно състояние на 07.10-данните излизат точно SNX, WCC, WSM (както в РЕАЛНИЯ бриф от 08.10: 9 → 3, всички с 'GLB от 08.10')")

print()
print("── 4. целият screen(): еднократно изграждане, после обикновеният хистерезис ──")
frames = {}
for s in TK:
    h = hist_of(s, with_actions=True)
    frames[s] = h
big = pd.concat(frames, axis=1)                                                                                                  # колони (тикър, поле) като yf.download(group_by="ticker")
calls = {"n": 0}
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: (calls.__setitem__("n", calls["n"] + 1), big[list(batch)])[1])})
tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_glbseed_"))
state = tmp / "glb_state.json"
before = {"updated": "2026-10-08", "events": {s: {"ticker": s, "line": EXPECT[s]["line"], "since": "2026-10-08", "glb_type": "classic", "prior_high": EXPECT[s]["line"]} for s in ("SNX", "WCC", "WSM")}}    # СИНТЕТИЧНО: състоянието от 08.10 (без белег)
state.write_text(json.dumps(before), encoding="utf-8")
assert g.load_seed_meta(state) == {}
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()) as out:
    res = g.screen(universe=TK, batch_size=50, state_path=state, today="2026-10-08")
saved = json.loads(state.read_text(encoding="utf-8"))
assert sorted(r["ticker"] for r in res) == sorted(TK) and saved["seed"] == {"version": config.GLB_SEED_VERSION, "sessions": 40, "from": "2026-08-12", "to": "2026-10-07"} and config.GLB_SEED_VERSION == 2
assert {s: e["since"] for s, e in saved["events"].items()} == {s: EXPECT[s]["since"] for s in TK}                               # реалните дати, не 08.10
assert "НАЧАЛНО състояние от историята" in out.getvalue()
print(f"  ✓ състояние без белег → еднократно изграждане: {len(res)} кандидата с реалните дати (WCC от {saved['events']['WCC']['since']}); белег seed v2 (40 сесии 12.08 → 07.10)")
with contextlib.redirect_stdout(io.StringIO()) as out2:
    res2 = g.screen(universe=TK, batch_size=50, state_path=state, today="2026-10-08")
assert sorted(r["ticker"] for r in res2) == sorted(TK) and "НАЧАЛНО" not in out2.getvalue() and "хистерезис:" in out2.getvalue()
assert json.loads(state.read_text(encoding="utf-8"))["seed"]["version"] == config.GLB_SEED_VERSION                                                    # белегът се пази при обикновен ден
print("  ✓ втори run: обикновен хистерезис (без ново изграждане), белегът остава")
config.GLB_SEED_SESSIONS = 0                                                                                                    # СИНТЕТИЧНО: изключено
state.write_text(json.dumps(before), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    res3 = g.screen(universe=TK, batch_size=50, state_path=state, today="2026-10-08")
assert sorted(r["ticker"] for r in res3) == ["SNX", "WCC", "WSM"] and "seed" not in json.loads(state.read_text(encoding="utf-8"))
config.GLB_SEED_SESSIONS = 40
print("  ✓ СИНТЕТИЧНО: GLB_SEED_SESSIONS=0 → старото поведение (SNX, WCC, WSM с 'от 08.10'), без белег")
print("\n✅ test_glb_seed: всичко мина")
