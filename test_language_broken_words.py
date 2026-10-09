"""
Езиков филтър · «нарастив/нарастива» и «мулти плиер / мулти-плиер» (09.10.2026). Две несъществуващи форми от макро брифа: «AI capex нарастива» (07.10), «AI capex нарастив преди» (09.10) и «мултипликатор» счупено на две
(09.10: «AI hardware мулти плиера», «мулти-плиер компресия», «мулти-плиера»). Първите са речникова замяна (_CYR_WORD_FIX), второто — фраза (_fix_broken_phrases, пази падежа).

РЕАЛНО: изреченията от публикуваните бриф-ове на 07.10 и 09.10 (tests/fixtures/language_broken_words_2026-10-09.json — само низовете със засегнатите думи) Измерването върху ВСИЧКИТЕ текстове на 83-те реални бриф-а е извън репото (2+3 срещания, нито едно легитимно). СИНТЕТИЧНО (маркирано): граничните примери (главна буква, множествено число, цели думи, които не бива да се пипат).
Пускане: python test_language_broken_words.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "language_broken_words_2026-10-09.json").read_text(encoding="utf-8"))

def fix(s):
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        out = ai_brief._fix_translit(s)
    return out, buf.getvalue()

print("── 1. РЕАЛНИТЕ изречения от 07.10 и 09.10 ──")
assert len(FX["strings"]) == 4 and any("мулти плиера" in x["text"] for x in FX["strings"])          # и формата с интервал е в реален текст (в същия низ като «нарастив»)
MAP = [("нарастива", "нарастване"), ("нарастив", "нарастване"), ("мулти плиера", "мултипликатора"), ("мулти-плиера", "мултипликатора"), ("мулти-плиер", "мултипликатор")]   # по-дългите първи; независимо от кода
def expected(text):
    for a, b in MAP:
        text = text.replace(a, b)
    return text
for item in FX["strings"]:
    out, log = fix(item["text"])
    assert out == expected(item["text"]), (item["date"], out)               # целият текст: сменена е САМО засегнатата дума
    assert "несъществуваща дума заменена" in log
    k = item["text"].index(item["probe_exact"])
    print(f"  ✓ {item['date']}: «…{item['text'][max(0, k - 28):k + len(item['probe_exact']) + 22]}…» → «{item['expect_contains'][0]}»; останалият текст е непроменен")

print()
print("── 2. граници (СИНТЕТИЧНИ) ──")
cases = {
    "Мулти плиер компресия е риск": "Мултипликатор компресия е риск",
    "мулти-плиерът нараства": "мултипликаторът нараства",
    "двата мулти плиери": "двата мултипликатори",
    "мулти-плиерите на сектора": "мултипликаторите на сектора",
    "ръстът на нарастива е бавен": "ръстът на нарастване е бавен",
}
for src, want in cases.items():
    assert fix(src)[0] == want, (src, fix(src)[0])
for whole in ("мултипликатор на оценката", "историческите мултипли", "мултиплът изисква ускоряване", "нарастващ интерес", "нарастване на TGA", "мултипликаторна компресия", "multi-plier"):
    assert fix(whole)[0] == whole, (whole, fix(whole)[0])
print("  ✓ главна буква, падежи (-а, -ът, -и, -ите) се пазят; цели думи («мултипликатор», «мултипли», «мултиплът», «нарастващ», «нарастване», «мултипликаторна») и латинското multi-plier не се пипат")
print("\n✅ test_language_broken_words: всичко мина")
