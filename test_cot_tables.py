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
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import cot, cot_theses as ct, ai_brief

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
assert n_entries == 70 and len(tickers) == 65
empty = [m for m, s in config.COT_DIRECT_TICKERS.items() if not s["tickers"]]
assert empty == ["Mexican Peso", "Coffee C", "Cocoa", "Cotton"]
print(f"  ✓ {len(LABELS)} пазара с вид и запис; {n_entries} реда, {len(tickers)} различни тикъра; 4 пазара са празни с причина: {empty};")
print("    знакът на типа съвпада със страната на експозицията във всеки ред; 0–4 тикъра на пазар")

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
print("── през ai_brief.cot_theses: директната е от таблицата, AI връща само cross (РЕАЛНИ cross отговори от 02.10) ──")
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
    rows = []
    for c in BRIEF["cot"]:
        if c["market"] in seen.get("skip", ()):
            continue
        move = "up" if c["direction"] == "extreme_short" else "down"
        if c["market"] in seen.get("wrong_move", ()):
            move = "down" if move == "up" else "up"
        rows.append({"market": c["market"], "assumed_move": move,
                     "direct_thesis": c.get("direct_thesis"),                              # РЕАЛНАТА стара AI директна теза — трябва да се игнорира
                     "cross_sector_thesis": c.get("cross_sector_thesis")})
    return json.dumps({"theses": rows}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
with contextlib.redirect_stdout(io.StringIO()):
    out = ai_brief.cot_theses(EXTREMES, [], None)
by = {c["market"]: c for c in out}
assert len(out) == 18
u = seen["user"]
assert '"direct_tickers"' in u and "TLT" in u and "САМО cross-sector" in u and "Не пиши думите bullish/bearish" in u
assert '"direct_thesis"' not in u and "direct_thesis" not in u                             # промптът не иска директна теза
cocoa_out = by["Cocoa"]["direct_thesis"]
assert cocoa_out["tickers"] == [] and "NIB е делистнат" in cocoa_out["empty_reason"]                # AI директните HSY/MDLZ не влизат
real_cocoa_cross = [t["ticker"] for t in BRIEF["cot"][[c["market"] for c in BRIEF["cot"]].index("Cocoa")]["cross_sector_thesis"]["tickers"]]
assert [t["ticker"] for t in by["Cocoa"]["cross_sector_thesis"]["tickers"]] == real_cocoa_cross       # cross-ът е реалният от 02.10, без промяна (няма директни по таблицата)
tlt = {t["ticker"]: (t["effect"], t["company"]) for t in by["30-Year Treasury Bond"]["direct_thesis"]["tickers"]}
assert tlt["TLT"][0] == "loses" and tlt["TBF"][0] == "gains" and "20+ Year" in tlt["TLT"][1]
assert by["30-Year Treasury Bond"]["direct_thesis"]["reasoning"].startswith("Фиксирана таблица с директни тикъри (не е AI).")
# cross: тикърите, които са директни по таблицата, се махат
real_cross = {c["market"]: [t["ticker"] for t in (c.get("cross_sector_thesis") or {}).get("tickers") or []] for c in BRIEF["cot"]}
for m, c in by.items():
    got = [t["ticker"] for t in (c["cross_sector_thesis"] or {}).get("tickers") or []]
    direct = {t["ticker"] for t in config.COT_DIRECT_TICKERS[m]["tickers"]}
    assert not set(got) & direct, (m, got)
    assert set(got) <= set(real_cross[m]), (m, got, real_cross[m])
print("  ✓ промптът носи direct_tickers и 'САМО cross-sector' (без инструкция за директна теза); 18 пазара в изхода; реалните стари AI директни")
print("    (Cocoa: HSY/MDLZ) се игнорират — директната е от таблицата; TLT губи, TBF печели, имената са от проверката; cross няма директни тикъри")

seen["skip"] = {"Wheat"}                                                                    # моделът не връща нищо за Wheat
with contextlib.redirect_stdout(io.StringIO()):
    out2 = ai_brief.cot_theses(EXTREMES, [], None)
w = {c["market"]: c for c in out2}["Wheat"]
assert [t["ticker"] for t in w["direct_thesis"]["tickers"]] == ["WEAT"] and w["direct_thesis"]["tickers"][0]["effect"] == "loses"
assert not w["cross_sector_thesis"]["tickers"] and w["cross_sector_thesis"]["empty_reason"]
seen["skip"] = set(); seen["wrong_move"] = {"Corn"}                                         # AI е приел обратното движение → cross се отхвърля, директната остава
with contextlib.redirect_stdout(io.StringIO()):
    out3 = ai_brief.cot_theses(EXTREMES, [], None)
cn = {c["market"]: c for c in out3}["Corn"]
assert cn["thesis_rejected"] and cn["cross_sector_thesis"] is None and [t["ticker"] for t in cn["direct_thesis"]["tickers"]] == ["CORN"]
print("  ✓ пазар без AI отговор (Wheat) пак се показва с директния WEAT (губи) и празен cross с причина; разминаване в assumed_move (Corn)")
print("    отхвърля само cross частта — директната (CORN) остава")
print()
print("Всички тестове минаха.")
