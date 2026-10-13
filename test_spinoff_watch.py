"""
13.10.2026 · предупреждение за ПРЕДСТОЯЩО отделяне от EDGAR 8-K (src/spinoff_watch.py) — детектор, EDGAR (подменен), кеш, дневник, картите, книгите, банерът и редът в main.run.

РЕАЛНО (tests/fixtures/edgar_8k/, свалени от SEC EDGAR на 13.10.2026):
  • CTVA_2026-09-15_8k_main.htm — 8-K на Corteva (7.01/8.01/9.01): Vylor, запис 24.09, разпределение 01.10, 1:1, тикър VYLR;
  • CTVA_submissions_2026-10-13.json — submissions JSON на Corteva (CIK 1755672), подаванията от 01.08.2026 нататък (останалото е отрязано, структурата е непроменена);
  • WDC_2025-02-03_8k_main.htm + WDC_2025-02-03_index.json + WDC_2025-02-03_ex99-1_excerpt.htm — основният документ НЯМА засичане, засичането е в приложението ex-99.1
    (информационният документ на Spinco/Sandisk — два реални откъса от 3.2 MB, байтовете са в HTML коментара в началото): запис 12.02.2025, разпределение 21.02.2025, 1/3 акция за 1;
  • LEN_2025-01-13_ex99-1.htm — Millrose, запис 21.01.2025, разпределение 07.02.2025, 1 за 2;
  • SPGI_2026-05-21_8k_main.htm — Mobility Global, запис 15.06.2026, разпределение 01.07.2026, 1:1;
  • PG_dividend_8k_main.htm — 8-K на P&G за обикновен дивидент ("payable … to shareholders of record") от контролната група — НЕ е засичане.
  • tests/fixtures/brief_2026-09-22.json и brief_2026-10-09.json — рамка за страницата и имейла.
СИНТЕТИЧНО (означено на място): подмененото теглене (get), CIK мапингът, submissions JSON на WDC (един ред с РЕАЛНИТЕ дата/accession/документ/точки), "липсващите" документи
(404), картите и записите в книгите, закачането на предупреждението към реалните карти от 22.09/09.10, кратките прозорци назад (SPINOFF_LOOKBACK_DAYS) и бюджетът.
Пускане: python test_spinoff_watch.py
"""
import sys, json, pathlib, tempfile, copy, re, io, contextlib, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_spinoff_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import spinoff_watch as sw, backtest, data_warnings, render
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))

FX = ROOT / "tests" / "fixtures" / "edgar_8k"
read = lambda n: (FX / n).read_text(encoding="utf-8", errors="replace")
CTVA_BASE = "https://www.sec.gov/Archives/edgar/data/1755672/000119312526391369"
WDC_BASE = "https://www.sec.gov/Archives/edgar/data/106040/000119312525019294"
WDC_SUB = {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2025-02-03"], "accessionNumber": ["0001193125-25-019294"],     # СИНТЕТИЧЕН submissions с РЕАЛНИЯ ред
                                  "primaryDocument": ["d922460d8k.htm"], "items": ["8.01,9.01"]}}}
DOCS = {"https://data.sec.gov/submissions/CIK0001755672.json": read("CTVA_submissions_2026-10-13.json"),
        f"{CTVA_BASE}/d71834d8k.htm": read("CTVA_2026-09-15_8k_main.htm"),
        "https://data.sec.gov/submissions/CIK0000106040.json": json.dumps(WDC_SUB),
        f"{WDC_BASE}/d922460d8k.htm": read("WDC_2025-02-03_8k_main.htm"),
        f"{WDC_BASE}/index.json": read("WDC_2025-02-03_index.json"),
        f"{WDC_BASE}/d922460dex991.htm": read("WDC_2025-02-03_ex99-1_excerpt.htm")}
CIK = {"CTVA": "1755672", "WDC": "106040"}                                    # СИНТЕТИЧНО: вместо company_tickers.json (мрежа)
calls = []


def fake_get(url):                                                            # СИНТЕТИЧНО: мрежата → РЕАЛНИТЕ файлове; липсващ документ → 404
    calls.append(url)
    if url in DOCS:
        return DOCS[url]
    raise RuntimeError("404 (СИНТЕТИЧНО: документът не е във fixture-ите)")


def check(tickers, today, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return sw.check(tickers, today, get=kw.pop("get", fake_get), cik_map=kw.pop("cik_map", CIK), **kw)


print("── 1. детекторът върху РЕАЛНИТЕ 8-K ──")
det = lambda n, t: sw.detect(sw.text_of(read(n)), t)
CT = det("CTVA_2026-09-15_8k_main.htm", "CTVA")
assert CT == {"record": "2026-09-24", "distribution": "2026-10-01", "ratio": "1:1", "new": "Vylor", "new_ticker": "VYLR"}, CT
assert det("WDC_2025-02-03_8k_main.htm", "WDC") is None
assert det("WDC_2025-02-03_ex99-1_excerpt.htm", "WDC") == {"record": "2025-02-12", "distribution": "2025-02-21", "ratio": "1/3 за 1", "new": "Spinco", "new_ticker": None}
assert det("LEN_2025-01-13_ex99-1.htm", "LEN") == {"record": "2025-01-21", "distribution": "2025-02-07", "ratio": "1 за 2", "new": "Millrose", "new_ticker": None}
assert det("SPGI_2026-05-21_8k_main.htm", "SPGI") == {"record": "2026-06-15", "distribution": "2026-07-01", "ratio": "1:1", "new": "Mobility Global", "new_ticker": None}
assert det("PG_dividend_8k_main.htm", "PG") is None
print("  ✓ CTVA (Vylor 1:1, 24.09 → 01.10, VYLR) · WDC — основният документ без засичане, ex-99.1: Spinco 1/3 за 1, 12.02 → 21.02 · LEN 1 за 2 · SPGI 1:1 · PG дивидент → нищо")

print()
print("── 2. recent_8k върху РЕАЛНИЯ submissions JSON на Corteva ──")
sub = json.loads(read("CTVA_submissions_2026-10-13.json"))
fs = sw.recent_8k(sub, "2026-08-14", "2026-10-13")
assert len(fs) == 14 and all(f["items"] and ("8.01" in f["items"] or "7.01" in f["items"]) for f in fs)
f915 = [f for f in fs if f["date"] == "2026-09-15"]
assert f915 == [{"date": "2026-09-15", "acc": "0001193125-26-391369", "doc": "d71834d8k.htm", "items": "7.01,8.01,9.01"}]
assert sw.recent_8k(sub, "2026-09-14", "2026-09-16") == f915
print(f"  ✓ 14 подавания 8-K с 8.01/7.01 от 14.08 до 13.10; 15.09 — 0001193125-26-391369 (7.01,8.01,9.01)")

print()
print("── 3. check(): CTVA на 16.09 — предупреждение, дневник, кеш ──")
config.SPINOFF_LOOKBACK_DAYS = 2                                              # СИНТЕТИЧНО: тесен прозорец → само РЕАЛНИЯТ документ от 15.09
act = check(["CTVA"], dt.date(2026, 9, 16))
assert list(act) == ["CTVA"] and {k: act["CTVA"][k] for k in CT} == CT and act["CTVA"]["filing_date"] == "2026-09-15" and act["CTVA"]["where"] == "main"
d = dict(sw.LAST_DIAG)
assert d["ok"] and d["checked"] == 1 and d["filings"] == 1 and d["fetched"] == 1 and d["logged"] == 1 and not d["errors"] and not d["unchecked"]
log = json.loads((config.DATA_DIR / config.SPINOFF_LOG_NAME).read_text(encoding="utf-8"))
assert log["entries"] == [{"ticker": "CTVA", "filing_date": "2026-09-15", "accession": "0001193125-26-391369", "record": "2026-09-24", "distribution": "2026-10-01",
                           "ratio": "1:1", "new": "Vylor", "new_ticker": "VYLR", "where": "main", "first_seen": "2026-09-16"}], log
n_doc = sum(1 for u in calls if u.endswith("d71834d8k.htm"))
config.SPINOFF_LOOKBACK_DAYS = 60                                             # истинският прозорец: 15.09 + РЕАЛНИТЕ подавания, които не са във fixture-ите (→ 404)
act2 = check(["CTVA"], dt.date(2026, 9, 30))                                   # между записа и разпределението — предупреждението стои
assert list(act2) == ["CTVA"] and sum(1 for u in calls if u.endswith("d71834d8k.htm")) == n_doc and sw.LAST_DIAG["fetched"] == 0
assert sw.LAST_DIAG["filings"] == len(sw.recent_8k(sub, "2026-08-01", "2026-09-30")) and len(sw.LAST_DIAG["errors"]) == sw.LAST_DIAG["filings"] - 1
log2 = json.loads((config.DATA_DIR / config.SPINOFF_LOG_NAME).read_text(encoding="utf-8"))
assert len(log2["entries"]) == 1 and sw.LAST_DIAG["logged"] == 0
assert sw.windows() == {"CTVA": [("2026-09-24", "2026-10-01")]}
print("  ✓ 16.09: активно (запис 24.09, разпределение 01.10); дневникът: CTVA · 8-K 15.09 · запис 24.09 · 01.10 · 1:1 · Vylor/VYLR")
print("  ✓ 30.09: пак активно (и при 404 за другите подавания); документът НЕ се тегли повторно (кеш по accession); дневникът — без дубликат")

calls.clear()
act3 = check(["CTVA"], dt.date(2026, 10, 13))                                  # след разпределението + 13 РЕАЛНИ подавания, които не са във fixture-ите (→ 404)
d3 = dict(sw.LAST_DIAG)
assert act3 == {} and d3["ok"] and d3["filings"] == 14 and len(d3["errors"]) == 13 and not any(u.endswith("d71834d8k.htm") for u in calls)
cache = json.loads((config.DATA_DIR / config.SPINOFF_CACHE_NAME).read_text(encoding="utf-8"))
assert list(cache["docs"]) == ["0001193125-26-391369"]                          # провалените не са в кеша → следващият run опитва пак
w = data_warnings.collect(None, None, spinoff_diag=d3)
assert len(w) == 1 and w[0]["source"] == "spinoff" and "1 от 1 тикъра не са проверени днес (CTVA)" in w[0]["message"]
print("  ✓ 13.10: след 01.10 няма предупреждение; 13 документа не се свалиха → не са в кеша, банер '1 от 1 тикъра не са проверени днес (CTVA) …'")

print()
print("── 4. check(): WDC — засичането е в приложението ex-99.1 (index.json) ──")
act_w = check(["WDC"], dt.date(2025, 2, 4))
assert act_w["WDC"]["where"] == "d922460dex991.htm" and act_w["WDC"]["distribution"] == "2025-02-21" and act_w["WDC"]["ratio"] == "1/3 за 1"
print("  ✓ основният документ без засичане → index.json → d922460dex991.htm: Spinco 1/3 за 1, 12.02 → 21.02")

print()
print("── 5. graceful ──")
act_f = check(["CTVA", "WDC"], dt.date(2026, 9, 16), get=lambda u: (_ for _ in ()).throw(RuntimeError("EDGAR down (СИНТЕТИЧНО)")))
assert act_f == {} and sw.LAST_DIAG["ok"] is False
wf = data_warnings.collect(None, None, spinoff_diag=dict(sw.LAST_DIAG))
assert len(wf) == 1 and "липсата на предупреждение днес НЕ значи, че няма предстоящо отделяне" in wf[0]["message"]
act_m = check(["CTVA"], dt.date(2026, 9, 16), cik_map={})
assert act_m == {} and sw.LAST_DIAG["ok"] is False and "CIK" in sw.LAST_DIAG["error"]
act_b = check(["CTVA", "WDC"], dt.date(2026, 9, 16), budget_sec=-1)            # СИНТЕТИЧНО: изчерпан бюджет
assert act_b == {} and sw.LAST_DIAG["unchecked"] == ["CTVA", "WDC"] and sw.LAST_DIAG["ok"]
wb = data_warnings.collect(None, None, spinoff_diag=dict(sw.LAST_DIAG))
assert len(wb) == 1 and "2 от 2 тикъра не са проверени днес (CTVA, WDC)" in wb[0]["message"]
config.SPINOFF_LOOKBACK_DAYS = 2
check(["CTVA"], dt.date(2026, 9, 16))
assert data_warnings.collect(None, None, spinoff_diag=dict(sw.LAST_DIAG)) == []
print("  ✓ EDGAR не отговаря → {} + банер 'липсата на предупреждение днес НЕ значи …'; без CIK мапинг → същото; изчерпан бюджет → 'не са проверени'; успешна проверка → без банер")

print()
print("── 6. текстът на картата и бележката ──")
WANT = ("⚠ Предстои отделяне на Vylor (1:1) на 01.10, запис 24.09 — от 01.10 историята ще е оценка; цената пада с ~стойността на VYLR (не е загуба); "
        "стопът в $ спира да важи; книгите не записват нов вход от датата на запис до отделянето")
assert sw.warning_text(act2["CTVA"]) == WANT, sw.warning_text(act2["CTVA"])
assert sw.note_text(act2["CTVA"]) == "предстои отделяне на 01.10 (запис 24.09)"
assert "стойността на Spinco" in sw.warning_text(act_w["WDC"])                  # без тикър на новата компания → името
cards = [{"ticker": "CTVA"}, {"ticker": "P"}]                                  # СИНТЕТИЧНИ карти
assert sw.annotate([cards], act2) == 1 and cards[0]["spinoff_warning"]["text"] == WANT and "spinoff_warning" not in cards[1]
print("  ✓", WANT)

print()
print("── 7. книгите: нов вход от 24.09 до 01.10 не се записва; отворен запис — само бележка ──")
for k in ("TRACK_BUYSTOP", "TRACK_QM", "TRACK_GLB_WISH"):
    setattr(config, k, True)
config.BUYSTOP_TRACK_FROM = config.QM_TRACK_FROM = config.GLB_WISH_TRACK_FROM = ""
backtest.SPINOFF_WINDOWS = sw.windows()
PLAN = {"valid": True, "method": "v2", "buy_stop": 80.0, "max_chase": 84.0, "stop_loss": 74.0, "target_1": 92.0, "entry_mid": 79.0, "valid_through": "2026-10-02"}   # СИНТЕТИЧНО
BS = {"ticker": "CTVA", "setup": {"kind": "below_pivot", "buy_stop": 80.0}, "plan_preview": PLAN}
QM = {"ticker": "CTVA", "trigger": 80.0, "adr": 2.1, "close": 79.0}
GW = {"ticker": "CTVA", "signal_date": "2026-09-24", "line": 78.0, "close": 79.0}
AC = {"ticker": "CTVA", "plan": PLAN}
backtest.LAST_SPINOFF_SKIPS.clear()
with contextlib.redirect_stdout(io.StringIO()):
    for day, want in (("2026-09-23", 4), ("2026-09-24", 0), ("2026-09-30", 0), ("2026-10-01", 0), ("2026-10-02", 4)):
        tr = {}
        backtest._ingest_action_list(tr, day, [AC]); backtest._ingest_buystop_list(tr, day, [BS])
        backtest._ingest_qm_list(tr, day, [QM]); backtest._ingest_glb_wish_list(tr, day, [GW])
        assert len(tr) == want, (day, list(tr))
skips = backtest.LAST_SPINOFF_SKIPS
assert len(skips) == 12 and {s["category"] for s in skips} == {"action", "buystop", "qm_breakout", "glb_wish"}
assert skips[0]["reason"] == "предстоящо отделяне: запис 2026-09-24, разпределение 2026-10-01 — нов вход не се записва"
print("  ✓ 23.09 и 02.10 — по 4 записа (Action, buy-stop, QM, Уиш); 24.09, 30.09, 01.10 — нито един, 12 причини в диагностиката")

tr = {}
backtest._ingest_buystop_list(tr, "2026-09-23", [BS]); backtest._ingest_qm_list(tr, "2026-09-23", [QM])
tr["CTVA_2026-09-01_buystop"] = {**tr["CTVA_2026-09-23_buystop"], "entry_date": "2026-09-01", "status": "stopped"}     # СИНТЕТИЧНО: затворен запис
backtest._save_tracker(tr)
assert backtest.live_tickers() == ["CTVA"]
assert backtest.apply_spinoff_notes(act2, dt.date(2026, 9, 30)) == 2
tr = backtest._load_tracker()
NOTE = {"text": "предстои отделяне на 01.10 (запис 24.09)", "record": "2026-09-24", "distribution": "2026-10-01"}
assert tr["CTVA_2026-09-23_buystop"]["spinoff_note"] == NOTE and tr["CTVA_2026-09-23_qm"]["spinoff_note"] == NOTE and "spinoff_note" not in tr["CTVA_2026-09-01_buystop"]
assert "needs_manual_review" not in tr["CTVA_2026-09-23_buystop"]                     # ръчният преглед е от деня на отделянето (_flag_spin_off), не от предупреждението
bsum = backtest.get_buystop_summary()
assert [r["spinoff_note"] for r in bsum["live"]] == [NOTE]
assert backtest.apply_spinoff_notes({}, dt.date(2026, 9, 30)) == 0 and backtest._load_tracker()["CTVA_2026-09-23_buystop"]["spinoff_note"] == NOTE   # провал на EDGAR ≠ махане
backtest.apply_spinoff_notes({}, dt.date(2026, 10, 2))
assert not any("spinoff_note" in r for r in backtest._load_tracker().values())
print("  ✓ живите записи (buy-stop, QM) — бележка 'предстои отделяне на 01.10 (запис 24.09)', без ръчен преглед; затвореният — без; празен резултат от EDGAR не я маха; след 01.10 се маха")

print()
print("── 8. страницата и имейлът (РЕАЛНИТЕ брифове от 09.10 и 22.09 като рамка; закачането е СИНТЕТИЧНО) ──")
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
b9 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-09.json").read_text(encoding="utf-8"))
sw.annotate([b9["qm_breakout"][:1], b9["glb_candidates"][:1]], {b9["qm_breakout"][0]["ticker"]: act2["CTVA"], b9["glb_candidates"][0]["ticker"]: act2["CTVA"]})
b9.setdefault("backtest", {})["buystop"] = bsum
bsum["live"][0]["spinoff_note"] = NOTE
page = flat(render.render_dashboard(b9))
assert page.count(WANT) == 2 and "⚠ предстои отделяне на 01.10 (запис 24.09)" in page
b22 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-09-22.json").read_text(encoding="utf-8"))
sw.annotate([b22["action"][:1]], {b22["action"][0]["ticker"]: act2["CTVA"]})
assert WANT in flat(render.render_dashboard(copy.deepcopy(b22))) and WANT in flat(render.render_email(b22))
wl = [{"ticker": "CTVA", "setup": {"kind": "too_wide", "struct_risk_pct": 12.0}, "spinoff_warning": cards[0]["spinoff_warning"]}]      # СИНТЕТИЧЕН компактен ред
assert render.split_watchlist(wl)[1][0]["spinoff"]["distribution"] == "2026-10-01"
print("  ✓ QM и GLB карти (09.10), Action карта и имейл (22.09), бележка в таблицата на buy-stop книгата, компактен ред на Watchlist")

print()
print("── 9. main.run: проверката е преди книгите, бележките — след записа и преди обобщенията ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_chk = src.index("spinoff_active = spinoff_watch.check(")
i_ann = src.index("spinoff_watch.annotate([action, watchlist, qm_cards, glb_candidates], spinoff_active)")
i_win = src.index("backtest.SPINOFF_WINDOWS = spinoff_watch.windows()")
i_upd = src.index("backtest.update_backtest_tracker(action, today, watchlist_before_expiry")
i_note = src.index("backtest.apply_spinoff_notes(spinoff_active")
i_sum = src.index("backtest_summary = backtest.get_backtest_summary()")
assert src.index("qm_cards = qm_breakout.cards(") < i_chk < i_ann < i_win < i_upd < i_note < i_sum
assert "budget_sec=config.SPINOFF_BUDGET_SEC" in src and "spinoff_diag=dict(spinoff_watch.LAST_DIAG)" in src and '"spinoff": {**spinoff_watch.LAST_DIAG, "skipped_entries"' in src
print("  ✓ QM/GLB карти → check → annotate → прозорци → книги → бележки → обобщения; банерът и brief['spinoff']")
print()
print("Всички тестове минаха.")
