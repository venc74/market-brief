"""
30.10.2026 · поправки от брифа, т. 1: AI резюметата на „Наблюдавани тикъри“ — на групи по 4 тикъра (config.WATCH_AI_BATCH_SIZE, отделни извиквания), резултатите се събират;
група, която не мина, оставя без резюме само своите тикъри, с причина (ai["missing"]) и ред в секцията. Реален дефект 30.10: 14 тикъра в едно извикване → отговорът спря на
2000 токена (stop_reason max_tokens, запис в ai_truncations) и резюме нямаше за нито един.

РЕАЛНО: tests/fixtures/watch_brief_2026-10-30.json — brief["watch"] от 30.10 (14 реда с новините и Form 4) и записите за секцията в ai_truncations / ai_usage;
tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): отговорите на модела, подмененият _call_claude, провалът на втората група.
Пускане: python test_watch_ai_batches.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_wbatch_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_brief_2026-10-30.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 0. РЕАЛНИЯТ дефект от 30.10 ──")
rows = [r for r in FX["watch"] if not r["quiet"]]
assert len(FX["watch"]) == 14 and not any((r.get("ai") or {}).get("summary") for r in FX["watch"])
assert FX["ai_truncations"] == [{"section": "Наблюдавани тикъри", "max_tokens": 2000, "output_tokens": 2000, "model": "claude-sonnet-4-6"}]
print(f"  ✓ 14 тикъра, {len(rows)} със събития — едно извикване, спряло на 2000 токена; резюмета няма")

print()
print("── 1. на групи по 4 — отделни извиквания, резултатите се събират (СИНТЕТИЧНИ отговори) ──")
calls = []
def fake(system, user, max_tokens=0, **k):
    ts = re.findall(r'"ticker": "([A-Z]+)"', user)
    calls.append(ts)
    if "CRCL" in ts and fail["on"]:
        raise ai_brief.TruncatedResponse("СИНТЕТИЧНО: max_tokens")
    return json.dumps({"digests": [{"ticker": t, "summary": f"Резюме за {t}.", "insider_read": "", "cross_reference": ""} for t in ts]}, ensure_ascii=False)
ai_brief._call_claude = fake
fail = {"on": False}
with q():
    out = ai_brief.watch_ticker_digest(rows, {"active_theses": [], "cot_markets": [], "leading_sectors": []})
assert config.WATCH_AI_BATCH_SIZE == 4 and [len(c) for c in calls] == [4] * (len(rows) // 4) + ([len(rows) % 4] if len(rows) % 4 else [])
assert [r["ticker"] for r in out] == [r["ticker"] for r in rows] and all(r["ai"]["summary"] == f"Резюме за {r['ticker']}." for r in out)
print(f"  ✓ {len(rows)} тикъра → {len(calls)} извиквания ({', '.join(str(len(c)) for c in calls)}); всеки — със своето резюме, в реда на списъка")

print()
print("── 2. една група не минава — само нейните тикъри са без резюме, с причина; редът в секцията ──")
calls.clear(); fail["on"] = True
with q():
    out = ai_brief.watch_ticker_digest(rows, {"active_theses": [], "cot_markets": [], "leading_sectors": []})
bad = next(c for c in calls if "CRCL" in c)
assert all(r["ai"] == {"missing": "отговорът е отрязан (лимитът за изход)"} for r in out if r["ticker"] in bad)
assert all(r["ai"]["summary"] for r in out if r["ticker"] not in bad)
by = {r["ticker"]: r for r in out}
b = copy.deepcopy(B19); b["watch"] = [by.get(r["ticker"], {**r, "ai": {}}) for r in FX["watch"]]
with q():
    page = render.render_dashboard(b, publish=False)
t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", page)))
want = "AI резюме днес няма за: " + ", ".join(f"{x} (отговорът е отрязан (лимитът за изход))" for x in bad) + " — групата им не мина"
assert want in t, want
good = next(r["ticker"] for r in out if r["ticker"] not in bad)
assert f"Резюме за {good}." in page and not any(f"Резюме за {x}." in page for x in bad)
print(f"  ✓ групата {', '.join(bad)} — без резюме, другите с; „AI резюме днес няма за: … — групата им не мина“")
assert ai_brief._SECTION_LABELS["_watch_digest_batch"] == "Наблюдавани тикъри"
print("\n✅ test_watch_ai_batches: всичко мина")
