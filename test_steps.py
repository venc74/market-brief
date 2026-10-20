"""
20.10.2026 · етап 3б, обвивката — стъпка 1 (дизайнът от доклада на етап 3, одобрен): src/steps.py и местата в main.run, които до 20.10 при провал оставяха само ред в лога
(предупрежденията за отчет, обратният залог, маркерите върху позициите, обобщенията на книгите, секцията "Наблюдавани", отчетът за сплитове, секторната карта, проверките на AI текста,
новините, изборът на модел, проверката за свеж бар, ограничението от distribution days, COT track record, short скрийнърът). Всяка стъпка: ok / частично / провал / пропусната;
провал без собствен банер → един ред "{етикет}: провал днес (…) — {последствие}".

СИНТЕТИЧНО (означено): функциите в част 1; инжектираните провали в част 3 (main.run целият, без мрежа и без ключове — всяко теглене пада, както при паднал Yahoo / Anthropic).
Пускане: python test_steps.py (през run_tests — с временни data/ и docs/)
"""
import sys, os, ast, json, pathlib, tempfile, io, contextlib, importlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

if not os.environ.get("MB_DATA_DIR"):                                                   # пуснат директно — временни папки (под run_tests ги дава runner-ът)
    _tmp = tempfile.TemporaryDirectory(prefix="mb_steps_")
    config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
    config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import steps

print("── 1. семантиката на step() (СИНТЕТИЧНО) ──")
steps.reset()
q = lambda: contextlib.redirect_stdout(io.StringIO())
with q():
    assert steps.step("a", lambda: 5, label="A", consequence="x") == 5
    assert steps.step("b", lambda: 1 / 0, fallback=[], label="Б", consequence="без Б днес") == []
    assert steps.step("c", lambda: 7, fallback=0, enabled=False, label="В", consequence="x") == 0
    assert steps.step("d", lambda: {"n": 3}, label="Г", consequence="непълно", partial=lambda v: ("3 от 5", {"n": v["n"]}) if v["n"] < 5 else None) == {"n": 3}
    try:
        steps.step("e", lambda: 1 / 0, label="Д", consequence="x", critical=True)
        raise AssertionError("critical трябва да вдигне")
    except ZeroDivisionError:
        pass
st = {r["name"]: r for r in steps.summary()}
assert [st[k]["status"] for k in "abcde"] == ["ok", "failed", "skipped", "partial", "failed"]
assert st["b"]["reason"].startswith("ZeroDivisionError") and st["d"]["detail"] == {"n": 3}
w = steps.warnings({"e"})                                                               # "e" вече има собствен банер → без втори
assert [(x["source"], x["level"]) for x in w] == [("b", "error"), ("d", "warn")]
assert w[0]["message"] == "Б: провал днес (ZeroDivisionError: division by zero) — без Б днес." and w[1]["message"] == "Г: частично днес (3 от 5) — непълно."
print("  ✓ ok / провал → fallback / пропусната / частично / critical вдига; банер само за провал и частично, без втори при собствен банер; провал → error, частично → warn")

print()
print("── 2. main.run: местата 'само лог' са в обвивката ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
run = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run")
names = [ast.literal_eval(c.args[0]) for c in ast.walk(run) if isinstance(c, ast.Call) and ast.unparse(c.func) == "steps.step"]
STEP1 = {"model", "bar_freshness", "distribution_cap", "news", "prose_checks", "cot_track", "earnings_warnings", "earnings_warnings_qm", "cot_opposites", "book_buystop", "book_qm",
         "book_glb_wish", "si_positions", "uov_positions", "qm_positions", "watch", "splits_report", "sector_card", "short_screener"}
assert set(names) == STEP1 and len(names) == len(STEP1), sorted(set(names) ^ STEP1)
tries = [n for n in ast.walk(run) if isinstance(n, ast.Try)]
assert len(tries) == 14, len(tries)                    # останалите имат собствен статус и банер (стъпки 2–3 на обвивката: модулните LAST_STATUS и локалните diag) + банерът за имейла
assert "steps.reset()" in src and '"run_steps": steps.summary()' in src and "data_warns += steps.warnings({w.get(\"source\") for w in data_warns})" in src
print(f"  ✓ {len(names)} стъпки в обвивката; останалите try в run() — {len(tries)} (собствен статус и банер); run_steps в брифа; банерите след тези на модулите")

print()
print("── 3. целият main.run без мрежа, с инжектирани провали (СИНТЕТИЧНО) ──")
from src import main
config.BAR_FRESHNESS_RETRY_SEC, config.BAR_FRESHNESS_MAX_WAIT_SEC = 1, 2
config.SPINOFF_BUDGET_SEC = config.UNUSUAL_OPTIONS_REFERENCE_BUDGET_SEC = 5
FAULTS = {"model": "src.model_selector.resolve_model", "bar_freshness": "src.bar_freshness.wait_for_fresh", "distribution_cap": "src.main.apply_distribution_cap",
          "news": "src.news_aggregator.significant_news", "prose_checks": "src.ai_brief.apply_sector_claims_to_narratives", "earnings_warnings": "src.earnings_move.annotate",
          "cot_opposites": "src.cot_opposites.annotate", "book_buystop": "src.backtest.get_buystop_summary", "book_qm": "src.backtest.get_qm_summary",
          "book_glb_wish": "src.backtest.get_glb_wish_summary", "si_positions": "src.dataroma.new_position_markers", "watch": "src.watch_monitor.collect",
          "splits_report": "src.splits_calendar.splits_report", "sector_card": "src.sector_claims.sector_card"}
for spec in FAULTS.values():
    mod, attr = spec.rsplit(".", 1)
    setattr(importlib.import_module(mod), attr, lambda *a, _n=spec, **k: (_ for _ in ()).throw(RuntimeError(f"инжектиран провал {_n}")))
with q():
    brief = main.run()
rs = {r["name"]: r for r in brief["run_steps"]}
enabled = {"bar_freshness": config.ENABLE_BAR_FRESHNESS, "distribution_cap": config.ENABLE_ENTRY_TIMING, "news": config.ENABLE_NEWS,
           "book_buystop": config.ENABLE_BACKTEST and config.TRACK_BUYSTOP, "book_qm": config.ENABLE_BACKTEST and config.TRACK_QM,
           "book_glb_wish": config.ENABLE_BACKTEST and config.TRACK_GLB_WISH, "watch": config.ENABLE_WATCH_MONITOR, "splits_report": config.ENABLE_SPLITS_CALENDAR}
want_failed = {k for k in FAULTS if enabled.get(k, True)}
assert {k for k, r in rs.items() if r["status"] == "failed"} == want_failed, {k: r["status"] for k, r in rs.items()}
sources = {w["source"] for w in brief["data_warnings"]}
assert want_failed <= sources, want_failed - sources
for k in want_failed:
    assert "инжектиран провал" in rs[k]["reason"]
gen = [w for w in brief["data_warnings"] if w["source"] in want_failed]
assert all(w["level"] == "error" and ": провал днес (RuntimeError: инжектиран провал" in w["message"] for w in gen if w["source"] in FAULTS)
assert (config.DATA_DIR / f"{brief['date']}.json").exists() and json.loads((config.DATA_DIR / f"{brief['date']}.json").read_text(encoding="utf-8"))["run_steps"]
print(f"  ✓ run-ът завършва; {len(want_failed)} инжектирани провала → статус 'failed' и банер за всеки; брифът носи run_steps ({len(rs)} стъпки)")
ex = next(w for w in brief["data_warnings"] if w["source"] == "earnings_warnings")
print(f"    пример (СИНТЕТИЧЕН провал): «{ex['message']}»")
print("\n✅ test_steps: всичко мина")
