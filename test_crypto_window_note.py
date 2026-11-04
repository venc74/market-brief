"""
04.11.2026 · четвърти преглед, С5: крипто секцията — бележка докъде стигат фийдовете (както под новините). Заглавието „Крипто · последните 30ч“ (в понеделник ≥ 72 ч) обещаваше
прозорец, който Cointelegraph (~30 заглавия) и CoinDesk (25) не покриват.

РЕАЛНО: brief["news_window"] и brief["crypto"]["pool_sources"] от брифа на 03.11.2026 (data/2026-11-03.json — вписани тук: тестовете не четат data/):
прозорец на новините от 02.11 06:30 UTC, 24.07 ч; крипто 30 ч; Cointelegraph 28 заглавия до 02.11 01:51Z, CoinDesk 25 до 02.11 05:18Z. tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): пълното покритие и празният фийд в т. 2.
Пускане: python test_crypto_window_note.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cryptonote_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

NW = {"since": "2026-11-02T06:30:00+00:00", "hours": 24.07, "day_queries": 0, "crypto_hours": 30}
PS = {"Cointelegraph": {"count": 28, "oldest": "2026-11-02T01:51Z"}, "CoinDesk": {"count": 25, "oldest": "2026-11-02T05:18Z"}}

print("── 1. РЕАЛНО 03.11 ──")
n = render.crypto_window_note(NW, PS)
assert n == ("Прозорец: 30 ч (от пн 02.11 00:34 UTC). Не стигат до началото му: Cointelegraph — до пн 02.11 01:51 (28 заглавия) · CoinDesk — до пн 02.11 05:18 (25 заглавия)"
             " — фийдът държи само последните си заглавия; по-старото не е проверено."), n
print("  ✓", n)

print("── 2. пълно покритие → няма бележка; празен фийд → „без заглавия“; стар бриф → None ──")
assert render.crypto_window_note(NW, {"Cointelegraph": {"count": 40, "oldest": "2026-11-02T00:10Z"}}) is None
assert "CoinDesk — без заглавия в прозореца" in render.crypto_window_note(NW, {"Cointelegraph": {"count": 40, "oldest": "2026-11-02T00:10Z"}, "CoinDesk": {"count": 0, "oldest": None}})
assert render.crypto_window_note({}, PS) is None and render.crypto_window_note(NW, None) is None
print("  ✓")

print("── 3. страницата ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b["news_window"] = NW
b["crypto"] = {"ok": True, "items": [], "pool": 53, "pool_sources": PS}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "Крипто · последните 30ч" in page and "Не стигат до началото му: Cointelegraph — до пн 02.11 01:51 (28 заглавия)" in page
print("  ✓ под крипто секцията")
print("\n✅ test_crypto_window_note: всичко мина")
