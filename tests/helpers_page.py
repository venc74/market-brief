"""
Обща помощна част за тестовете на "стоп и размер" (07.10.2026): страница на брифа с РЕАЛНИ нива — EXEL (Action), EXPD (Watchlist, buy-stop), DOCN/CORT/CRL (QM breakout) и SYNA (EP) — върху РЕАЛНИЯ бриф от
05.10. Нищо не се пише в docs/ и data/ на проекта (временни папки). Ползват я test_sizing_js.py и test_no_account_numbers.py.
РЕАЛНО: ohlc_EXEL.csv (бар 26.06), brief_2026-10-05.json (карта EXPD), qm_frames_2026-10-02.json (DOCN/CORT/CRL), qm_ep_2026-10-02.json (SYNA after-hours 01.10). СИНТЕТИЧНО: само обвивката около EP реда
(катализатор без заглавие) и режимът/датата на плана на EXEL (29.06 е реалната дата на сигнала).
"""
import sys, json, copy, pathlib, tempfile, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
F = ROOT / "tests" / "fixtures"


def build_brief():
    """→ (brief, {тикър: levels}). Подменя config.DOCS_DIR/DATA_DIR с временни папки."""
    import pandas as pd
    import config
    from src import screener, setup_rules, sizing, trade_levels as tl, qm_breakout as q, qm_ep, backtest
    from src import main as brief_main
    config.ENABLE_BACKTEST = False
    d = pathlib.Path(tempfile.mkdtemp(prefix="mb_page_"))
    config.DOCS_DIR, config.DATA_DIR = d / "docs", d / "data"
    config.DOCS_DIR.mkdir()
    config.DATA_DIR.mkdir()
    backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

    df = pd.read_csv(F / "ohlc_EXEL.csv", index_col=0, parse_dates=True).loc[:"2026-06-26"]
    spy = pd.read_csv(F / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:"2026-06-26"]
    exel = screener._evaluate_technicals("EXEL", df, spy)
    exel.update({"company": "EXEL Corp", "sector": "Healthcare", "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False}, "options": {}, "short_view": {},
                 "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    exel["setup"] = setup_rules.classify_setup(exel, dt.date(2026, 6, 29))
    action, _ = brief_main.apply_hard_rules([exel], 0.5, "Defensive")
    assert [a["ticker"] for a in action] == ["EXEL"]

    B05 = json.loads((F / "brief_2026-10-05.json").read_text(encoding="utf-8"))
    expd = copy.deepcopy({w["ticker"]: w for w in B05["watchlist"]}["EXPD"])
    expd["plan_preview"] = sizing.buy_stop_preview(expd, 0.5, "2026-10-05")
    expd["levels"] = tl.for_candidate(expd["plan_preview"], {**expd, "adr_pct": 2.01}, 0.5, "вход при задействане (buy-stop)")   # 2.01 = РЕАЛНИЯТ ADR20 на EXPD към 02.10

    QMF = json.loads((F / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
    frames = {t: pd.DataFrame({"Open": x["o"], "High": x["h"], "Low": x["l"], "Close": x["c"], "Volume": x["v"]}, index=pd.to_datetime(x["dates"])) for t, x in QMF["frames"].items()}
    rows, _ = q.scan_frames(frames, lead=QMF["lead"])

    EP = json.loads((F / "qm_ep_2026-10-02.json").read_text(encoding="utf-8"))
    dd = EP["daily"]["SYNA"]
    daily = {"SYNA": pd.DataFrame({"Open": dd["o"], "High": dd["h"], "Low": dd["l"], "Close": dd["c"], "Volume": dd["v"]}, index=pd.to_datetime(dd["dates"]))}
    syna = qm_ep.enrich_gappers([{"ticker": "SYNA", "session": "2026-10-01", "prev_close": 106.15, "ah_price": 122.04, "gap_pct": 14.97}], daily)[0]
    syna.update({"company": "Synaptics Inc", "headlines": [], "catalyst_label": "Неясен катализатор", "surprise": None, "summary_bg": None, "ah_volume_available": False})

    b = copy.deepcopy(B05)
    b["action"], b["watchlist"] = action, [expd]
    b["qm_breakout"] = q.cards(rows)
    b["qm_diag"] = {"universe": 903, "with_history": 892, "leaders": 167, "candidates": 3, "shown": 3, "as_of": QMF["as_of"], "lead_pct": config.QM_LEAD_PCT, "ok": True, "batches": 10, "batches_failed": 0}
    b["qm_ep"] = {"ok": True, "rows": [syna], "not_neglected": [], "log": {}}
    b.setdefault("backtest", {})["qm_breakout"] = backtest.get_qm_summary()
    levels = {"EXEL": action[0]["levels"], "EXPD": expd["levels"], "SYNA": syna["levels"], **{c["ticker"]: c["levels"] for c in b["qm_breakout"]}}
    return b, levels
