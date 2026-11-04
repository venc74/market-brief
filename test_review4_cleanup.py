"""
04.11.2026 · четвърти преглед, т. 3 (опростяване): пазач, че махнатото не се връща незабелязано —
  • AI контекстът „глобално срещу регионално“ за short кандидатите (ai_brief.SYSTEM_SHORT_CONTEXT / short_thesis_global_context, main._short_global_context,
    config.ENABLE_SHORT_AI_CONTEXT / MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT) — спрян от 03.10, short модулът е замразен;
  • render._cot_html (бележките „обратен залог“ — cot_notes не се попълва от 03.11);
  • news_aggregator._fetch_nitter и config.NEWS_ENABLE_NITTER / NITTER_HANDLES / NITTER_INSTANCES (изключени);
  • news_aggregator._RAW_MEMO (един извикващ; ключът никога не съвпадаше) — тестовете подменят gather_raw;
  • параметърът available_dates на шаблона (не се ползва);
  • watch_monitor._yf_news (резервата на RSS — от 29.10 връщаше нищо; виж test_watch_news_status).
Проверката е по кода (СИНТЕТИЧНО няма — само четене на файловете в src/, templates/ и config.py).
Пускане: python test_review4_cleanup.py
"""
import sys, pathlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

code = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in [*ROOT.glob("src/*.py"), ROOT / "config.py", *ROOT.glob("templates/*.j2")]}
gone = ["_short_global_context(", "short_thesis_global_context(", "SYSTEM_SHORT_CONTEXT =", "ENABLE_SHORT_AI_CONTEXT =", "MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT =",
        "def _cot_html", "_cot_html(", "def _fetch_nitter", "NEWS_ENABLE_NITTER =", "NITTER_HANDLES =", "NITTER_INSTANCES =", "_RAW_MEMO =", "_RAW_MEMO[",
        "available_dates", "def _yf_news", "_yf_news("]
hits = [(name, f) for name in gone for f, s in code.items() if name in s]
assert not hits, hits
print(f"  ✓ {len(gone)} махнати имена — нито едно в src/, templates/ и config.py")
print("\n✅ test_review4_cleanup: всичко мина")
