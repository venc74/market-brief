"""
20.10.2026 · етап 3, част Б: ЕДНО теглене за корпоративните действия. До 20.10 маркерът (annotate, под прага на същественост) теглеше отделно yf.download(period="6mo") за същите
тикъри, които exclude() вече беше изтеглил за скрийнъра, GLB и QM (fetch_actions, 5 години). Сега маркерът чете кеша на run-а (_SERIES); тегли само тикъри без серия там.
Поведението е същото — сравнение стар ↔ нов код (scratchpad на сесията): 24 реални брифа (17.09–20.10) + реалните fixture-и на 5 дати, с нормално, частично и пълно падане
на тегленето — 39 сценария, 0 разлики; тегленията 129 → 101 (по едно по-малко на нормален run).

РЕАЛНО: tests/fixtures/corp_actions_2026-10-09.json (Close и Stock Splits от Yahoo на 09.10.2026: CTVA 6.665 на 01.10, MIDD 1.243, FDX 1.241, цели 2:1 / 4:1 / 1:3).
СИНТЕТИЧНО (означено): подмененият yf.download, редовете на модулите, празната серия на тикъра "ZZZ", паднало теглене.
Пускане: python test_corp_action_one_fetch.py
"""
import sys, ast, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import corp_actions as ca

FX = json.loads((ROOT / "tests/fixtures/corp_actions_2026-10-09.json").read_text(encoding="utf-8"))["tickers"]
frame = lambda t: pd.DataFrame({"Close": FX[t]["close"], "Stock Splits": FX[t]["splits"]}, index=pd.to_datetime(FX[t]["dates"]))
BIG = pd.concat({t: frame(t) for t in FX}, axis=1)
EMPTY = pd.DataFrame({"Close": [float("nan")] * len(BIG), "Stock Splits": [float("nan")] * len(BIG)}, index=BIG.index)
CALLS, FAIL = [], [0]


def fake_download(batch, **kw):                                                            # СИНТЕТИЧНО: Yahoo с реалните серии от 09.10
    CALLS.append((list(batch), sorted(k for k in kw if k in ("start", "period"))))
    if FAIL[0]:
        FAIL[0] -= 1
        raise RuntimeError("Yahoo down (СИНТЕТИЧНО)")
    data = pd.concat({t: (BIG[t] if t in FX else EMPTY) for t in batch}, axis=1)
    if all(t not in FX for t in batch):
        return data.iloc[0:0]                                                                # само непознати тикъри → празен резултат (както Yahoo)
    return data


ca.yf = type("Y", (), {"download": staticmethod(fake_download)})
q = lambda: contextlib.redirect_stdout(io.StringIO())
T = sorted(FX)


def main_order(tickers, fail=0):
    """Редът в main.run: изключване (скрийнър, GLB, Уиш, QM), после маркерът върху останалите карти."""
    CALLS.clear(); FAIL[0] = fail
    with q():
        ca.reset()
        scr, _ = ca.exclude([{"ticker": t} for t in tickers], "screener", "2026-10-09")
        glb, _ = ca.exclude([{"ticker": t, "prior_high_month": "2026-06"} for t in tickers], "glb", "2026-10-09")
        ca.exclude([{"ticker": t, "prior_high_month": "2026-06"} for t in tickers], "glb_wish", "2026-10-09")
        qm, _ = ca.exclude([{"ticker": t} for t in tickers], "qm", "2026-10-09")
        cards = [scr, glb, qm]
        diag = ca.annotate(cards, "2026-10-09")
    return cards, diag


print("── 1. редът на main.run: едно теглене за изключването И маркера ──")
cards, diag = main_order(T)
assert len(CALLS) == 1 and CALLS[0][1] == ["start"], CALLS
old_path = lambda ts: {t: ([x.date().isoformat() for x in frame(t)["Stock Splits"].dropna().index], [float(v) for v in frame(t)["Stock Splits"].dropna()]) for t in ts}
kept = sorted({c["ticker"] for g in cards for c in g})
with q():
    old = ca.annotate([[{"ticker": c["ticker"]} for c in g] for g in cards], "2026-10-09", fetch=old_path)        # старият път: отделно теглене (подменено — същите реални серии)
    alone = ca.annotate([[{"ticker": t} for t in T]], "2026-10-09", fetch=old_path)
assert diag["ok"] and diag["flagged"] == old["flagged"] == [] and "CTVA" not in kept and "MIDD" not in kept
assert alone["flagged"] == [{"ticker": "CTVA", "date": "2026-10-01", "ratio": 6.665}]
print(f"  ✓ {len(CALLS)} теглене (fetch_actions, от началото на 5-те години); маркерът върху останалите карти ({', '.join(kept)}) = старият път с отделно теглене")
print("  ✓ CTVA (6.665) и MIDD (1.243) са изключени, затова маркер няма; без изключването маркерът би хванал CTVA")

print()
print("── 2. изключването падна (СИНТЕТИЧНО) → маркерът тегли сам, както преди ──")
cards, diag = main_order(T, fail=1)
assert diag["ok"] and len(CALLS) == 2, CALLS
print(f"  ✓ скрийнърът без данни; GLB тегли наново, маркерът ползва неговия кеш: {len(CALLS)} тегления")
cards, diag = main_order(T, fail=99)
assert not diag["ok"] and "Yahoo down" in diag["error"] and not any(c.get("corp_action") for g in cards for c in g)
print("  ✓ всички тегления паднаха → маркерът ok=False, без маркери (банерът в data_warnings)")

print()
print("── 3. тикър с празна серия (СИНТЕТИЧНО 'ZZZ') не сваля маркерите на останалите ──")
cards, diag = main_order(T + ["ZZZ"])
assert diag["ok"] and len(CALLS) == 2 and CALLS[1][0] == ["ZZZ"], CALLS
left = {c["ticker"] for g in cards for c in g}
assert "ZZZ" in left and diag["checked"] == len(left)
print("  ✓ второ теглене само за ZZZ; празният отговор не прави маркера 'неуспешен' (старото общо теглене също не падаше)")

print()
print("── 4. пазач: едно място, което тегли ──")
src = (ROOT / "src/corp_actions.py").read_text(encoding="utf-8")
calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and ast.unparse(n.func) == "yf.download"]
assert len(calls) == 1 and "def fetch_splits" not in src, [n.lineno for n in calls]
print("  ✓ yf.download само във fetch_actions; fetch_splits го няма")
print("\n✅ test_corp_action_one_fetch: всичко мина")
