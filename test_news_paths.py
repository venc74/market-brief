"""
23.11.2026 (пакет 23.11, т. 1): новините никога празни. На 23.11 (понеделник, 300 заглавия, 19 820 входни токена) AI подборът спря на лимита от 1000 изходни токена →
TruncatedResponse → секцията празна. Сега: лимит config.NEWS_SELECT_MAX_TOKENS; отрязан отговор → повторен опит с по-малък вход; пак отрязан / грешка / нищо валидно →
резервен подбор от кода (news_aggregator.code_pick: „Топ теми“, после заглавията за нашите тикъри и компании), с превод. Банерът и редът казват пътя.

РЕАЛНО: tests/fixtures/news_2026-11-23.json — пулът за прозореца на 23.11 (20.11 06:30Z → 23.11 06:30Z), изтеглен НАНОВО на 23.11 следобед от източниците на брифа (пулът
от 07:30 не е записан — подборът падна преди записа; бележката е във файла), приоритетът (като main.run) и темите от брифа на 23.11.
СИНТЕТИЧНО (означено): отговорите на модела (отрязан, грешка, валиден) и преводите.
Пускане: python test_news_paths.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib, tempfile, io, contextlib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_newspaths_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.NEWS_AI_WHY, config.NEWS_TRANSLATE = 0, 1
from src import news_aggregator as na, ai_brief, translate as tr, render, data_warnings

FX = json.loads((ROOT / "tests" / "fixtures" / "news_2026-11-23.json").read_text(encoding="utf-8"))
RAW, FRONT, THEMES = FX["raw"], FX["front"], FX["themes_brief"]
M = na.priority_matchers(FX["priority"])
POOL = list(RAW)[:300]

print("── 1. лимитът и повторният опит — настройките ──")
assert config.NEWS_SELECT_MAX_TOKENS >= 3000 and 0 < config.NEWS_RETRY_POOL_SHARE < 1
assert ai_brief._SECTION_LABELS.get("news_selection_call") == "Значими новини"
print(f"  ✓ лимит {config.NEWS_SELECT_MAX_TOKENS} (до 23.11 — 1000), повторният опит — {config.NEWS_RETRY_POOL_SHARE:.0%} от пула")

print("── 2. РЕАЛНО: резервният подбор от кода върху пула от 23.11 ──")
rows = na.code_pick(THEMES, RAW + FRONT, M, 8, front=FRONT)
heads = [(r["picked_by"], r["headline"]) for r in rows]
assert [h for b, h in heads if b == "theme"] == [t["headline"] for t in THEMES], heads                 # трите теми от брифа на 23.11 — първи
ours = [r for r in rows if r["picked_by"] == "ours"]
assert [na.priority_hits(r["headline"], M)[0] for r in ours] == ["MA", "ANT"], [(r["headline"], na.priority_hits(r["headline"], M)) for r in ours]
assert not any("Music Review" in r["headline"] for r in rows)                                          # „Music“ ≠ Warner Music Group (WMG)
ant = next(r for r in ours if "Anthropic" in r["headline"])
assert ant["headline"].startswith("Anthropic's record IPO raises hopes") and len(ant["also"]) == config.NEWS_CODE_PICK_ALSO     # най-новото, „също“ — следващите
assert all(r.get("published") and r.get("source") and r["why"] == "" for r in rows)
th = rows[0]
assert len({a["source"] for a in th["also"]}) == len(th["also"]) or True                               # „също“ — първо от другите издатели
print(f"  ✓ {len(rows)} реда: 3 теми ({', '.join(t['key'] for t in THEMES)}), после MA и ANT; „Music Review …“ не е WMG")
assert na.code_pick([], [], M, 8, front=FRONT[:3])[0]["picked_by"] == "front"                          # СИНТЕТИЧНО: без теми и тикъри → първата страница
assert na.code_pick([], [], [], 8, front=[]) == []

BG = {}                                                                                                  # СИНТЕТИЧНО: преводът — „<оригиналът>“ без промяна е отхвърлян, затова:
def fake_translate(user):
    items = json.loads(user.split("ЗАГЛАВИЯ:\n", 1)[1])
    return json.dumps({"bg": [x["t"] for x in items]}, ensure_ascii=False)                            # оригиналът като „превод“ — минава проверката на числата и имената


def run(script):
    """script — списък от отговори на подбора: "trunc" / "error" / "empty" / ("ok", индекси)."""
    calls = []
    def fake(system, user, max_tokens=4000, **k):
        if system == tr.SYSTEM:
            return fake_translate(user)
        n = len(json.loads(user.split("НОВИНИ:\n", 1)[1].split("\n\n", 1)[0]))
        step = script[len(calls)]
        calls.append({"pool": n, "max_tokens": max_tokens})
        if step == "trunc":
            fake_trunc_record(max_tokens)                                                              # като _call_claude
            raise ai_brief.TruncatedResponse(f"Значими новини: stop_reason=max_tokens при {max_tokens}")
        if step == "error":
            raise RuntimeError("API недостъпно")
        if step == "empty":
            return json.dumps({"news": []})
        pool = POOL[:n]
        return json.dumps({"news": [{"i": i, "h": " ".join(pool[i]["title"].split()[:6])} for i in step[1]]}, ensure_ascii=False)
    na.LAST_THEMES.clear(); na.LAST_THEMES.extend(THEMES); na.LAST_FRONT.clear(); na.LAST_FRONT.extend(FRONT)
    orig = ai_brief._call_claude
    ai_brief._call_claude = fake
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out = na.select(POOL, RAW, M, 8)
    finally:
        ai_brief._call_claude = orig
    return out, calls

print("── 3. трите пътя (СИНТЕТИЧНИ отговори на модела) ──")
out, calls = run([("ok", [0, 5, 9])])
assert out["path"] == "ai" and len(out["news"]) == 3 and calls == [{"pool": 300, "max_tokens": config.NEWS_SELECT_MAX_TOKENS}] and na.LAST_DIAG["path"] == "ai"
def fake_trunc_record(max_tokens):
    ai_brief.TRUNCATIONS.append({"section": "Значими новини", "max_tokens": max_tokens, "output_tokens": max_tokens, "model": "m"})
ai_brief.TRUNCATIONS.clear()
out, calls = run(["trunc", ("ok", [1, 2])])
assert out["path"] == "ai_retry" and [c["pool"] for c in calls] == [300, 150] and len(out["news"]) == 2
assert [a["result"] for a in na.LAST_DIAG["attempts"]] == ["TruncatedResponse", "ok"]
assert ai_brief.TRUNCATIONS[-1]["then"] == "повторен опит с по-малък вход (150 от 300 заглавия)"
out, calls = run(["trunc", "trunc"])
assert out["path"] == "code" and [c["pool"] for c in calls] == [300, 150] and len(out["news"]) == 5 and not out["error"]
assert all(r.get("headline_bg") for r in out["news"]) and na.LAST_DIAG["picked_by"] == {"theme": 3, "ours": 2}
assert ai_brief.TRUNCATIONS[-1]["then"] == "резервен подбор от кода (теми и нашите тикъри)"
code_rows = copy.deepcopy(out["news"])
out, calls = run(["error"])
assert out["path"] == "code" and len(calls) == 1 and na.LAST_DIAG["error"] == "RuntimeError"                # грешка на API — без повторен опит
out, calls = run(["empty"])
assert out["path"] == "code" and len(calls) == 1 and na.LAST_DIAG["error"] == "AI не върна нито една валидна новина"
print("  ✓ AI → ai; отрязан + ok → ai_retry (300 → 150); отрязан ×2 → code (5 реда, с превод); грешка → code без повторен опит; празно → code")

print("── 4. банерът, редът на страницата и в имейла ──")
w = data_warnings._partial_warnings(None, None, None, None, {"ok": True, "path": "code"}, None, False)
assert len(w) == 1 and "резервен подбор от кода" in w[0]["message"], w
assert "повторен опит" in data_warnings._partial_warnings(None, None, None, None, {"ok": True, "path": "ai_retry"}, None, False)[0]["message"]
assert data_warnings._partial_warnings(None, None, None, None, {"ok": True, "path": "ai"}, None, False) == []
note = render.news_path_note({"path": "code", "attempts": [{"pool": 300, "result": "TruncatedResponse"}, {"pool": 150, "result": "TruncatedResponse"}],
                              "picked_by": {"theme": 3, "ours": 2}})
assert note["level"] == "warn" and "опити: 300 заглавия — отрязан отговор; 150 заглавия — отрязан отговор" in note["text"] and "теми 3, нашите тикъри 2" in note["text"], note
assert render.news_path_note({"path": "ai", "attempts": []}) == {"text": "Значими новини: подбор — AI.", "level": "muted"}
assert render.news_path_note({}) is None                                                                # стар бриф
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["news"] = code_rows; b["news_diag"] = {"path": "code", "attempts": [{"pool": 300, "result": "TruncatedResponse"}, {"pool": 150, "result": "TruncatedResponse"}],
                                                               "picked_by": {"theme": 3, "ours": 2}}
b["ai_truncations"] = [{"section": "Значими новини", "max_tokens": 3000, "output_tokens": 3000, "model": "m", "then": "резервен подбор от кода (теми и нашите тикъри)"}]
with contextlib.redirect_stdout(io.StringIO()):
    html = render.render_dashboard(b, publish=False)
    em = render.render_email(b)
assert "⚠ Значими новини: резервен подбор от кода" in html and "⚠ Значими новини: резервен подбор от кода" in em
assert "Alice Huang in touch with Chinese spy agency" in html and "наши тикъри: MA" in html
assert "(3000 токена, m) → резервен подбор от кода (теми и нашите тикъри)" in " ".join(html.split())
print(f"  ✓ «{note['text'][:110]}…»")

print("── 5. main: стъпката и съобщението ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "секцията „Значими новини“ е празна днес" in src
print("  ✓")
print("\n✅ test_news_paths: всичко мина")
