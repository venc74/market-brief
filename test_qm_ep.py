"""
Qullamaggie (06.10.2026) · т.3: EP наблюдение (src/qm_ep.py) — в 07:30 брифът показва after-hours гаповете ≥ 10% за тикъри от универса, при "пренебрегване" (ръст ≤ 20% за предходните ~3 месеца)
и с максимален стоп 1×ADR като информация; AI само класифицира катализатора от заглавията, а всяко число в прозата се проверява от кода; after-hours гапът се логва срещу реалния гап на
отварянето (за решение след 4–6 седмици); без Track Record.

РЕАЛНО: 5-минутни барове с prepost и дневни данни на SYNA, VICR, NKE, AAPL (tests/fixtures/qm_ep_2026-10-02.json): SYNA +15.0% after-hours на 01.10.2026 (106.16 → 122.04; оферта за придобиване от ON
Semi), отваря 02.10 на 121.70 (+14.65%), ръст за 63 дни −11.2%, ADR 4.49%; VICR +9.6% на 30.09 (под прага), NKE −8.6%, AAPL ~0%. Заглавията на SYNA са от Yahoo Finance RSS. СИНТЕТИЧНО: отговорите на
AI (подменен ai_call), граничните стойности, допълнителните записи в дневника.
Пускане: python test_qm_ep.py
"""
import sys, json, pathlib, tempfile, copy, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import qm_ep as ep

F = json.loads((ROOT / "tests" / "fixtures" / "qm_ep_2026-10-02.json").read_text(encoding="utf-8"))
D = dt.date.fromisoformat
assert (config.QM_EP_GAP_PCT, config.QM_EP_NEGLECT_RET63_PCT, config.QM_EP_STOP_ADR) == (10.0, 20.0, 1.0)


def m5(t, upto=None):
    m = F["m5"][t]
    df = pd.DataFrame({"Open": m["o"], "High": m["h"], "Low": m["l"], "Close": m["c"], "Volume": m["v"]}, index=pd.DatetimeIndex(pd.to_datetime(m["ts"], utc=True)))
    if upto:
        df = df[df.index.tz_convert("America/New_York").date <= D(upto)]
    return df


def daily(t):
    d = F["daily"][t]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))


TICKERS = ["SYNA", "VICR", "NKE", "AAPL"]
FR_0110 = {t: m5(t, "2026-10-01") for t in TICKERS}                      # каквото вижда брифът в 07:30 на 02.10 (до 19:55 ET = 01:55 Берлин)
FR_0210 = {t: m5(t) for t in TICKERS}

print("── after-hours гап от 5-минутни барове (РЕАЛНИ) ──")
e = ep.extract_ah(FR_0110["SYNA"])
assert (e["session"], e["prev_close"], e["ah_price"], e["ah_bars"], e["ah_last_et"]) == ("2026-10-01", 106.16, 122.04, 46, "19:55") and e["ah_volume"] == 0.0
print(f"  ✓ SYNA: сесия 01.10, затваряне $106.16 → последен after-hours бар (19:55 ET = 01:55 Берлин) $122.04 = {100 * (e['ah_price'] / e['prev_close'] - 1):+.2f}%; 46 after-hours бара, обем 0 (Yahoo не дава обем)")
rows, diag = ep.scan_after_hours(FR_0110)
assert [r["ticker"] for r in rows] == ["SYNA"] and round(rows[0]["gap_pct"], 2) == 14.96 and diag["session"] == "2026-10-01" and diag["gappers"] == 1 and diag["tickers_with_ah"] == 4
assert diag["zero_volume_share"] == 1.0
print("  ✓ скан към 01.10 (брифът от 02.10): само SYNA ≥ 10%; VICR (+1.9% тази вечер; +9.6% беше на 30.09), NKE (−8.6%, надолу), AAPL — не; обемът в after-hours е нула за всички 4")
rows2, diag2 = ep.scan_after_hours(FR_0210)
assert rows2 == [] and diag2["session"] == "2026-10-02" and diag2["gappers"] == 0
rows3, _ = ep.scan_after_hours(FR_0110, gap_pct=8.0)
assert [r["ticker"] for r in rows3] == ["SYNA"]
noah = FR_0110["SYNA"]
ixn = noah.index.tz_convert("America/New_York")
noah = noah[~((ixn.date == D("2026-10-01")) & (ixn.hour * 60 + ixn.minute >= 960))]                  # без post-market барове на 01.10 → най-новата сесия с after-hours е 30.09 (гап ~0)
rows4, dg4 = ep.scan_after_hours({"SYNA": noah})
assert rows4 == [] and dg4["session"] == "2026-09-30"
few = FR_0110["SYNA"].copy()
ix = few.index.tz_convert("America/New_York")
few = few[~((ix.date == D("2026-10-01")) & (ix.hour * 60 + ix.minute >= 960 + 25))]                    # само 3 post-market бара (16:00, 16:10, 16:15 — Yahoo пропуска бар-ове без сделки) → 122.04 вече го няма
assert ep.extract_ah(few)["ah_bars"] == 3
assert ep.scan_after_hours({"SYNA": few}, min_bars=4)[0] == []
print("  ✓ към 02.10 вечерта няма гапове (макс. +4.4% в целия универс); праг 8% не добавя; без post-market барове — нищо; под 3 after-hours бара — не се брои")
# сесията се определя по мнозинството тикъри
old = FR_0110["NKE"].copy(); old.index = old.index - pd.Timedelta(days=3)
_, dg = ep.scan_after_hours({**FR_0110, "NKE": old})
assert dg["session"] == "2026-10-01" and dg["in_session"] == 3
print("  ✓ сесията е най-честата измежду тикърите — тикър с по-стари данни се изключва")

print()
print("── пренебрегване, ADR и максимален стоп (РЕАЛНИ дневни данни) ──")
rows, _ = ep.scan_after_hours(FR_0110)
en = ep.enrich_gappers(rows, {"SYNA": daily("SYNA")})[0]
d = F["daily"]["SYNA"]; i = d["dates"].index("2026-10-01"); c, h, l, v = (np.array(d[k]) for k in ("c", "h", "l", "v"))
adr = 100 * (np.mean(h[i - 19:i + 1] / l[i - 19:i + 1]) - 1)                                             # НЕЗАВИСИМО: формулата от qullamaggie.com/faq
ret63 = (c[i] / c[i - 63] - 1) * 100
assert abs(en["adr"] - adr) < 1e-9 and abs(en["ret63_pct"] - ret63) < 1e-9 and en["neglect"] is True and en["liquid"] is True and round(en["ret63_pct"], 1) == -11.2 and round(en["adr"], 2) == 4.49
assert en["prev_close"] == 106.15 and round(en["gap_pct"], 2) == 14.97 and en["max_stop"] == round(122.04 * (1 - adr / 100), 2) == 116.56 and en["max_stop_pct"] == 4.5
print(f"  ✓ SYNA: официално затваряне $106.15 → гап +14.97%; ръст за 63 дни −11.2% (≤ +20% → 'пренебрегната'); ADR 4.49%; информативен максимален стоп $116.56 (122.04 − 1×ADR)")
run_up = copy.deepcopy(daily("SYNA")); run_up.iloc[:i - 62, :4] = run_up.iloc[:i - 62, :4].values * 0.7                           # СИНТЕТИЧНО: същата акция, но с по-ниска цена преди 63 бара (ръст ≈ +27%)
en2 = ep.enrich_gappers(rows, {"SYNA": run_up})[0]
assert en2["neglect"] is False and en2["ret63_pct"] > 20
assert ep.enrich_gappers(rows, {})[0]["neglect"] is None
print(f"  ✓ СИНТЕТИЧНО: при ръст {en2['ret63_pct']:.0f}% за 3 месеца → не е 'пренебрегната'; без дневни данни → neglect None (не се показва като пренебрегната)")

print()
print("── заглавия и AI класификация (проверена от кода) ──")
HL = F["headlines"]["SYNA"]
rss = "<rss><channel>" + "".join(f"<item><title>{h['title'].replace('&', '&amp;')}</title><pubDate>{pd.Timestamp(h['published'], tz='UTC').strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for h in HL) + "</channel></rss>"
got = ep.parse_rss(rss)
assert [g["title"] for g in got] == [h["title"] for h in HL] and got[0]["published"] == "2026-10-05 09:11"
got2 = ep.parse_rss(rss, since=dt.datetime(2026, 10, 2, 18, 0))
assert [g["published"] for g in got2] == ["2026-10-05 09:11", "2026-10-03 03:30", "2026-10-02 19:52", "2026-10-02 18:53"] and len(ep.parse_rss(rss, limit=2)) == 2 and ep.parse_rss("не е xml") == []
print("  ✓ РЕАЛНИТЕ заглавия на SYNA (6): разбор, филтър по време, лимит; повреден XML → []")
good = {"ticker": "SYNA", "catalyst": "m_and_a", "summary_bg": "ON Semi предлага изцяло парична оферта за придобиване на Synaptics.", "surprise": "yes"}
v, why = ep.verify_ai_item(good, HL, {"SYNA"})
assert v == {"ticker": "SYNA", "catalyst": "m_and_a", "catalyst_label": ep.CATALYSTS["m_and_a"], "summary_bg": good["summary_bg"], "surprise": "yes"} and why is None
v, why = ep.verify_ai_item({**good, "summary_bg": "Придобиване за $6 млрд. според заглавията."}, HL, {"SYNA"})                       # 6 не е в заглавията (там е 5.7)
assert v["summary_bg"] is None and v["catalyst"] == "m_and_a" and why == "резюмето съдържа число извън заглавията (6)"
v, why = ep.verify_ai_item({**good, "summary_bg": "Скача с 14.1% заради сделка за 5.7 млрд."}, HL, {"SYNA"})                         # 14.1 и 5.7 са дословно в заглавията → минава
assert v["summary_bg"] and why is None
v, _ = ep.verify_ai_item({**good, "catalyst": "превземане", "surprise": "maybe"}, HL, {"SYNA"})
assert v["catalyst"] == "unknown" and v["surprise"] == "unclear"
assert ep.verify_ai_item({**good, "ticker": "ZZZ"}, HL, {"SYNA"}) == (None, "тикър извън заявката") and ep.verify_ai_item("не е речник", HL, {"SYNA"})[0] is None
v, _ = ep.verify_ai_item({**good, "summary_bg": "а" * 300}, HL, {"SYNA"})
assert len(v["summary_bg"]) == 218 and v["summary_bg"].endswith("…")
print("  ✓ проверката: число извън заглавията (6 вместо 5.7) → резюмето се маха, катализаторът остава; 14.1 и 5.7 са дословно в заглавията → минава; непознат катализатор → unknown; чужд тикър → отхвърлен")

calls = []
def fake_ai(system, user):
    calls.append(user)
    items = []
    for r in json.loads(user.split("заглавия от Yahoo Finance): ")[1].split("\n\nКАТАЛИЗАТОРИ")[0]):
        items.append({"ticker": r["ticker"], "catalyst": "earnings_guidance", "summary_bg": "Отчет на компанията.", "surprise": "unclear"})
    return json.dumps({"items": items})
rows7 = [{"ticker": f"T{i}", "headlines": [{"title": "Earnings beat"}]} for i in range(7)] + [{"ticker": "NOHL", "headlines": []}]
res, notes = ep.classify_catalysts(rows7, ai_call=fake_ai)
assert len(calls) == 2 and len(res) == 8 and res["NOHL"]["catalyst"] == "unknown" and res["NOHL"]["summary_bg"] is None and res["T0"]["catalyst"] == "earnings_guidance" and notes == []
assert "SYNA" not in calls[0] and calls[0].count('"headlines"') == 5 and calls[1].count('"headlines"') == 2
print("  ✓ AI на batch-ове: 7 тикъра със заглавия → 2 извиквания (5 + 2); тикър без заглавия — 'unknown' без AI")
res, notes = ep.classify_catalysts(rows7[:2], ai_call=lambda s, u: (_ for _ in ()).throw(RuntimeError("API")))
assert all(res[t]["catalyst"] == "unknown" for t in ("T0", "T1")) and notes == ["AI партида 1 пропадна: RuntimeError", "T0: няма отговор", "T1: няма отговор"]
print("  ✓ провал на AI → 'unknown' за всички в партидата, с бележка; run-ът не пада")

print()
print("── дневник: after-hours гап срещу реалния гап на отварянето ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_ep_")
LOG = pathlib.Path(tmp.name) / "ep_ah_log.json"
log = ep.load_log(LOG)
assert log == {"entries": []}
allrows = ep.enrich_gappers(ep.scan_after_hours(FR_0110, gap_pct=0.05)[0], {t: daily(t) for t in TICKERS})                      # СИНТЕТИЧНО: нисък праг 0.05%, за да влязат и другите (VICR +1.9%, AAPL +0.1%; NKE е надолу)
n = ep.add_entries(log, allrows, "2026-10-02")
assert n == 3 and ep.add_entries(log, allrows, "2026-10-02") == 0                                                               # без дубликати
syna = next(x for x in log["entries"] if x["ticker"] == "SYNA")
assert syna["gap_session"] == "2026-10-02" and syna["ah_gap_pct"] == 14.97 and syna["prev_close"] == 106.15 and syna["open_gap_pct"] is None
assert ep.resolve_entries(log, D("2026-10-02"), lambda ts: {}) == 0                                                              # gap_session още не е минала
nres = ep.resolve_entries(log, D("2026-10-05"), lambda ts: {t: daily(t) for t in ts})
assert nres == 3 and syna["open_gap_pct"] == 14.65 and syna["close_pct"] == 14.08 and syna["high_pct"] == 14.91 and syna["resolved_on"] == "2026-10-05"
s = ep.summarize_log(log["entries"])
assert s["resolved"] == 3 and s["held_at_open"] == 1 and s["held_share_pct"] == 33.0
print(f"  ✓ SYNA: after-hours +14.97% → реално отваряне 02.10 на $121.70 = +14.65% (затваря +14.08%): гапът е издържал; разминаване −0.32 пр.п.")
log["entries"] += [{"ticker": f"X{i}", "ah_gap_pct": 10 + i, "open_gap_pct": 10 + i - (1 if i % 2 else 3), "session": "2026-10-0%d" % (i + 1)} for i in range(5)]       # СИНТЕТИЧНО: още 5 разрешени
s = ep.summarize_log(log["entries"])
assert s["resolved"] == 8 and s["corr"] is not None and s["median_diff_pp"] is not None
ep.save_log(log, LOG)
assert ep.load_log(LOG)["entries"][0]["ticker"] == "SYNA" and ep.load_log(pathlib.Path(tmp.name) / "няма.json") == {"entries": []}
LOG.write_text("{счупен", encoding="utf-8")
assert ep.load_log(LOG) == {"entries": []}
print("  ✓ записът е по (тикър, сесия) без дубликати, разрешава се, щом gap_session мине; обобщение (колко отварят ≥ 10%, медианно разминаване, корелация); счупен/липсващ файл → празен дневник")

print()
print("── цялото наблюдение (РЕАЛНИ данни към 02.10 07:30; подменени теглене и AI) ──")
LOG2 = pathlib.Path(tmp.name) / "log2.json"
ai_calls = []
def ai(system, user):
    ai_calls.append(user)
    return json.dumps({"items": [{"ticker": "SYNA", "catalyst": "m_and_a", "summary_bg": "ON Semi предлага изцяло парична оферта за Synaptics.", "surprise": "yes"}]})
out = ep.run(["SYNA", "VICR", "NKE", "AAPL"], D("2026-10-02"), fetch_5m_fn=lambda u: (FR_0110, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=lambda ts: {t: daily(t) for t in ts},
             headlines_fn=lambda t, since: HL, ai_call=ai, name_lookup=lambda t: "Synaptics Inc", log_path=LOG2)
assert out["ok"] is True and out["session"] == "2026-10-01" and [r["ticker"] for r in out["rows"]] == ["SYNA"] and out["not_neglected"] == []
r = out["rows"][0]
assert (r["company"], r["catalyst"], r["surprise"], r["ah_volume_available"], r["max_stop"], r["neglect"]) == ("Synaptics Inc", "m_and_a", "yes", False, 116.56, True)
assert len(r["headlines"]) == 3 and out["log"]["entries"] == 1 and out["log"]["added_today"] == 1 and out["log"]["resolved"] == 0 and len(ai_calls) == 1
print(f"  ✓ SYNA: after-hours +{r['gap_pct']:.1f}% (затваряне $106.15 → $122.04), ръст за 3 месеца {r['ret63_pct']:.0f}%, ADR {r['adr']:.1f}%, максимален стоп ${r['max_stop']}, катализатор: {r['catalyst_label']}; обем не е наличен; дневникът има 1 запис")
out_b = ep.run(["SYNA"], D("2026-10-05"), fetch_5m_fn=lambda u: (FR_0210, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=lambda ts: {t: daily(t) for t in ts}, headlines_fn=lambda t, s: [], ai_call=ai, log_path=LOG2)
assert out_b["rows"] == [] and out_b["log"]["resolved"] == 1 and out_b["log"]["held_at_open"] == 1 and out_b["log"]["resolved_today"] == 1
print("  ✓ следващият бриф (05.10): дневникът разрешава записа на SYNA срещу реалното отваряне (+14.65%) — 'издържал гап': 1 от 1")
down = {t: m5(t) for t in TICKERS}
down2 = copy.deepcopy(run_up)
out_c = ep.run(["SYNA"], D("2026-10-02"), fetch_5m_fn=lambda u: (FR_0110, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=lambda ts: {"SYNA": down2}, headlines_fn=lambda t, s: HL, ai_call=ai,
               log_path=pathlib.Path(tmp.name) / "log3.json")
assert out_c["rows"] == [] and out_c["not_neglected"][0]["ticker"] == "SYNA" and out_c["not_neglected"][0]["why"].startswith("ръст ") and "> 20%" in out_c["not_neglected"][0]["why"]
print(f"  ✓ СИНТЕТИЧНО: същата акция с ръст {out_c['not_neglected'][0]['ret63_pct']:.0f}% за 3 месеца → не се показва, но се споменава ('{out_c['not_neglected'][0]['why']}') и се логва")
out_d = ep.run(["A"], D("2026-10-02"), fetch_5m_fn=lambda u: (_ for _ in ()).throw(RuntimeError("Yahoo")), log_path=pathlib.Path(tmp.name) / "log4.json")
assert out_d["ok"] is False and out_d["rows"] == [] and "RuntimeError" in out_d["notes"][0]
out_e = ep.run(["A"], D("2026-10-02"), fetch_5m_fn=lambda u: ({}, {"batches": 3, "batches_failed": 3}), log_path=pathlib.Path(tmp.name) / "log5.json")
assert out_e["ok"] is False and out_e["rows"] == []
print("  ✓ провал на теглене → ok=False с причина (run-ът не пада); всички партиди неуспешни → ok=False")
print()
print("── банер и свързване в main.run ──")
from src import data_warnings
assert data_warnings.collect(None, None, qm_ep=None) == [] and data_warnings.collect(None, None, qm_ep={"ok": True, "diag": {"batches": 10, "batches_failed": 0}}) == []
w = data_warnings.collect(None, None, qm_ep={"ok": False, "notes": ["RuntimeError: Yahoo"], "diag": {}})
assert w == [{"source": "qm_ep", "level": "warn", "message": "EP наблюдение (after-hours): не се изпълни (RuntimeError: Yahoo) — празният списък НЕ значи, че няма гапове след затваряне."}]
w = data_warnings.collect(None, None, qm_ep={"ok": True, "diag": {"batches": 10, "batches_failed": 2}})
assert "2 от 10 партиди" in w[0]["message"]
import ast
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
epc = [n for n in ast.walk(run_fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run" and getattr(n.func.value, "id", "") == "qm_ep"]
assert len(epc) == 1 and ast.unparse(epc[0].args[0]) == "qm_universe" and any(k.arg == "name_lookup" for k in epc[0].keywords)
keys = [k.value for n in ast.walk(run_fn) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
assert "qm_ep" in keys
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "qm_breakout.scan(universe=qm_universe)" in src and src.count("screener.build_universe()") == 1 and "qm_ep=qm_ep_out" in src
print("  ✓ провал на after-hours тегленето → банер ('празният списък НЕ значи, че няма гапове'); run(): ЕДИН универс за скенера и за EP, EP се вика с име на компания, brief има 'qm_ep'")
print()
print("Всички тестове минаха.")
