"""
Тези · гейт G4 и подгрупи с собствен ориентир (08.10.2026, точка 2в). Реален дефект на 07.10: "Black Hills plans $1.8 billion investment to power Google's data center" (газова централа; BKH не е в тезата)
беше маркирано като ПОТВЪРЖДЕНИЕ на ядрената теза — през chain_step: проверява се само дословният цитат от веригата ("AI data center-ите гладуват за стабилна базова мощност"), а тази стъпка е изпълнена и от газова
централа.
  • G4: за confirmed/challenged моделът връща и ДОСЛОВНОТО заглавие (headline_quote); кодът изисква то да е част от днешните новини и цялото заглавие да съдържа тикър, име на компания от тезата или термин на механизма
    ѝ (config.THESIS_BASKETS "names"/"terms");
  • подгрупи в THESIS_BASKETS (ядрена: уран/добив срещу оператори/реактори) със СОБСТВЕН ориентир, таблица и обобщение в каре "Контекст".

РЕАЛНО: tests/fixtures/thesis_markings_2026-10-08.json — всички 14 приети маркирания confirmed/challenged от 21.09 до 08.10 с бележката на модела (цитира заглавията) и ротацията на 08.10 за URA, XLU, XLF.
СИНТЕТИЧНО (маркирано): структурните полета на модела (basis, chain_quote, affected_tickers … — в брифа се пазят само приетите маркирания, не и отговорът), цените за таблиците, празните конфигурации.
Пускане: python test_thesis_g4.py
"""
import sys, json, pathlib, re, copy, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import tempfile
import config
from src import ai_brief, thesis_context, render

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_g4_"))
config.DOCS_DIR, config.DATA_DIR = _tmp / "docs", _tmp / "data"                    # render_dashboard пише docs/index.html — не в проекта
config.DOCS_DIR.mkdir()
config.DATA_DIR.mkdir()

FX = json.loads((ROOT / "tests" / "fixtures" / "thesis_markings_2026-10-08.json").read_text(encoding="utf-8"))
BASKETS = {b["name"]: b for b in config.THESIS_BASKETS}
NUC = BASKETS["Ядрена енергия"]
BKH = "Black Hills plans $1.8 billion investment to power Google's data center"
CEG = "Google, Constellation near deal for nuclear power"

print("── 1. котвите в конфига ──")
for name, b in BASKETS.items():
    assert b.get("names") and b.get("terms"), name
for g in NUC["groups"]:
    assert set(g["tickers"]) <= set(NUC["tickers"]) and g["sector_etf"] in config.SECTOR_ETFS, g
assert sorted(t for g in NUC["groups"] for t in g["tickers"]) == sorted(NUC["tickers"])
print(f"  ✓ всички {len(BASKETS)} тези имат names и terms; подгрупите на ядрената покриват точно нейните тикъри, всяка с ETF от SECTOR_ETFS: " + "; ".join(f"{g['name']} → {g['sector_etf']}" for g in NUC["groups"]))
am = ai_brief._anchor_match
assert am(NUC, BKH) is None and am(NUC, CEG) == "Constellation" and am(NUC, "Cameco signs uranium supply deal") == "Cameco" and am(NUC, "Vistra shares jump") == "Vistra"
assert am(NUC, "OKLO announces reactor site") == "OKLO" and am(NUC, "Oklahoma data center").__class__ is type(None)       # тикър само като цяла дума; "Oklahoma" не е "Oklo"
assert am(BASKETS["Финанси при стръмна крива"], "Treasury yields climb") == "yield*" or am(BASKETS["Финанси при стръмна крива"], "Treasury yields climb") == "treasur*"
assert am(BASKETS["Полупроводници и AI инфраструктура"], "AI spending boom") == "ai" and am(BASKETS["Полупроводници и AI инфраструктура"], "Said it was a fair deal") is None   # "ai" е цяла дума, не част от "said"/"fair"
print("  ✓ _anchor_match: тикър (цяла дума, главни букви), име на компания, термин ('*' = наставки); 'Oklahoma' не е Oklo, 'said' не е 'ai'; BKH няма котва")

print()
print("── 2. фалшиви положителни: РЕАЛНИТЕ 14 приети маркирания confirmed/challenged ──")
quoted = re.compile(r"""["“„'‘]([^"”“„'’]{12,200})["”“'’]""")
res = []
for m in FX["markings"]:
    heads = [h for h in quoted.findall(m["note"] or "") if " " in h]
    ok = any(am(BASKETS[m["thesis"]], h) for h in heads)
    res.append((m["date"], m["thesis"], m["status"], ok, heads))
bad = [(d, t, h) for d, t, s, ok, h in res if not ok]
assert len(res) == 14 and [(d, t) for d, t, _ in bad] == [("2026-10-07", "Ядрена енергия")], bad
assert all(BKH.startswith(h[:40]) or "Black Hills" in h for h in bad[0][2][:1])
print(f"  ✓ от 14 реални маркирания G4 отхвърля точно едно — това от 07.10 (ядрена, BKH + «Robust AI spending…»); останалите 13 имат поне едно цитирано заглавие с котва на тезата (0 фалшиви положителни)")

print()
print("── 3. _news_gate с headline_quote (СИНТЕТИЧНИ структурни полета, РЕАЛНИ заглавия) ──")
nuc_thesis = {"name": "Ядрена енергия", "tickers": NUC["tickers"], "chain": NUC["chain"], "status": "structural"}
HEADS = [BKH, CEG, "Oil rises as concerns over Houthi attacks on Saudi Arabia eclipse supply recovery"]
base = {"basis": "chain_step", "event_type": "contract", "affected_tickers": ["VST", "CEG"], "effect": "positive", "subject_ticker": None,
        "chain_quote": "AI data center-ите гладуват за стабилна базова мощност 24/7"}
g = lambda **kw: ai_brief._news_gate(nuc_thesis, {**base, **kw}, "confirmed", HEADS)
assert ai_brief._news_gate(nuc_thesis, base, "confirmed") == (None, "")                                                    # без заглавия (старият подпис) — G4 не работи
r, why = g(headline_quote=BKH)
assert r == "G4" and "Black Hills" in why and "няма тикър, име на компания или термин на механизма" in why
assert g(headline_quote=CEG) == (None, "")
assert g(headline_quote="Google, Constellation near deal")[0] is None                                                      # частичен дословен цитат
assert g(headline_quote=None)[0] == "G4" and g(headline_quote="кратко")[0] == "G4"
r, why = g(headline_quote="Google and Vistra near a nuclear deal")
assert r == "G4" and "дословно" in why
tk_event = {"basis": "ticker_event", "event_type": "contract", "subject_ticker": "CEG", "affected_tickers": ["CEG"], "effect": "positive"}
assert ai_brief._news_gate(nuc_thesis, {**tk_event, "headline_quote": CEG}, "confirmed", HEADS) == (None, "")
assert ai_brief._news_gate(nuc_thesis, {**tk_event, "headline_quote": BKH}, "confirmed", HEADS)[0] == "G4"
assert ai_brief._news_gate({"name": "Нова теза без котви", "tickers": ["AAA"], "chain": "x y z", "status": "watch"}, {**tk_event, "subject_ticker": "AAA", "affected_tickers": ["AAA"], "headline_quote": BKH}, "confirmed", HEADS) == (None, "")
print("  ✓ BKH → G4 («няма тикър, име на компания или термин на механизма»); Constellation → приет (и частичен дословен цитат); без/кратко/недословно заглавие → G4; ticker_event също минава през G4; теза без котви в конфига — само проверката на цитата")

print()
print("── 4. през thesis_reality_check (подменен модел, РЕАЛНИ заглавия) ──")
news = [{"headline": h, "why": "x"} for h in HEADS]
answer = {"checks": [
    {"name": "Ядрена енергия", "news_status": "confirmed", "note": f"„{BKH}“ показва търсене на базова мощност за AI.", "basis": "chain_step", "subject_ticker": None,
     "affected_tickers": ["VST", "CEG"], "effect": "positive", "chain_quote": "AI data center-ите гладуват за стабилна базова мощност 24/7", "headline_quote": BKH, "event_type": "contract"}]}
seen = {}
ai_brief._call_claude = lambda system, user, **k: (seen.setdefault("user", user), json.dumps(answer, ensure_ascii=False))[1]
th = [{"name": n, "chain": b["chain"], "tickers": b["tickers"], "status": b["default_status"]} for n, b in BASKETS.items()]
with contextlib.redirect_stdout(io.StringIO()):
    out = ai_brief.thesis_reality_check(copy.deepcopy(th), news)
nuc = next(t for t in out if t["name"] == "Ядрена енергия")
assert "news_status" not in nuc
rej = ai_brief.THESIS_CHECK_DIAG["rejected"]
assert [(r["thesis"], r["rule"], r["headline_quote"]) for r in rej] == [("Ядрена енергия", "G4", BKH)] and "accepted" not in ai_brief.THESIS_CHECK_DIAG
assert '"headline_quote"' in seen["user"] and "газова централа за data center" in seen["user"]
answer["checks"][0].update(headline_quote=CEG, note=f"„{CEG}“ — стъпка от веригата.")
with contextlib.redirect_stdout(io.StringIO()):
    out2 = ai_brief.thesis_reality_check(copy.deepcopy(th), news)
assert next(t for t in out2 if t["name"] == "Ядрена енергия")["news_status"] == "confirmed" and ai_brief.THESIS_CHECK_DIAG["accepted"] == [{"thesis": "Ядрена енергия", "status": "confirmed"}]
print("  ✓ СИНТЕТИЧЕН отговор на модела с РЕАЛНОТО заглавие на BKH → отхвърлен (G4, с цитираното заглавие в диагностиката, без news_status); с заглавието за Constellation → приет")

print()
print("── 5. подгрупи в каре «Контекст» (РЕАЛНА ротация на 08.10, СИНТЕТИЧНИ цени) ──")
import pandas as pd, numpy as np
idx = pd.bdate_range(end="2026-10-07", periods=260)
def series(drift):                                                            # СИНТЕТИЧНА серия: drift = дневен ръст
    return pd.Series(100 * np.exp(drift * np.arange(len(idx))), index=idx)
CL = {"CCJ": series(-0.0008), "DNN": series(-0.0006), "VST": series(0.0015), "CEG": series(0.0012), "OKLO": series(0.0010), "NNE": series(0.0004)}
thesis_context._closes = lambda tickers: {t: CL[t] for t in tickers if t in CL}
thesis_context._next_earnings = lambda sym, today: None
t_in = [{"name": "Ядрена енергия", "tickers": NUC["tickers"], "status": "structural", "news_status": "confirmed", "chain": NUC["chain"]}]
with contextlib.redirect_stdout(io.StringIO()):
    outc = thesis_context.annotate(t_in, FX["rotation_2026_10_08"], "Defensive", set(), set(), set(), dt.date(2026, 10, 8))
ctx = outc[0]["context"]
assert [g["name"] for g in ctx["groups"]] == ["Уран и добив", "Оператори и реактори"]
g1, g2 = ctx["groups"]
assert [r["ticker"] for r in g1["rows"]] == ["CCJ", "DNN"] and [r["ticker"] for r in g2["rows"]] == ["VST", "CEG", "OKLO", "NNE"]
assert g1["sector"]["etf"] == "URA" and g2["sector"]["etf"] == "XLU" and g2["sector"]["label"] == "прокси: комунални услуги"
rot = {r["etf"]: r for r in FX["rotation_2026_10_08"]}
assert g1["sector"]["rs_4w"] == rot["URA"]["rs_chg_4w_pct"] and g2["sector"]["rs_4w"] == rot["XLU"]["rs_chg_4w_pct"] and g1["sector"]["rs_4w"] != g2["sector"]["rs_4w"]
assert g1["summary"].startswith("2/2 под 200DMA") and g2["summary"].startswith("0/4 под 200DMA")
assert ctx["price_diverges"] is True and ctx["rows"] and len(ctx["rows"]) == 6 and ctx["sector"]["etf"] == "URA"           # урановата група е под 200DMA → предупреждението за цената
print(f"  ✓ две групи със собствен ориентир: «{g1['name']}» (URA, RS 4с {g1['sector']['rs_4w']}) и «{g2['name']}» (XLU, RS 4с {g2['sector']['rs_4w']}); обобщенията са по група: «{g1['summary']}» / «{g2['summary']}»")
t_one = [{"name": "Финанси при стръмна крива", "tickers": ["JPM", "BAC"], "status": "active", "chain": "x"}]
CL.update({"JPM": series(0.001), "BAC": series(0.0005)})
with contextlib.redirect_stdout(io.StringIO()):
    one = thesis_context.annotate(t_one, FX["rotation_2026_10_08"], "Defensive", set(), set(), set(), dt.date(2026, 10, 8))
assert "groups" not in one[0]["context"] and one[0]["context"]["sector"]["etf"] == "XLF"
print("  ✓ теза без подгрупи (Финанси) — каре като преди, без groups")
html = render.render_dashboard({**json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8")), "theses": outc + one})
assert html.count('class="ctx-group"') == 2 and "Уран и добив" in html and "Оператори и реактори" in html and "Сектор URA" in html and "Сектор XLU (прокси: комунални услуги)" in html
assert html.count("Сектор XLF") == 1
print("  ✓ страницата (РЕАЛНИЯТ бриф от 05.10 със СИНТЕТИЧНИ context-и): две групи в ядрената с по свой «Сектор URA» / «Сектор XLU (прокси: комунални услуги)»; Финанси с един «Сектор XLF»")
print("\n✅ test_thesis_g4: всичко мина")
