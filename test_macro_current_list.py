"""
17.11.2026 (пакет 1, т. 9): макро разказът продължаваше да цитира BLSH и CRCL (13.11, 16.11, 17.11) — махнати от наблюдаваните на 16.11. Идваха от крипто блока на
промпта (config.CRYPTO_TICKERS: COIN, HOOD, CRCL, BLSH). Сега списъкът е COIN, HOOD и промптът получава само текущия списък — и при стари данни (кешът на деня).

РЕАЛНО: изреченията на разказа от 17.11 (data/2026-11-17.json — „BLSH -12.2%, HOOD -7.4%, CRCL -7.3% и COIN -6.1% за последната сесия“, цитирано); крипто данните от
macro_story_2026-10-29.json (с CRCL и BLSH в „tickers“). Пускане: python test_macro_current_list.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "macro_story_2026-10-29.json").read_text(encoding="utf-8"))
print("── 1. списъкът и промптът ──")
assert config.CRYPTO_TICKERS == ["COIN", "HOOD"]
assert {t["ticker"] for t in FX["crypto"]["tickers"]} >= {"CRCL", "BLSH"}                       # РЕАЛНИТЕ данни от 29.10 — с четирите
blk = ai_brief._crypto_block(FX["crypto"])
assert '"ticker": "HOOD"' in blk and '"ticker": "COIN"' in blk and "CRCL" not in blk and "BLSH" not in blk
p = ai_brief.macro_user_prompt(FX["macro"], FX["rotation"], FX["thermometer"], FX["news"], FX["crypto"])
assert '"ticker": "CRCL"' not in p and '"ticker": "BLSH"' not in p
print("  ✓ промптът — само COIN и HOOD (CRCL и BLSH от стария кеш — филтрирани)")
print("\n✅ test_macro_current_list: всичко мина")
