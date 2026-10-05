"""
Пакет 3 · т.е (2026-10-05): COT whitelist-ът е по ТОЧНО име или cftc_contract_market_code (не по ключови думи с избор на първия
по азбучен ред); тест, който изисква точно един кандидат за всеки запис и гърми при 0 или >1; Brent е махнат.

РЕАЛНО: пълният списък на CFTC контрактите (име + код) за TFF и Disaggregated от 05.10.2026 (tests/fixtures/cot_markets_2026-10-05.json,
последен отчет 29.09.2026); старите ключови думи (вградени тук само за сравнението) върху същия списък: XRP 2 кандидата, Gold 2,
Brent 6. СИНТЕТИЧНО: преименуван контракт със същия код, двусмислен кеш, липсващ пазар.
Пускане: python test_cot_whitelist.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import cot

LIST = json.loads((ROOT / "tests" / "fixtures" / "cot_markets_2026-10-05.json").read_text(encoding="utf-8"))
MARKETS = {src: {r["name"]: r["code"] for r in LIST[src]} for src in ("tff", "disaggregated")}


def candidates(entry, markets):
    return cot.whitelist_candidates(entry, markets[entry[1]])


print("── РЕАЛЕН списък на CFTC от 05.10.2026: точно един кандидат за всеки запис ──")
assert len(cot.MAJOR_MARKETS) == 40 and len({e[0] for e in cot.MAJOR_MARKETS}) == 40            # уникални етикети
assert not [e for e in cot.MAJOR_MARKETS if "brent" in e[0].lower() or "BRENT" in e[2]]
bad = {}
for e in cot.MAJOR_MARKETS:
    c = cot.whitelist_contracts(e, MARKETS[e[1]])
    if len(c) != 1:
        bad[e[0]] = c
assert not bad, f"записи без точно един кандидат-контракт: {bad}"                                  # гърми при 0 или >1
for e in cot.MAJOR_MARKETS:                                                                       # и името, и кодът сочат към ЕДИН И СЪЩ ред
    assert MARKETS[e[1]].get(e[2]) == e[3], (e[0], e[2], e[3], MARKETS[e[1]].get(e[2]))
print("  ✓ 40 записа (20 TFF + 20 Disaggregated), за всеки точно един контракт-кандидат, а името и кодът сочат към същия ред")
# името в записа е ТЕКУЩОТО име на контракта: сред всички имена с този код най-скорошното е то
INFO = {src: {r["name"]: (r["last"], r["n"]) for r in LIST[src]} for src in MARKETS}
multi = {}
for e in cot.MAJOR_MARKETS:
    cands = candidates(e, MARKETS)
    assert cot.pick_current_name({m: INFO[e[1]][m] for m in cands}) == e[2], (e[0], cands)
    if len(cands) > 1:
        multi[e[0]] = cands
assert multi == {"Ultra Treasury Bond": ["ULTRA US T BOND - CHICAGO BOARD OF TRADE", "ULTRA UST BOND - CHICAGO BOARD OF TRADE"]}
print("  ✓ РЕАЛЕН случай с две имена на един контракт: Ultra T-Bond (код 020604) е 'ULTRA US T BOND' (2 седмици, до 16.09.2025) и 'ULTRA UST BOND' (142 седмици) —")
print("    броят се за един контракт, взема се най-скорошното име; записът е точно него")
src_counts = {s: sum(1 for e in cot.MAJOR_MARKETS if e[1] == s) for s in ("tff", "disaggregated")}
assert src_counts == {"tff": 20, "disaggregated": 20}
print("  ✓ Brent Crude го няма (в CFTC има само NYMEX финансов 'BRENT LAST DAY'; петролът е покрит от WTI)")
print()

print("── защо старият метод беше нестабилен (РЕАЛНИ ключови думи върху РЕАЛНИЯ списък) ──")
OLD = {"XRP": ("tff", ["XRP"], ["NANO", "MICRO"]), "Gold": ("disaggregated", ["GOLD"], ["MICRO", "MINI"]),
       "Brent Crude": ("disaggregated", ["BRENT"], [])}
counts = {}
for label, (src, kws, exs) in OLD.items():
    counts[label] = [m for m in MARKETS[src] if all(k in m.upper() for k in kws) and not any(x in m.upper() for x in exs)]
assert len(counts["XRP"]) == 2 and len(counts["Gold"]) == 2 and len(counts["Brent Crude"]) == 6
assert sorted(counts["XRP"])[0] == "XRP - CHICAGO MERCANTILE EXCHANGE" and sorted(counts["Gold"])[0] == "GOLD - COMMODITY EXCHANGE INC."
print("  ✓ старите ключови думи: XRP 2 кандидата (CME и Coinbase Derivatives), Gold 2 (COMEX и Coinbase Derivatives), Brent 6;")
print("    правилният печелеше само защото е пръв по азбучен ред — новият запис е точен и не зависи от реда")
print()

print("── тестът гърми при 0 или >1 кандидата (СИНТЕТИЧНО) ──")
entry = next(e for e in cot.MAJOR_MARKETS if e[0] == "Gold")
gone = {"disaggregated": {k: v for k, v in MARKETS["disaggregated"].items() if k != entry[2] and v != entry[3]}}
assert candidates(entry, gone) == []                                                              # 0 кандидата
two = {"disaggregated": {**MARKETS["disaggregated"], "GOLD - КОПИЕ": entry[3]}}                  # друго име със същия код → 2 имена, 1 контракт
assert len(candidates(entry, two)) == 2 and len(cot.whitelist_contracts(entry, two["disaggregated"])) == 1
dup = {"disaggregated": {**MARKETS["disaggregated"], "ДРУГО ИМЕ": entry[3], entry[2]: "999999"}}  # името сочи към код 999999, кодът 088691 — към ДРУГО име
assert len(cot.whitelist_contracts(entry, dup["disaggregated"])) == 2
renamed = {"disaggregated": {("GOLD - НОВО ИМЕ" if k == entry[2] else k): v for k, v in MARKETS["disaggregated"].items()}}
assert candidates(entry, renamed) == ["GOLD - НОВО ИМЕ"]                                          # преименуван контракт със същия код → 1 по код
print("  ✓ липсващ пазар → 0; двойник със същия код → 2 имена, но 1 контракт; име и код към РАЗЛИЧНИ контракти → 2 контракта; преименуване със същия код → точно 1 (по кода)")
print()

print("── _resolve_whitelist върху кеш (СИНТЕТИЧЕН кеш с РЕАЛНИТЕ имена) ──")
def cache_of(markets, with_codes=False):
    c = {"tff": {m: [{"date": "2026-09-29", "net": 1.0}] for m in markets["tff"]},
         "disaggregated": {m: [{"date": "2026-09-29", "net": 1.0}] for m in markets["disaggregated"]}}
    if with_codes:
        c["codes"] = {s: {m: code for m, code in markets[s].items() if code} for s in markets}
    return c
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = cot._resolve_whitelist(cache_of(MARKETS))
assert len(res) == 40 and dict((l, m) for l, s, m in res)["Gold"] == "GOLD - COMMODITY EXCHANGE INC." and dict((l, m) for l, s, m in res)["XRP"] == "XRP - CHICAGO MERCANTILE EXCHANGE"
assert "whitelist miss" not in buf.getvalue() and "двусмислие" not in buf.getvalue()
print("  ✓ върху пълния реален списък (с кеш без кодове) и всичките 40 записа се резолвират до точното име; Gold → COMEX, XRP → CME")
# преименуван контракт: името го няма, кодът го намира
ren = {s: dict(v) for s, v in MARKETS.items()}
ren["tff"]["XRP - НОВО ИМЕ"] = ren["tff"].pop("XRP - CHICAGO MERCANTILE EXCHANGE")
with contextlib.redirect_stdout(io.StringIO()):
    res_ren = dict((l, m) for l, s, m in cot._resolve_whitelist(cache_of(ren, with_codes=True)))
    res_noc = dict((l, m) for l, s, m in cot._resolve_whitelist(cache_of(ren, with_codes=False)))
assert res_ren["XRP"] == "XRP - НОВО ИМЕ" and "XRP" not in res_noc
print("  ✓ СИНТЕТИЧНО: борсата преименува XRP — със записан код пазарът се намира, без код е whitelist miss (лог), не грешен избор")
# двусмислие: две различни имена съвпадат (едното по име, другото по код) → пропуска се, не избира първото
amb = {s: dict(v) for s, v in MARKETS.items()}
amb["disaggregated"]["GOLD - ДВОЙНИК"] = entry[3]
amb["disaggregated"][entry[2]] = "999999"                                                         # името и кодът сочат към РАЗЛИЧНИ контракти
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res_amb = dict((l, m) for l, s, m in cot._resolve_whitelist(cache_of(amb, with_codes=True)))
assert "Gold" not in res_amb and "whitelist двусмислие: 'Gold' има 2 различни контракта" in buf.getvalue() and len(res_amb) == 39
print("  ✓ СИНТЕТИЧНО: името и кодът сочат към различни контракти → 'двусмислие', пазарът се пропуска (останалите 39 са наред)")
# две имена на ЕДИН контракт в кеша: взема се най-скорошното, не първото по азбука
two_names = {s: dict(v) for s, v in MARKETS.items()}
cache2 = cache_of(two_names, with_codes=True)
cache2["disaggregated"]["GOLD - A ПО-СТАРО ИМЕ"] = [{"date": "2025-01-07", "net": 1.0}]
cache2["codes"]["disaggregated"]["GOLD - A ПО-СТАРО ИМЕ"] = entry[3]
with contextlib.redirect_stdout(io.StringIO()):
    res_two = dict((l, m) for l, s, m in cot._resolve_whitelist(cache2))
assert res_two["Gold"] == "GOLD - COMMODITY EXCHANGE INC."                                         # "A…" е първо по азбука, но по-старо
print("  ✓ СИНТЕТИЧНО: две имена на един контракт в кеша ('GOLD - A ПО-СТАРО ИМЕ' е първо по азбука, но с по-стара дата) → взема се най-скорошното")
print()

print("── кеш: кодът се записва ──")
fetched = [{"market": "GOLD - COMMODITY EXCHANGE INC.", "date": "2026-10-06", "net": 5.0, "code": "088691"},
           {"market": "ВРЕМЕНЕН - БЕЗ КОД", "date": "2026-10-06", "net": 1.0, "code": None}]
orig = cot._fetch_since
cot._fetch_since = lambda *a, **k: fetched
c = {"tff": {}, "disaggregated": {"GOLD - COMMODITY EXCHANGE INC.": [{"date": "2026-09-29", "net": 1.0}]}}
with contextlib.redirect_stdout(io.StringIO()):
    cot._update_report(c, "disaggregated", "x", "l", "s")
cot._fetch_since = orig
assert c["codes"]["disaggregated"] == {"GOLD - COMMODITY EXCHANGE INC.": "088691"} and len(c["disaggregated"]["GOLD - COMMODITY EXCHANGE INC."]) == 2
print("  ✓ _update_report записва cache['codes'][source][пазар] (само ако има код); сериите се сливат както преди")
print()
print("Всички тестове минаха.")
