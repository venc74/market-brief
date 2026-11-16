"""
16.11.2026 (пакет 16.11, т. 15): купувач във висяща сделка (BKH купува NWE) — информативен етикет „купувач в сделка: придобива NWE (обявена 18.08.2025) — само информация,
не изключва“ върху картите, реда в радара и наблюдаваните; тикърът остава във всички скенери. Тикърът на купувача — по името от 8-K: първо имената от таблиците на Wikipedia
(„Black Hills Corporation“ → BKH), после картата на SEC (заглавие с наставка за щат: „black hills sd“); частният купувач (Mountain Holding → EQH) — без етикет.

РЕАЛНО: tests/fixtures/deal_state_pending_2026-11-16.json — висящите сделки (data/deal_state.json към 16.11: CART ← DoorDash, EQH ← Mountain Holding, NWE ← Black Hills);
tests/fixtures/sec_name_map_deals_2026-11-16.json — записите от data/sec_tickers.json (SEC company_tickers) за DASH, BKH, NWE, CART, EQH, KDP; wiki_sp400_2026-10-30.html.gz — имената
на S&P 400; brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): картите.
Пускане: python test_deal_buyer.py
"""
import sys, gzip, io, copy, json, pathlib, tempfile, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_buyer_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import spinoff_watch as sw, render

FXD = ROOT / "tests" / "fixtures"
PEND = json.loads((FXD / "deal_state_pending_2026-11-16.json").read_text(encoding="utf-8"))["pending"]
SEC = json.loads((FXD / "sec_name_map_deals_2026-11-16.json").read_text(encoding="utf-8"))["map"]
t400 = next(t for t in pd.read_html(io.StringIO(gzip.decompress((FXD / "wiki_sp400_2026-10-30.html.gz").read_bytes()).decode("utf-8", "replace"))) if "Symbol" in t.columns)
NAMES = dict(zip(t400["Symbol"].astype(str), t400["Security"].astype(str)))

print("── 1. РЕАЛНО: тикърът на купувача ──")
assert sw.buyer_ticker("Black Hills Corporation", NAMES, SEC) == "BKH"                # Wikipedia (S&P 400)
assert sw.buyer_ticker("Black Hills Corporation", {}, SEC) == "BKH"                    # SEC: „black hills sd“
assert sw.buyer_ticker("DoorDash, Inc.", NAMES, SEC) == "DASH" and sw.buyer_ticker("Mountain Holding, Inc.", NAMES, SEC) is None
print("  ✓ Black Hills → BKH (Wikipedia и SEC с „/SD/“), DoorDash → DASH, Mountain Holding — частен, без тикър")

print("── 2. РЕАЛНО: етикетите от висящите сделки към 16.11 ──")
M = sw.buyer_marks(PEND, NAMES, SEC)
assert sorted(M) == ["BKH", "DASH"]
assert M["BKH"]["text"] == "купувач в сделка: придобива NWE (обявена 18.08.2025) — само информация, не изключва"
assert M["DASH"]["text"] == "купувач в сделка: придобива CART (обявена 28.10.2026) — само информация, не изключва"
cards = [{"ticker": "BKH"}, {"ticker": "NWE"}]                                             # СИНТЕТИЧНО
assert sw.annotate_buyers([cards], M) == 1 and cards[0]["deal_buyer"] == M["BKH"]["text"] and "deal_buyer" not in cards[1]
print(f"  ✓ BKH — „{M['BKH']['text']}“; DASH — CART")

print("── 3. страницата: радарът ──")
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19)
_, radar = render.split_canslim(b["watchlist"])
t = radar[0]["ticker"]
b["deal_buyers"] = {t: M["BKH"]["text"]}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert M["BKH"]["text"] in page
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "spinoff_watch.buyer_marks(spinoff_watch.pending_tickers(), screener.LAST_UNIVERSE_NAME, dataroma._ticker_map())" in src
print("  ✓ редът в радара; картите и наблюдаваните — същият текст")
print("\n✅ test_deal_buyer: всичко мина")
