"""
30.10.2026 · поправки от брифа, т. 4 (проверката в кода): всяко число в макро разказа трябва да го има във входовете на деня (новини, уреди, макро / фючърси, ротация, крипто) с
разумна точност — иначе частта с него се маха (news_aggregator._why_trim_sentence, като при „защо“ в новините), а при нечетим остатък — изречението; запис в
ai_macro["numbers_fixed"]. Разумна точност: закръглено до знаците в текста (17.2 ← 17.21, 13 ← 12.9), без знак, % ↔ б.п., „1,016“ — хиляди; числата — само от стойностите
(не от имената на полетата), от датите — само годината.
Разказът не цитира нашите проучвания: от контекста на уредите е махнат текстът „термометър, не предсказание: в проучването ни …“ (30.10 разказът го цитира).

Измерено (РЕАЛНО): последните 24 текста (29.09–30.10) срещу входовете, които моделът е виждал всеки ден (30.10 — новият контекст, без текста на проучването) —
1 от 136 изречения с число без опора: 30.10, „47–72%“ от цитата на проучването (вярно попадение по новото правило); 0 фалшиви.

РЕАЛНО: tests/fixtures/narrative_numbers_2026-10-30.json — 24-те текста и числата от входовете им; входовете и текстът на брифа от 30.10.
СИНТЕТИЧНО (означено): измисленото число в т. 3, подмененият _call_claude.
Пускане: python test_narrative_numbers.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_nnum_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief as ab, news_aggregator as na

FX = json.loads((ROOT / "tests" / "fixtures" / "narrative_numbers_2026-10-30.json").read_text(encoding="utf-8"))
B = FX["b30"]

print("── 1. РЕАЛНИТЕ 24 текста срещу входовете, които моделът е виждал — пада само цитатът на проучването от 30.10 ──")
n_sent, hits = 0, {}
for d in FX["days"]:
    new, fixed = ab.check_narrative_numbers(d["macro_brief"], d["values"])
    if fixed:
        hits[d["date"]] = [f["removed"] for f in fixed]
    else:
        assert new == "\n\n".join(ab.paragraphs(d["macro_brief"])), d["date"]
    n_sent += sum(len(na._WHY_SENT.split(p)) for p in ab.paragraphs(d["macro_brief"]))
assert len(FX["days"]) == 24 and n_sent == 136 and hits == {"2026-10-30": [["47–72%"]]}, hits
print(f"  ✓ 1 от {n_sent} изречения (29.09–30.10): 30.10 „47–72%“ — цитатът на проучването; 0 фалшиви")

print()
print("── 2. 30.10 с новия контекст: цитатът на проучването вече не е във входовете — „47–72%“ пада ──")
ctx = ab._thermo_context(B["thermometer"])
sofr = next(c for c in ctx if c["name"].startswith("SOFR"))
assert "проучването" not in sofr["label"] and "не влиза в режима" not in sofr["label"] and sofr["label"].startswith("+4.0 б.п. към 28.10")
vals = ab.narrative_sources(B["macro"], B["rotation"], B["thermometer"], B["news"], B["crypto"])
new, fixed = ab.check_narrative_numbers(B["ai_macro"]["macro_brief"], vals)
assert [f["removed"] for f in fixed] == [["47–72%"]] and "47–72%" not in new and new.count("\n\n") == 2
assert "Intel надолу с 22%" in new and "$103.31" in new and "$1,016 млрд" in new                                   # с опора — непокътнати (и хилядите)
print("  ✓ махнато: 47–72% (цитатът на проучването); останалите числа (Intel 22%, WTI $103.31, TGA $1,016 млрд) — с опора")

print()
print("── 3. през macro_and_sector_brief — запис в numbers_fixed (СИНТЕТИЧНО измислено число) ──")
story = "Петролът скочи до $120 заради атаката в Ормузкия проток, а WTI е на $103.31.\n\nЗа нас: енергетиката печели."
ab._call_claude = lambda system, user, **k: json.dumps({"macro_brief": story, "sector_logic": []}, ensure_ascii=False)
with contextlib.redirect_stdout(io.StringIO()) as log:
    out = ab.macro_and_sector_brief(B["macro"], B["rotation"], B["thermometer"], news=B["news"], crypto=B["crypto"])
assert out["macro_brief"] == "Петролът скочи заради атаката в Ормузкия проток, а WTI е на $103.31.\n\nЗа нас: енергетиката печели."
assert out["numbers_fixed"][0]["removed"] == ["до $120"] and "число без опора във входовете" in log.getvalue()
assert ab._supported("17.2", [17.21]) and ab._supported("13", [12.9]) and ab._supported("44", [0.44]) and not ab._supported("13", [12.4])
print("  ✓ „до $120“ пада, $103.31 остава; numbers_fixed и ред в лога; точността: 17.2 ← 17.21, 13 ← 12.9, 44 б.п. ← 0.44%, 13 ↚ 12.4")
two, f2 = ab.check_narrative_numbers("Геополитиката добавя премия (WTI +90.14, но -2.94% за 5 дни). За нас: енергетиката.", [5.0])     # РЕАЛНО изречение от 08.10, празни входове
assert two == "За нас: енергетиката." and f2[0]["kept"] is None                                                                    # 2+ числа без опора — пада цялото
print("  ✓ 2+ числа без опора в изречението („(WTI +90.14, но -2.94% …)“) — пада цялото, не остава „(WTI, но )“")
print("\n✅ test_narrative_numbers: всичко мина")
