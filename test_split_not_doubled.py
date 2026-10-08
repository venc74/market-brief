"""
GLB · цените не се коригират втори път за сплитове (08.10.2026). Yahoo `Close`/`Open`/`High`/`Low` при yf.download(..., auto_adjust=False) са ВЕЧЕ ретроактивно split-коригирани; ръчната split-only корекция в
glb_screener.screen() (от 24.08) ги делеше втори път (NVDA 07.06.2024: 12.09 вместо 120.89) и занижаваше линията на акции със сплит. Корекцията е махната.

РЕАЛНО: tests/fixtures/yahoo_splits_2026-10-08.json — 150 дневни бара около сплита на NVDA (10:1, 10.06.2024), AAPL (4:1, 31.08.2020) и AMZN (20:1, 06.06.2022), точно както ги връща yf.download(auto_adjust=False,
actions=True) с yfinance 1.5.2 на 08.10.2026 (колоната "Stock Splits" е реална). СИНТЕТИЧНО (маркирано): подменените yf.download / име на компания и празното състояние на хистерезиса.
Пускане: python test_split_not_doubled.py
"""
import sys, json, pathlib, tempfile, inspect, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import glb_screener as g

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_splits_2026-10-08.json").read_text(encoding="utf-8"))["tickers"]
assert sorted(FX) == ["AAPL", "AMZN", "NVDA"]
RATIO = {"NVDA": 10.0, "AAPL": 4.0, "AMZN": 20.0}

print("── 1. предпоставката върху РЕАЛНИТЕ отговори на Yahoo: цените около сплита вече са непрекъснати ──")
for t, d in FX.items():
    k = d["dates"].index(d["split_date"])
    assert d["splits"] == {d["split_date"]: RATIO[t]}                       # реалната колона "Stock Splits": коефициентът е на датата на сплита
    before, on = d["c"][k - 1], d["c"][k]
    assert abs(on / before - 1) < 0.07, (t, before, on)                      # ден до ден ~ нормално движение, не скок ×коефициент
    would_be = before / RATIO[t]                                             # това даваше махнатата корекция за деня преди сплита
    assert on / would_be > RATIO[t] * 0.9
    print(f"  ✓ {t}: close преди сплита {before:.2f} → в деня на сплита {on:.2f} ({(on / before - 1) * 100:+.1f}%) — Yahoo вече е коригирал; старата корекция щеше да даде {would_be:.2f} (скок ×{on / would_be:.1f} в деня на сплита)")

print()
print("── 2. screen(): данните стигат до оценката такива, каквито ги връща Yahoo ──")
g._verified_company_name = lambda s: {"name": s, "verified": True}          # СИНТЕТИЧНО: без мрежа
g.time = type("T", (), {"sleep": staticmethod(lambda s: None)})
def frame(d):
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))
def frame_actions(d):                                                         # както Yahoo при actions=True: колона "Stock Splits" с РЕАЛНИТЕ коефициенти (0 иначе)
    f = frame(d)
    f["Dividends"] = 0.0
    f["Stock Splits"] = [d["splits"].get(x, 0.0) for x in d["dates"]]
    return f
big = pd.concat({t: frame(d) for t, d in FX.items()}, axis=1)
big_actions = pd.concat({t: frame_actions(d) for t, d in FX.items()}, axis=1)
calls = []
def fake_download(batch, **kw):
    calls.append(kw)
    return (big_actions if kw.get("actions") else big)[list(batch)]
g.yf = type("Y", (), {"download": staticmethod(fake_download)})
tmp = tempfile.TemporaryDirectory(prefix="mb_split_")

def run(state_name, seeded):
    cap = {"eval": {}, "replay": {}, "wish": {}}
    orig_wish = g.wish_signal
    g._evaluate_ticker = lambda sym, hist, m=0.0: cap["eval"].setdefault(sym, hist.copy()) is None and None
    g.replay_observations = lambda sym, hist, n, m: (cap["replay"].setdefault(sym, hist.copy()), {})[1]
    g.wish_signal = lambda df, today=None: (cap["wish"].setdefault(id(df), df.copy()), orig_wish(df, today))[1]
    state = pathlib.Path(tmp.name) / state_name
    if seeded:                                                                 # СИНТЕТИЧНО: празно състояние на хистерезиса с актуалния белег → обикновен дневен run
        state.write_text(json.dumps({"updated": "2026-10-08", "events": {}, "seed": {"version": config.GLB_SEED_VERSION, "sessions": 40, "from": None, "to": None}}), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        g.screen(universe=list(FX), batch_size=50, state_path=state, today="2026-10-09")
    g.wish_signal = orig_wish
    return cap
cap_daily = run("state_daily.json", True)
cap_seed = run("state_seed_missing.json", False)
for label, got in (("обикновен дневен run", cap_daily["eval"]), ("начално състояние от историята", cap_seed["replay"])):
    assert sorted(got) == ["AAPL", "AMZN", "NVDA"], (label, sorted(got))
    for t, h in got.items():
        for col, key in (("Close", "c"), ("High", "h"), ("Low", "l"), ("Open", "o")):
            assert list(h[col]) == FX[t][key], (label, t, col)
    print(f"  ✓ {label}: Close/High/Low/Open на NVDA, AAPL и AMZN са идентични с реалните отговори на Yahoo (нито едно деление)")
wish_dfs = list(cap_daily["wish"].values())
assert len(wish_dfs) == 3 and all(list(df["Close"]) == FX[t]["c"] for df, t in zip(wish_dfs, FX))
print("  ✓ и сигналът за книгата «GLB по Уиш» получава същите цени")
assert all("actions" not in kw and kw.get("auto_adjust") is False for kw in calls)
print(f"  ✓ теглене: auto_adjust=False, без actions=True (колоната 'Stock Splits' вече не е нужна) — {len(calls)} извиквания")

print()
print("── 3. кодът ──")
src = inspect.getsource(g)
assert not hasattr(g, "_split_only_adjust") and "_split_only_adjust(" not in src and "Stock Splits" not in inspect.getsource(g.screen) and "actions=True" not in inspect.getsource(g.screen)
print("  ✓ _split_only_adjust е махната от glb_screener, screen() не чете 'Stock Splits' и не иска actions=True")
print("\n✅ test_split_not_doubled: всичко мина")
