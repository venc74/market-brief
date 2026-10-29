"""
29.10.2026 · чужди символи (CJK) в AI текста: маха се ЦЯЛОТО изречение, не само символите, и се отбелязва в ai_truncations (kind "cjk") + ред в банера.
Случаят: why_now на WSM на 29.10 — „Пробивът над $256.86 би бил технически cataly за momentum, …“; по елиминация (json_repair не дава „cataly“; другите филтри не махат букви)
моделът е продължил „cataly…“ с китайски, както на 21.09 „потенциален催化剂“ (= catalyst), а филтърът от 28.09 е махнал само символите. В историята CJK е винаги дума насред изречение:
6 появи 06.07–28.09 (損害, 底, 升级, 映射, 催化剂, 純 — преди филтъра, видими в данните); след филтъра единственият видим остатък е „cataly“ (29.10; сканирани всички латински думи
от 28.09 насам, които са начало на по-дълга дума от историята — останалите са истински английски думи).

РЕАЛНО: tests/fixtures/cjk_sentences_2026-10-29.json — всичките 6 низа с CJK от публикуваните брифове и why_now на WSM от 29.10 (публикуваният, след филтъра);
tests/fixtures/brief_2026-10-19.json — за рендера.
СИНТЕТИЧНО (означено): реконструкцията на суровия why_now на WSM (какво е стояло след „cataly“, не се знае) и подмененият requests.post (без мрежа).
Пускане: python test_cjk_sentences.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cjk_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "cjk_sentences_2026-10-29.json").read_text(encoding="utf-8"))
CASES = FX["cases"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
assert [c["date"] for c in CASES] == ["2026-07-06", "2026-07-15", "2026-08-07", "2026-09-10", "2026-09-21", "2026-09-28"]

print("── 1. шестте РЕАЛНИ низа с CJK: изречението пада цяло, останалите остават ──")
for c in CASES:
    s = c["text"]
    with q():
        out = ai_brief._fix_translit(s)
    assert not ai_brief._CJK_RE.search(out)
    sents = re.split(r"(?<=[.!?…])\s+", s)
    bad = [x for x in sents if ai_brief._CJK_RE.search(x)]
    assert len(bad) == 1 and bad[0] not in out                                                              # изречението с CJK — го няма
    for x in sents:
        if x not in bad and not re.search(r"[A-Za-z]{2,}[а-я]|[а-я][A-Za-z]{2,}", x):                       # (другите изречения — без промяна; смесените думи може да се пипнат от другите поправки)
            assert x in out, (c["date"], x[:60])
    print(f"  ✓ {c['date']} {c['path']}: махнато «{bad[0][:70]}…» ({len(s)} → {len(out)} знака)")
cat = next(c for c in CASES if c["date"] == "2026-09-21")
assert cat["text"].startswith("Earnings на 2026-10-29 (38 дни) — потенциален催化剂 ако")
with q():
    assert ai_brief._fix_translit([cat["text"], "Следващ катализатор"]) == ["Следващ катализатор"]           # СИНТЕТИЧНО второ: елемент само от изречението с CJK пада от списъка
print("  ✓ 21.09 catalysts[0] (едно изречение) — елементът пада от списъка")

print()
print("── 2. WSM 29.10: през _parse_json — изречението пада, запис в ai_truncations с етикета на секцията ──")
pub = FX["wsm_2026_10_29"]["ai"]["why_now"]
assert "технически cataly за momentum" in pub                                                               # РЕАЛНО: публикуваното след стария филтър
raw_why = pub.replace("технически cataly за", "технически cataly催化剂 за")                               # СИНТЕТИЧНО: реконструкция на суровия отговор
first, second = pub.split(". ", 1)
config.ANTHROPIC_API_KEY = "SYNTHETIC-NOT-A-KEY"
raw = json.dumps({"tickers": [{**FX["wsm_2026_10_29"]["ai"], "why_now": raw_why}]}, ensure_ascii=False)


class _Resp:
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": raw}], "stop_reason": "end_turn", "usage": {"input_tokens": 3166, "output_tokens": 690}}


ai_brief.requests.post = lambda *a, **k: _Resp()
ai_brief.TRUNCATIONS.clear()


def _narratives_for_batch():                                                                                # името носи етикета (както в кода)
    return ai_brief._parse_json(ai_brief._call_claude(ai_brief.SYSTEM_TICKERS, "СИНТЕТИЧЕН промпт", max_tokens=8000))


buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = _narratives_for_batch()
why = out["tickers"][0]["why_now"]
assert why == first + "." and "cataly" not in why
T = copy.deepcopy(ai_brief.TRUNCATIONS)
assert len(T) == 1 and T[0]["kind"] == "cjk" and T[0]["section"] == "Тикър наративи" and T[0]["chars"] == "催化剂" and T[0]["removed"][0].startswith("Пробивът над $256.86")
assert "чужди символи '催化剂' — махнато цялото изречение" in buf.getvalue()
print(f"  ✓ why_now: «{why[:80]}…» — без „cataly“; ai_truncations: Тикър наративи, cjk «{T[0]['removed'][0][:50]}…»")

print()
print("── 3. банерът ──")
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19)
b["ai_truncations"] = T
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Тикър наративи — махнато изречение с чужди символи (催化剂) «Пробивът над $256.86 би бил технически cataly催化剂 за momentum" in page
print("  ✓ „Тикър наративи — махнато изречение с чужди символи (催化剂) «Пробивът над $256.86 …»“")
print("\n✅ test_cjk_sentences: всичко мина")
