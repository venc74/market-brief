"""
Офлайн реплей (етап 3, част Б) — СЪБИРАЧЪТ. Пуска се вътре във временно копие на кода (src/, templates/, config.py) с data/ от бот commit-а на деня —
config.ROOT / DATA_DIR / DOCS_DIR сочат там. Без мрежа (пазачът tests/_nonet в PYTHONPATH). Вика само публични функции, които съществуват и в стария, и в новия код.

  python replay_collect.py day YYYY-MM-DD OUT.json      — брифът на деня: страница, имейл, четирите книги, четците, сесиите за деня, сетъпите на картите
  python replay_collect.py global FIXTURES_DIR OUT.json — сесиите за всички дати 2024–2028, ADR върху реалните барове от fixture-ите
"""
import copy, datetime as dt, io, contextlib, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
D = dt.date.fromisoformat
quiet = lambda: contextlib.redirect_stdout(io.StringIO())


def _safe(fn, *a, **k):
    try:
        with quiet():
            return fn(*a, **k)
    except Exception as e:
        return f"ГРЕШКА {type(e).__name__}: {e}"


def sessions_for(d: dt.date) -> dict:
    from src import setup_rules, bar_freshness, health_monitor, qm_ep, corp_actions, earnings_move, cot_track, sessions, backtest
    iso = d.isoformat()
    return {
        "is_session": _safe(setup_rules.is_session, d),
        "sessions_between_m10": _safe(setup_rules.sessions_between, d - dt.timedelta(days=10), d),
        "session_window": (lambda w: [x.isoformat() for x in w] if isinstance(w, list) else w)(_safe(setup_rules.session_window, iso)),
        "valid_through": _safe(setup_rules.valid_through, iso),
        "calendar_note": _safe(setup_rules.market_calendar_note, d),
        "ny_open_berlin": _safe(setup_rules.ny_time_in_berlin, d, 9, 30),
        "expected_session": _safe(bar_freshness.expected_session, iso),
        "prev_session": str(_safe(health_monitor.prev_session, d)),
        "next_session": str(_safe(qm_ep.next_session, d)),
        "sessions_since_m30": _safe(corp_actions.sessions_since, d - dt.timedelta(days=30), d),
        "sessions_after_60": str(_safe(corp_actions._sessions_after, d, 60)),
        "earn_sessions_after_p20": _safe(earnings_move.sessions_after, d, d + dt.timedelta(days=20)),
        "week_close_date": _safe(cot_track.week_close_date, d - dt.timedelta(days=d.weekday())),
        "sessions_in_p30": _safe(sessions.sessions_in, d, d + dt.timedelta(days=30)),          # 30.10.2026 (т. 8): thesis_context._business_days е махнат — същата сметка
        "late_discovery": _safe(backtest._is_late_discovery, {"resolution_date": iso, "discovered_date": (d + dt.timedelta(days=3)).isoformat()}),
    }


def collect_day(date: str) -> dict:
    import config
    from src import render, backtest, setup_rules, enrich
    render.berlin_clock = lambda: ("07:30", "CEST")                       # часът на генериране — фиксиран (иначе всяка двойка се различава)
    render.premarket_note = lambda *a, **k: ""
    backtest._fetch_current_prices = lambda tickers: {}                    # текущите цени са мрежа
    enrich.earnings_recap = lambda t: None
    b = json.loads((config.DATA_DIR / f"{date}.json").read_text(encoding="utf-8"))
    out = {"date": date}
    html = _safe(render.render_dashboard, copy.deepcopy(b), publish=False, as_of=D(date))
    out["html"] = re.sub(r"\s+", " ", html) if isinstance(html, str) else html
    em = _safe(render.render_email, copy.deepcopy(b))
    out["email"] = re.sub(r"\s+", " ", em) if isinstance(em, str) else em
    out["books"] = {k: _safe(getattr(backtest, k)) for k in ("get_backtest_summary", "get_buystop_summary", "get_qm_summary", "get_glb_wish_summary") if hasattr(backtest, k)}
    out["readers"] = {k: _safe(getattr(backtest, k)) for k in ("live_buystop_by_ticker", "pending_buystop_by_ticker", "live_tickers", "action_signals") if hasattr(backtest, k)}
    try:
        from src import main
        out["readers"]["main._live_positions"] = _safe(main._live_positions)
        out["readers"]["main._last_resolved_positions"] = _safe(main._last_resolved_positions)
        out["readers"]["main._pending_action_plans"] = _safe(main._pending_action_plans)
    except Exception as e:
        out["readers"]["main"] = f"ГРЕШКА {type(e).__name__}"
    try:
        from src import oi_snapshot
        out["readers"]["oi_snapshot.snapshot_tickers"] = _safe(oi_snapshot.snapshot_tickers)
    except Exception as e:
        out["readers"]["oi_snapshot"] = f"ГРЕШКА {type(e).__name__}"
    out["sessions"] = sessions_for(D(date))
    setups = {}
    live = _safe(backtest.live_buystop_by_ticker) or {}
    for sec in ("action", "watchlist"):
        for c in b.get(sec) or []:
            cc = {k: v for k, v in c.items() if k not in ("setup", "ai")}
            st = _safe(setup_rules.classify_setup, cc, D(date))
            if isinstance(st, dict) and isinstance(live, dict) and c["ticker"] in live:
                st = _safe(setup_rules.apply_book_window, st, live[c["ticker"]], date)
            setups[f"{sec}:{c['ticker']}"] = st
    out["setups"] = setups
    return out


def collect_global(fixtures: pathlib.Path) -> dict:
    import pandas as pd
    from src import trade_levels, qm_breakout, qm_ep
    out = {"sessions": {}}
    d = dt.date(2024, 1, 1)
    while d <= dt.date(2028, 12, 31):
        out["sessions"][d.isoformat()] = sessions_for(d)
        d += dt.timedelta(days=1)
    frames = {}
    ohlcv = lambda v: pd.DataFrame({"Open": v["o"], "High": v["h"], "Low": v["l"], "Close": v["c"], "Volume": v["v"]}, index=pd.to_datetime(v["dates"]))
    for pat, key in (("qm_frames_*.json", "frames"), ("glb_wish_frames_*.json", "frames"), ("glb_seed_*.json", "tickers"), ("ohlc_EXPD_SPY_raw_*.json", "bars")):
        for f in sorted(fixtures.glob(pat)):
            raw = json.loads(f.read_text(encoding="utf-8")).get(key) or {}
            for t, v in raw.items():
                v = v.get("daily", v) if isinstance(v, dict) else v
                try:
                    frames[f"{f.stem}:{t}"] = ohlcv(v)
                except Exception:
                    continue
    for f in sorted(fixtures.glob("ohlc_*.csv")):
        frames[f.stem] = pd.read_csv(f, index_col=0, parse_dates=True)
    adr = {}
    for k, df in frames.items():
        h, l = df["High"], df["Low"]
        adr[k] = {"trade_levels": [trade_levels.adr_pct(h.iloc[:i], l.iloc[:i]) for i in range(max(1, len(df) - 120), len(df) + 1)]}
        if "Volume" in df:
            feats = _safe(qm_breakout.compute_features, df.dropna())
            adr[k]["qm_breakout"] = [None if x != x else round(float(x), 12) for x in feats["adr"]] if isinstance(feats, dict) else feats
            sess = df.index[-1].date().isoformat()
            rows = [{"ticker": "X", "session": sess, "ah_price": float(df["Close"].iloc[-1]) * 1.12}]
            e = _safe(qm_ep.enrich_gappers, rows, {"X": df.dropna()})
            adr[k]["qm_ep"] = (None if e[0]["adr"] is None else round(e[0]["adr"], 12)) if isinstance(e, list) else e
    out["adr"] = adr
    return out


if __name__ == "__main__":
    mode, arg, dest = sys.argv[1], sys.argv[2], sys.argv[3]
    res = collect_day(arg) if mode == "day" else collect_global(pathlib.Path(arg))
    pathlib.Path(dest).write_text(json.dumps(res, ensure_ascii=False, default=str, sort_keys=True), encoding="utf-8")
