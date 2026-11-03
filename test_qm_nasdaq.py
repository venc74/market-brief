"""
03.11.2026 · разходката, т. 11 (Kullamägi), 2: пазарът по неговото правило — QQQ над / под SMA10 и SMA20 по затварянето на последната сесия. Ред в секцията (и в имейла):
„Nasdaq над 10/20 DMA“ или „Nasdaq под 10/20 DMA — по неговото правило Kullamägi не би търгувал днес“ (смесеното — без твърдение за правилото). Само информация, без филтър.
Състоянието се записва във всеки нов запис в книгата qm_breakout (rec["nasdaq"]); от стар snapshot — от snap["qm_market"].

РЕАЛНО: tests/fixtures/qqq_daily_2026-11-03.json — затварянията на QQQ (3 месеца до 02.11), свалени на 03.11.2026; tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подмененото теглене (връща РЕАЛНИТЕ затваряния), смесените и „над двете“ случаи (отрязана история), картата в книгата.
Пускане: python test_qm_nasdaq.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_qmnq_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_breakout as qb, backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "qqq_daily_2026-11-03.json").read_text(encoding="utf-8"))
C = pd.Series(FX["close"], index=pd.to_datetime(FX["dates"]))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. nasdaq_trend — РЕАЛНИТЕ затваряния на QQQ ──")
t = qb.nasdaq_trend(C)
assert t == {"date": "2026-11-02", "close": 681.09, "sma10": round(C.iloc[-10:].mean(), 2), "sma20": round(C.iloc[-20:].mean(), 2), "above10": False, "above20": False}, t
assert (t["sma10"], t["sma20"]) == (709.77, 724.43)
assert qb.nasdaq_line(t) == "Nasdaq под 10/20 DMA — по неговото правило Kullamägi не би търгувал днес"
print(f"  ✓ 02.11: QQQ ${t['close']} под SMA10 ${t['sma10']} и SMA20 ${t['sma20']} → „{qb.nasdaq_line(t)}“")
seen = {}
for n in range(20, len(C) + 1):                                                                 # СИНТЕТИЧНО: историята, отрязана до всеки ден
    x = qb.nasdaq_trend(C.iloc[:n])
    seen.setdefault((x["above10"], x["above20"]), x["date"])
assert (True, True) in seen and qb.nasdaq_line(qb.nasdaq_trend(C.loc[:seen[(True, True)]])) == "Nasdaq над 10/20 DMA"
mixed = [k for k in seen if k[0] != k[1]]
assert mixed and all(qb.nasdaq_line(qb.nasdaq_trend(C.loc[:seen[k]])) in ("Nasdaq над 20 DMA, под 10 DMA", "Nasdaq над 10 DMA, под 20 DMA") for k in mixed)
assert qb.nasdaq_trend(C.iloc[:19]) is None and qb.nasdaq_line(None) is None
print(f"  ✓ в историята: над двете на {seen[(True, True)]}; смесено — " + ", ".join(f"{seen[k]} ({qb.nasdaq_line(qb.nasdaq_trend(C.loc[:seen[k]]))})" for k in mixed) + "; под 20 затваряния → няма ред")

print()
print("── 2. fetch_nasdaq_trend (СИНТЕТИЧНО: тегленето връща РЕАЛНИТЕ затваряния) ──")
frame = pd.DataFrame({"Close": C})
assert qb.fetch_nasdaq_trend(download=lambda s: frame) == t
with q() as log:
    assert qb.fetch_nasdaq_trend(download=lambda s: (_ for _ in ()).throw(ConnectionError("СИНТЕТИЧНО"))) is None
assert "Nasdaq (QQQ) спрямо 10/20 DMA — не се изтегли: ConnectionError" in log.getvalue()
print("  ✓ същият резултат през тегленето; провал → None и ред в лога")

print()
print("── 3. книгата: състоянието в новия запис (днешните карти и стар snapshot) ──")
card = {"ticker": "СИНТ", "trigger": 100.0, "adr": 4.0, "close": 98.0}                         # СИНТЕТИЧНО: картата
tracker = {}
backtest._ingest_new_positions(tracker, today_date="2026-11-03", today_regime="Defensive", today_qm=[card], today_context={"nasdaq": t})
assert tracker["СИНТ_2026-11-03_qm"]["nasdaq"] == t and tracker["СИНТ_2026-11-03_qm"]["regime"] == "Defensive"
(config.DATA_DIR / "2026-11-02.json").write_text(json.dumps({"date": "2026-11-02", "thermometer": {"regime": "Defensive"},
                                                            "qm_breakout": [{**card, "ticker": "СТАР"}], "qm_market": t}), encoding="utf-8")    # СИНТЕТИЧНО: snapshot
backtest._ingest_new_positions(tracker, today_date="2026-11-03")
assert tracker["СТАР_2026-11-02_qm"]["nasdaq"] == t
backtest._ingest_new_positions(tracker, today_date="2026-11-04", today_qm=[{**card, "ticker": "БЕЗ"}])
assert tracker["БЕЗ_2026-11-04_qm"]["nasdaq"] is None                                          # без контекст → None, не измислено
print("  ✓ rec[\"nasdaq\"] = {date, close, sma10, sma20, above10, above20}; от стар snapshot — snap[\"qm_market\"]; без него — None")

print()
print("── 4. страницата и имейлът (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
b = copy.deepcopy(B19); b["qm_market"] = t
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
    mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_email(b))))
line = "Nasdaq под 10/20 DMA — по неговото правило Kullamägi не би търгувал днес · QQQ $681.09 на 02.11, SMA10 $709.77, SMA20 $724.43"
assert line + " — само информация, не филтър" in page and line + " — само информация" in mail
assert page.index("Пробиви по Kullamägi (Breakout)") < page.index(line)
b.pop("qm_market")
with q():
    old = render.render_dashboard(b, publish=False)
assert "Nasdaq под 10/20 DMA" not in old                                                         # стар бриф без ключа — без реда
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'today_context={"nasdaq": qm_market}' in main_src and '"qm_market": qm_market,' in main_src and 'steps.step("qm_market", qm_breakout.fetch_nasdaq_trend' in main_src
print(f"  ✓ „{line}“ — в секцията и в имейла; стар бриф — без реда; main подава състоянието на книгата и го пази в brief[\"qm_market\"]")
print("\n✅ test_qm_nasdaq: всичко мина")
