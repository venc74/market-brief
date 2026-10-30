"""
30.10.2026 · разходката, т. 8: разделът „Геополитически тези · мониторинг“ — махнат изцяло: кошниците в config (THESIS_BASKETS, подгрупите, THESIS_REVIEW_DAYS),
тригерите им (macro_layer.thesis_monitor / _trigger_fires / thesis_review), AI подборът на свързани новини (ai_brief.thesis_news_pick, _anchor_match, THESIS_CHECK_DIAG,
news_aggregator.raw_pool — единственият му потребител), карето „Контекст“ (src/thesis_context.py) и active_theses в контекста на AI резюметата на наблюдаваните тикъри.
Остават: COT тезите (друг раздел — CSS класовете .theses / .thesis / .thesis-head / .thesis-name / .thesis-chain са техни) и таблицата .ctx-table (лидерите в секторната карта).

Измерено (РЕАЛНО, data/ 21–30.10, 8 брифа): извикването „Тези: свързани новини“ — средно 1 890 входни + 116 изходни токена на ден; плюс 1 yf.download (~25 тикъра)
и tk.calendar за тикърите в карета.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — бриф с 6 тези и thesis_check_diag (стар бриф: страницата вече не ги показва).
Пускане: python test_theses_removed.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, importlib.util
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_theses_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render, ai_brief, macro_layer, news_aggregator

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. кодът ──")
assert not any(hasattr(config, n) for n in ("THESIS_BASKETS", "THESIS_REVIEW_DAYS", "ENABLE_THESIS_CONTEXT", "THESIS_PICK_MAX_CANDIDATES", "THESIS_PICK_MAX_PER_THESIS", "THESIS_PICK_MAX_TOKENS"))
assert not any(hasattr(macro_layer, n) for n in ("thesis_monitor", "thesis_review", "_trigger_fires"))
assert not any(hasattr(ai_brief, n) for n in ("thesis_news_pick", "_anchor_match", "THESIS_CHECK_DIAG", "SYSTEM_THESIS_PICK")) and "thesis_news_pick" not in ai_brief._SECTION_LABELS
assert not hasattr(news_aggregator, "raw_pool") and importlib.util.find_spec("src.thesis_context") is None
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert not re.search(r"thesis_monitor|thesis_context|thesis_news_pick|active_theses|\"theses\"|thesis_check_diag|raw_pool", main_src)
print("  ✓ config, macro_layer, ai_brief, news_aggregator и main — без тезите; src/thesis_context.py го няма")

print()
print("── 2. страницата: РЕАЛЕН стар бриф (19.10) с 6 тези — разделът и карето не се показват; COT тезите остават ──")
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(copy.deepcopy(B19), publish=False)
assert len(B19["theses"]) == 6 and "thesis_check_diag" in B19
assert "Геополитически тези" not in page and "Контекст · само данни" not in page and "thesis-ctx" not in page and "Тригер активен" not in page
assert all(t["chain"] not in page for t in B19["theses"])
assert ".theses {" in page and ".thesis-chain {" in page and ".ctx-table {" in page                  # COT картите и таблицата на лидерите
print("  ✓ без „Геополитически тези“, без карето „Контекст“ и веригите на тезите; CSS-ът на COT картите и .ctx-table остава")

print()
print("── 3. AI резюметата на наблюдаваните тикъри — контекстът е без active_theses ──")
seen = {}
ai_brief._call_claude = lambda system, user, **k: (seen.setdefault("u", user), json.dumps({"digests": []}))[1]   # СИНТЕТИЧНО: подменен модел
row = {"ticker": "TDOC", "news": [{"title": "x", "publisher": "y"}], "insider": [], "insider_cluster": False, "quiet": False}
with contextlib.redirect_stdout(io.StringIO()):
    ai_brief.watch_ticker_digest([row], {"cot_markets": ["Gold"], "leading_sectors": ["Енергетика"]})
assert "active_theses" not in seen["u"] and '"leading_sectors": ["Енергетика"]' in seen["u"]
assert '"active_theses"' not in main_src
print("  ✓ main подава само cot_markets и leading_sectors")
print("\n✅ test_theses_removed: всичко мина")
