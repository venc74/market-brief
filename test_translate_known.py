"""
27.11.2026 (уикенд пакет, т. 11): проверката на превода — фалшиви тревоги всеки ден (KONG, CEO, TECH, GDP, SOUTHEAST, HERE / WHAT / WHY, „ANTHROPIC,“). Сега иска САМО: числата
(и мащаба), тикърите от универса и нашите, собствените имена от известен списък (translate.KNOWN_NAMES, местата, името на наблюдаваната компания) + дните от седмицата и месеците
(в двете посоки). TRANSLATE_KNOWN_ONLY = 1.

РЕАЛНО: tests/fixtures/translations_2026-11-23_27.json — всичките 71 превода от брифовете 23–27.11 с решението на старата проверка и универсът от 27.11. СИНТЕТИЧНО (означено):
грешните варианти в т. 3.
Пускане: python run_tests.py test_translate_known
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import translate as tr

FX = json.loads((ROOT / "tests" / "fixtures" / "translations_2026-11-23_27.json").read_text(encoding="utf-8"))
known = (set(FX["universe_tickers"]), tr.KNOWN_NAMES | {k for k in tr._PLACES if k not in tr._PLACES_GENERIC})
assert config.TRANSLATE_KNOWN_ONLY == 1

print("── 1. РЕАЛНО: седмицата 23–27.11 ──")
old_rej = [r for r in FX["rows"] if r["rejected"]]
now = {i: tr.problems(r["orig"], r["bg"], set(), known=known) for i, r in enumerate(FX["rows"])}
assert len(FX["rows"]) == 71 and len(old_rej) == 12
assert all(not now[i] for i, r in enumerate(FX["rows"]) if r["rejected"])                                 # 12 от 12 минават
caught = [(r["orig"], now[i]) for i, r in enumerate(FX["rows"]) if not r["rejected"] and now[i]]
assert caught == [("50 ETFs Add to Accenture (ACN) Holdings on Tuesday", ["Tuesday → събота"])], caught    # единствената истинска грешка — хваната
print("  ✓ 12 от 12 отхвърлени досега минават; новата проверка хваща 1 истинска грешка: „… on Tuesday“ → „в събота“")

print("── 2. дните и месеците ──")
assert tr.when_problems("Bitcoin drops as November spot ETF outflows increase", "Bitcoin спада, тъй като ноемврийските изходящи потоци") == []
assert tr.when_problems("Fed may hike in December", "Fed може да вдигне лихвите през декември") == []
assert tr.when_problems("Here Is What You May Not Know", "Ето какво може би не знаете") == []
assert tr.when_problems("Results on May 5", "Резултати на 5 юни") == ["May → юни"]                       # СИНТЕТИЧНО
assert tr.when_problems("Jobs data due Friday", "Данните за заетостта излизат") == ["Friday"]            # СИНТЕТИЧНО: изпуснат ден
print("  ✓ прилагателните („ноемврийските“), „may“ като глагол, грешен и изпуснат ден / месец")

print("── 3. какво още се иска (СИНТЕТИЧНИ грешни преводи) ──")
assert tr.problems("Nvidia halts server shipments to four Southeast Asian countries, FT reports - Reuters",
                   "Nvidia спира доставките на сървъри за четири държави в Югоизточна Азия, съобщава FT", set(), known=known) == []      # РЕАЛНОТО заглавие от 27.11 (SOUTHEAST)
assert tr.problems("US third-quarter GDP growth revised sharply higher - Reuters", "Растежът на БВП на САЩ за третото тримесечие е ревизиран рязко нагоре", set(), known=known) == []
assert tr.problems("Trump says Xi agreed on tariffs", "Тръмп казва, че Си се е съгласил за митата", set(), known=known) == ["TRUMP", "XI"]
assert tr.problems("50 ETFs Add to Accenture (ACN) Holdings", "50 ETF-а добавиха към позициите си в Accenture", set(), known=known) == ["ACN"]
assert tr.problems("Fed holds rates at 4.5%", "Fed запазва лихвите на 4,25%", set(), known=known) == ["4.5"]
print("  ✓ числата, известните имена и тикърите от универса — да; CEO / GDP / SOUTHEAST — не")
print("\n✅ test_translate_known: всичко мина")
