"""
Скрийнър · хистерезис на RS линията: вход ≥ 97%, оставане ≥ 94% от 52-седмичния максимум (09.10.2026). Преди: единен праг 97% — EXPD мигаше около него (95.9% на 06.10 го махна от списъка; на 17.09, 21.09, 24.09…
същото). Измерване върху РЕАЛНИ дневни данни на 903 тикъра за 80-те дни на брифовете: излизания и връщане до 5 сесии 248 → 93 (−62%), смяна на имена на ден 13.4 → 8.9, средно R на buy-stop книгата −0.57 → −0.53.
Състоянието (data/screener_rs_state.json) е множеството на тикърите, преминали ВСИЧКИ технически филтри при предишния успешен run; паднал Yahoo не го пипа.

РЕАЛНО: tests/fixtures/screen_real_2026-10-06.json — дневни барове на EXPD и SPY (300 сесии до 06.10.2026); тестът минава през screener._evaluate_technicals и explain_exclusion. СИНТЕТИЧНО (маркирано): състоянието,
подменените technical_screen/yf в run_screen, повреденият state файл.
Пускане: python test_rs_hysteresis.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener

tmp = tempfile.TemporaryDirectory(prefix="mb_rsh_")
config.RS_LINE_STATE_FILE = pathlib.Path(tmp.name) / "screener_rs_state.json"
SCR = json.loads((ROOT / "tests" / "fixtures" / "screen_real_2026-10-06.json").read_text(encoding="utf-8"))
f = SCR["frames"]["EXPD"]
DF = pd.DataFrame({"High": f["h"], "Low": f["l"], "Close": f["c"], "Volume": f["v"]}, index=pd.to_datetime(f["dates"]))
SPY = pd.Series(SCR["spy"]["c"], index=pd.to_datetime(SCR["spy"]["dates"]))
assert config.RS_LINE_ENTER == 0.97 and config.RS_LINE_STAY == 0.94 and screener.RS_LINE_NEAR_HIGH == 0.97 and screener.RS_LINE_STAY == 0.94

print("── 1. РЕАЛНИЯТ EXPD, ден по ден (RS линия в % от 52-седмичния максимум) ──")
days = [d for d in DF.index if pd.Timestamp("2026-09-01") <= d <= pd.Timestamp("2026-10-06")]
rows = []
for d in days:
    x, sp = DF[DF.index <= d], SPY[SPY.index <= d]
    rs = (x["Close"] / sp.reindex(x.index).ffill()).dropna().iloc[-252:]
    pct = float(rs.iloc[-1] / rs.max()) * 100                                                   # независимо смятане
    rows.append((d, x, sp, pct))
statA, statB, state = [], [], False
for d, x, sp, pct in rows:
    a = screener._evaluate_technicals("EXPD", x, sp)
    b = screener._evaluate_technicals("EXPD", x, sp, held=state)
    if a is not None:
        assert pct >= 96.95 and b is not None and b["rs_held"] is False and b["rs_line_pct"] == a["rs_line_pct"] and a["rs_held"] is False
    if b is not None and a is None:
        assert 94 <= pct < 97 and b["rs_held"] is True and b["rs_status"] == "near_high"             # допуснат САМО заради хистерезиса
    statA.append(a is not None); statB.append(b is not None); state = b is not None
trans = lambda s: sum(1 for i in range(1, len(s)) if s[i] != s[i - 1])
assert trans(statA) == 5 and trans(statB) == 2, (trans(statA), trans(statB))
byd = {d.date().isoformat(): (round(p, 1), A, B) for (d, _, _, p), A, B in zip(rows, statA, statB)}
assert byd["2026-09-17"] == (96.8, False, True) and byd["2026-09-24"] == (93.3, False, False) and byd["2026-10-06"] == (95.9, False, True)
assert byd["2026-09-25"] == (94.7, False, False)                                                    # изпаднал под 94% → пак е нов тикър: чака 97%, не се връща при 94.7%
print(f"  ✓ {len(days)} сесии 01.09–06.10: единен праг 97% → в списъка/извън го {trans(statA)} пъти; с хистерезис → {trans(statB)} пъти (17.09 96.8% остава; 25.09 94.7% не се връща след излизането на 24.09; 06.10 95.9% остава)")
print("    (5 → 2 за един тикър не е обещание: реалното измерване върху 903 тикъра е −62% при излизания и връщане до 5 сесии, 248 → 93; изходът на 24.09 и 30.09 е от друг филтър — цената под 50DMA)")

print()
print("── 2. причината за излизане (explain_exclusion) ──")
x, sp = DF[DF.index <= "2026-10-06"], SPY[SPY.index <= "2026-10-06"]
assert screener.explain_exclusion("EXPD", x, sp, SCR["rs_scores"]) == "RS линия 95.9% от 52-седмичния максимум < 97%"
assert screener.explain_exclusion("EXPD", x, sp, SCR["rs_scores"], held=True) is None                # задържан: 95.9% ≥ 94%
FA = SCR["frames"]["AAPL"]
DA = pd.DataFrame({"High": FA["h"], "Low": FA["l"], "Close": FA["c"], "Volume": FA["v"]}, index=pd.to_datetime(FA["dates"]))
assert screener.explain_exclusion("AAPL", DA, SPY, SCR["rs_scores"]) == "RS линия 92.2% от 52-седмичния максимум < 97%"                       # РЕАЛЕН AAPL към 06.10
assert screener.explain_exclusion("AAPL", DA, SPY, SCR["rs_scores"], held=True) == "RS линия 92.2% от 52-седмичния максимум < 94% (оставане по хистерезис; вход ≥ 97%)"
assert screener._evaluate_technicals("AAPL", DA, SPY, held=True) is None
x3, sp3 = DF[DF.index <= "2026-09-24"], SPY[SPY.index <= "2026-09-24"]
assert screener.explain_exclusion("EXPD", x3, sp3, SCR["rs_scores"], held=True) == "trend template: цената е под 50DMA"                          # 24.09: другият филтър е първият, не RS
print("  ✓ EXPD 06.10: 95.9% < 97% за нов тикър, но задържан е ОК; AAPL 06.10: «RS линия 92.2% … < 94% (оставане по хистерезис; вход ≥ 97%)»; EXPD 24.09 — първо пада друг филтър (под 50DMA)")

print()
print("── 3. състоянието ──")
assert screener.load_rs_state() == set()                                                          # липсващ файл
screener.save_rs_state({"B", "A"}, "2026-10-09")
assert screener.load_rs_state() == {"A", "B"} and json.loads(config.RS_LINE_STATE_FILE.read_text())["tickers"] == ["A", "B"]
config.RS_LINE_STATE_FILE.write_text("{не е json", encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()) as out:
    assert screener.load_rs_state() == set()
assert "нечетимо" in out.getvalue()
assert screener.next_rs_state({"A", "B", "C"}, {"B", "D"}, {"A", "B", "D"}) == {"B", "D", "C"}      # A има данни и не оцелява → отпада; C няма данни (паднала партида) → пази се
print("  ✓ липсващ/повреден файл → празно (с лог); тикър без данни днес пази състоянието си; оцелелите влизат")

print()
print("── 4. run_screen: заредено състояние, запис само след успешен run (СИНТЕТИЧНО подменени technical_screen/fundamental_screen) ──")
calls = []
def fake_tech(universe, batch_size=100, held=None):
    calls.append(held)
    screener.LAST_STATUS.update(ok=True, kind="ok")
    screener.LAST_RS_EVALUATED.clear(); screener.LAST_RS_EVALUATED.update(universe)
    return [{"ticker": "AAA", "rs_held": True}, {"ticker": "BBB", "rs_held": False}]
screener.build_universe = lambda: ["AAA", "BBB", "CCC"]
screener.technical_screen = fake_tech
screener.fundamental_screen = lambda rows: rows
screener.apply_sector_tailwind = lambda finalists, leaders, names: finalists
config.RS_LINE_STATE_FILE.unlink()
with contextlib.redirect_stdout(io.StringIO()):
    screener.run_screen([])
assert calls == [None] or calls[0] in (None, set())                                                  # празно състояние → извиква се без held (както преди)
assert screener.load_rs_state() == {"AAA", "BBB"}
screener.save_rs_state({"AAA", "ZZZ"}, "2026-10-08")
with contextlib.redirect_stdout(io.StringIO()) as out:
    screener.run_screen([])
assert calls[-1] == {"AAA", "ZZZ"} and screener.load_rs_state() == {"AAA", "BBB", "ZZZ"}             # ZZZ няма данни днес (не е в универса) → пази се
assert "хистерезис на RS линията: 2 тикъра от предишния run, 1 остават между 94% и 97%: ['AAA']" in out.getvalue()
def failed_tech(universe, batch_size=100, held=None):
    screener.LAST_STATUS.update(ok=False, kind="spy_failed")
    return []
screener.technical_screen = failed_tech
before = config.RS_LINE_STATE_FILE.read_text(encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    screener.run_screen([])
assert config.RS_LINE_STATE_FILE.read_text(encoding="utf-8") == before                                # паднал Yahoo не нулира състоянието
config.RS_LINE_HYSTERESIS = False
calls.clear(); screener.technical_screen = fake_tech
with contextlib.redirect_stdout(io.StringIO()):
    screener.run_screen([])
assert calls == [None] and screener.load_rs_state() == {"AAA", "BBB", "ZZZ"}                          # изключено: не чете и не пише
config.RS_LINE_HYSTERESIS = True
print("  ✓ празно състояние → извикване без held; със състояние → held; запис след успешен run (тикър без данни пази състоянието си); паднал run не го пипа; RS_LINE_HYSTERESIS=0 → не чете и не пише")

print()
print("── 5. картата ──")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "st.rs_held" in tpl and "(задържан)" in tpl
print("  ✓ шаблонът показва «NN.N% от макс. (задържан)» при rs_held")
print("\n✅ test_rs_hysteresis: всичко мина")
