"""
20.10.2026 · етап 3, част Б: NYSE сесиите на едно място (src/sessions.py) вместо ~10 копия. Поведението е същото — офлайн реплеят (tools/replay_offline.py,
стар ↔ нов код): сесийните функции за всички 1 827 дати 2024–2028 и 24 реални брифа (17.09–20.10) — 0 разлики.

РЕАЛНО: config.NYSE_HOLIDAYS (официалният календар на nyse.com), датите на реалните случаи (Thanksgiving 26.11.2026, Разпети петък 03.04.2026, Labor Day 07.09.2026,
Q4 2025 срокът за 13F → 17.02.2026). СИНТЕТИЧНО: барове с частичен днешен ред.
Пускане: python test_sessions.py
"""
import sys, ast, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import sessions as s

D = dt.date.fromisoformat
assert {"2026-11-26", "2026-04-03", "2026-09-07"} <= set(config.NYSE_HOLIDAYS)

print("── 1. семантиките ──")
assert s.is_session("2026-11-27") and not s.is_session("2026-11-26") and not s.is_session(D("2026-10-18"))
assert s.next_session("2026-11-25") == D("2026-11-27") and s.prev_session("2026-11-27") == D("2026-11-25") and s.prev_session("2026-09-08") == D("2026-09-04")
assert s.roll_forward(D("2026-02-14")) == D("2026-02-17") and s.roll_back(D("2026-04-03")) == D("2026-04-02")
assert s.next_weekday("2026-11-25") == D("2026-11-26")                                         # празникът НЕ се прескача (календарната бележка)
assert s.sessions_between("2026-11-24", "2026-11-30") == 2 and s.sessions_in("2026-11-20", "2026-11-30") == 5 and s.sessions_in("2026-11-30", "2026-11-20") == 0
assert s.busday_count("2026-11-23", "2026-11-30") == 4 and s.busday_count("2026-11-30", "2026-11-23") == -4
assert s.add_sessions("2026-11-24", 2) == D("2026-11-27") and s.session_window("2026-11-26", 3) == [D("2026-11-27"), D("2026-11-30"), D("2026-12-01")]
assert s.week_last_session("2026-03-30") == D("2026-04-02") and s.week_last_session("2026-09-28") == D("2026-10-02")
print("  ✓ сесия / следваща / предишна / напред / назад / следващ делничен / строго между / (a, b] / [a, b) / +n сесии / прозорец / край на седмицата")

print()
print("── 2. старите имена са обвивки на модула ──")
from src import setup_rules, bar_freshness, health_monitor, qm_ep, corp_actions, earnings_move, cot_track, dataroma, thesis_context
assert setup_rules.is_session is s.is_session and setup_rules.sessions_between is s.sessions_between and setup_rules.next_weekday is s.next_weekday
assert bar_freshness.expected_session("2026-11-27") == "2026-11-25" and health_monitor.prev_session("2026-11-27") == D("2026-11-25") and qm_ep.next_session(D("2026-11-25")) == D("2026-11-27")
assert corp_actions.sessions_since(D("2026-11-23"), D("2026-11-30")) == 4 and corp_actions._sessions_after(D("2026-11-24"), 2) == D("2026-11-27")
assert earnings_move.sessions_after(D("2026-11-20"), D("2026-11-30")) == 5 and thesis_context._business_days(D("2026-11-20"), D("2026-11-30")) == 5
assert cot_track.week_close_date(pd.Timestamp("2026-03-30")) == "2026-04-02" and dataroma.filing_deadline(D("2025-12-31")) == D("2026-02-17")
print("  ✓ setup_rules, bar_freshness, health_monitor, qm_ep, corp_actions, earnings_move, thesis_context, cot_track, dataroma — през src/sessions")

print()
print("── 3. частичният днешен бар (СИНТЕТИЧНО) ──")
idx = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])
bars = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)
assert list(s.complete_bars(bars, "2026-10-20").index) == list(idx[:2]) and s.complete_bars(bars, None) is bars
tz = bars.copy(); tz.index = tz.index.tz_localize("America/New_York")
assert len(s.complete_bars(tz, D("2026-10-20"))) == 2
print("  ✓ барът с дата ≥ днес се маха; без today — както е; индекс с часова зона")

print()
print("── 4. пазач: логиката за сесии не се копира извън src/sessions.py ──")
bad = []
for f in sorted((ROOT / "src").glob("*.py")):
    if f.name == "sessions.py":
        continue
    src = f.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.While, ast.If)) and "NYSE_HOLIDAYS" in ast.unparse(node.test) and "weekday" in ast.unparse(node.test):
            bad.append(f"{f.name}:{node.lineno}")
    if "busday_count(" in src and "sessions.busday_count" not in src.replace("np.busday_count", ""):
        bad.append(f"{f.name}: busday_count")
assert not bad, bad
print("  ✓ няма цикъл/проверка 'weekday + NYSE_HOLIDAYS' и busday_count извън модула")
print("\n✅ test_sessions: всичко мина")
