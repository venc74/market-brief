"""
Пакет 4б (06.10.2026) · т.д: при отчет в следващите ~20 сесии картата (Action/Watchlist и имейлът) показва предупреждение с датата и очакваното движение от опциите — "пазарът очаква ±X%";
само информация, без промяна на размера. Очакваното движение = ATM straddle на падежа СЛЕД отчета с извадена базова волатилност (падежът ПРЕДИ отчета), от следобедната снимка; ненадеждно → само датата
и "няма данни за очаквано движение" с причината.

РЕАЛНО: котировките на FTNT/AVT/ARW от Yahoo на 05.10.2026 ~14:45 UTC (tests/fixtures/straddles_2026-10-05.json: цена, падежи, bid/ask около ATM) и РЕАЛНИТЕ карти от брифа на 05.10.2026
(tests/fixtures/brief_2026-10-05.json: EXPD отчет 03.11, FTNT 28.10, AVT 28.10, ARW 29.10, ...). СИНТЕТИЧНО: граничните промени на снимката (спред, дати, липсващ падеж), подменената снимка/yfinance,
временната data/.
Пускане: python test_earnings_warning.py
"""
import sys, json, math, pathlib, tempfile, copy, ast, datetime as dt, html as htmllib, shutil, types
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import earnings_move as em, oi_snapshot, render

D = dt.date.fromisoformat
FIX = ROOT / "tests" / "fixtures"
F = json.loads((FIX / "straddles_2026-10-05.json").read_text(encoding="utf-8"))["tickers"]
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {c["ticker"]: c for c in B05["action"] + B05["watchlist"]}
TODAY, SESSION = D("2026-10-05"), D("2026-10-05")


class Chain:
    def __init__(self, c, p):
        self.calls, self.puts = c, p


class Tk:                                                                        # yfinance-заместител от РЕАЛНИТЕ котировки на фикстурата
    def __init__(self, d):
        self.d, self.options, self.fast_info = d, tuple(d["options"]), {"last_price": d["spot"]}

    def option_chain(self, e):
        c = self.d["chains"][e]
        return Chain(pd.DataFrame(c["calls"]), pd.DataFrame(c["puts"]))


def mid_at(sym, exp, strike):                                                    # НЕЗАВИСИМО от кода: mid на call+put от суровите редове на фикстурата
    ch = F[sym]["chains"][exp]
    m = lambda rows: next((r["bid"] + r["ask"]) / 2 for r in rows if r["strike"] == strike)
    return m(ch["calls"]) + m(ch["puts"])


print("── търговски сесии ──")
assert em.sessions_after(D("2026-10-05"), D("2026-10-28")) == 17 and em.sessions_after(D("2026-10-05"), D("2026-11-03")) == 21     # 20 сесии → границата е между FTNT (17) и EXPD (21)
assert em.sessions_after(D("2026-11-24"), D("2026-11-27")) == 2                                                                     # 26.11 е празник (Thanksgiving)
assert em.sessions_after(D("2026-10-05"), D("2026-10-05")) == 0 and em.sessions_after(D("2026-10-09"), D("2026-10-12")) == 1       # уикендът не брои
print("  ✓ 05.10 → 28.10 = 17 сесии (FTNT); → 03.11 = 21 (EXPD, извън 20); Thanksgiving и уикенд не се броят")

print()
print("── РЕАЛНО: FTNT (отчет 28.10, опции от 05.10) ──")
st = em.snapshot_straddle(Tk(F["FTNT"]), "2026-10-28", SESSION)
assert st["after"]["expiry"] == "2026-10-30" and st["before"]["expiry"] == "2026-10-23" and st["after"]["sessions"] == 19 and st["before"]["sessions"] == 14
A, B = mid_at("FTNT", "2026-10-30", 185.0), mid_at("FTNT", "2026-10-23", 185.0)
exp_pct = round(math.sqrt(A * A - B * B * 19 / 14) / F["FTNT"]["spot"] * 100, 1)
res = em.event_move(st, "2026-10-28")
assert res["pct"] == exp_pct == 10.7 and res["naive_pct"] == round(A / F["FTNT"]["spot"] * 100, 1) == 13.9
assert (res["straddle_after"], res["straddle_before"], res["after_expiry"], res["before_expiry"]) == (round(A, 2), round(B, 2), "2026-10-30", "2026-10-23")
print(f"  ✓ straddle на 30.10 = ${A:.2f} (±{res['naive_pct']}% — включва 25 дни базова волатилност), на 23.10 = ${B:.2f}; събитието = sqrt({A:.2f}² − {B:.2f}²·19/14) / ${F['FTNT']['spot']} = ±{res['pct']}%")

print()
print("── РЕАЛНО: AVT и ARW — само месечни падежи (20.11), далеч след отчета ──")
for sym, e, gap in (("AVT", "2026-10-28", 23), ("ARW", "2026-10-29", 22)):
    r = em.event_move(em.snapshot_straddle(Tk(F[sym]), e, SESSION), e)
    assert r["pct"] is None and r["reason"] == f"първият падеж след отчета е 2026-11-20, {gap} дни след него — премията е предимно времева стойност", r
print("  ✓ AVT/ARW: първият падеж след отчета е 20.11 (22–23 дни след него) → 'няма данни за очаквано движение' с причината, не число")

print()
print("── граници (СИНТЕТИЧНИ промени на реалната снимка на FTNT) ──")
base = copy.deepcopy(st)
mut = lambda f: (lambda c: (f(c), c)[1])(copy.deepcopy(base))
cases = [
    ("тикър извън снимката", None, "2026-10-28", "тикърът не е в опционната снимка"),
    ("сменена дата на отчета", base, "2026-10-29", "датата на отчета е сменена след снимката (при снимката: 2026-10-28)"),
    ("снимката няма падеж след отчета", {**base, "after": None, "reason": "няма падеж след отчета"}, "2026-10-28", "няма падеж след отчета"),
    ("широк спред след", mut(lambda c: c["after"].update(call_spread_pct=40.0)), "2026-10-28", "спредът bid/ask на падежа след отчета (2026-10-30) е твърде широк"),
    ("далечен страйк", mut(lambda c: c["after"].update(strike=170.0)), "2026-10-28", "няма страйк близо до цената на падежа след отчета (2026-10-30)"),
    ("без падеж преди", mut(lambda c: c.pop("before")), "2026-10-28", "няма падеж преди отчета — базовата волатилност не може да се извади"),
    ("широк спред преди", mut(lambda c: c["before"].update(put_spread_pct=60.0)), "2026-10-28", "спредът bid/ask на падежа преди отчета (2026-10-23) е твърде широк — базовата волатилност не може да се извади"),
    ("падежът преди е твърде близо", mut(lambda c: c["before"].update(sessions=2)), "2026-10-28", "падежът преди отчета (2026-10-23) е твърде близо до снимката"),
    ("събитието не се вижда", mut(lambda c: c["before"].update(call_mid=20.0, put_mid=20.0)), "2026-10-28", "премията преди и след отчета е почти еднаква — събитието не се вижда в цените"),
    ("нереалистично", mut(lambda c: c["after"].update(call_mid=400.0, put_mid=400.0)), "2026-10-28", None),
    ("котировка липсва", mut(lambda c: c["after"].update(reason="няма котировка (bid/ask) за put на страйк 185")), "2026-10-28", "падежът след отчета 2026-10-30: няма котировка (bid/ask) за put на страйк 185"),
]
for name, s_, d_, want in cases:
    r = em.event_move(s_, d_)
    assert r["pct"] is None, (name, r)
    if want:
        assert r["reason"] == want, (name, r["reason"])
    else:
        assert r["reason"].startswith("нереалистична оценка"), r
far = mut(lambda c: c["before"].update(expiry="2026-10-02"))                                                      # падежите са > 21 дни един от друг
far["after"]["expiry"] = "2026-10-30"
assert "твърде раздалечени" in em.event_move(mut(lambda c: c["before"].update(expiry="2026-10-02")), "2026-10-28")["reason"]
print(f"  ✓ {len(cases) + 1} граници — всяка води до 'няма данни' със съответната причина (тикър/дата/падеж/спред/страйк/базова линия/невидимо събитие/нереалистично)")

print()
print("── текстът на предупреждението ──")
w = em.warning_for("2026-10-28", TODAY, st)
assert w["sessions"] == 17 and w["implied_move_pct"] == 10.7
assert w["text"] == ("⚠ Отчет на 28.10 (след 17 сесии) — пазарът очаква ±10.7% при отчета (оценка от straddle-ите на 23.10 и 30.10 с извадена базова волатилност; "
                     "цена $182.79, опции от 05.10).")
print("  ", w["text"])
wa = em.warning_for("2026-10-28", TODAY, em.snapshot_straddle(Tk(F["AVT"]), "2026-10-28", SESSION))
assert wa["text"] == "⚠ Отчет на 28.10 (след 17 сесии) — няма данни за очаквано движение (първият падеж след отчета е 2026-11-20, 23 дни след него — премията е предимно времева стойност)."
print("  ", wa["text"])
assert em.warning_for("2026-11-03", TODAY, st) is None and em.warning_for("2026-10-04", TODAY, st) is None          # EXPD (21 сесии) и минал отчет — без предупреждение
assert em.warning_for("2026-10-05", TODAY, st)["text"].startswith("⚠ Отчет на 05.10 (днес)") and em.warning_for("2026-10-06", TODAY, st)["text"].startswith("⚠ Отчет на 06.10 (утре)")
assert em.warning_for("2026-10-07", TODAY, None, "опционната снимка липсва")["text"] == "⚠ Отчет на 07.10 (след 2 сесии) — няма данни за очаквано движение (опционната снимка липсва)."
print("  ✓ днес / утре / след N сесии; над 20 сесии или минал отчет — нищо; липсваща снимка — само датата")

print()
print("── РЕАЛНИТЕ карти от 05.10 ──")
snap = {"horizon_days": 28, "session_date": "2026-10-05", "straddles": {s: em.snapshot_straddle(Tk(F[s]), CARDS[s]["earnings"]["next_earnings"], SESSION) for s in ("FTNT", "AVT", "ARW")}}
cards = copy.deepcopy(list(CARDS.values()))
n = em.annotate(cards, TODAY, snapshot_loader=lambda: (snap, "2026-10-05", ""))
got = {c["ticker"]: c.get("earnings_warning") for c in cards}
assert n == 3 and {t for t, w in got.items() if w} == {"FTNT", "AVT", "ARW"}                                   # EXPD/AMD/ZBRA/ANET (03.11, 21 сесии), KEYS, NTAP — извън 20 сесии
assert got["FTNT"]["implied_move_pct"] == 10.7 and got["AVT"]["implied_move_pct"] is None and got["ARW"]["implied_move_pct"] is None
assert (got["FTNT"]["sessions"], got["AVT"]["sessions"], got["ARW"]["sessions"]) == (17, 17, 18)
for c in cards:                                                                                                  # само информация: нищо друго по картата не се пипа
    orig = CARDS[c["ticker"]]
    assert {k: v for k, v in c.items() if k != "earnings_warning"} == orig
print("  ✓ FTNT (28.10, 17 сесии): ±10.7%; AVT (28.10) и ARW (29.10, 18 сесии): няма данни; EXPD/AMD/ZBRA/ANET (21), KEYS, NTAP — без предупреждение; картите не се променят другаде")
cards = copy.deepcopy(list(CARDS.values()))
em.annotate(cards, TODAY, snapshot_loader=lambda: (None, "", "следобедната OI снимка за сесията 02.10 липсва"))
assert [c["earnings_warning"]["reason"] for c in cards if "earnings_warning" in c] == ["следобедната OI снимка за сесията 02.10 липсва"] * 3
cards = copy.deepcopy(list(CARDS.values()))
em.annotate(cards, TODAY, snapshot_loader=lambda: ({"horizon_days": 28, "tickers": {}}, "2026-10-02", ""))
assert {c["earnings_warning"]["reason"] for c in cards if "earnings_warning" in c} == {"снимката още няма данни за отчети (стар формат)"}
cards = copy.deepcopy(list(CARDS.values()))
em.annotate(cards, TODAY, snapshot_loader=lambda: (_ for _ in ()).throw(RuntimeError("мрежа")))
assert all("earnings_warning" in c and "снимката не се зареди" in c["earnings_warning"]["reason"] for c in cards if c["ticker"] in ("FTNT", "AVT", "ARW"))
print("  ✓ липсваща снимка / снимка без straddle-и (стар формат) / провал при зареждане — само датата и причината, run-ът не пада")

print()
print("── върху страницата и в имейла ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_earn_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
brief = copy.deepcopy(B05)
em.annotate(brief["watchlist"], TODAY, snapshot_loader=lambda: (snap, "2026-10-05", ""))
page = " ".join(htmllib.unescape(render.render_dashboard(brief)).split())
assert 'class="earn-warn">⚠ Отчет на 28.10 (след 17 сесии) — пазарът очаква ±10.7% при отчета' in page
assert page.count("няма данни за очаквано движение") == 2
print("  ✓ Watchlist картите на FTNT/AVT/ARW показват реда (±10.7% / 'няма данни за очаквано движение' ×2)")
act = copy.deepcopy(CARDS["FTNT"])                                                                                  # СИНТЕТИЧНО: РЕАЛНАТА карта на FTNT като Action (за да се види и Action картата и имейлът)
act.update({"plan": {"method": "v2", "buy_stop": 190.0, "max_chase": 199.5, "stop_loss": 175.0, "risk_pct": 7.9, "target_1": 220.0, "target_1_fraction": 0.5,
                     "shares": 30, "total_investment": 5700, "stop_basis": "x", "max_risk_usd": 500, "sizing_factor": 0.5, "entry_mid": 190.0,
                     "valid_through": "2026-10-09", "window_sessions": 5, "target_2": "t", "time_horizon": "2–4 седмици", "pct_of_portfolio": 5.7},
            "base_type": "база", "weinstein_stage": 2, "rs_status": "new_high", "markers": []})
b2 = copy.deepcopy(B05); b2["action"] = [act]; em.annotate(b2["action"], TODAY, snapshot_loader=lambda: (snap, "2026-10-05", ""))
page2 = " ".join(htmllib.unescape(render.render_dashboard(b2)).split())
assert page2.count("пазарът очаква ±10.7%") >= 1 and '<div class="earn-warn">' in page2
email = htmllib.unescape(render.render_email(b2))
assert "⚠ Отчет на 28.10 (след 17 сесии) — пазарът очаква ±10.7% при отчета" in email
print("  ✓ същият ред върху Action картата и в имейла (РЕАЛНАТА FTNT като Action — синтетичен само планът)")

print()
print("── следобедната снимка записва straddle-ите ──")
shutil.copy(FIX / "brief_2026-10-05.json", config.DATA_DIR / "2026-10-05.json")                                      # РЕАЛНИЯТ бриф → дати на отчетите на кандидатите
FK = {s: Tk(F[s]) for s in ("FTNT", "AVT", "ARW")}
yfm = types.SimpleNamespace(Ticker=lambda sym: FK[sym])
out = em.snapshot_straddles(["FTNT", "AVT", "ARW", "EXPD"], SESSION, yfm)                                            # EXPD е в прозореца (отчет 03.11 = +29 дни), но заместителят няма верига за него → пропуска се
assert sorted(out) == ["ARW", "AVT", "FTNT"] and out["FTNT"]["after"]["expiry"] == "2026-10-30"
out = em.snapshot_straddles(["FTNT", "ZZZ"], SESSION, yfm)                                                          # ZZZ няма дата в брифовете и календарът (подменен) гърми → пропуска се
assert list(out) == ["FTNT"]
print("  ✓ снимката пази сурови крачета за тикърите с отчет в следващите ~32 дни (дати от картите на последните брифове); тикър без дата/с провал се пропуска")
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
