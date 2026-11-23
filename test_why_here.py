"""
17.11.2026 (пакет 1, т. 2а — решение след стратегическия преглед): AI абзацът на картите („защо сега / бизнес / катализатори / рискове“) — махнат; вместо него ред от кода
„Защо е тук: …“ само от полетата на картата (render.why_here): RS rating, RS линията, Stage 2 и trend template, EPS и приходите г/г, секторът (водещ — по SECT✓),
разстоянието до 52-седмичния връх. Без AI извикване за картите.

РЕАЛНО: tests/fixtures/why_here_cards_2026-11-17.json — полетата на RGA, CSX, NDAQ, MET от брифа на 17.11 (Watchlist); brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): т. 2 — карта без полета.
Пускане: python test_why_here.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_why_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render, ai_brief

FX = {c["ticker"]: c for c in json.loads((ROOT / "tests" / "fixtures" / "why_here_cards_2026-11-17.json").read_text(encoding="utf-8"))["cards"]}

print("── 1. РЕАЛНО: картите от 17.11 ──")
assert render.why_here(FX["RGA"]) == ("RS 85 (перцентил в универса) · RS линията на нов връх · Stage 2, trend template ✓ · EPS +80% г/г, приходи +22% г/г · "
                                      "Финанси — водещ сектор (XLF) · 1.9% под 52-седм. връх"), render.why_here(FX["RGA"])
assert render.why_here(FX["CSX"]) == ("RS 83 (перцентил в универса) · RS линията близо до върха · Stage 2, trend template ✓ · EPS +52% г/г, приходи +12% г/г · "
                                      "Индустрия (XLI) · 2.9% под 52-седм. връх")
for t in ("NDAQ", "MET"):
    assert "водещ сектор (XLF)" in render.why_here(FX[t])
print(f"  ✓ RGA: «{render.why_here(FX['RGA'])}»")

print("── 2. СИНТЕТИЧНО: празна карта → празен ред ──")
assert render.why_here({}) == "" and render.why_here(None) == ""
print("  ✓ без полета — нищо")

print("── 3. страницата: „Защо е тук“, без AI абзаца ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
_, radar = render.split_canslim(b["watchlist"])
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
for gone in ("st.ai.why_now", "st.ai.catalysts", "st.ai.risks", "st.ai.business_bg", "st.ai.earnings_call", "Защо точно сега", "Катализатори · 4–8 седмици"):
    assert gone not in tpl, gone
assert "<h3>Защо е тук</h3>" in tpl and "<p>Защо е тук: {{ wh }}</p>" in tpl
assert not hasattr(ai_brief, "ticker_narratives") and not hasattr(ai_brief, "SYSTEM_TICKERS")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'steps.step("narratives"' not in src and "ai_brief.ticker_narratives" not in src
print("  ✓ шаблонът — „Защо е тук“; без „Защо точно сега“, „Бизнес“, „Катализатори“, „Рискове“; main не вика AI за картите")
print("\n✅ test_why_here: всичко мина")
