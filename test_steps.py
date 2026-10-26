"""
20.10.2026 · етап 3б, обвивката — стъпка 1 (дизайнът от доклада на етап 3, одобрен): src/steps.py и местата в main.run, които до 20.10 при провал оставяха само ред в лога
(предупрежденията за отчет, обратният залог, маркерите върху позициите, обобщенията на книгите, секцията "Наблюдавани", отчетът за сплитове, секторната карта, проверките на AI текста,
новините, изборът на модел, проверката за свеж бар, ограничението от distribution days, COT track record, short скрийнърът). Всяка стъпка: ok / частично / провал / пропусната;
провал без собствен банер → един ред "{етикет}: провал днес (…) — {последствие}".

СИНТЕТИЧНО (означено): функциите в част 1; инжектираните провали в част 3 (main.run целият, без мрежа и без ключове — всяко теглене пада, както при паднал Yahoo / Anthropic).
Пускане: python test_steps.py (през run_tests — с временни data/ и docs/)
"""
import sys, os, ast, json, pathlib, tempfile, io, contextlib, importlib, subprocess
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

# 21.10.2026: част 3 пуска ЦЕЛИЯ main.run — иска мрежовата защита (tests/_nonet) и временни data/ / docs/ още при импорта на config (пътищата в config се смятат тогава).
# Пуснат директно (python test_steps.py), без тях run-ът тегли на живо и пише в реалните data/ (20.10: put_call_history.json и uov_ratio_history.json — възстановени от git).
# Затова директното пускане минава отново през средата на run_tests.
if not os.environ.get("MB_DATA_DIR") or "_nonet" not in os.environ.get("PYTHONPATH", ""):
    import run_tests
    with tempfile.TemporaryDirectory(prefix="mb_steps_") as _td:
        sys.exit(subprocess.run([sys.executable, __file__], cwd=str(ROOT), env=run_tests.test_env(run_tests.clean_env(), pathlib.Path(_td))).returncode)

import config
assert str(config.DATA_DIR) == os.environ["MB_DATA_DIR"] and not str(config.DATA_DIR.resolve()).startswith(str((ROOT / "data").resolve()))
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
         "book_glb_wish", "book_glb_wish_high", "si_positions", "uov_positions", "qm_positions", "watch", "splits_report", "sector_card", "short_screener"}
STEP2 = {"qm_universe", "qm_scan", "qm_ep", "ins_positions", "health"}            # стъпка 2: локалният статус (qm_diag, qm_ep_out, ins_pos_status, health) — собственият банер остава
STEP3 = {"thermometer", "distribution_days", "sector_rotation", "screener", "narratives", "narratives_merge", "glb", "spinoff"}    # стъпка 3: модулният статус (LAST_STATUS / LAST_DIAG)
STEP4 = {"crypto", "options_record", "merger_pre", "event_labels"}                                                    # етап 4 (22.10): крипто секцията — без собствен банер, обвивката дава един; 4б (26.10): целите на придобиване преди класификацията
ALL = STEP1 | STEP2 | STEP3 | STEP4
assert set(names) == ALL and len(names) == len(ALL), sorted(set(names) ^ ALL)
tries = [n for n in ast.walk(run) if isinstance(n, ast.Try)]
assert len(tries) == 1 and "email" in ast.unparse(tries[0]), len(tries)       # остава само банерът за неизпратения имейл (след рендера — той е самият банер)
assert "steps.reset()" in src and '"run_steps": steps.summary()' in src and "data_warns += steps.warnings({w.get(\"source\") for w in data_warns})" in src
print(f"  ✓ {len(names)} стъпки в обвивката; в run() остава 1 try (банерът за неизпратения имейл); run_steps в брифа; банерите след тези на модулите")

print()
print("── 3. целият main.run без мрежа, с инжектирани провали (СИНТЕТИЧНО) ──")
from src import main
config.BAR_FRESHNESS_RETRY_SEC, config.BAR_FRESHNESS_MAX_WAIT_SEC = 1, 2
config.ENABLE_MARKET_CLOSED_SKIP = 0                                                # 24.10: тестът върви и в почивен ден (иначе run() спира преди стъпките)
config.SPINOFF_BUDGET_SEC = config.UNUSUAL_OPTIONS_REFERENCE_BUDGET_SEC = 5
FAULTS = {"model": "src.model_selector.resolve_model", "bar_freshness": "src.bar_freshness.wait_for_fresh", "distribution_cap": "src.main.apply_distribution_cap",
          "news": "src.news_aggregator.significant_news", "prose_checks": "src.ai_brief.apply_sector_claims_to_narratives", "earnings_warnings": "src.earnings_move.annotate",
          "cot_opposites": "src.cot_opposites.annotate", "book_buystop": "src.backtest.get_buystop_summary", "book_qm": "src.backtest.get_qm_summary",
          "book_glb_wish": "src.backtest.get_glb_wish_summary", "book_glb_wish_high": "src.backtest.get_glb_wish_summary", "si_positions": "src.dataroma.new_position_markers", "watch": "src.watch_monitor.collect",
          "splits_report": "src.splits_calendar.splits_report", "sector_card": "src.sector_claims.sector_card", "health": "src.health_monitor.check"}
OWN_SOURCE = {"health": "health:health_monitor"}                                         # стъпка 2: собственият ред на монитора, не втори банер
for spec in FAULTS.values():
    mod, attr = spec.rsplit(".", 1)
    setattr(importlib.import_module(mod), attr, lambda *a, _n=spec, **k: (_ for _ in ()).throw(RuntimeError(f"инжектиран провал {_n}")))
with q():
    brief = main.run()
rs = {r["name"]: r for r in brief["run_steps"]}
enabled = {"bar_freshness": config.ENABLE_BAR_FRESHNESS, "distribution_cap": config.ENABLE_ENTRY_TIMING, "news": config.ENABLE_NEWS,
           "book_buystop": config.ENABLE_BACKTEST and config.TRACK_BUYSTOP, "book_qm": config.ENABLE_BACKTEST and config.TRACK_QM,
           "book_glb_wish": config.ENABLE_BACKTEST and config.TRACK_GLB_WISH, "book_glb_wish_high": config.ENABLE_BACKTEST and config.TRACK_GLB_WISH_HIGH, "watch": config.ENABLE_WATCH_MONITOR, "splits_report": config.ENABLE_SPLITS_CALENDAR}
# стъпка 3: без мрежа източниците наистина падат — модулният статус го казва (failed_if), банерът е собственият (sector_rotation, screener, glb, distribution_days)
NATURAL = {"sector_rotation", "screener", "glb", "distribution_days"}
NATURAL_WRAPPED = {"crypto"} if config.ENABLE_CRYPTO_SECTION else set()             # без мрежа фийдът е празен → провал с банера на обвивката (не инжектиран)
want_failed = {k for k in FAULTS if enabled.get(k, True)} | {k for k in NATURAL if enabled.get(k, True) and (k != "glb" or config.ENABLE_GLB_SCREENER)} | NATURAL_WRAPPED
assert {k for k, r in rs.items() if r["status"] == "failed"} == want_failed, {k: r["status"] for k, r in rs.items()}
sources = {w["source"] for w in brief["data_warnings"]}
assert {OWN_SOURCE.get(k, k) for k in want_failed} <= sources, {OWN_SOURCE.get(k, k) for k in want_failed} - sources
assert not any(w["source"] == "health" for w in brief["data_warnings"])                  # без втори банер за монитора
for k in NATURAL & want_failed:                                                           # собственият банер на модула — без втори от обвивката
    assert not any(w["source"] == k and w["message"].startswith(("Секторната ротация:", "Скрийнърът:", "GLB скрийнърът:", "Distribution days (SPY / QQQ):")) for w in brief["data_warnings"]), k
for k in want_failed - NATURAL - NATURAL_WRAPPED:
    assert "инжектиран провал" in rs[k]["reason"]
assert all(any(w["source"] == k and ": провал днес (" in w["message"] for w in brief["data_warnings"]) for k in NATURAL_WRAPPED)
gen = [w for w in brief["data_warnings"] if w["source"] in want_failed]
assert all(w["level"] == "error" and ": провал днес (RuntimeError: инжектиран провал" in w["message"] for w in gen if w["source"] in FAULTS and w["source"] not in OWN_SOURCE)
assert any(w["source"] == "health:health_monitor" and "мониторът не се изпълни (RuntimeError" in w["message"] for w in brief["data_warnings"])
assert (config.DATA_DIR / f"{brief['date']}.json").exists() and json.loads((config.DATA_DIR / f"{brief['date']}.json").read_text(encoding="utf-8"))["run_steps"]
print(f"  ✓ run-ът завършва; {len(want_failed - NATURAL)} инжектирани провала и {len(want_failed & NATURAL)} истински (без мрежа) → 'failed' и по един банер; run_steps ({len(rs)} стъпки)")
ex = next(w for w in brief["data_warnings"] if w["source"] == "earnings_warnings")
print(f"    пример (СИНТЕТИЧЕН провал): «{ex['message']}»")
print("\n✅ test_steps: всичко мина")
