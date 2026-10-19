"""
13.10.2026 · "X е единственият сектор с положителна RS …" — фактът е от кода (sector_claims.facts, в макро промпта), а противоречащото твърдение се заменя в макро текста, във веригите
на sector_logic и в why_now на картите.

Случаят (РЕАЛЕН, брифът от 13.10): веригата за XLK — "…е единственият сектор с положителна RS на двата хоризонта", а в ротацията XLV (+0.39 / +5.54) и XLE (+0.38 / +13.73) също са
положителни и на двата; изречението е преписано в наратива на ANET. Измерено върху 85 брифа с ротация: 12 противоречащи твърдения (07.31, 08.03, 08.05, 08.13, 08.17, 08.18×2, 10.09×2,
10.13×2) — всичките наистина грешни; квалифицираните ("извън XLK", "non-defensive") не се пипат.

19.10.2026 (етап 2, т. 5): при противоречие се заменя ЦЯЛОТО изречение с изречение от кода (19.10 XLE: частичната замяна оставяше "… (XLE, XLP, XLV, XLU, XLB, XLY) (+6.52%), и на
12-седмичен хоризонт (+14.76%), и на 6-месечен връх …"; "12-седмичен хоризонт" не се разпознаваше като втори хоризонт); "положителна 4W RS ПРИ отрицателна 12W RS" е "само 4 седмици" —
05.08 XLE е ВЯРНО (единственият само за 4 седмици), а кодът го "поправяше": от 12-те замени в извадката 11 са реални, 05.08 беше фалшива.

РЕАЛНО: tests/fixtures/sector_claims_2026-10-13.json — ротацията и текстовете на модела от 10 брифа; tests/fixtures/brief_2026-10-19.json — ротацията и поправеното изречение за XLE
(оригиналът е в sector_claims_fixed). СИНТЕТИЧНО (означено): ротацията с един-единствен положителен сектор (вярно твърдение), подмененото извикване на модела.
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
print("── 3. цялата извадка: 11 замени, всичките противоречат на таблицата; вярното (05.08) и квалифицираните — не ──")
hits = []
for d, b in FX.items():
    f = sc.facts(b["rotation"])
    for x in b["texts"]:
        new, probs = sc.clean(x["text"], f, x.get("etf") if x["field"] == "sector_logic" else None)
        for p in probs:
            assert len(p["listed"]) != 1 or (p["subject"] and p["subject"] != p["listed"][0])          # заменено е само твърдение, което е невярно по таблицата
            hits.append((d, x["field"], x.get("etf") or x.get("ticker"), p["scope"]))
assert len(hits) == 11, hits
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
print("── 4. вярно твърдение (СИНТЕТИЧНА ротация: само XLK е положителен и на двата) — остава ──")
fs = sc.facts([{"etf": "XLK", "rs_chg_4w_pct": 4.0, "rs_chg_12w_pct": 4.7}, {"etf": "XLV", "rs_chg_4w_pct": -0.4, "rs_chg_12w_pct": 5.5}])
assert sc.check(why, fs) == [] and sc.check(chain, fs, "XLK") == []
print("  ✓ при един-единствен положителен сектор, който е подлогът — без замяна")

print()
print("── 5. ai_brief: веригите се поправят в макро стъпката, наративите — след сливането ──")
out = ai_brief._apply_sector_claims({"macro_brief": "", "regime_comment": "", "sector_logic": [{"etf": "XLK", "chain": chain}]}, FX["2026-10-13"]["rotation"])
assert "единствен" not in out["sector_logic"][0]["chain"] and out["sector_claims_fixed"][0]["field"] == "sector_logic:XLK"
cards = [{"ticker": "ANET", "ai": {"why_now": why}}, {"ticker": "EXPD", "ai": {"why_now": "Без твърдения."}}]
fixed = ai_brief.apply_sector_claims_to_narratives(cards, FX["2026-10-13"]["rotation"])
assert [x["ticker"] for x in fixed] == ["ANET"] and "единствен" not in cards[0]["ai"]["why_now"] and cards[1]["ai"]["why_now"] == "Без твърдения."
seen = {}
ai_brief._call_claude = lambda system, user, **k: seen.setdefault("user", user) and '{"macro_brief": "", "sector_logic": [], "regime_comment": ""}'   # СИНТЕТИЧНО
ai_brief._macro_and_sector_brief_ai({}, FX["2026-10-13"]["rotation"], {"regime": "Defensive", "indicators": []}, news=[])
assert "ГОТОВО ОТ КОДА за RS на секторите (13.10.2026): Сектори с положителна RS и на 4, и на 12 седмици: XLK, XLV, XLE;" in seen["user"]
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index("ai_brief.merge_narratives(candidates, narratives)") < src.index("ai_brief.apply_sector_claims_to_narratives(candidates, rotation)")
print("  ✓ фактът е в макро промпта; веригата е поправена преди промпта на тикърите; why_now — след merge_narratives; brief['sector_claims_fixed']")
print()
print("Всички тестове минаха.")
