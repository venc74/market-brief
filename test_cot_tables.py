"""
Пакет 3 · т.в (2026-10-05): директната COT теза идва от фиксирана таблица в config.py (пазар → директни тикъри със страна на
експозицията и mechanism_type), ефектът (печели/губи) се изчислява от кода по таблицата за знака; AI пише само cross-sector тезите.

РЕАЛНО: (1) пазарите от cot.MAJOR_MARKETS; (2) проверка през Yahoo от 05.10.2026 на всеки тикър от таблицата — последен търгуван
ден, тип, име, категория (tests/fixtures/cot_direct_tickers_2026-10-05.json; FXM, JO, NIB, BAL, COW, CTRA са делистнати/несъществуващи и ги
няма в таблицата); (3) брифът от 02.10.2026 (18 COT екстремума с реалните посоки, реалните AI директни и cross теми от стария формат).
СИНТЕТИЧНО: подменените _call_claude и _verified_company_name (имена от реалната проверка), граничните знаци, невалидни записи,
пазар без AI отговор. Таблицата е ПРЕДЛОЖЕНИЕ за преглед от потребителя — тестът проверява вътрешната ѝ съгласуваност, не че изборът е верен.
Пускане: python test_cot_tables.py
"""
import sys, json, pathlib, io, contextlib, tempfile as _tf
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import cot, cot_theses as ct, ai_brief

_CACHE_DIR = _tf.TemporaryDirectory(prefix="mb_cotcache_")
_cache_n = [0]
def fresh_cache():
    """нов (празен) файл за кеша на тезите във временна директория — реалният data/cot_theses_cache.json не се пипа"""
    _cache_n[0] += 1
    return pathlib.Path(_CACHE_DIR.name) / f"cache_{_cache_n[0]}.json"


FIX = ROOT / "tests" / "fixtures"
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
BRIEF = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
LABELS = [e[0] for e in cot.MAJOR_MARKETS]

print("── таблиците покриват всичките 40 пазара и са вътрешно съгласувани ──")
assert set(config.COT_MARKET_KINDS) == set(LABELS) == set(config.COT_DIRECT_TICKERS) and len(LABELS) == 40
KINDS = {"equity_index", "volatility", "fx_foreign", "fx_usd", "rate", "crypto", "commodity"}
assert set(config.COT_MARKET_KINDS.values()) <= KINDS
n_entries = 0
for m, spec in config.COT_DIRECT_TICKERS.items():
    kind, ts = config.COT_MARKET_KINDS[m], spec["tickers"]
    assert len(ts) <= 4 and len({e["ticker"] for e in ts}) == len(ts), m
    if not ts:
        assert spec.get("empty_reason"), m                                              # празен запис → причина
    for e in ts:
        n_entries += 1
        assert e["side"] in ("long", "short") and isinstance(e["partial"], bool), (m, e)
        sign = ct.entry_sign(e, kind)
        assert sign in (1, -1), (m, e)                                                  # типът важи за вида на пазара
        assert (sign == 1) == (e["side"] == "long"), (m, e)                             # знакът на типа съвпада със side
        assert e["mechanism_type"] in config.COT_DIRECT_ONLY_TYPES or e["mechanism_type"] in config.COT_MECHANISM_SIGN, (m, e)
tickers = sorted({e["ticker"] for s in config.COT_DIRECT_TICKERS.values() for e in s["tickers"]})
assert n_entries == 65 and len(tickers) == 62
empty = [m for m, s in config.COT_DIRECT_TICKERS.items() if not s["tickers"]]
assert empty == ["Mexican Peso", "Soybean Oil", "Soybean Meal", "Coffee C", "Cocoa", "Cotton", "Live Cattle"]
# правилото на потребителя (05.10): само притежатели/производители (L) или обратни продукти (S) — никакви купувачи/преработватели/потребители
for m, spec in config.COT_DIRECT_TICKERS.items():
    for e in spec["tickers"]:
        assert (e["side"], e["mechanism_type"]) in config.COT_DIRECT_ALLOWED, (m, e)
        assert e["mechanism_type"] not in ("input_cost", "consumer_wallet", "substitute"), (m, e)
removed = {t for t in ("TSN", "BG", "ADM") if t in tickers}
assert not removed, removed                                                                  # TSN (Live Cattle) и BG/ADM (Soybean Oil/Meal) вече не са директни
assert all("cross" in config.COT_DIRECT_TICKERS[m]["empty_reason"] for m in ("Soybean Oil", "Soybean Meal", "Live Cattle"))
partial = sorted({(m, e["ticker"]) for m, s in config.COT_DIRECT_TICKERS.items() for e in s["tickers"] if e["partial"]})
assert partial == [("Heating Oil", "MPC"), ("Heating Oil", "VLO"), ("Lean Hogs", "SFD"), ("Palladium", "SBSW"), ("Platinum", "SBSW"), ("RBOB Gasoline", "MPC"), ("RBOB Gasoline", "VLO")]
print(f"  ✓ {len(LABELS)} пазара с вид и запис; {n_entries} реда, {len(tickers)} различни тикъра; 7 пазара са празни с причина: {empty};")
print("    знакът на типа съвпада със страната на експозицията във всеки ред; 0–4 тикъра на пазар")
print("  ✓ правилото на потребителя: всеки ред е (long, tracks_instrument | output_price) или (short, tracks_instrument); TSN, BG, ADM ги няма; VLO/MPC (p) остават")

print()
print("── РЕАЛНА проверка през Yahoo (05.10.2026) ──")
dead = [t for t, r in CHK.items() if not r["last"]]
assert sorted(dead) == ["BAL", "COW", "CTRA", "FXM", "JO", "NIB"]
assert not set(dead) & set(tickers)                                                        # делистнатите не са в таблицата
for t in tickers:
    assert CHK[t]["last"] >= "2026-10-01" and CHK[t]["name"], t                              # всички търгуват и имат име
mism = []
for m, spec in config.COT_DIRECT_TICKERS.items():
    for e in spec["tickers"]:
        r = CHK[e["ticker"]]
        lookup = {"name": r["name"], "verified": True, "quote_type": r["quote_type"], "category": r["category"], "long_name": r["name"], "sector": None, "industry": None}
        if ai_brief._is_mismatched_commodity_etf(lookup, m):
            mism.append((m, e["ticker"]))
assert not mism, mism                                                                       # нито един commodity ETF не е за друга суровина
print("  ✓ и 65-те тикъра търгуват (последен ден ≥ 01.10.2026) и имат име; 6-те делистнати (FXM, JO, NIB, BAL, COW, CTRA) ги няма;")
print("    нито един commodity ETF от таблицата не е 'за друга суровина' по съществуващата проверка (_is_mismatched_commodity_etf)")

print()
print("── таблицата за знака ──")
assert list(config.COT_MECHANISM_SIGN) == ["input_cost", "output_price", "fx_revenue_translation", "fx_cost_local", "rate_asset_yield",
                                           "rate_duration_valuation", "index_beta", "risk_off_hedge", "substitute", "consumer_wallet", "other"]
assert [t for t, s in config.COT_MECHANISM_SIGN.items() if not s["direct"]] == ["index_beta", "risk_off_hedge", "consumer_wallet", "other"]
assert "tracks_instrument" not in config.COT_MECHANISM_SIGN and config.COT_DIRECT_ONLY_TYPES == {"tracks_instrument"}
assert config.COT_MECHANISM_SIGN["other"]["sign"] == {}                                     # "other" няма посока
# (тип, вид) → знак при цена↑; при цена↓ е обратното
S = ct.mechanism_sign
assert (S("input_cost", "commodity"), S("output_price", "commodity"), S("substitute", "commodity"), S("consumer_wallet", "commodity")) == (-1, 1, 1, -1)
assert (S("fx_revenue_translation", "fx_foreign"), S("fx_revenue_translation", "fx_usd"), S("fx_cost_local", "fx_foreign"), S("fx_cost_local", "fx_usd")) == (1, -1, -1, 1)
assert (S("rate_asset_yield", "rate"), S("rate_duration_valuation", "rate")) == (-1, 1)
assert (S("index_beta", "equity_index"), S("index_beta", "volatility"), S("risk_off_hedge", "equity_index"), S("risk_off_hedge", "volatility")) == (1, -1, -1, 1)
assert S("input_cost", "rate") is None and S("rate_asset_yield", "commodity") is None and S("other", "commodity") is None and S("измислен", "commodity") is None
assert ct.effect_from_sign(-1, "down") == "gains" and ct.effect_from_sign(-1, "up") == "loses" and ct.effect_from_sign(1, "down") == "loses" and ct.effect_from_sign(1, "up") == "gains"
print("  ✓ 10 типа + 'other' в реда от заявката; типове 7, 8, 10 и 'other' не са пряк механизъм; знаците по вид на пазара;")
print("    тип, който не важи за вида на пазара (input_cost за облигации, rate_* за стока), и 'other' нямат знак")

print()
print("── директната теза за РЕАЛНИТЕ екстремуми от 02.10 ──")
ROWS = {c["market"]: c for c in BRIEF["cot"]}
def move_of(row):
    return ai_brief._instrument_move(row)
def eff(row, ticker):
    th = ct.direct_thesis(row["market"], move_of(row))
    return {t["ticker"]: t["effect"] for t in th["tickers"]}[ticker]
assert (ROWS["30-Year Treasury Bond"]["direction"], ROWS["Cocoa"]["direction"], ROWS["Copper"]["direction"]) == ("extreme_long", "extreme_short", "extreme_long")
bond = ct.direct_thesis("30-Year Treasury Bond", move_of(ROWS["30-Year Treasury Bond"]))
assert [(t["ticker"], t["effect"]) for t in bond["tickers"]] == [("TLT", "loses"), ("VGLT", "loses"), ("TBF", "gains")]      # цена↓: дългите ETF губят, инверсният печели
assert "цената на 30-Year Treasury Bond НАДОЛУ (= доходността нагоре)" in bond["reasoning"] and "TBF печели (обратен (−1×)" in bond["reasoning"]
cu = ct.direct_thesis("Copper", move_of(ROWS["Copper"]))
assert {t["ticker"]: t["effect"] for t in cu["tickers"]} == {"CPER": "loses", "FCX": "loses", "SCCO": "loses"}
rb = ct.direct_thesis("RBOB Gasoline", move_of(ROWS["RBOB Gasoline"]))
assert {t["ticker"]: (t["effect"], t["partial"]) for t in rb["tickers"]} == {"UGA": ("loses", False), "VLO": ("loses", True), "MPC": ("loses", True)}
assert "частична експозиция" in rb["reasoning"]
ru = ct.direct_thesis("E-mini Russell 2000", move_of(ROWS["E-mini Russell 2000"]))                                   # extreme_short → цена↑
assert {t["ticker"]: t["effect"] for t in ru["tickers"]} == {"IWM": "gains", "VTWO": "gains"}
cocoa = ct.direct_thesis("Cocoa", move_of(ROWS["Cocoa"]))
assert cocoa["tickers"] == [] and cocoa["no_direct_link"] and "NIB е делистнат" in cocoa["empty_reason"]
assert ct.direct_thesis("Mexican Peso", move_of(ROWS["Mexican Peso"]))["empty_reason"].startswith("няма листнат американски продукт")
unknown = ct.direct_thesis("Измислен пазар", move_of(ROWS["Copper"]))
assert unknown["tickers"] == [] and "няма запис в таблицата" in unknown["empty_reason"]
print("  ✓ 30Y (extreme_long → цена↓): TLT и VGLT губят, инверсният TBF печели; Copper: CPER/FCX/SCCO губят; RBOB: UGA губи, VLO/MPC губят (частична);")
print("    Russell (extreme_short → цена↑): IWM и VTWO печелят; Cocoa и Mexican Peso — празен запис с причина от таблицата")
agree = dis = 0
for c in BRIEF["cot"]:
    old = {t["ticker"]: t.get("effect") for t in (c.get("direct_thesis") or {}).get("tickers") or []}
    for tk, e_old in old.items():
        tab = {t["ticker"]: t["effect"] for t in ct.direct_thesis(c["market"], move_of(c))["tickers"]}
        if tk in tab:
            agree += tab[tk] == e_old; dis += tab[tk] != e_old
assert (agree, dis) == (7, 0)
print("  ✓ РЕАЛНО сравнение със стария AI: 7 общи (пазар, тикър) двойки от 02.10 — 7 със същия ефект, 0 с обратен")

print()
print("── през ai_brief.cot_theses: директната е от таблицата, AI връща само cross (СИНТЕТИЧЕН отговор в новия формат) ──")
ANS = json.loads((FIX / "cot_model_answers_2026-10-02.json").read_text(encoding="utf-8"))["markets"]       # реални (пазар, тикър) двойки от 02.10; типове/quote от теста
company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for c in BRIEF["cot"]:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            company.setdefault(t["ticker"], t["company"])
def fake_lookup(t):
    r = CHK.get(t)
    return {"name": company.get(t, t), "verified": t in company, "quote_type": (r or {}).get("quote_type"), "category": (r or {}).get("category"),
            "long_name": company.get(t), "sector": None, "industry": None}
ai_brief._verified_company_name = fake_lookup
config.COT_BATCH_SIZE = 100                                                               # един batch → едно извикване
EXTREMES = [{k: c[k] for k in ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")} for c in BRIEF["cot"]]
seen = {}
def fake_claude(system, user, max_tokens=0):
    seen["user"] = user
    rows = [{"market": m, "tickers": [dict(t, ticker=t["ticker"]) for t in v] + seen.get("extra", {}).get(m, [])} for m, v in ANS.items() if m not in seen.get("skip", ())]
    return json.dumps({"theses": rows}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
with contextlib.redirect_stdout(io.StringIO()):
    out = ai_brief.cot_theses(EXTREMES, [], None, cache_path=fresh_cache())
by = {c["market"]: c for c in out}
assert len(out) == 18
u = seen["user"]
assert '"direct_tickers"' in u and "TLT" in u and "direct_thesis" not in u        # промптът не иска директна теза
assert "НЕ тикъри от" in u and "direct_tickers" in u
cocoa_out = by["Cocoa"]["direct_thesis"]
assert cocoa_out["tickers"] == [] and "NIB е делистнат" in cocoa_out["empty_reason"]               # директната идва от таблицата (празен запис)
tlt = {t["ticker"]: (t["effect"], t["company"]) for t in by["30-Year Treasury Bond"]["direct_thesis"]["tickers"]}
assert tlt["TLT"][0] == "loses" and tlt["TBF"][0] == "gains" and "20+ Year" in tlt["TLT"][1]
assert by["30-Year Treasury Bond"]["direct_thesis"]["reasoning"].startswith("Фиксирана таблица с директни тикъри (не е AI).")
cross30 = by["30-Year Treasury Bond"]["cross_sector_thesis"]["tickers"]
assert [(t["ticker"], t["effect"]) for t in cross30] == [("JPM", "gains")]                          # rate_asset_yield, цена↓ → доходност↑ → печели
print("  ✓ промптът носи direct_tickers (с TLT) и не иска директна теза; Cocoa: директната е празен запис от таблицата с причина;")
print("    30Y: TLT губи, TBF печели (таблица), cross JPM печели (механизъм rate_asset_yield) — 18 пазара в изхода")

seen["extra"] = {"Corn": [{"ticker": "CORN", "company": "Teucrium Corn Fund", "mechanisms": [{"type": "output_price", "quote": "фонд върху фючърси на царевица"}]}]}   # моделът повтаря директен тикър
with contextlib.redirect_stdout(io.StringIO()):
    out_dup = ai_brief.cot_theses(EXTREMES, [], None, cache_path=fresh_cache())
corn_cross = {c["market"]: c for c in out_dup}["Corn"]["cross_sector_thesis"]["tickers"]
assert [t["ticker"] for t in corn_cross] == ["TSN", "PPC"]                                         # CORN е директен по таблицата → махнат от cross
seen["extra"] = {}
seen["skip"] = {"Wheat"}                                                                          # моделът не връща нищо за Wheat
with contextlib.redirect_stdout(io.StringIO()):
    out2 = ai_brief.cot_theses(EXTREMES, [], None, cache_path=fresh_cache())
w = {c["market"]: c for c in out2}["Wheat"]
assert [t["ticker"] for t in w["direct_thesis"]["tickers"]] == ["WEAT"] and w["direct_thesis"]["tickers"][0]["effect"] == "loses"
assert not w["cross_sector_thesis"]["tickers"] and w["cross_sector_thesis"]["empty_reason"] == "моделът не върна пазара, следващият run опитва пак"
print("  ✓ повтореният директен тикър (CORN) се маха от cross; пазар без AI отговор (Wheat) пак се показва с директния WEAT (губи) и празен cross с причина")
print()
print("Всички тестове минаха.")
