"""
Пакет 3 · т.з (2026-10-05): "дали работи COT" — (1) потвърждение от цената, изчислено от кода: инструментът ПРЕСИЧА 10-седмичната си средна в
посоката на contrarian сигнала ("потвърдено от цената" / "още не"); (2) малък track record: доходността на инструмента 2, 4 и 8 седмици
след всеки as_of с екстремум от наличната история — един ред на пазар и обобщение за секцията (src/cot_track.py).

РЕАЛНО: пълните COT серии (166 седмици) и седмичните цени от Yahoo (5 г.) за 18-те пазара от брифа на 02.10.2026 (tests/fixtures/cot_series_*.json,
cot_prices_*.json, теглени на 05.10.2026); самите екстремуми и техните percentile от брифа. Всички цифри за потвърждение/доходности по-долу са
замразени от реалния ход на кода върху тези данни към 05.10.2026. СИНТЕТИЧНО: серии за граничните случаи (пресичане/дължина на серията/поглед
напред), редовете за статистиката, провалите на теглене.
Пускане: python test_cot_track.py
"""
import sys, json, pathlib, io, contextlib, datetime as dt, tempfile, html as htmllib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import cot, cot_track as tr, render

FIX = ROOT / "tests" / "fixtures"
BRIEF = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
SER = json.loads((FIX / "cot_series_2026-10-05.json").read_text(encoding="utf-8"))["series"]
PR = json.loads((FIX / "cot_prices_2026-10-05.json").read_text(encoding="utf-8"))["prices"]
BY_SYMBOL = {v["symbol"]: pd.Series({pd.Timestamp(k): x for k, x in v["closes"].items()}) for v in PR.values()}
fetch = lambda sym: BY_SYMBOL[sym].copy()
TODAY = dt.date(2026, 10, 5)
W = lambda start, vals: pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="7D"), dtype=float)


print("── потвърждение: пресичане на SMA10 в посоката на сигнала (СИНТЕТИЧНО) ──")
flat = [100.0] * 12
c = tr.confirmation(W("2026-01-05", flat + [99.0]), "extreme_long")                        # слиза под SMA10 тази седмица
assert c["confirmed"] and c["state"] == "confirmed" and c["weeks_on_side"] == 1 and c["crossed"] and c["side"] == "below"
c = tr.confirmation(W("2026-01-05", flat + [99.0, 98.0, 97.0, 96.0]), "extreme_long")      # 4 седмици от тази страна → още скорошно
assert c["confirmed"] and c["weeks_on_side"] == 4
c = tr.confirmation(W("2026-01-05", flat + [99.0, 98.0, 97.0, 96.0, 95.0]), "extreme_long")   # 5 седмици → вече не е скорошно пресичане
assert not c["confirmed"] and c["state"] == "stale_cross" and c["weeks_on_side"] == 5
c = tr.confirmation(W("2026-01-05", flat + [101.0]), "extreme_long")                       # още над SMA10
assert not c["confirmed"] and c["state"] == "not_crossed" and c["side"] == "above"
c = tr.confirmation(W("2026-01-05", flat + [101.0]), "extreme_short")                      # огледално: extreme_short иска цена НАД SMA10
assert c["confirmed"] and c["want"] == "above" and c["weeks_on_side"] == 1
c = tr.confirmation(W("2026-01-05", [100.0 - i for i in range(14)]), "extreme_long")       # от самото начало под средната — няма пресичане в историята
assert not c["confirmed"] and c["state"] == "from_start" and not c["crossed"]
assert tr.confirmation(W("2026-01-05", [1.0] * 8), "extreme_long") is None                 # твърде кратка история
nan = W("2026-01-05", flat + [99.0]); nan.iloc[3] = float("nan")
assert tr.confirmation(nan.dropna(), "extreme_long")["confirmed"]
print("  ✓ под SMA10 тази седмица → потвърдено; 4 седмици от тази страна → още потвърдено, 5 → 'още не' (пресичането не е скорошно); още над → 'още не';")
print("    extreme_short е огледално (цена НАД SMA10); от самото начало от тази страна → 'още не' (няма пресичане); кратка история → None")

d = pd.date_range("2026-09-14", periods=3, freq="7D")                                       # понеделници 14.09, 21.09, 28.09
cl = pd.Series([1.0, 2.0, 3.0], index=d)
assert list(tr.completed(cl, dt.date(2026, 10, 2)).index.date) == [dt.date(2026, 9, 14), dt.date(2026, 9, 21)]          # петък 02.10: барът от 28.09 още не е завършен
assert list(tr.completed(cl, dt.date(2026, 10, 3)).index.date) == [dt.date(2026, 9, 14), dt.date(2026, 9, 21), dt.date(2026, 9, 28)]   # събота: завършен
assert list(tr.completed(cl, dt.date(2026, 10, 5)).index.date) == [dt.date(2026, 9, 14), dt.date(2026, 9, 21), dt.date(2026, 9, 28)]   # понеделник: 05.10 още не съществува
print("  ✓ само ЗАВЪРШЕНИ седмични бари: петък сутрин текущата седмица не се брои, от събота — да")

print()
print("── екстремумите в историята съвпадат с продукционния код (РЕАЛНО) ──")
n_ok = 0
for row in BRIEF["cot"]:
    pts = SER[row["market"]]
    last = [e for e in tr.historical_extremes(pts) if e["as_of"] == row["as_of"]]
    prod = cot._market_extreme(row["market"], pts, row["category"], config.COT_PERCENTILE_LOW, config.COT_PERCENTILE_HIGH)
    assert len(last) == 1 and last[0]["direction"] == row["direction"] == prod["direction"] and last[0]["pct"] == row["percentile"] == prod["percentile"], row["market"]
    n_ok += 1
assert n_ok == 18
print("  ✓ за всичките 18 пазара последният исторически екстремум (as_of 22.09.2026) има същата посока и percentile като реалния ред от брифа и като cot._market_extreme")

print()
print("── редовете на track record: цена на входа, хоризонти, без поглед напред ──")
pts = [{"date": (dt.date(2026, 1, 6) + dt.timedelta(weeks=i)).isoformat(), "net": float(i)} for i in range(70)]           # СИНТЕТИЧНО: нетната позиция расте → екстремум extreme_long
bars = W("2026-01-05", [100.0 + i for i in range(70)])                                                                       # цена: +1 на седмица
rows = tr.track_rows(pts, bars)
assert rows and all(r["direction"] == "extreme_long" for r in rows) and rows[0]["as_of"] == pts[config.COT_TRACK_MIN_PRIOR_WEEKS]["date"]
r0 = rows[0]
i0 = config.COT_TRACK_MIN_PRIOR_WEEKS
assert r0["entry"] == bars.iloc[i0] and abs(r0["r2"] - (bars.iloc[i0 + 2] / bars.iloc[i0] - 1)) < 1e-12 and abs(r0["r8"] - (bars.iloc[i0 + 8] / bars.iloc[i0] - 1)) < 1e-12
assert rows[-1]["r8"] is None and rows[-1]["r2"] is None                                                                      # последният екстремум още няма бъдещи бари
future = bars.copy(); future.iloc[i0 + 1:] = 1.0                                                                              # променяме само БЪДЕЩИТЕ цени след първия екстремум
rows2 = tr.track_rows(pts, future)
assert rows2[0]["confirmed"] == rows[0]["confirmed"] and rows2[0]["entry"] == rows[0]["entry"]                               # потвърждението за седмицата не зависи от бъдещето
assert tr._signed(0.05, "extreme_long") == -0.05 and tr._signed(0.05, "extreme_short") == 0.05 and tr._signed(None, "extreme_long") is None
print("  ✓ входът е затварянето на бара на as_of; r2/r4/r8 = бар[i+k]/бар[i] − 1; последният екстремум няма бъдещи бари (None); потвърждението за седмицата не се променя, когато се пипат САМО бъдещите цени;")
print("    доходността в посока на сигнала е обърната за extreme_long")

st = tr.stats([{"as_of": "2026-01-06", "direction": "extreme_long", "market": "A", "r2": -0.02, "r4": -0.04, "r8": 0.10},
               {"as_of": "2026-01-13", "direction": "extreme_long", "market": "A", "r2": -0.01, "r4": 0.02, "r8": None},
               {"as_of": "2026-03-03", "direction": "extreme_long", "market": "A", "r2": 0.03, "r4": 0.01, "r8": -0.05},
               {"as_of": "2026-01-06", "direction": "extreme_long", "market": "B", "r2": -0.04, "r4": -0.02, "r8": -0.02}])
assert st["n"] == 4 and st["episodes"] == 3                                                                                  # A: [06.01, 13.01] един епизод + 03.03; B: един → 3 (по пазар)
assert st["h2"] == {"n": 4, "mean_signal_pct": 1.0, "hit_pct": 75} and st["h8"]["n"] == 3 and st["h8"]["hit_pct"] == 67
print("  ✓ СИНТЕТИЧНО: епизодите се броят ПО ПАЗАР (две поредни седмици = един епизод; друг пазар в същата седмица е друг); успехът е дял в посоката на сигнала; None се пропуска")

print()
print("── РЕАЛНО: ценово потвърждение и track record за екстремумите от 02.10 (към 05.10.2026) ──")
out, sm = tr.annotate(BRIEF["cot"], SER, TODAY, fetch)
by = {r["market"]: r for r in out}
conf = [m for m, r in by.items() if r["price_confirmation"]["confirmed"]]
assert conf == ["Copper", "Mexican Peso", "Australian Dollar", "Cotton", "Wheat"]
assert [(m, by[m]["price_confirmation"]["state"], by[m]["price_confirmation"]["weeks_on_side"]) for m in ("30-Year Treasury Bond", "5-Year Treasury Note", "2-Year Treasury Note", "Soybeans")] == \
       [("30-Year Treasury Bond", "stale_cross", 14), ("5-Year Treasury Note", "stale_cross", 14), ("2-Year Treasury Note", "stale_cross", 7), ("Soybeans", "not_crossed", 0)]
assert by["Copper"]["price_confirmation"]["text"] == "Цената пресече SMA10 в посоката на сигнала (под нея, тази седмица); цена 6.492 срещу SMA10 6.5617 (-1.1%)."
assert by["Cotton"]["price_confirmation"]["text"].startswith("Цената пресече SMA10 в посоката на сигнала (под нея, преди 3 седмици)")
assert by["30-Year Treasury Bond"]["price_confirmation"]["text"].startswith("Цената е под SMA10 от 14 седмици — пресичането в посоката на сигнала не е скорошно (над 4)")
assert by["Soybeans"]["price_confirmation"]["text"].startswith("Цената не е пресякла SMA10 в посоката на сигнала (още е над нея)")
assert by["Lean Hogs"]["price_confirmation"]["text"].startswith("Цената не е пресякла SMA10 в посоката на сигнала (още е под нея)")        # extreme_short: огледално
for r in out:                                                                                                                 # никъде думата "потвърд…"
    assert "потвърд" not in (r["price_confirmation"]["text"] + r["track_record"]["text"]).lower(), r["market"]
print("  ✓ пресекли SMA10 в посоката на сигнала: Copper, Mexican Peso, Australian Dollar, Cotton, Wheat (5 от 18); 30Y и 5Y са под средната от 14 седмици (не е скорошно пресичане);")
print("    Soybeans още над средната — 'не е пресякла'; текстовете са неутрални (без думата 'потвърдено')")
t = by["Copper"]["track_record"]
assert (t["n"], t["episodes"], t["direction"]) == (35, 3, "extreme_long") and t["h4"] == {"n": 33, "mean_signal_pct": -2.31, "hit_pct": 24, "mean_raw_pct": 2.31}
assert by["Cotton"]["track_record"]["text"].endswith("Малка извадка — не е за изводи.") and "Малка извадка" not in by["Copper"]["track_record"]["text"]
assert by["Copper"]["track_record"]["text"] == ("История: 35 седмици с екстремум в тази посока (3 епизода); доходност на инструмента след 2/4/8 седмици: "
                                               "+1.3% (26% в посоката на сигнала) / +2.3% (24% в посоката на сигнала) / +5.1% (28% в посоката на сигнала).")
assert by["5-Year Treasury Note"]["track_record"]["n"] == 1 and by["5-Year Treasury Note"]["track_record"]["h4"]["n"] == 0 and "— / — / —" in by["5-Year Treasury Note"]["track_record"]["text"]
print("  ✓ Copper: 35 седмици с екстремум extreme_long в 3 епизода — медта на 4 седмици след тях е средно +2.3% (обратно на сигнала; успех 24%); Cotton: малка извадка (2 епизода);")
print("    5-Year: само 1 седмица (нов екстремум) — още няма бъдещи бари → '— / — / —'")
assert (sm["markets"], sm["n"], sm["episodes"]) == (18, 387, 53)
assert sm["h2"] == {"n": 369, "mean_signal_pct": -0.29, "hit_pct": 47} and sm["h4"] == {"n": 340, "mean_signal_pct": -0.28, "hit_pct": 50} and sm["h8"] == {"n": 298, "mean_signal_pct": -1.19, "hit_pct": 50}
assert (sm["confirmed"]["n"], sm["confirmed"]["episodes"], sm["not_confirmed"]["n"], sm["not_confirmed"]["episodes"]) == (72, 35, 315, 55)
assert sm["confirmed"]["h4"] == {"n": 65, "mean_signal_pct": -1.18, "hit_pct": 52} and sm["not_confirmed"]["h4"] == {"n": 275, "mean_signal_pct": -0.06, "hit_pct": 50}
assert sm["text"] == ("Обобщение (в посока на сигнала, 18 пазара, 387 седмици в 53 епизода): след 2/4/8 седмици -0.3% (47%) / -0.3% (50%) / -1.2% (50%). "
                      "С пресичане на SMA10: n=72, след 4 седм. -1.2% (52% успех); без пресичане: n=315, след 4 седм. -0.1% (50% успех) "
                      "(SMA10 = 10-седмична средна на седмичните затваряния). "
                      "Седмиците се припокриват и историята е ~2–3 години — ориентир, не доказателство.")
assert "потвърд" not in sm["text"].lower()
print("  ✓ обобщение: 18 пазара, 387 седмици с екстремум в 53 епизода; в посока на сигнала след 2/4/8 седмици средно −0.3% / −0.3% / −1.2% (успех 47% / 50% / 50%);")
print("    с пресичане на SMA10 72 седмици (19%), без — 315; на 4 седмици −1.2% срещу −0.1% — пресичането не помага в тази извадка")

print()
print("── graceful degradation ──")
def flaky(sym):
    if sym == "HG=F":
        raise ConnectionError("Yahoo down")
    return fetch(sym)
with contextlib.redirect_stdout(io.StringIO()):
    out2, sm2 = tr.annotate(BRIEF["cot"], SER, TODAY, flaky)
b2 = {r["market"]: r for r in out2}
assert "price_confirmation" not in b2["Copper"] and "track_record" not in b2["Copper"] and "price_confirmation" in b2["Wheat"]
assert sm2["markets"] == 17
with contextlib.redirect_stdout(io.StringIO()):
    o3, s3 = tr.annotate(BRIEF["cot"], SER, TODAY, lambda sym: (_ for _ in ()).throw(RuntimeError("всичко е счупено")))
assert all("price_confirmation" not in r for r in o3) and s3 is None and [r["market"] for r in o3] == [r["market"] for r in BRIEF["cot"]]
o4, s4 = tr.annotate([{**BRIEF["cot"][0], "market": "Непознат пазар"}], SER, TODAY, fetch)
assert "price_confirmation" not in o4[0] and s4 is None
o5, _ = tr.annotate(BRIEF["cot"][:1], {}, TODAY, fetch)                                              # няма COT серия → потвърждението остава, track record — не
assert "price_confirmation" in o5[0] and "track_record" not in o5[0]
print("  ✓ провал на един символ → само този пазар остава без полетата (17 в обобщението); всичко счупено → редовете са непроменени, без обобщение; непознат пазар/липсваща серия — без изключение")

print()
print("── в страницата ──")
brief = json.loads(json.dumps(BRIEF)); brief["cot"] = out; brief["cot_summary"] = sm
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
        plain = htmllib.unescape(render.render_dashboard(json.loads(json.dumps(BRIEF))))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
assert sm["text"] in page and by["Copper"]["price_confirmation"]["text"] in page and by["Copper"]["track_record"]["text"] in page
assert "Цената пресече SMA10 в посоката на сигнала" in page and "Цената не е пресякла SMA10" in page
assert "Потвърдено от цената" not in page and "✔" not in page.split("COT Екстремуми")[1].split("</section>")[0]                  # без думата и без отметката
assert "Потвърдено от цената" not in plain                                                          # стар бриф без полетата — без промяна
print("  ✓ над картите — един ред обобщение; във всяка карта — неутрален ред за SMA10 и ред за историята; стар бриф без тези полета се рендерира както преди")

print()
print("Всички тестове минаха.")
