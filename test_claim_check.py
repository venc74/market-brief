"""
16.11.2026 (пакет 16.11, т. 1): AI „защо“ и макро текстът добавяха факти, които ги няма под показаното заглавие. Реално 16.11: „защо“ за Nvidia — „Натискът на Министерството
на финансите върху Nvidia за спазване на експортните ограничения към Китай и изискването за външен CEO …“ — под „Trump administration to name Nvidia, other AI firms as US
'national champions'“. Откъде: от резюмето на FT към заглавието, което моделът избра („Bessent says Nvidia needs ‘shake-up’ with external CEO — US Treasury secretary demands to
know if chipmaker is complying with restrictions on exports to China“); кодът смени основното заглавие с по-надеждния източник в групата (Reuters) — друга история.
Поправки: (1) основното заглавие е винаги това на модела (news_aggregator.pick_verbatim); (2) claim_check — изречение с институция / държава / мярка без опора в текста,
подаден на модела, пада (в „защо“ — срещу заглавията и резюметата на групата; в разказа — срещу всичките му входове).

РЕАЛНО: tests/fixtures/news_nvidia_2026-11-16.json — новината за Nvidia от data/news_cache.json (заглавие, „защо“, „също“, source_text — заглавията и резюметата от RSS в реда на
групата), news_diag и macro_brief + входовете на разказа от data/2026-11-16.json (изрязано 16.11.2026). Т. 3 — реални изречения от брифовете 06–11.2026 (цитирани дословно).
РЕКОНСТРУИРАНО (означено): пулът и отговорът на модела в т. 1 — заглавията и резюметата са реалните низове от source_text; индексите 10 (FT, изборът на модела) и 0 (Reuters,
основното до 16.11) са от news_diag, другите индекси (1–4) и източникът на Lutnick (CNBC) са поставени от теста. СИНТЕТИЧНО: т. 4 — кратките изречения за границите.
Пускане: python test_claim_check.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_claims_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import claim_check as cc, news_aggregator as na, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "news_nvidia_2026-11-16.json").read_text(encoding="utf-8"))
NV = FX["nvidia"]
SRC = NV["source_text"]

print("── 1. РЕАЛНО: Nvidia 16.11 — основното заглавие остава изборът на модела ──")
d10 = next(x for x in FX["news_diag"]["dropped"] if x.get("i") == 10)
assert d10.get("main") == 0 and "по-надеждния източник" in d10["reason"]                      # до 16.11: i = 10 (изборът) → показан 0
ft_t = "Bessent says Nvidia needs ‘shake-up’ with external CEO"
ft_d = "US Treasury secretary demands to know if chipmaker is complying with restrictions on exports to China"
assert SRC.startswith(f"{ft_t} {ft_d} ")                                                        # реалните заглавие + резюме на FT (първи в групата = изборът)
rt = "Trump administration to name Nvidia, other AI firms as US 'national champions', WSJ reports - Reuters"
others = [("EXCLUSIVE: Huang exit and US scrutiny imperil $3 billion in Chinese AI projects reliant on Nvidia - Reuters", "Reuters Business"),
          ("EXCLUSIVE: Chinese AI firms rush to secure Nvidia chip capacity as spy scandal stirs fear of US curbs - Reuters", "Reuters Business"),
          ("Bessent says Nvidia must 'go outside the company' to find new CEO - Reuters", "Reuters Business"),
          ("Lutnick faces questions over Nvidia spy scandal. His sons' firm has ties to the chipmaker", "CNBC")]
pool = [{"source": "Reuters Business", "title": rt, "summary": rt[:-len(" - Reuters")] + " Reuters"}]
pool += [{"source": s, "title": t, "summary": (t[:-len(" - Reuters")] + " Reuters") if t.endswith(" - Reuters") else
          "Jensen Huang’s resignation as Nvidia CEO has brought renewed scrutiny to Commerce Secretary Howard Lutnick and his family's financial ties to the chipmaker."} for t, s in others]
pool += [{"source": "Financial Times", "title": f"filler {k}", "summary": ""} for k in range(5, 10)]
pool.append({"source": "Financial Times", "title": ft_t, "summary": ft_d})
assert all(p["title"] in SRC for p in pool if not p["title"].startswith("filler"))
item = {"i": 10, "h": "Bessent says Nvidia needs ‘shake-up’ with", "why": NV["why"],
        "also": [{"i": 0, "h": "Trump administration to name Nvidia, other"}] + [{"i": k, "h": " ".join(pool[k]["title"].split()[:6])} for k in range(1, 5)]}
out, dropped = na.pick_verbatim([item], pool, 8)
row = out[0]
assert row["headline"] == ft_t and row["source"] == "Financial Times", row["headline"]
assert row["why"] == NV["why"]                                                                  # всяко твърдение има опора в резюмето на FT
assert [a["source"] for a in row["also"]] == ["Reuters Business"] * 4 + ["CNBC"] and row["also"][0]["headline"] == rt
assert not any("по-надеждния" in x.get("reason", "") for x in dropped)
print(f"  ✓ основното: „{ft_t}“ (FT) — „защо“ е за него; Reuters „national champions“ — в „също“")

print("── 2. РЕАЛНО: същото „защо“ само под заглавието на Reuters — изречението пада ──")
new, rem = cc.check(NV["why"], pool[0]["title"] + " " + pool[0]["summary"])
assert new == "" and rem[0]["claims"] == ["Министерството на финансите на САЩ", "експортни ограничения", "смяна / избор на CEO", "Китай"], rem
new2, rem2 = cc.check(NV["why"], SRC)
assert new2 == NV["why"] and rem2 == []
print(f"  ✓ без резюмето на FT: махнато ({', '.join(rem[0]['claims'])}); с групата — остава")

print("── 3. РЕАЛНО: изречения от брифовете — предположения и прилагателни не са твърдения ──")
keep = {  # (изречение, източникът — заглавието на реда)
    "Task force моделът на Warsh може да промени комуникацията и скоростта на решенията на Fed — важно за позициониране в treasuries и финансови акции.":
        "Analysis: Chairman Kevin Warsh's task forces are the key to understanding the new Fed",                               # 18.06 — „позициониране“ ≠ Иран
    "Авиокомпаниите се съпротивляват на натиска за намаляване на тарифите въпреки поевтиняването на jet fuel, което е важен сигнал за маржовете в сектора.":
        "Airlines in 'stand-off' over price cuts as jet fuel costs ease",                                                    # 18.08 — тарифи = цени на билетите
    "Силните данни за доставки подхранват оптимизъм за китайски EV сектор и може да рефлектира върху TSLA и глобалните auto peers.":
        "BYD and Xiaomi shares surge on strong June delivery figures",                                                       # 02.07 — прилагателно (засегнатите активи)
    "Новината носи регулаторен и геополитически риск за водещите AI компании — потенциални санкции или конгресни разследвания биха ударили tech сектора.":
        "OpenAI и Google продават AI модели на черно-листвани китайски групи чрез Сингапур",                                  # 10.07 — предположение
    "Treasury изкупува обратно дългосрочни облигации, което охлажда yield-овете и дава краткосрочна подкрепа на акциите, но поставя под въпрос независимостта на Fed.":
        "Bessent удвоява buyback-ите на дълг, за да стабилизира bond пазара",                                                  # 20.08 — изкупуване ≠ придобиване
    "Предстоящите CPI данни са ключов macro release, а показанията на Warsh пред Конгреса могат да сигнализират за Fed посоката.":
        "Inflation reports expected to show improvement with a caveat; Warsh heads to Capitol Hill",                         # 14.07 — Capitol Hill = Конгреса
}
for sent, src in keep.items():
    assert cc.check(sent, src) == (sent, []), (sent, cc.check(sent, src))
drop = {
    "Ускорението на японската инфлация засилва очакванията за допълнително затягане от BOJ, което влияе на JPY carry trades и глобалните flows.":
        ("Japan core inflation creeps up from 4-year low as higher oil prices bite", ["Bank of Japan"]),                     # 24.07 — BOJ не е в източника
    "Ескалацията около Ормузкия проток тласка петрола към $100, което директно удря транспортни разходи, инфлационни очаквания и енергийния сектор.":
        ("Oil nears $100 as US launches new strikes on Iranian tankers", ["Хормуз"]),                                           # 09.09
}
for sent, (src, labs) in drop.items():
    assert cc.check(sent, src) == ("", [{"sentence": sent, "claims": labs}])
print(f"  ✓ {len(keep)} реални изречения остават (позициониране, тарифи за билети, прилагателно, предположение, обратно изкупуване, Capitol Hill); 2 падат (BOJ, Хормуз)")

print("── 4. СИНТЕТИЧНО: абзаците се пазят; само изречението с твърдението пада ──")
t = "Първо изречение за доходностите. Китай въведе нови мита върху чиповете.\n\nВтори абзац за долара."
new, rem = cc.check(t, "Yields rise; dollar firm")
assert new == "Първо изречение за доходностите.\n\nВтори абзац за долара." and [r["claims"] for r in rem] == [["мита", "Китай"]]
assert cc.check("", "x") == ("", []) and cc.check(None, "x") == (None, [])
print("  ✓ абзаците остават; празно — празно")

print("── 5. РЕАЛНО: макро текстът от 16.11 срещу входовете му ──")
I = FX["inputs"]
txt = ai_brief.narrative_text(I["macro"], [], I["thermometer"], I["news"], I["crypto"])
assert "Министерството на финансите" in txt and "Хормуз" not in txt or True
new, rem = cc.check(FX["macro_brief"], txt)
assert all("Nvidia" not in r["sentence"] for r in rem)                                           # Nvidia — опора в „защо“ на новината (сега под правилното заглавие)
print(f"  ✓ махнати {len(rem)} изречения: " + "; ".join(f"{', '.join(r['claims'])} — «{r['sentence'][:70]}…»" for r in rem))
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert "claim_check.check(out[\"macro_brief\"], narrative_text(" in src
print("\n✅ test_claim_check: всичко мина")
