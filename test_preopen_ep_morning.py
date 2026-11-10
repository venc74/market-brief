"""
10.11.2026 (т. 2): всеки сутрешен EP кандидат, който не е сред гаповете в карето в 15:05, остава с ред — не изпада тихо. Реално: SANM 10.11 — сутрин
AH +20.2%; в карето (09:08 Ню Йорк) го нямаше. Причината НЕ е липсваща цена: в 09:00 премаркетът беше $163.00 срещу затваряне $149.55 = +9.0% — под прага +10%.
Без премаркет цена → „няма премаркет цена (Yahoo): <причината>“.

РЕАЛНО: tests/fixtures/ep_5m_sanm_aaon_2026-11-10.csv (Yahoo 5m с премаркет, изтеглени 10.11 в 09:57 Ню Йорк), tests/fixtures/ep_aaon_sanm_2026-11-10.json
(сутрешният qm_ep и карето от 10.11), tests/fixtures/brief_2026-10-19.json (рамката на страницата).
СИНТЕТИЧНО (означено): т. 3 — изрязани бари (без премаркет / без редовната сесия / празно) и прагът 8%.
Пускане: python test_preopen_ep_morning.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_epmorning_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen, render

FXD = ROOT / "tests" / "fixtures"
FX = json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
raw = pd.read_csv(FXD / "ep_5m_sanm_aaon_2026-11-10.csv", comment="#")
raw["Datetime"] = pd.to_datetime(raw["Datetime"], utc=True)
FR = {t: g.set_index("Datetime").drop(columns="ticker") for t, g in raw.groupby("ticker")}
NOW = dt.datetime(2026, 11, 10, 14, 8, tzinfo=dt.timezone.utc)                     # 09:08 Ню Йорк — часът на карето от 10.11
BRIEF = {"qm_ep": FX["qm_ep"]}

print("── 1. РЕАЛНО: в 09:08 Ню Йорк AAON е гап, SANM е под прага ──")
pts, gaps, _ = preopen.scan(FR, NOW)
assert [g["ticker"] for g in gaps] == ["AAON"] and abs(gaps[0]["gap_pct"] - FX["preopen"]["gaps"][0]["gap_pct"]) < 1.0      # картата от 10.11: AAON +14.52%
s = pts["SANM"]
assert (round(s["prev_close"], 2), s["pm_price"], s["pm_bars"], s["pm_last_ny"]) == (149.55, 163.0, 22, "09:00")
assert round((s["pm_price"] / s["prev_close"] - 1) * 100, 1) == 9.0
rows = preopen.ep_morning(BRIEF, pts, FR, gaps, NOW)
T = "сутрин AH +20.2% → премаркет +9.0% ($163.00 в 09:00 Ню Йорк; затваряне $149.55) — под прага +10%"
assert [r["ticker"] for r in rows] == ["SANM"] and rows[0]["text"] == T and rows[0]["no_price"] is False
print(f"  ✓ AAON — гап (+{gaps[0]['gap_pct']:.1f}%); SANM — {T}")

print("── 2. РЕАЛНО през run(): тикърите на кандидатите се теглят, редът е в резултата ──")
asked = []
def fetch5(ts):
    asked.extend(ts); return FR
none = lambda *a, **k: {}
with contextlib.redirect_stdout(io.StringIO()):
    res = preopen.run(NOW, fetch5=fetch5, brief=BRIEF, records=[], watched=[], universe=["AAON"], daily_fn=lambda ts: {}, filings_fn=lambda t, s, now_utc=None: [], headlines_fn=lambda t, since: [])
assert "SANM" in asked                                                              # не е в universe — идва от сутрешните EP редове
assert [g["ticker"] for g in res["gaps"]] == ["AAON"] and [x["ticker"] for x in res["ep_morning"]] == ["SANM"] and preopen.has_news(res)
print("  ✓ SANM е в заявката и в res['ep_morning']; has_news → имейл")

print("── 3. без премаркет цена — причината (СИНТЕТИЧНО: изрязани РЕАЛНИ бари) ──")
ix = FR["SANM"].index.tz_convert("America/New_York")
no_pm = FR["SANM"][~((ix.date == dt.date(2026, 11, 10)) & (ix.hour * 60 + ix.minute < 570))]
no_reg = FR["SANM"][ix.date != dt.date(2026, 11, 9)]
assert preopen.premarket_point(no_pm, NOW) is None and preopen.premarket_point(no_reg, NOW) is None
assert preopen.premarket_missing_reason(no_pm, NOW) == "няма премаркет бари днес до 09:08 Ню Йорк"
assert preopen.premarket_missing_reason(no_reg, NOW) == "няма бар от редовната сесия на 09.11"
assert preopen.premarket_missing_reason(None, NOW) == preopen.premarket_missing_reason(no_pm.iloc[:0], NOW) == "Yahoo не върна 5-минутни бари"
fr2 = {**FR, "SANM": no_pm}
p2, g2, _ = preopen.scan(fr2, NOW)
r2 = preopen.ep_morning(BRIEF, p2, fr2, g2, NOW)
assert r2[0]["text"] == "сутрин AH +20.2% → няма премаркет цена (Yahoo): няма премаркет бари днес до 09:08 Ню Йорк" and r2[0]["no_price"]
r3 = preopen.ep_morning(BRIEF, p2, {}, g2, NOW)
assert r3[0]["text"].endswith("няма премаркет цена (Yahoo): Yahoo не върна 5-минутни бари")
old = config.PREOPEN_GAP_PCT; config.PREOPEN_GAP_PCT = 8.0                          # прагът 8% → SANM става гап и редът изчезва
try:
    p4, g4, _ = preopen.scan(FR, NOW)
    assert {g["ticker"] for g in g4} == {"AAON", "SANM"} and preopen.ep_morning(BRIEF, p4, FR, g4, NOW) == []
    assert preopen.ep_morning(BRIEF, p4, FR, g4[:1], NOW)[0]["why"].startswith("извън първите")          # изрязан от PREOPEN_MAX_ROWS
finally:
    config.PREOPEN_GAP_PCT = old
assert preopen.ep_morning({}, pts, FR, gaps, NOW) == [] and preopen.ep_morning(None, pts, FR, gaps, NOW) == []
print("  ✓ без премаркет / без редовната сесия / без бари; праг 8% → гап, без ред; извън първите N")

print("── 4. карето на страницата и имейлът ──")
day = {**FX["preopen"], "ep_morning": rows}
mail = preopen.email_html(day)
assert "Сутрешните EP кандидати извън гаповете" in mail and T in mail and mail.index("AAON") < mail.index(T)
bb = copy.deepcopy(B19); bb["preopen"] = day
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert "Сутрешните EP кандидати извън гаповете · 1" in page and T in page and page.index("AAON") < page.index(T)
d2 = {**FX["preopen"], "gaps": [], "levels": [], "watch": [], "ep_morning": r2}                  # само кандидатът без цена — карето не казва „нищо“
bb["preopen"] = d2
with contextlib.redirect_stdout(io.StringIO()):
    page2 = render.render_dashboard(bb, publish=False)
assert r2[0]["text"] in page2 and "Нищо за отбелязване" not in page2 and preopen.has_news(d2)
bb["preopen"] = {k: v for k, v in FX["preopen"].items()}                                         # стар запис — без полето
with contextlib.redirect_stdout(io.StringIO()):
    assert "Сутрешните EP кандидати" not in render.render_dashboard(bb, publish=False)
print("  ✓ страницата и имейлът; само кандидат без цена → не „Нищо за отбелязване“; стар запис — без реда")
print("\n✅ test_preopen_ep_morning: всичко мина")
