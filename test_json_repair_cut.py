"""
29.10.2026 · json_repair реже текста: макро текстът на 29.10 свърши на «…че ново покачване „не би било грешка» (329 знака), а моделът е завършил нормално (stop_reason end_turn,
1735 / 8000 токена) — ai_truncations беше празен. Причината: българският цитат е затворен с ASCII " и след него идва запетая; json.loads пада, json_repair затваря низа на кавичката
и изпуска останалото без грешка. Поправката (ai_brief._parse_json + repair_cuts): изрязан низ (в суровия отговор продължава с текст, не с JSON синтаксис; или с отворена „; или поправеният
JSON е с ≥ 40 знака по-къс) → ЕДИН повторен опит на извикването; ако пак — „✂ текстът е непълен днес“ в самото поле, запис в ai_truncations (kind "json_repair") и ред в банера.
Правилото за кавичките — и в двата промпта с най-много проза (QUOTES_RULE).
Историята (13.06–29.10, 3322 текстови полета): 1 изрязано поле — 29.10; „…" с ASCII затваряща без изрязване — още 4 (30.09, 21.10 ×2, 29.10 „надолу").

РЕАЛНО: tests/fixtures/ai_json_cut_2026-10-29.json — публикуваният ai_macro на 29.10 и входовете на макро промпта; tests/fixtures/brief_2026-10-19.json — за рендера.
СИНТЕТИЧНО (означено): суровият отговор (не е запазен — продължението след кавичката е измислено), подмененият requests.post (без мрежа), ключът, дребните JSON случаи в т. 2.
Пускане: python test_json_repair_cut.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_jcut_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_json_cut_2026-10-29.json").read_text(encoding="utf-8"))
AM = FX["ai_macro"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
CUT = AM["macro_brief"]                                                                                     # РЕАЛНО: публикуваният (изрязан) текст
assert len(CUT) == 329 and CUT.endswith("ново покачване „не би било грешка") and FX["ai_usage_macro"]["stop_reason"] == "end_turn"
CONT = ", подкрепя тезата за по-висока крайна доходност и задържа натиска върху growth имената."               # СИНТЕТИЧНО: продължението не е запазено
FULL = CUT + "“" + CONT


def raw_of(macro_brief_json: str) -> str:
    """Суровият отговор: РЕАЛНИТЕ полета на 29.10 (sector_logic, regime_comment) + macro_brief, както е подаден."""
    tail = json.dumps({"sector_logic": AM["sector_logic"], "regime_comment": AM["regime_comment"]}, ensure_ascii=False)[1:]
    return '{"macro_brief": "' + macro_brief_json + '", ' + tail


RAW_CUT = raw_of(CUT + '"' + CONT)                                                                         # СИНТЕТИЧНО: ASCII " затваря цитата, после запетая
RAW_OK = raw_of(json.dumps(FULL, ensure_ascii=False)[1:-1])

print("── 1. json_repair реже на кавичката; repair_cuts го хваща ──")
import json_repair
rep = json_repair.loads(RAW_CUT)
assert rep["macro_brief"] == CUT and rep["regime_comment"] == AM["regime_comment"]                         # точно публикуваното на 29.10
cuts = ai_brief.repair_cuts(RAW_CUT, rep)
assert [c["field"] for c in cuts] == ["macro_brief"] and cuts[0]["tail"].endswith("„не би било грешка") and cuts[0]["lost"].startswith(", подкрепя")
assert ai_brief.repair_cuts(RAW_OK, json.loads(RAW_OK)) == []
print(f"  ✓ поправеният macro_brief = публикуваният (329 знака); изрязано: «…{cuts[0]['tail'][-30:]}» → изпуснато «{cuts[0]['lost'][:30]}…»")

print()
print("── 2. обичайните поправки на json_repair не са изрязване (СИНТЕТИЧНИ малки JSON-и + РЕАЛНОТО „надолу\" от 29.10) ──")
sig = AM["сигнал"]
assert '„надолу"' in sig                                                                                    # РЕАЛНО: цитат с ASCII затваряща, след нея « (» — не запетая
for raw in ('{"a": "' + sig + '", "b": "дълъг текст за проверка"}',                                       # кавичка вътре, без запетая след нея — json_repair пази текста
            '{"a": "дълъг текст за проверка" "b": "още един дълъг текст"}',                               # липсваща запетая
            '{"a": "дълъг текст за проверка", "b": "отрязан в края на отговор',                           # отрязан в края (това се хваща от stop_reason, не тук)
            '{"a": "технически "catalyst" за momentum, но без макро подкрепа"}'):                        # кавички около дума
    r = json_repair.loads(raw)
    assert ai_brief.repair_cuts(raw, r) == [], raw[:60]
r = json_repair.loads('{"a": "дълъг текст за проверка"}\nБележка: горното е JSON.')                       # текст след JSON-а (Extra data) — не е част от полетата
assert ai_brief.repair_cuts('{"a": "дълъг текст за проверка"}\nБележка: горното е JSON.', r, extra_data=True) == []
print("  ✓ кавичка без запетая след нея, липсваща запетая, отрязан край, кавички около дума, текст след JSON-а — без сигнал")

print()
print("── 3. един повторен опит на извикването (подменен requests.post — СИНТЕТИЧНО) ──")
config.ANTHROPIC_API_KEY = "SYNTHETIC-NOT-A-KEY"
sent = []


class _Resp:
    def __init__(self, text): self.text_ = text
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": self.text_}], "stop_reason": "end_turn", "usage": {"input_tokens": 9394, "output_tokens": 1735}}


def run_macro(responses):
    sent.clear(); ai_brief.TRUNCATIONS.clear(); ai_brief.AI_USAGE.clear()
    queue = list(responses)
    ai_brief.requests.post = lambda url, headers=None, json=None, timeout=None: (sent.append(json), _Resp(queue.pop(0)))[1]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai_brief._macro_and_sector_brief_ai(FX["macro"], FX["rotation"], FX["thermometer"])
    return out, buf.getvalue()


out, log = run_macro([RAW_CUT, RAW_OK])
assert len(sent) == 2 and sent[0] == sent[1]                                                                # същото извикване
assert out["macro_brief"] == FULL and ai_brief.TRUNCATIONS == []
assert [u["section"] for u in ai_brief.AI_USAGE] == ["Макро бриф и секторна карта"] * 2                    # повторният опит носи етикета на секцията
assert "json_repair изряза текст — Макро бриф и секторна карта" in log and "един повторен опит" in log
print("  ✓ първият отговор — изрязан, повторният — цял: macro_brief е пълният текст, ai_truncations празен; 2 записа в ai_usage със същия етикет")

out, log = run_macro([RAW_CUT, RAW_CUT])
assert len(sent) == 2 and out["macro_brief"] == CUT + ai_brief.CUT_MARK
T = copy.deepcopy(ai_brief.TRUNCATIONS)                                                                      # копие — следващият run_macro го нулира
assert len(T) == 1 and T[0]["kind"] == "json_repair" and T[0]["section"] == "Макро бриф и секторна карта" and T[0]["fields"] == ["macro_brief"] and T[0]["retried"]
assert "текстът е непълен днес (json_repair — и след повторния опит)" in log
print(f"  ✓ и двата изрязани: «…{out['macro_brief'][-60:]}»; запис в ai_truncations (json_repair, macro_brief, след повторен опит)")

out, log = run_macro(['{"macro_brief": "' + FULL + '", "sector_logic": [], "regime_comment": "кратък коментар към режима"}'])
assert len(sent) == 1 and ai_brief.TRUNCATIONS == []                                                       # валиден JSON — без повторение
print("  ✓ валиден JSON — едно извикване, без запис")

print()
print("── 4. банерът и правилото в промпта ──")
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19)
b["ai_truncations"] = copy.deepcopy(T) + [{"section": "COT тези", "max_tokens": 6000, "output_tokens": 6000, "model": "claude-sonnet-4-6"}]   # СИНТЕТИЧНО: двата вида записи
b["ai_macro"]["macro_brief"] = CUT + ai_brief.CUT_MARK                                                   # изрязаният текст с маркера (както в т. 3)
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
    mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_email(b))))
assert "Макро бриф и секторна карта — текстът е непълен днес: JSON-ът на модела беше счупен (най-често кавичка в текста) и поправката изряза част — свършва на «…" in page
assert "; и повторният опит не помогна" in page and "COT тези — моделът достигна лимита си за изход (6000 токена, claude-sonnet-4-6)" in page
assert "„не би било грешка … ✂ текстът е непълен днес" in page and "„не би било грешка … ✂ текстът е непълен днес" in mail
assert ai_brief.QUOTES_RULE in ai_brief.SYSTEM_MACRO and ai_brief.QUOTES_RULE in ai_brief.SYSTEM_TICKERS and "„…“" in ai_brief.QUOTES_RULE
print("  ✓ банерът: „… — текстът е непълен днес: …; и повторният опит не помогна“, старият запис (лимит) — както преди; маркерът — и на страницата, и в имейла")
print("  ✓ правилото за кавичките — в SYSTEM_MACRO и SYSTEM_TICKERS")
print("\n✅ test_json_repair_cut: всичко мина")
