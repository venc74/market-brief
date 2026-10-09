"""
Маркер "корпоративно действие" върху картите (09.10.2026). Yahoo записва отделянето на Vylor от CTVA на 01.10 като "сплит" с нецял коефициент 6.665 и коригира историята с оценъчен коефициент (в деня цената скача +7.9% при дневно
отклонение 1.9%). Картите на Action, Watchlist, GLB и QM получават ред "⚠ корпоративно действие на ДД.ММ … историята около датата е приблизителна", ако в последните 60 сесии има събитие с НЕЦЯЛ коефициент; цели
коефициенти (2:1, 4:1, 1:5) са точни корекции и не се маркират. Маркер, не изключване.

РЕАЛНО: tests/fixtures/corp_actions_2026-10-09.json — колоните Close и Stock Splits от yf.download(period="6mo", actions=True) на 09.10.2026 за CTVA (6.665 на 01.10), P (няма), IESC/APH/MNST (цял 2:1 в прозореца), MIDD (1.243
на 07.07, преди 67 сесии), BDX, DD (0.3333 = 1:3), FDX (1.241), CRWD (4:1); tests/fixtures/brief_2026-10-09.json — реалният бриф от 09.10 (реалната карта на CTVA в GLB, Watchlist, QM картите SN/ELF/CORT) и
brief_2026-09-22.json (реалните Action карти AMD, TWLO). СИНТЕТИЧНО (маркирано): подменените yf.download / fetch; сериите на CTVA, дадени на тикъри от картите (EXPD, SN, първата Action карта), само за да се провери мястото на реда.
Пускане: python test_corp_action_marker.py
"""
import sys, json, pathlib, copy, io, contextlib, datetime as dt, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import tempfile
import numpy as np
import pandas as pd
import config
from src import corp_actions as ca, data_warnings, render

_tmp = tempfile.TemporaryDirectory(prefix="mb_corp_")                                      # render_dashboard пише в docs/ и data/ — във временна папка, не в реалните
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"; config.DATA_DIR = pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
FX = json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-09.json").read_text(encoding="utf-8"))["tickers"]
B9 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-09.json").read_text(encoding="utf-8"))
B2 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-09-22.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 10, 9)
assert config.CORP_ACTION_WARN_SESSIONS == 60

print("── 1. кой коефициент е цял ──")
for r in (2, 4, 10, 20, 25, 0.5, 0.2, 0.3333, 0.33333333, 5.0):
    assert ca.is_whole_ratio(r), r
for r in (6.665, 1.243, 1.272, 1.241, 1.5, 2.39, 1.057, 0.9535, 1.0, 0, -2, None, "x"):
    assert not ca.is_whole_ratio(r), r
print("  ✓ цели (точна корекция): 2, 4, 10, 20, 25, 1:2, 1:5, 1:3 (реалното 0.3333 на DD); нецели: 6.665 (CTVA), 1.243 (MIDD), 1.272 (BDX), 1.241 (FDX), 1.5, 2.39; невалидни → не е цял")
assert ca.sessions_since(dt.date(2026, 10, 1), TODAY) == 6 and ca.sessions_since(dt.date(2026, 9, 4), dt.date(2026, 9, 8)) == 1        # сесиите от деня на събитието до деня ПРЕДИ днес: 01,02,05,06,07,08.10 = 6; 04.09 → 08.09 е само петъкът 04.09 (07.09 е Labor Day)
print("  ✓ сесиите се броят без уикенди и NYSE празниците (от 04.09 до 08.09 е 1 сесия, защото 07.09 е празник)")

print()
print("── 2. РЕАЛНИТЕ данни на Yahoo от 09.10: кой получава маркер ──")
def frame(t):
    d = FX[t]
    return pd.DataFrame({"Close": d["close"], "Stock Splits": d["splits"]}, index=pd.to_datetime(d["dates"]))
big = pd.concat({t: frame(t) for t in FX}, axis=1)
calls = []
def fake_download(batch, **kw):
    calls.append((list(batch), kw))
    return big[list(batch)]
ca.yf = type("Y", (), {"download": staticmethod(fake_download)})
cards = [{"ticker": t} for t in FX]
diag = ca.annotate([cards], "2026-10-09")
assert diag["ok"] and diag["checked"] == 10 and [f["ticker"] for f in diag["flagged"]] == ["CTVA"], diag
assert calls and calls[0][1].get("actions") is True and calls[0][1].get("auto_adjust") is False and len(calls) == 1
ctva = next(c for c in cards if c["ticker"] == "CTVA")["corp_action"]
assert (ctva["date"], ctva["ratio"], ctva["sessions_ago"]) == ("2026-10-01", 6.665, 6)
assert ctva["text"] == "⚠ корпоративно действие на 01.10 (коефициент 6.665 — отделяне или сплит с нецял коефициент) — историята около датата е приблизителна"
assert all("corp_action" not in c for c in cards if c["ticker"] != "CTVA")
print(f"  ✓ маркирани: само CTVA — «{ctva['text']}»; ЕДНА партида към Yahoo за всички тикъри")
print("  ✓ без маркер: P (няма събития); IESC, APH, MNST (цял 2:1 в прозореца — точна корекция); MIDD (1.243, но преди 67 сесии — извън 60); BDX, DD (0.3333 = 1:3, цял), FDX, CRWD (4:1, преди 69 сесии)")
cards2 = [{"ticker": t} for t in FX]
d70 = ca.annotate([cards2], "2026-10-09", sessions=70)
assert [f["ticker"] for f in d70["flagged"]] == ["CTVA", "MIDD"], d70
d100 = ca.annotate([[{"ticker": t} for t in FX]], "2026-10-09", sessions=100)
assert [f["ticker"] for f in d100["flagged"]] == ["CTVA", "FDX", "MIDD"], d100
print("  ✓ прозорецът е параметър: при 70 сесии към CTVA се добавя MIDD (67), при 100 — и FDX (91); цели коефициенти (DD, CRWD, IESC…) не се маркират при никакъв прозорец")

print()
print("── 3. защо е предупреждение: денят на отделянето (РЕАЛНИ цени) ──")
c = FX["CTVA"]["close"]; dts = FX["CTVA"]["dates"]
r = pd.Series(c, index=pd.to_datetime(dts)).pct_change()
k = dts.index("2026-10-01")
jump, sigma = float(r.iloc[k]) * 100, float(r.iloc[:k].std()) * 100
assert 7.5 < jump < 8.3 and 1.0 < sigma < 3.0 and jump / sigma > 3.5
print(f"  ✓ CTVA на 01.10: {jump:+.1f}% при дневно отклонение {sigma:.1f}% за предходните {k} дни ({jump / sigma:.1f}σ) — корекцията с 6.665 е оценка, историята около датата е приблизителна")

print()
print("── 4. страницата и имейлът ──")
def series_for(*tickers):                                                  # СИНТЕТИЧНО: реалната серия на CTVA, дадена на тикъри от картите, само за да се провери мястото на реда
    s = (FX["CTVA"]["dates"], FX["CTVA"]["splits"])
    return lambda ts: {t: s for t in ts if t in tickers}
b = copy.deepcopy(B9)
diag = ca.annotate([b["action"], b["watchlist"], b["glb_candidates"], b["qm_breakout"]], "2026-10-09", fetch=series_for("CTVA", "EXPD", "SN"))
assert [f["ticker"] for f in diag["flagged"]] == ["CTVA", "EXPD", "SN"]
glb_ctva = next(g for g in b["glb_candidates"] if g["ticker"] == "CTVA")
assert glb_ctva["corp_action"]["date"] == "2026-10-01" and "corp_action" not in next(g for g in b["glb_candidates"] if g["ticker"] == "P")
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(copy.deepcopy(b)); mail = render.render_email(copy.deepcopy(b))
WARN = "⚠ корпоративно действие на 01.10"
assert page.count('class="corp-warn"') == 3 and page.count(WARN) == 3
def around(h, marker, before=3000):
    i = h.index(marker); return htmllib.unescape(re.sub(r"<[^>]+>", " ", h[max(0, i - before):i]))
assert "CTVA" in around(page[page.index("GLB Watchlist"):], WARN) and "EXPD" in around(page[page.index("<h2>Watchlist"):], WARN)
qm_i = page.index('class="corp-warn"', page.index('<div class="qm-grid">')); assert "SN" in htmllib.unescape(re.sub(r"<[^>]+>", " ", page[qm_i - 3000:qm_i]))
print("  ✓ страница: ред «⚠ корпоративно действие на 01.10 …» точно на трите карти — реалната карта на CTVA в GLB (P няма), Watchlist (EXPD) и QM (SN)")
assert mail.count(WARN) == 1 and "SN" in htmllib.unescape(re.sub(r"<[^>]+>", " ", mail[mail.index(WARN) - 900:mail.index(WARN)]))
print("  ✓ имейл: редът е под QM картата SN")
b2 = copy.deepcopy(B2)
t0 = b2["action"][0]["ticker"]
ca.annotate([b2["action"], b2["watchlist"]], "2026-10-09", fetch=series_for(t0))
with contextlib.redirect_stdout(io.StringIO()):
    page2 = render.render_dashboard(copy.deepcopy(b2)); mail2 = render.render_email(copy.deepcopy(b2))
assert page2.count(WARN) == 1 and mail2.count(WARN) == 1 and t0 in htmllib.unescape(re.sub(r"<[^>]+>", " ", page2[page2.index(WARN) - 1800:page2.index(WARN)]))
print(f"  ✓ Action ({t0}, РЕАЛНА карта от 22.09): редът е на страницата и в имейла")
with contextlib.redirect_stdout(io.StringIO()):
    old_page = render.render_dashboard(copy.deepcopy(B9))
assert 'class="corp-warn"' not in old_page.replace("/* 09.10", "") .split("</style>")[1]
print("  ✓ бриф без маркери (или стар) — страницата без реда")

print()
print("── 5. при провал: без маркери, предупреждение в брифа ──")
def boom(ts): raise RuntimeError("Yahoo недостъпен")
cards3 = [{"ticker": "CTVA"}]
with contextlib.redirect_stdout(io.StringIO()):
    dg = ca.annotate([cards3], "2026-10-09", fetch=boom)
assert dg["ok"] is False and "RuntimeError" in dg["error"] and "corp_action" not in cards3[0]
w = data_warnings._corp_warning(dg)
assert len(w) == 1 and w[0]["source"] == "corp_actions" and "НЕ значи" in w[0]["message"] and data_warnings._corp_warning({"ok": True}) == [] and data_warnings._corp_warning(None) == []
assert ca.annotate([[]], "2026-10-09")["checked"] == 0
dnone = ca.annotate([[{"ticker": "X"}]], "2026-10-09", fetch=lambda ts: {})
assert dnone["ok"] and dnone["flagged"] == []
print("  ✓ падналото теглене → ok=False, карти без маркер, предупреждение «… липсата на маркер … НЕ значи, че няма …»; празен списък / тикър без данни — без грешка")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "corp_actions.annotate([action, watchlist, glb_candidates, qm_cards], today)" in src and "corp_diag=corp_diag" in src and '"corp_actions": corp_diag' in src
print("  ✓ main.run: маркерът се слага върху Action, Watchlist, GLB и QM картите преди сглобяването на брифа; diag е в brief['corp_actions'] и в data_warnings")
print("\n✅ test_corp_action_marker: всичко мина")
