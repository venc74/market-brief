"""
Пакет 1б (2026-10-05) · свързването в main.run (оркестраторът не се пуска в тестовете, затова структурна проверка по AST): update_backtest_tracker получава днешния
Watchlist и режима СЛЕД като са изчислени, а обобщението на buy-stop книгата влиза в brief["backtest"] след Action обобщението, под TRACK_BUYSTOP и в try/except.
Всичко е върху РЕАЛНИЯ код на src/main.py (без данни). Пускане: python test_buystop_wiring.py
"""
import ast, pathlib

SRC = pathlib.Path(__file__).parent / "src" / "main.py"
tree = ast.parse(SRC.read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")


def first_store(name):
    return min(n.lineno for n in ast.walk(run) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store))


def call(attr):
    return [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


upd = call("update_backtest_tracker")
assert len(upd) == 1
args = upd[0].args
assert [ast.unparse(a) for a in args[:3]] == ["action", "today", "watchlist"] and "regime" in ast.unparse(args[3]) and "thermo" in ast.unparse(args[3]), [ast.unparse(a) for a in args]
assert first_store("watchlist") < upd[0].lineno and first_store("thermo") < upd[0].lineno
print("  ✓ update_backtest_tracker(action, today, watchlist, thermo…regime) — Watchlist и режимът са изчислени преди извикването")

summ = call("get_buystop_summary")
base = call("get_backtest_summary")
assert len(summ) == 1 and len(base) == 1 and summ[0].lineno > base[0].lineno
src = SRC.read_text(encoding="utf-8").splitlines()
block = "\n".join(src[summ[0].lineno - 4: summ[0].lineno + 3])
assert "config.TRACK_BUYSTOP" in block and "try:" in block and 'backtest_summary["buystop"]' in block and "except Exception" in block
print("  ✓ backtest_summary['buystop'] = get_buystop_summary() — след get_backtest_summary(), под TRACK_BUYSTOP, в try/except (провал → празно, run-ът не пада)")
print()
print("Всички тестове минаха.")
