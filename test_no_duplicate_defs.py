"""
19.10.2026 · пазач: функция / клас на най-горното ниво не се дефинира два пъти в един модул на src/ (и config.py).

Повод (РЕАЛЕН, етап 2, т. 2 — локално, преди push): новата _news_block за промпта на тикърите беше със СЪЩОТО име като съществуващата _news_block на макро промпта
в src/ai_brief.py — втората дефиниция засенчва първата и макро промптът губеше "ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ" (хвана го test_macro_news). Сега е _ticker_news_block.
Пускане: python test_no_duplicate_defs.py
"""
import ast, pathlib, collections
ROOT = pathlib.Path(__file__).parent

bad = {}
files = sorted((ROOT / "src").glob("*.py")) + [ROOT / "config.py"]
for p in files:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    names = collections.Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    dup = sorted(k for k, v in names.items() if v > 1)
    if dup:
        bad[p.name] = dup
assert not bad, bad
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert "def _news_block(" in src and "def _ticker_news_block(" in src
print(f"  ✓ {len(files)} модула — без двойни дефиниции на най-горното ниво")
print("\n✅ test_no_duplicate_defs: всичко мина")
