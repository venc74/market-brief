"""
29.10.2026 · разходката, т. 3, решение 3: празно „защо“ в „Значими новини“ (29.10: 2 от 8 — CNBC „Fed meeting recap…“ и FT „Fed holds fire…“; 23.10: AP за jobless claims).
Причината — нашият филтър, не моделът: pick_verbatim отхвърля ред с празно "why" от модела ("празно why" → отпада), т.е. показан ред с празно "why" е бил непразен и е изпразнен
от _why_numbers — изречение с число, което го няма в заглавието и резюмето, падаше цяло, а "why" обикновено е едно изречение. Сега пада само частта с числото
(числото с мярката и количествения предлог); цялото изречение — само ако остатъкът е под 4 думи или пак носи число. Изреченията се делят само пред главна буква / цифра
(до 29.10 и след "млрд. долара").

РЕАЛНО: tests/fixtures/why_numbers_2026-10-29.json — всички 39 "why" от историята (13.06–29.10) с число извън заглавието и трите реда с празно "why"; tests/fixtures/news_raw_pool_2026-10-15.json.
СИНТЕТИЧНО (означено): реконструкциите на изпразнените "why" от 29.10 в т. 2 (суровият отговор не е запазен — логът не е четен), отговорът на модела в т. 3.
Пускане: python test_why_trim.py
"""
import sys, json, pathlib, tempfile, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_why_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na

FX = json.loads((ROOT / "tests" / "fixtures" / "why_numbers_2026-10-29.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНИТЕ 39 \"why\" с число извън заглавието: изрязва се частта, нито едно не остава празно ──")
assert len(FX["cases"]) == 39
for c in FX["cases"]:
    out, rem = na._why_numbers(c["why"], c["headline"])
    assert (out, rem) == (c["expected"], c["removed"]), c["date"]
    assert out and len(out) < len(c["why"])
by = lambda d, start: next(c["expected"] for c in FX["cases"] if c["date"] == d and c["why"].startswith(start))
show = [("2026-07-15", "Блокадата на Ормузкия проток застрашава световните петролни доставки, което директно движи цените на суровия петрол и енергийния сектор."),
        ("2026-09-17", "Централното събитие за деня — Fed повиши лихвата под Warsh, което директно удря equity valuations, bond yields и USD."),
        ("2026-08-05", "Силни резултати при AMD с ръст в data center сегмента, но негативната реакция на акцията сигнализира завишени очаквания и потенциален натиск върху целия AI/chip сектор."),
        ("2026-09-21", "Позитивният тон преди Trump-Xi срещата намалява trade war риска и подкрепя risk-on настроения в equity и FX пазарите."),
        ("2026-10-22", "CSI 300 със спад от юнския връх генерира негативен сентимент към EM активи, суровини и компании с голяма китайска експозиция."),
        ("2026-10-29", "Сделка при оценка разчупва вялия M&A пазар и движи акциите на delivery и grocery tech сектора.")]
for d, want in show:
    assert want in [c["expected"] for c in FX["cases"] if c["date"] == d], d
    print(f"  ✓ {d}: «{want[:95]}…»")
dd = next(c for c in FX["cases"] if c["date"] == "2026-10-29")
assert dd["why"].startswith("Сделка при оценка от около 17 млрд. долара разчупва")                         # до 29.10 изречението се делеше след "млрд." — "долара разчупва …" оставаше отделно
assert "S&P 500 компании" in by("2026-08-03", "Над 130 S&P 500 компании") and "10-year yield" in by("2026-09-16", "10-year yield на")
print("  ✓ имената не се пипат („S&P 500“, „10-year“); 29.10 DoorDash — едно изречение, не две (след „млрд. долара“)")

print()
print("── 2. трите РЕАЛНИ реда с празно \"why\" — и механизмът (СИНТЕТИЧНИ реконструкции на суровото изречение) ──")
assert [(e["date"], e["source"]) for e in FX["empty_why"]] == [("2026-10-23", "AP Business"), ("2026-10-29", "CNBC"), ("2026-10-29", "Financial Times")]
assert all(e["why"] == "" for e in FX["empty_why"])
for e, raw, want in (
        (FX["empty_why"][2], "Fed запазва лихвите на 3.75–4% въпреки по-високата инфлация, което засилва hawkish очакванията и натиска облигациите.",
         "Fed запазва лихвите въпреки по-високата инфлация, което засилва hawkish очакванията и натиска облигациите."),
        (FX["empty_why"][1], "Warsh съкращава заседанията до 6 годишно — по-рядка комуникация и по-голяма волатилност около всяко решение.",
         "Warsh съкращава заседанията годишно — по-рядка комуникация и по-голяма волатилност около всяко решение."),
        (FX["empty_why"][0], "Молбите за помощ при безработица паднаха под 200 000 — силен пазар на труда намалява шанса за понижение на лихвите.",
         "Молбите за помощ при безработица паднаха — силен пазар на труда намалява шанса за понижение на лихвите.")):
    have = {x.replace(",", ".") for x in na._NUM_RE.findall(e["headline"])}
    old = " ".join(s for s in re.split(r"(?<=[.!?])\s+", raw) if not [x for x in na._NUM_RE.findall(na._NUM_NAME_RE.sub(" ", s)) if x.replace(",", ".") not in have])   # кодът до 29.10
    out, rem = na._why_numbers(raw, e["headline"])
    assert old == "" and out == want, (out, rem)
    print(f"  ✓ {e['date']} {e['source']}: до 29.10 → празно; сега → «{out[:70]}…» (махнато: {rem})")

print()
print("── 3. pick_verbatim: редът остава със съкратеното \"why\", махнатото е в причините (СИНТЕТИЧЕН отговор, РЕАЛЕН пул от 15.10) ──")
POOL = json.loads((ROOT / "tests" / "fixtures" / "news_raw_pool_2026-10-15.json").read_text(encoding="utf-8"))["items"]
i = 0
news, dropped = na.pick_verbatim([{"i": i, "h": " ".join(POOL[i]["title"].split()[:6]), "why": "Натиск върху доходностите с 12 б.п. за седмица, което удря growth акциите."}], POOL, 8)
assert news[0]["why"] == "Натиск върху доходностите за седмица, което удря growth акциите." and dropped[0]["removed"] == ["с 12 б.п."]
assert dropped[0]["reason"] == "число в why, което го няма в заглавието и резюмето — махната е частта с него"
print(f"  ✓ «{news[0]['why']}» · в причините: {dropped[0]['removed']}")

print()
print("── 4. пак пада цялото изречение, когато числото е самото твърдение (СИНТЕТИЧНО) ──")
assert na._why_numbers("Подкрепа за полупроводниците. Печалбата е +40% — ориентир за AI.", "TSMC") == ("Подкрепа за полупроводниците.", ["Печалбата е +40% — ориентир за AI."])
assert na._why_numbers("Ръст от 40%.", "TSMC") == ("", ["Ръст от 40%."])
print("  ✓ „Печалбата е +40% — …“ и „Ръст от 40%.“ — изречението пада (под 4 думи без числото)")
print("\n✅ test_why_trim: всичко мина")
