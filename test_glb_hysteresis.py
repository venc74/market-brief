"""
Пакет 4б (06.10.2026) · т.е: GLB хистерезис — вход само при close ≥ линията × 1.01; кандидатът остава, докато close ≥ линията × 0.97; събитието (линия, дата на входа, тип) се пази в
data/glb_state.json и оцелява при смяна на месеца; картата показва "GLB от <дата>, +X% над линията". Параметрите са в config.py.

РЕАЛНО: цените на 13 тикъра (tests/fixtures/glb_prices_2026-10-05.json — месечни close преди 06.2026, дневни от 06.2026) и РЕАЛНИТЕ GLB списъци от брифовете 14.08–05.10 за тях; реплей с продукционните
функции. Реплеят върху ВСИЧКИ 55 тикъра от реалните списъци (скриптове в scratchpad, не в теста): реално 150 промени (4.2/ден), хистерезис 58 (1.6/ден); нулирания (≥50% изчезват) — реално 1 (02.09),
хистерезис 0; тикъри с ≥2 отделни периода — 23 → 7; но средният размер на списъка расте от 11.2 на 19.3 (пробивите остават до −3% под линията). СИНТЕТИЧНО: месечните серии/цените в граничните
тестове, подменените yf.download/име на компания, временната data/.
Пускане: python test_glb_hysteresis.py
"""
import sys, json, pathlib, tempfile, copy, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import glb_screener as g, render

g._verified_company_name = lambda t: {"name": t}
FIX = ROOT / "tests" / "fixtures"
P = json.loads((FIX / "glb_prices_2026-10-05.json").read_text(encoding="utf-8"))
assert (config.GLB_HYSTERESIS, config.GLB_ENTRY_MARGIN_PCT, config.GLB_EXIT_MARGIN_PCT) == (True, 1.0, 3.0)

print("── буферът при входа (СИНТЕТИЧНА месечна серия: линия 100 от януари, 6 месеца unpenetrated) ──")
idx = pd.date_range("2026-01-31", periods=8, freq="ME")
mk = lambda last: pd.Series([100, 92, 93, 94, 95, 96, 97, last], index=idx)
assert g._monthly_duration_check(mk(100.5)) is not None and g._monthly_duration_check(mk(100.0)) is None            # старото правило: close > линията (без буфер)
assert g._monthly_duration_check(mk(100.5), 1.0) is None and g._monthly_duration_check(mk(100.99), 1.0) is None
r = g._monthly_duration_check(mk(101.0), 1.0)
assert r is not None and r["prior_high"] == 100.0 and r["months_unpenetrated"] == 6
print("  ✓ без буфер: 100.5 е вход (граничният случай, който мига); с буфер 1%: 100.99 не е вход, 101.00 (= линията × 1.01) е")

print()
print("── apply_hysteresis (чиста функция; СИНТЕТИЧНИ наблюдения) ──")
entry = lambda price: {"ticker": "AAA", "company": "AAA", "glb_type": "classic", "prior_high": 100.0, "prior_high_month": "2026-01", "months_unpenetrated": 6,
                       "ath_label": "all_time_high", "history_years": 20.0, "tightness": None, "risk_note": "n", "price": price}
ev, rows, ch = g.apply_hysteresis({}, {"AAA": {"close": 101.5, "entry": entry(101.5)}}, "2026-09-01")
assert ch["entered"] == ["AAA"] and ev["AAA"]["since"] == "2026-09-01" and ev["AAA"]["line"] == 100.0 and rows[0]["pct_vs_line"] == 1.5 and rows[0]["price"] == 101.5
ev, rows, ch = g.apply_hysteresis(ev, {"AAA": {"close": 99.0, "entry": None}}, "2026-09-02")                          # месецът се смени, месечният гейт вече не минава — събитието остава
assert [r["ticker"] for r in rows] == ["AAA"] and rows[0]["pct_vs_line"] == -1.0 and rows[0]["since"] == "2026-09-01" and rows[0]["line"] == 100.0
ev, rows, ch = g.apply_hysteresis(ev, {"AAA": {"close": 97.0, "entry": None}}, "2026-09-03")                          # точно линията × 0.97 → остава (≥)
assert [r["ticker"] for r in rows] == ["AAA"]
ev2, rows, ch = g.apply_hysteresis(ev, {"AAA": {"close": 96.99, "entry": None}}, "2026-09-04")
assert rows == [] and ev2 == {} and ch["dropped"] == ["AAA"]
ev3, rows, ch = g.apply_hysteresis(ev, {}, "2026-09-04")                                                                # без данни днес (провал на теглене) → събитието се пази, не се показва
assert ev3 == ev and rows == [] and ch["held_unseen"] == ["AAA"]
ev4, rows, ch = g.apply_hysteresis(ev, {"AAA": {"close": None, "entry": None}}, "2026-09-04")
assert ev4 == ev and ch["held_unseen"] == ["AAA"]
ev5, rows, ch = g.apply_hysteresis(ev2, {"AAA": {"close": 101.2, "entry": entry(101.2)}}, "2026-09-10")                # след отпадане — нов вход само през правилото за вход, с нова дата
assert ev5["AAA"]["since"] == "2026-09-10" and ch["entered"] == ["AAA"]
print("  ✓ вход 101.5 (дата, линия, тип се замразяват); следващият месец без месечен гейт — остава (−1.0% под линията); точно 97.00 остава, 96.99 отпада; без данни — пази се, не се показва; нов вход — нова дата")

print()
print("── РЕАЛЕН реплей: 13 тикъра, 37 дни (14.08–05.10) ──")
days = sorted(P["real"]); T = sorted(P["monthly"])


def hist(sym, day):
    s = pd.Series({**P["monthly"][sym], **P["daily"][sym]}); s.index = pd.to_datetime(s.index)
    s = s[s.index < pd.Timestamp(day)].sort_index()                                  # брифът е в 05:30 UTC → последният завършен бар е преди деня му
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 1.0})


old, new, state = {}, {}, {}
for d in days:
    o, obs = set(), {}
    for t in T:
        h = hist(t, d)
        if len(h) < 60:
            continue
        if g._monthly_duration_check(h["Close"].resample("ME").last().dropna()) is not None:
            o.add(t)
        obs[t] = {"close": float(h["Close"].iloc[-1]), "entry": None if t in state else g._evaluate_ticker(t, h, config.GLB_ENTRY_MARGIN_PCT)}
    state, rows, ch = g.apply_hysteresis(state, obs, d)
    old[d], new[d] = o, {r["ticker"] for r in rows}
real = {d: set(P["real"][d]) for d in days}
churn = lambda S: sum(len(S[a] - S[b]) + len(S[b] - S[a]) for a, b in zip(days, days[1:]))
agree, total = sum(len(old[d] & real[d]) for d in days), sum(len(real[d]) for d in days)
assert (agree, total) == (106, 111)
assert (churn(real), churn(old), churn(new)) == (43, 35, 17)
print(f"  ✓ двигателят: старото правило върху цените възпроизвежда {agree} от {total} реални реда (95%); промени между дните (изчезвания + появявания): реално {churn(real)}, старо {churn(old)}, хистерезис {churn(new)}")
a, b = "2026-09-01", "2026-09-02"
assert (len(real[a]), len(real[b]), len(real[a] - real[b])) == (7, 1, 7) and (len(new[a]), len(new[b]), sorted(new[a] - new[b])) == (10, 6, ["BLK", "LITE", "PH", "WTW"])
print(f"  ✓ 01.09→02.09 (месечното нулиране): реално {len(real[a])} → {len(real[b])} (всички 7 изчезват); хистерезис {len(new[a])} → {len(new[b])} — отпадат само BLK, LITE, PH, WTW (реално под линията × 0.97)")
a, b = "2026-10-01", "2026-10-02"
assert (len(real[a]), len(real[b]), len(real[a] - real[b])) == (3, 0, 3) and (len(new[a]), len(new[b]), new[a] - new[b]) == (6, 6, set())
print(f"  ✓ 01.10→02.10: реално {len(real[a])} → {len(real[b])} (изчезват 3: GILD, TMO, WAT); хистерезис {len(new[a])} → {len(new[b])}, нищо не изчезва")

print()
print("── screen() със състояние (СИНТЕТИЧНИ цени, подменено yf.download) ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_glb_")
STATE = pathlib.Path(tmp.name) / "glb_state.json"
days_idx = pd.bdate_range("2026-01-01", "2026-09-03")
monthly_end = {1: 100, 2: 92, 3: 93, 4: 94, 5: 95, 6: 96, 7: 97, 8: 101.5}                                              # линия 100 (януари), август затваря 101.5


def frame(last_close_by_date: dict):
    closes = []
    for d in days_idx:
        if d <= pd.Timestamp("2026-08-31"):
            m = monthly_end[d.month]
            closes.append(m if d == days_idx[days_idx.month == d.month][-1] else m - 1.0)
        else:
            closes.append(last_close_by_date.get(d.strftime("%Y-%m-%d"), 99.0))
    s = pd.Series(closes, index=days_idx)
    return pd.DataFrame({"Open": s, "High": s + 0.5, "Low": s - 0.5, "Close": s, "Volume": 1e6, "Stock Splits": 0.0})


def run(through: str, today: str, closes: dict):
    df = frame(closes)
    g.yf.download = lambda batch, **kw: df[df.index <= pd.Timestamp(through)]
    g.time.sleep = lambda s: None
    return g.screen(universe=["AAA"], state_path=STATE, today=today)


r1 = run("2026-08-31", "2026-09-01", {})
assert [x["ticker"] for x in r1] == ["AAA"] and r1[0]["since"] == "2026-09-01" and r1[0]["line"] == 100.0 and r1[0]["pct_vs_line"] == 1.5
st = json.loads(STATE.read_text(encoding="utf-8"))
assert st["updated"] == "2026-09-01" and st["events"]["AAA"]["line"] == 100.0 and st["events"]["AAA"]["since"] == "2026-09-01" and "price" not in st["events"]["AAA"]
r2 = run("2026-09-01", "2026-09-02", {"2026-09-01": 99.0})                              # нов месец; линията по месечната серия вече е 101.5 → старото правило би скрило кандидата
assert [x["ticker"] for x in r2] == ["AAA"] and r2[0]["since"] == "2026-09-01" and r2[0]["line"] == 100.0 and r2[0]["pct_vs_line"] == -1.0
r3 = run("2026-09-02", "2026-09-03", {"2026-09-01": 99.0, "2026-09-02": 96.0})
assert r3 == [] and json.loads(STATE.read_text(encoding="utf-8"))["events"] == {}
STATE.write_text("{счупен json", encoding="utf-8")
assert g.load_state(STATE) == {} and g.load_state(pathlib.Path(tmp.name) / "няма.json") == {}
print("  ✓ ден 1: вход при 101.5 (≥ 101), състоянието е записано; ден 2 (нов месец, close 99): още е кандидат — 'GLB от 01.09, −1.0% под линията', линията е замразена на 100; ден 3 (96 < 97): отпада, състоянието е празно;")
print("    повреден/липсващ state файл → чист старт без грешка")

print()
print("── картата ──")
tmp2 = tempfile.TemporaryDirectory(prefix="mb_glbp_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp2.name) / "docs", pathlib.Path(tmp2.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
brief = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
brief["glb_candidates"] = [{**r2[0], "in_screener": False}]
page = " ".join(htmllib.unescape(render.render_dashboard(brief)).split())
assert "<b>GLB от 01.09</b>, 1.0% под линията ($100.00)" in page
brief["glb_candidates"] = [{**r1[0], "in_screener": False}]
assert "<b>GLB от 01.09</b>, 1.5% над линията ($100.00)" in " ".join(htmllib.unescape(render.render_dashboard(brief)).split())
old_row = {k: v for k, v in r1[0].items() if k not in ("since", "pct_vs_line", "line")}                                  # стар бриф без полетата — без реда и без грешка
brief["glb_candidates"] = [old_row]
assert "GLB от" not in " ".join(htmllib.unescape(render.render_dashboard(brief)).split())
print("  ✓ 'GLB от 01.09, 1.5% над линията ($100.00)' / '1.0% под линията'; ред без новите полета (стар бриф) — без реда")

print()
print("Всички тестове минаха.")
