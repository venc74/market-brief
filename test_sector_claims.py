"""
13.10.2026 · "X е единственият сектор с положителна RS …" — фактът е от кода (sector_claims.facts, в макро промпта), а противоречащото твърдение се заменя в макро текста, във веригите
на sector_logic и в why_now на картите.

Случаят (РЕАЛЕН, брифът от 13.10): веригата за XLK — "…е единственият сектор с положителна RS на двата хоризонта", а в ротацията XLV (+0.39 / +5.54) и XLE (+0.38 / +13.73) също са
положителни и на двата; изречението е преписано в наратива на ANET. Измерено върху 85 брифа с ротация: 12 противоречащи твърдения (07.31, 08.03, 08.05, 08.13, 08.17, 08.18×2, 10.09×2,
10.13×2) — всичките наистина грешни; квалифицираните ("извън XLK", "non-defensive") не се пипат.

19.10.2026 (етап 2, т. 5): при противоречие се заменя ЦЯЛОТО изречение с изречение от кода (19.10 XLE: частичната замяна оставяше "… (XLE, XLP, XLV, XLU, XLB, XLY) (+6.52%), и на
12-седмичен хоризонт (+14.76%), и на 6-месечен връх …"; "12-седмичен хоризонт" не се разпознаваше като втори хоризонт); "положителна 4W RS ПРИ отрицателна 12W RS" е "само 4 седмици" —
05.08 XLE е ВЯРНО (единственият само за 4 седмици), а кодът го "поправяше": от 12-те замени в извадката 11 са реални, 05.08 беше фалшива.

26.10.2026 (етап 4б, т. 5): и "единственият сектор с (потвърдено) лидерство …" / "единственият водещ сектор" — 23.10 и 26.10 XLE ("… с потвърдено лидерство и на двата хоризонта, и на
6-месечния връх по RS"), а XLV беше положителен и на двата хоризонта (и на 26.10 — също на 6-месечен връх). Върху 94 брифа с ротация: 7 такива твърдения — 4 грешни (13.08 MPC, 20.10, 23.10,
26.10), 2 верни като съчетание с 6-месечния връх (15.10, 16.10), 1 с условие, което кодът не проверява (21.10). В извадката от 13.10 това добавя 13.08 MPC → 12 замени.

РЕАЛНО: tests/fixtures/sector_claims_2026-10-13.json — ротацията и текстовете на модела от 10 брифа; tests/fixtures/brief_2026-10-19.json — ротацията и поправеното изречение за XLE
(оригиналът е в sector_claims_fixed). tests/fixtures/sector_lead_claims_2026-10-26.json — ротацията и веригите с "единственият … лидерство" от 15.10, 16.10,
20.10, 21.10, 23.10 и 26.10 (data/, 26.10). СИНТЕТИЧНО (означено): ротацията с един-единствен положителен сектор (вярно твърдение), подмененото извикване на модела.
Пускане: python test_sector_claims.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import sector_claims as sc, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "sector_claims_2026-10-13.json").read_text(encoding="utf-8"))["briefs"]

print("── 1. фактът от кода (13.10) ──")
f13 = sc.facts(FX["2026-10-13"]["rotation"])
assert f13["both"] == ["XLK", "XLV", "XLE"]
assert f13["text"].startswith("Сектори с положителна RS и на 4, и на 12 седмици: XLK, XLV, XLE;")
print("  ✓", f13["text"])

print()
print("── 2. брифът от 13.10: веригата за XLK и наративът на ANET ──")
t = {(x["field"], x.get("etf") or x.get("ticker")): x["text"] for x in FX["2026-10-13"]["texts"]}
chain, why = t[("sector_logic", "XLK")], t[("why_now", "ANET")]
assert "е единственият сектор с положителна RS на двата хоризонта" in chain and "XLK е единственият сектор с положителна RS на двата хоризонта" in why
new, pr = sc.clean(chain, f13, "XLK")
assert len(pr) == 1 and pr[0]["replacement"] == "XLK: положителна RS и на 4, и на 12 седмици — заедно с XLV, XLE (по таблицата на ротацията)." and "единствен" not in new
assert pr[0]["replacement"] in new and pr[0]["sentence"] not in new                                    # заменено е ЦЯЛОТО изречение (сегмент)
new2, pr2 = sc.clean(why, f13)
assert len(pr2) == 1 and "XLK: положителна RS и на 4, и на 12 седмици — заедно с XLV, XLE (по таблицата на ротацията)" in new2
assert new[:new.index(pr[0]["replacement"])] == chain[:chain.index(pr[0]["sentence"])]                 # текстът преди изречението е непокътнат
print("  ✓ веригата и ANET: цялото изречение → 'XLK: положителна RS и на 4, и на 12 седмици — заедно с XLV, XLE (по таблицата на ротацията).'")

print()
print("── 3. цялата извадка: 12 замени, всичките противоречат на таблицата; вярното (05.08) и квалифицираните — не ──")
hits = []
for d, b in FX.items():
    f = sc.facts(b["rotation"])
    for x in b["texts"]:
        new, probs = sc.clean(x["text"], f, x.get("etf") if x["field"] == "sector_logic" else None)
        for p in probs:
            assert len(p["listed"]) != 1 or (p["subject"] and p["subject"] != p["listed"][0])          # заменено е само твърдение, което е невярно по таблицата
            hits.append((d, x["field"], x.get("etf") or x.get("ticker"), p["scope"]))
assert len(hits) == 12, hits
assert ("2026-08-13", "why_now", "MPC", "both") in hits                                               # 26.10: "единственият сектор с двойно потвърдено RS лидерство" (XLE при 5 сектора)
assert sorted({h[0] for h in hits}) == ["2026-07-31", "2026-08-03", "2026-08-13", "2026-08-17", "2026-08-18", "2026-10-09", "2026-10-13"]
x0805 = next(x for x in FX["2026-08-05"]["texts"] if x.get("etf") == "XLE")
assert "XLE е единственият сектор с положителна 4W RS (+3.82%) ПРИ отрицателна 12W RS (-7.21%)" in x0805["text"] and sc.facts(FX["2026-08-05"]["rotation"])["only_4w"] == ["XLE"]
assert sc.check(x0805["text"], sc.facts(FX["2026-08-05"]["rotation"]), "XLE") == []                   # ВЯРНО — до 19.10 се "поправяше"
q = {(x["field"], x.get("etf")): x["text"] for x in FX["2026-09-22"]["texts"] + FX["2026-09-30"]["texts"]}
assert "единственият сектор извън XLK с положителна RS на двата хоризонта" in q[("sector_logic", "XLC")] and sc.check(q[("sector_logic", "XLC")], sc.facts(FX["2026-09-22"]["rotation"]), "XLC") == []
assert "единственият non-defensive сектор" in q[("sector_logic", "XLK")] and sc.check(q[("sector_logic", "XLK")], sc.facts(FX["2026-09-30"]["rotation"]), "XLK") == []
print(f"  ✓ {len(hits)} замени в 7 брифа (скоупове: {sorted({h[3] for h in hits})}); 05.08 'положителна 4W RS ПРИ отрицателна 12W' (вярно — само XLE) — непокътнато; 22.09 'извън XLK' и 30.09 'non-defensive' — непокътнати")
b0731 = {(x["field"], x.get("etf") or x.get("ticker")): x["text"] for x in FX["2026-07-31"]["texts"]}
n731, _ = sc.clean(b0731[("sector_logic", "XLF")], sc.facts(FX["2026-07-31"]["rotation"]), "XLF")
assert "XLF: положителна RS и на 4, и на 12 седмици — заедно с XLV (по таблицата на ротацията)." in n731 and "+6.04%" not in n731      # "и на 4w (…), и на 12w (…)" → двата, цялото изречение
print("  ✓ 31.07: 'положителна RS и на 4w (+4.62%), и на 12w (+6.04%)' се разпознава като двата хоризонта и се заменя цялото изречение")
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
fx19 = B19["sector_claims_fixed"][0]
c19 = next(x["chain"] for x in B19["ai_macro"]["sector_logic"] if x["etf"] == "XLE")
assert "(XLE, XLP, XLV, XLU, XLB, XLY) (+6.52%), и на 12-седмичен хоризонт (+14.76%)" in c19                                   # какво излезе на страницата на 19.10 (разбито)
broken = fx19["replacement"].rstrip() + " (+6.52%), и на 12-седмичен хоризонт (+14.76%), и на 6-месечен връх по RS — лидерството е структурно, не временно."
orig19 = c19.replace(c19[c19.index(fx19["replacement"].rstrip()):c19.index(broken) + len(broken)] if broken in c19 else "", fx19["sentence"])
assert fx19["sentence"] in orig19
n19, p19 = sc.clean(orig19, sc.facts(B19["rotation"]), "XLE")
assert [(p["scope"], p["listed"]) for p in p19] == [("both", ["XLE", "XLP", "XLV"])]
assert "XLE: положителна RS и на 4, и на 12 седмици — заедно с XLP, XLV; на 6-месечен връх по RS — заедно с XLV (по таблицата на ротацията). В Defensive режим" in n19
print("  ✓ 19.10 XLE: 'и на 4-седмичен (+6.52%), и на 12-седмичен хоризонт (+14.76%)' → двата хоризонта; цялото изречение → 'XLE: положителна RS и на 4, и на 12 седмици — заедно с XLP, XLV; на 6-месечен връх по RS — заедно с XLV …'")

print()
print("── 3б. „единственият сектор с … лидерство“ (РЕАЛНИТЕ вериги, 15.10–26.10) ──")
LD = json.loads((ROOT / "tests" / "fixtures" / "sector_lead_claims_2026-10-26.json").read_text(encoding="utf-8"))["briefs"]
res = {}
for d, b in LD.items():
    f = sc.facts(b["rotation"])
    for x in b["chains"]:
        new, probs = sc.clean(x["chain"], f, x["etf"])
        res[(d, x["etf"])] = (new, probs)
fixed = sorted(k for k, (_, pr) in res.items() if pr)
assert fixed == [("2026-10-20", "XLE"), ("2026-10-23", "XLE"), ("2026-10-26", "XLE")], fixed
f26 = sc.facts(LD["2026-10-26"]["rotation"])
assert f26["both"] == ["XLE", "XLV"] and f26["at_6m_high"] == ["XLE", "XLV"] and f26["leaders"] == ["XLE", "XLV"]
n26, p26 = res[("2026-10-26", "XLE")]
assert [(p["subject"], p["scope"], p["listed"]) for p in p26] == [("XLE", "both+6m", ["XLE", "XLV"])]
assert p26[0]["sentence"].endswith("единственият сектор с потвърдено лидерство и на двата хоризонта, и на 6-месечния връх по RS.") and "единствен" not in n26
assert ("XLE: положителна RS и на 4, и на 12 седмици — заедно с XLV; на 6-месечен връх по RS — заедно с XLV; водещи по кода: XLE, XLV (по таблицата на ротацията). "
        "В Defensive режим") in n26
n23, p23 = res[("2026-10-23", "XLE")]
assert "XLE е единственият сектор с лидерство и на 4 седмици (+8.39% RS), и на 12 седмици (+12.40% RS)" in p23[0]["sentence"]
assert [(p["scope"], p["listed"]) for p in p23] == [("both", ["XLP", "XLE", "XLV", "XLY"])]          # "и на 4 седмици (…), и на 12 седмици (…)" → двата хоризонта
assert [(p["scope"], p["listed"]) for p in res[("2026-10-20", "XLE")][1]] == [("both", ["XLE", "XLP", "XLV"])]
for k in (("2026-10-15", "XLE"), ("2026-10-16", "XLV")):                                               # ВЯРНО: на двата хоризонта И на 6-месечен връх е само подлогът
    assert "единственият сектор с потвърдено лидерство на двата" in LD[k[0]]["chains"][[c["etf"] for c in LD[k[0]]["chains"]].index(k[1])]["chain"] and not res[k][1]
c21 = next(c["chain"] for c in LD["2026-10-21"]["chains"] if c["etf"] == "XLE")
assert "единственият сектор с убедено лидерство и на двата хоризонта и без история на изоставане" in c21 and not res[("2026-10-21", "XLE")][1]   # условие, което кодът не проверява
print("  ✓ 20.10, 23.10, 26.10 XLE → изречение от кода (26.10: 'XLE: … — заедно с XLV; на 6-месечен връх по RS — заедно с XLV; водещи по кода: XLE, XLV'); "
      "15.10 XLE и 16.10 XLV (двата хоризонта И 6-месечен връх — само те) и 21.10 ('… и без история на изоставане') — непокътнати")
fl = sc.facts(LD["2026-10-26"]["rotation"])
assert sc.check("XLE е единственият водещ сектор в момента.", fl)[0]["listed"] == ["XLE", "XLV"]                            # СИНТЕТИЧНО изречение: "водещ" без хоризонт → водещите по кода
assert sc.check("XLE е единственият сектор с дефанзивно лидерство.", fl) == []                                              # СИНТЕТИЧНО: друго твърдение — не се пипа
assert sc.check("XLE е единственият сектор с лидерство извън защитните.", fl) == []                                          # СИНТЕТИЧНО: квалифицирано
print("  ✓ СИНТЕТИЧНИ изречения: 'единственият водещ сектор' → водещите по кода; 'дефанзивно лидерство' и 'извън …' — непокътнати")

print()
print("── 4. вярно твърдение (СИНТЕТИЧНА ротация: само XLK е положителен и на двата) — остава ──")
fs = sc.facts([{"etf": "XLK", "rs_chg_4w_pct": 4.0, "rs_chg_12w_pct": 4.7}, {"etf": "XLV", "rs_chg_4w_pct": -0.4, "rs_chg_12w_pct": 5.5}])
assert sc.check(why, fs) == [] and sc.check(chain, fs, "XLK") == []
print("  ✓ при един-единствен положителен сектор, който е подлогът — без замяна")

print()
print("── 5. от 30.10.2026 (разходката, т. 7) проверките не се прилагат — веригите отпаднаха, а в историята са сработвали само в тях (4 от 4) ──")
assert not hasattr(ai_brief, "_apply_sector_claims") and not hasattr(ai_brief, "apply_sector_claims_to_narratives")
seen = {}
ai_brief._call_claude = lambda system, user, **k: seen.setdefault("user", user) and '{"macro_brief": ""}'   # СИНТЕТИЧНО
ai_brief._macro_and_sector_brief_ai({}, FX["2026-10-13"]["rotation"], {"regime": "Defensive", "indicators": []}, news=[])
assert "ГОТОВО ОТ КОДА за RS на секторите" not in seen["user"] and '"sector_logic"' not in seen["user"]
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "apply_sector_claims_to_narratives" not in src and "sector_claims.sector_card" not in src
print("  ✓ промптът е без фактите и без веригите; main не вика проверките; функциите на sector_claims (т. 1–4) остават")
print()
print("Всички тестове минаха.")
