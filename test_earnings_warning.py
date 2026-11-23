"""
Пакет 4б (06.10.2026) · т.д: при отчет в следващите ~20 сесии картата (Action/Watchlist и имейлът) показва предупреждение с датата — само информация, без промяна на размера.
17.11.2026 (пакет 1, т. 2в — решение след стратегическия преглед): очакваното движение от опциите (straddle-ите от следобедната OI снимка) — махнато с опционния стек;
остава „⚠ Отчет на ДД.ММ (след N сесии).“ (днес / утре / ~прогноза).

РЕАЛНО: картите от брифа на 05.10 (tests/fixtures/brief_2026-10-05.json: EXPD отчет 03.11, FTNT 28.10, AVT 28.10, ARW 29.10, ...).
СИНТЕТИЧНО (означено): FTNT като Action карта (синтетичен само планът); датите за „днес“ / „утре“ / прогноза; временната data/.
Пускане: python test_earnings_warning.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, re, json, pathlib, tempfile, copy, ast, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import earnings_move as em, render

D = dt.date.fromisoformat
FIX = ROOT / "tests" / "fixtures"
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {c["ticker"]: c for c in B05["action"] + B05["watchlist"]}
TODAY = D("2026-10-05")

print("── текстът на предупреждението ──")
w = em.warning_for("2026-10-28", TODAY)
assert w == {"date": "2026-10-28", "sessions": 17, "estimate": False, "text": "⚠ Отчет на 28.10 (след 17 сесии)."}, w
assert em.warning_for("2026-11-03", TODAY) is None and em.warning_for("2026-10-04", TODAY) is None          # EXPD (21 сесии) и минал отчет — без предупреждение
assert em.warning_for("2026-10-05", TODAY)["text"] == "⚠ Отчет на 05.10 (днес)." and em.warning_for("2026-10-06", TODAY)["text"] == "⚠ Отчет на 06.10 (утре)."
assert em.warning_for("2026-10-07", TODAY, estimate=True)["text"] == "⚠ Отчет на ~07.10 (прогноза) (след 2 сесии)."                     # СИНТЕТИЧНО
assert "очаква" not in w["text"] and "implied_move_pct" not in w
print("  ✓ днес / утре / след N сесии / ~прогноза; над 20 сесии или минал отчет — нищо; без очакваното движение от опциите")

print()
print("── РЕАЛНИТЕ карти от 05.10 ──")
cards = copy.deepcopy(list(CARDS.values()))
n = em.annotate(cards, TODAY)
got = {c["ticker"]: c.get("earnings_warning") for c in cards}
assert n == 3 and {t for t, w in got.items() if w} == {"FTNT", "AVT", "ARW"}                                   # EXPD/AMD/ZBRA/ANET (03.11, 21 сесии), KEYS, NTAP — извън 20 сесии
assert (got["FTNT"]["sessions"], got["AVT"]["sessions"], got["ARW"]["sessions"]) == (17, 17, 18)
for c in cards:                                                                                                  # само информация: нищо друго по картата не се пипа
    assert {k: v for k, v in c.items() if k != "earnings_warning"} == CARDS[c["ticker"]]
print("  ✓ FTNT и AVT (28.10, 17 сесии), ARW (29.10, 18 сесии); EXPD/AMD/ZBRA/ANET (21), KEYS, NTAP — без предупреждение; картите не се променят другаде")

print()
print("── върху страницата и в имейла ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_earn_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
brief = copy.deepcopy(B05)
em.annotate(brief["watchlist"], TODAY)
page = " ".join(htmllib.unescape(render.render_dashboard(brief)).split())
txt = " ".join(re.sub(r"<[^>]+>", " ", page).split())
row = lambda t: txt[txt.index(t + " ", txt.index("На радара (")):][:160]
assert "· отчет 28.10" in row("FTNT") and "(±" not in row("FTNT") and "· отчет 29.10" in row("ARW")
print("  ✓ редът на FTNT/AVT/ARW (too_wide) в „На радара“ носи отчета: «отчет 28.10», без ±%")
act = copy.deepcopy(CARDS["FTNT"])                                                                                  # СИНТЕТИЧНО: РЕАЛНАТА карта на FTNT като Action
act.update({"plan": {"method": "v2", "buy_stop": 190.0, "max_chase": 199.5, "stop_loss": 175.0, "risk_pct": 7.9, "target_1": 220.0, "target_1_fraction": 0.5,
                     "shares": 30, "total_investment": 5700, "stop_basis": "x", "max_risk_usd": 500, "sizing_factor": 0.5, "entry_mid": 190.0,
                     "valid_through": "2026-10-09", "window_sessions": 5, "target_2": "t", "time_horizon": "2–4 седмици", "pct_of_portfolio": 5.7},
            "base_type": "база", "weinstein_stage": 2, "rs_status": "new_high", "markers": []})
b2 = copy.deepcopy(B05); b2["action"] = [act]; em.annotate(b2["action"], TODAY)
page2 = " ".join(htmllib.unescape(render.render_dashboard(b2)).split())
assert "⚠ Отчет на 28.10 (след 17 сесии)." in page2 and '<div class="earn-warn">' in page2 and "пазарът очаква" not in page2
email = htmllib.unescape(render.render_email(b2))
assert "⚠ Отчет на 28.10 (след 17 сесии)." in email and "пазарът очаква" not in email
print("  ✓ същият ред върху Action картата и в имейла (РЕАЛНАТА FTNT като Action — синтетичен само планът)")

tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
calls = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "annotate" and getattr(n.func.value, "id", "") == "earnings_move"]
exp_call = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "apply_regime_gate_expiry"]
main_calls = [c for c in calls if ast.unparse(c.args[0]) == "action + watchlist"]
assert len(main_calls) == 1 and main_calls[0].lineno > exp_call[0].lineno
qm_calls = [c for c in calls if ast.unparse(c.args[0]) == "qm_cards"]                                                  # 08.10: предупреждение за отчет и върху QM картите
assert len(qm_calls) == 1 and len(calls) == 2
print("  ✓ main.run: earnings_move.annotate(action + watchlist) — след изтичането на Watchlist (картите са окончателни); и един отделен извик за qm_cards")

print()
print("Всички тестове минаха.")
