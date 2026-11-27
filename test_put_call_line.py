"""
16.11.2026 (пакет 16.11, т. 2): макро текстът обърна смисъла на Put/Call — „на 7-ми перцентил … ниско самодоволство в смисъл, че хеджовете са малко“; нисък P/C = малко хеджове
= ВИСОКО самодоволство (плочката го казва правилно). Сега изречението за P/C е от кода (thermometer.put_call_sentence) — под разказа, на страницата и в имейла; Put/Call не стига
до модела (_thermo_context), а AI изречение за P/C пада в проверката за термини (и в „защо“ на новините). В историята: 14 изречения за P/C в 109 разказа.

РЕАЛНО: tests/fixtures/news_nvidia_2026-11-16.json — macro_brief и термометърът от data/2026-11-16.json (P/C 0.89, 7.4. percentile от 108 дни, червено); т. 2 — реални изречения от
разказите на 18.09 и 11.09 (дословно); brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): т. 1 — зеленото и жълтото състояние, скрит индикатор.
Пускане: python test_put_call_line.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_pc_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "news_nvidia_2026-11-16.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
TH = FX["inputs"]["thermometer"]
PC = next(i for i in TH["indicators"] if i["name"] == "Put/Call (SPY)")

print("── 1. изречението от кода ──")
assert (PC["value"], PC["percentile"], PC["status"]) == (0.89, 7.4, "red")
S = th.put_call_sentence(PC)
assert S == "Put/Call (SPY) 0.89 — 7. percentile от 108 дни: малко хеджове спрямо собствената история — високо самодоволство (червено; само информация — не влиза в режима).", S
assert "за режима" not in S                                                                             # 27.11.2026 (т. 8): P/C — само информативен от 18.11
g = th.put_call_sentence({**PC, "value": 1.45, "percentile": 95.0, "status": "green"})                 # СИНТЕТИЧНО
assert g.endswith("много хеджове спрямо собствената история — страх, сигнал в обратна посока (зелено; само информация — не влиза в режима).")
assert th.put_call_sentence({**PC, "value": 1.13, "percentile": 49.0, "status": "yellow"}).endswith("в нормалния диапазон за собствената история (жълто; само информация — не влиза в режима).")
assert th.put_call_sentence({"name": "Put/Call (SPY)", "value": None, "hide": True}) is None and th.put_call_sentence(None) is None
print(f"  ✓ РЕАЛНО 16.11: „{S}“")

print("── 2. РЕАЛНО: AI изреченията за P/C падат (разказът на 16.11, 18.09, 11.09) ──")
txt = FX["macro_brief"]
assert "Put/Call коефициентът е на 7-ми перцентил" in txt
new, fixed = ai_brief.check_market_terms(txt, [], None, None)
assert "Put/Call" not in new and [f["term"] for f in fixed] == ["Put/Call"] and "ниско самодоволство" in fixed[0]["sentence"]
assert len(new) > len(txt) - len(fixed[0]["sentence"]) - 5                                            # останалото — непокътнато
for sent in ("P/C ratio 0.87 е жълт (леко повишена предпазливост), а IEI/HYG на 0.0 percentile по ниво означава рекордно стегнат кредитен спред — комплацентност, а не комфорт, което прибавя asymmetric downside риск ако нещо се обърка.",
             "SPY е под 50DMA (757.83 vs 758.25) при breadth само 28% над 40DMA — повърхностно изглежда слабо, но Put/Call 1.44 и Fed Net Liquidity $5852.5 млрд (↑от $5795.3) осигуряват буфер срещу по-дълбока разпродажба."):
    assert ai_brief.check_market_terms(sent, [], None, None)[0] == ""
news = [{"headline": "x", "why": "Ниският P/C показва еуфория.", "source_text": "x"}]
ai_brief.check_news_why_terms(news)
assert news[0]["why"] == ""                                                                           # и в „защо“ на новините
print(f"  ✓ махнато: «{fixed[0]['sentence'][:80]}…»; 18.09 и 11.09 — също; и в „защо“")

print("── 3. P/C не стига до модела ──")
ctx = ai_brief._thermo_context(TH)
assert not any(str(r["name"]).startswith("Put/Call") for r in ctx) and any(r["name"] == "VIX" for r in ctx)
print("  ✓ контекстът за разказа е без Put/Call")

print("── 4. страницата и имейлът: под разказа ──")
b = copy.deepcopy(B19); b["thermometer"] = TH; b["ai_macro"] = {"macro_brief": new}
with contextlib.redirect_stdout(io.StringIO()):
    page, mail = render.render_dashboard(b, publish=False), render.render_email(b)
assert S in page and S in mail and page.index("<h2>Макро бриф</h2>") < page.index(S)
assert "ниско самодоволство" not in page
b["thermometer"] = {**TH, "indicators": [i for i in TH["indicators"] if not i["name"].startswith("Put/Call")]}
with contextlib.redirect_stdout(io.StringIO()):
    assert "Put/Call (SPY)" not in render.render_email(b)
print("  ✓ редът е под разказа (страница и имейл); без индикатор — без ред")
print("\n✅ test_put_call_line: всичко мина")
