"""
12.11.2026 (т. 2, CRWV 11.11): дневникът на EP (data/ep_ah_log.json) записва и гаповете ≥ 10%, видени в карето преди отварянето (09:05 Ню Йорк) — не само after-hours гаповете
от сутрешния бриф — с отварянето и затварянето. Записват се в сутрешния бриф на следващия ден (един писач на дневника) от data/preopen/<дата>.json и се разрешават веднага;
пропуснатите от 04.11 насам се допълват сами (до 30 дни назад). Реално: CRWV 11.11 — премаркет +13.4% (09:05) → отваряне +14.85% → затваряне +24.71%.

РЕАЛНО: tests/fixtures/preopen_gaps_2026-11-04_12.json — гаповете от седемте каре 04.11–12.11 (data/preopen/, изрязани до date / session / time_ny / gaps, 12.11.2026);
tests/fixtures/ep_ah_log_2026-11-12.json — дневникът към 12.11 (9 after-hours записа); tests/fixtures/ep_preopen_daily_2026-11-12.csv — дневните бари от Yahoo (auto_adjust=False)
за 16-те тикъра, 28.10–11.11, изтеглени 12.11.2026 в 15:59 Берлин; brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): т. 5 — 12 гапа в един ден (над PREOPEN_MAX_ROWS), нечетим файл.
Пускане: python test_ep_log_preopen.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_eplog_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import qm_ep, preopen, render

FXD = ROOT / "tests" / "fixtures"
PG = json.loads((FXD / "preopen_gaps_2026-11-04_12.json").read_text(encoding="utf-8"))["files"]
LOG0 = {"entries": json.loads((FXD / "ep_ah_log_2026-11-12.json").read_text(encoding="utf-8"))["entries"]}
_d = pd.read_csv(FXD / "ep_preopen_daily_2026-11-12.csv")
DAILY = {t: g.set_index(pd.DatetimeIndex(pd.to_datetime(g["date"])))[["Open", "High", "Low", "Close", "Volume"]] for t, g in _d.groupby("ticker")}
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
PDIR = config.DATA_DIR / "preopen"; PDIR.mkdir()
for day, p in PG.items():
    (PDIR / f"{day}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
D = dt.date.fromisoformat
daily_fn = lambda ts: {t: DAILY[t] for t in ts if t in DAILY}

print("── 1. РЕАЛНО: гаповете от карето 04.11–11.11 (за брифа на 12.11) ──")
rows = qm_ep.preopen_gaps(D("2026-11-12"), PDIR)
assert [(r["ticker"], r["gap_session"]) for r in rows][:3] == [("DUOL", "2026-11-04"), ("BRKR", "2026-11-04"), ("KD", "2026-11-04")]
assert len(rows) == 15 and "TTEK" not in {r["ticker"] for r in rows}                     # 12.11 — днешното каре още не е минало
crwv = next(r for r in rows if r["ticker"] == "CRWV")
assert crwv == {"ticker": "CRWV", "session": "2026-11-10", "gap_session": "2026-11-11", "prev_close": 48.73, "pm_price": 55.27, "pm_gap_pct": 13.42,
                "pm_last_ny": "09:05", "neglect": True, "ret63_pct": -54.8}, crwv
assert len(qm_ep.preopen_gaps(D("2026-11-13"), PDIR)) == 16 and qm_ep.preopen_gaps(D("2026-12-20"), PDIR) == []       # до 30 дни назад
print(f"  ✓ 15 гапа от 6 каре (09.11 — без гапове); CRWV 11.11: +13.42% в 09:05 ($55.27 срещу $48.73)")

print("── 2. РЕАЛНО: в дневника — нови записи и допълнени after-hours записи ──")
log = copy.deepcopy(LOG0)
ah_before = qm_ep.summarize_log(log["entries"])
added, merged = qm_ep.add_preopen_entries(log, rows, "2026-11-12")
assert (added, merged) == (11, 4), (added, merged)
m = {e["ticker"]: e for e in log["entries"]}
assert [t for t in ("DUOL", "APP", "ABNB", "AAON") if m[t].get("source") is None and m[t]["pm_gap_pct"] is not None] == ["DUOL", "APP", "ABNB", "AAON"]
assert m["AAON"]["ah_gap_pct"] == 15.64 and m["AAON"]["pm_gap_pct"] == 14.52 and m["AAON"]["open_gap_pct"] == 13.95          # сутрин и в 15:05 — един запис
assert m["CRWV"]["source"] == "preopen" and m["CRWV"]["ah_gap_pct"] is None and m["CRWV"]["open_gap_pct"] is None
assert qm_ep.add_preopen_entries(log, rows, "2026-11-12") == (0, 0)                       # без дубликати
assert qm_ep.summarize_log(log["entries"]) == ah_before                                   # after-hours обобщението не се променя
print("  ✓ 11 нови (source preopen), 4 допълнени (DUOL, APP, ABNB, AAON — и сутрин, и в 15:05); повторно — нищо; after-hours обобщението — същото")

print("── 3. РЕАЛНО: отварянето и затварянето ──")
n = qm_ep.resolve_entries(log, D("2026-11-12"), daily_fn)
assert n == 11
assert (m["CRWV"]["open_gap_pct"], m["CRWV"]["close_pct"], m["CRWV"]["high_pct"]) == (14.85, 24.71, 27.28), m["CRWV"]
assert (m["NBIS"]["open_gap_pct"], m["NBIS"]["close_pct"]) == (11.73, 15.44) and (m["TPR"]["open_gap_pct"], m["TPR"]["close_pct"]) == (11.72, 7.07)
sp = qm_ep.summarize_preopen(log["entries"])
assert sp == {"entries": 15, "resolved": 15, "since": "2026-11-04", "held_at_open": 15, "median_open_gap_pct": 12.66, "median_close_pct": 15.44}, sp
print("  ✓ CRWV 11.11: отваряне +14.85%, затваряне +24.71% (връх +27.28%); от 04.11: 15 от 15 отварят ≥ 10%, медиана — отваряне +12.66%, затваряне +15.44%")

print("── 4. run(): дневникът, вчерашният ред, страницата и имейлът ──")
LOG = pathlib.Path(_tmp.name) / "log.json"
LOG.write_text(json.dumps(LOG0), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    out = qm_ep.run([], D("2026-11-12"), fetch_5m_fn=lambda u: ({}, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=daily_fn, log_path=LOG, preopen_dir=PDIR)
L = out["log"]
assert L["entries"] == 9 and L["yesterday"] == [] and L["preopen"]["entries"] == 15 and (L["preopen"]["added_today"], L["preopen"]["merged_today"]) == (11, 4)
assert [(y["ticker"], y["pm_gap_pct"], y["open_gap_pct"], y["close_pct"], y["held"]) for y in L["yesterday_pm"]] == [
    ("CRWV", 13.42, 14.85, 24.71, True), ("NBIS", 10.9, 11.73, 15.44, True)], L["yesterday_pm"]             # само 11.11 — допълнените назад са в общия брой
saved = json.loads(LOG.read_text(encoding="utf-8"))["entries"]
assert len(saved) == 20 and sum(1 for e in saved if e.get("source") == "preopen") == 11
with contextlib.redirect_stdout(io.StringIO()):
    again = qm_ep.run([], D("2026-11-12"), fetch_5m_fn=lambda u: ({}, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=daily_fn, log_path=LOG, preopen_dir=PDIR)
assert (again["log"]["preopen"]["added_today"], again["log"]["preopen"]["merged_today"]) == (0, 0) and len(json.loads(LOG.read_text())["entries"]) == 20
bb = copy.deepcopy(B19); bb["qm_ep"] = out
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
txt = " ".join(__import__("re").sub(r"<[^>]+>", " ", page).split())
assert ("Вчерашният дневник — премаркет в 09:05 Ню Йорк (карето) срещу отваряне и затваряне: CRWV премаркет +13.4% (09:05) → отваряне +14.8% (издържа ≥ 10%) "
        "→ затваряне +24.7%; NBIS премаркет +10.9% (09:05) → отваряне +11.7% (издържа ≥ 10%) → затваряне +15.4%.") in txt, txt[txt.find("Вчерашният"):][:400]
assert "Вчера няма гапове за проверка срещу отварянето" not in txt
assert ("Гаповете от карето в 09:05 Ню Йорк (от 04.11): записи 15, разрешени 15; 15 от тях отварят ≥ 10%, медиана — отваряне +12.7%, затваряне +15.4%.") in txt
assert "Общо в дневника: записи 9, разрешени 9" in txt                                     # after-hours частта — както досега
mail = render._qm_email_block(bb)
assert "Вчера, премаркет в 09:05 Ню Йорк: CRWV +13.4% → отваряне +14.8% (издържа) → затваряне +24.7%; NBIS +10.9% → отваряне +11.7% (издържа) → затваряне +15.4%." in mail
print("  ✓ страницата: вчерашният ред за CRWV и NBIS + общият брой от 04.11; after-hours редът — без промяна; имейлът")

print("── 5. preopen.gaps_all: всички гапове ≥ 10%, и над показаните; СИНТЕТИЧНО ──")
p11 = PG["2026-11-11"]["gaps"]
ga = preopen.gaps_all([{**g, "prev_close": g["prev_close"] + 0.5} for g in p11], p11)           # показаните — официалното затваряне от ep_rows, не 5-минутното
assert [(g["ticker"], g["prev_close"], g["gap_pct"], g["neglect"]) for g in ga] == [("CRWV", 48.73, 13.42, True), ("NBIS", 134.0, 10.9, True)]
many = [{"ticker": f"T{i:02d}", "session": "2026-11-10", "prev_close": 10.0, "pm_price": 11.5 - i * 0.01, "gap_pct": 15 - i * 0.1, "pm_bars": 5, "pm_last_ny": "09:05"} for i in range(12)]
ga2 = preopen.gaps_all(many, [])
assert len(ga2) == 12 and ga2[-1]["ticker"] == "T11" and ga2[-1]["neglect"] is None
(PDIR / "2026-11-10.json").write_text(json.dumps({**PG["2026-11-10"], "gaps_all": ga2}), encoding="utf-8")
assert sum(1 for r in qm_ep.preopen_gaps(D("2026-11-12"), PDIR) if r["gap_session"] == "2026-11-10") == 12      # gaps_all има предимство пред gaps
(PDIR / "2026-11-09.json").write_text("{счупен", encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    assert len(qm_ep.preopen_gaps(D("2026-11-12"), PDIR)) == 26                              # нечетимият файл се пропуска
print("  ✓ 12 гапа в един ден — всички в дневника (gaps_all); нечетим файл — пропуснат")
print("\n✅ test_ep_log_preopen: всичко мина")
