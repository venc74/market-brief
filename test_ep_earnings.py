"""
17.11.2026 (пакет 1, т. 6): EP гап с 8-K т. 2.02 (резултати) — ред „отчет: EPS $X срещу очаквани $Y (изненада ±Z%)“ (Yahoo, earnings dates) и заглавие само ако е за отчета
или прогнозата. Реално: в карето в 15:05 APP (05.11) носеше „ETFs Are Net Sellers of AppLovin (APP) on Nov. 3“, AAON (10.11) — „The Aaon Group Announces Quarterly Cash
Dividend“, а и двете имаха 8-K т. 2.02 от предишната вечер.

РЕАЛНО: tests/fixtures/eps_surprise_app_aaon_2026-11-17.json — get_earnings_dates на APP и AAON (Yahoo, 17.11.2026); заглавията и 8-K — от data/preopen/2026-11-05.json и
2026-11-10.json (карето) и от сутрешните EP редове на 05.11 и 10.11 (цитирани тук). brief_2026-10-19.json и ep_aaon_sanm_2026-11-10.json — рамката и карето.
СИНТЕТИЧНО (означено): т. 3 — липсващ отчетен EPS.
Пускане: python test_ep_earnings.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_epearn_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, preopen, render

FXD = ROOT / "tests" / "fixtures"
EPS = json.loads((FXD / "eps_surprise_app_aaon_2026-11-17.json").read_text(encoding="utf-8"))
APP_HL = [{"title": "ETFs Are Net Sellers of AppLovin (APP) on Nov. 3", "source": None},                                        # РЕАЛНО: избраното в карето на 05.11
          {"title": "AppLovin Corp (APP) (Q3 2026) Earnings Call Highlights: Record $2. ...", "source": None}]                   # РЕАЛНО: от сутрешния EP ред на 05.11
AAON_HL = [{"title": "The Aaon Group Announces Quarterly Cash Dividend", "source": None},                                     # РЕАЛНО: карето на 10.11
           {"title": "AAON Q3 Earnings Call Highlights", "source": None}]                                                      # РЕАЛНО: сутрешният EP ред на 10.11
F_APP = [{"accepted_et": "2026-11-04 16:08", "items": ["2.02", "5.07"]}]
F_AAON = [{"accepted_et": "2026-11-09 16:09", "items": ["2.02", "4.02", "7.01"]}]

print("── 1. РЕАЛНО: изненадата в EPS ──")
a = qm_ep.eps_surprise("APP", "2026-11-04", rows=EPS["APP"]); b = qm_ep.eps_surprise("AAON", "2026-11-09", rows=EPS["AAON"])
assert a == {"date": "2026-11-04", "reported": 4.3, "estimate": 4.03, "surprise_pct": 6.7} and b["surprise_pct"] == 43.5
assert qm_ep.earnings_line(a) == "отчет: EPS $4.30 срещу очаквани $4.03 (изненада +6.7%)"
assert qm_ep.earnings_line(b) == "отчет: EPS $0.83 срещу очаквани $0.58 (изненада +43.5%)"
print(f"  ✓ APP: «{qm_ep.earnings_line(a)}»; AAON: «{qm_ep.earnings_line(b)}»")

print("── 2. РЕАЛНО: заглавията — само за отчета ──")
assert qm_ep.has_202(F_APP) and qm_ep.has_202(F_AAON) and qm_ep.has_202([{"items": [["2.02", "Results", "резултати"]]}]) and not qm_ep.has_202([{"items": ["7.01"]}])
assert [h["title"] for h in qm_ep.earnings_headlines(APP_HL)] == [APP_HL[1]["title"]]
assert [h["title"] for h in qm_ep.earnings_headlines(AAON_HL)] == [AAON_HL[1]["title"]]
assert qm_ep.earnings_headlines([{"title": "8-K (SEC) …", "source": "SEC"}]) == [{"title": "8-K (SEC) …", "source": "SEC"}]
print("  ✓ „ETFs Are Net Sellers…“ и „Quarterly Cash Dividend“ — вън; „… Earnings Call Highlights“ — остава; редът на 8-K — остава")

print("── 3. СИНТЕТИЧНО: без отчетен EPS ──")
assert qm_ep.earnings_line(qm_ep.eps_surprise("X", "2026-11-04", rows=[{"date": "2026-11-04 16:00:00-05:00", "EPS Estimate": 1.0, "Reported EPS": None}])) == \
    "отчет (8-K т. 2.02): изненадата в EPS не е налична (Yahoo няма отчетен EPS за тази дата)"
print("  ✓ причината — изрично")

print("── 4. карето в 15:05: ep_rows (подменени източници с РЕАЛНИТЕ данни на AAON) ──")
from src import qm_ep as Q
gaps = [{"ticker": "AAON", "session": "2026-11-09", "prev_close": 100.0, "pm_price": 114.5, "pm_bars": 5, "pm_volume": 1000, "pm_last_ny": "09:00", "gap_pct": 14.5}]
with contextlib.redirect_stdout(io.StringIO()):
    rows = preopen.ep_rows(gaps, daily_fn=lambda t: {}, filings_fn=lambda sym, sess, **k: [{"accepted_et": "2026-11-09 16:09", "items": [("2.02", "Results", "финансови резултати"), ("4.02", "x", "y")]}],
                           headlines_fn=lambda sym, since: AAON_HL, name_lookup=lambda t: "AAON, Inc.", eps_fn=lambda t, s: Q.eps_surprise(t, s, rows=EPS["AAON"]))
r = rows[0]
assert r["earnings_text"] == "отчет: EPS $0.83 срещу очаквани $0.58 (изненада +43.5%)" and r["headline"]["title"] == "AAON Q3 Earnings Call Highlights"
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "{{ g.earnings_text }}" in tpl and "{{ r.earnings_text }}" in tpl
mail = preopen.email_html({**json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))["preopen"], "gaps": rows})
assert "отчет: EPS $0.83 срещу очаквани $0.58 (изненада +43.5%)" in mail and "Quarterly Cash Dividend" not in mail
print("  ✓ AAON в карето: редът за отчета и заглавието за отчета; имейлът — същото")
print("\n✅ test_ep_earnings: всичко мина")
