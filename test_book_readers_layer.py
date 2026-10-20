"""
20.10.2026 · етап 3, част Б: един слой за четене на книгите (src/backtest.py: book_records, latest_by_ticker, book_intervals, overlaps; LIVE / POSITION). До 20.10 всеки
четец повтаряше филтъра "книга + методология + статус", "най-скорошният запис на тикъра" и интервалите за отметките "и Action / и buy-stop / и QM": main._live_positions,
_pending_action_plans, _last_resolved_positions, pending_buystop_by_ticker, live_buystop_by_ticker, live_tickers, четирите обобщения и следобедната OI снимка.
Поведението е същото — стар ↔ нов код (scratchpad на сесията): 24 реални tracker-а от бот commit-ите (17.09–20.10) + смесен tracker в двата реда, 11 четеца — 0 разлики;
офлайн реплеят на 24 брифа (с _pending_action_plans и snapshot_tickers) — 0 разлики.

РЕАЛНО: tests/fixtures/buystop_book_2026-10-12.json (записите на buy-stop книгата преди и след run-а на 12.10: EXPD и ANET pending → open), qm_book_2026-10-12.json
(записите на qm_breakout), backtest_tracker_v1_2026-10-02.json (реалният v1 архив). СИНТЕТИЧНО (означено): v1 записите, пре-етикетирани като v2 Action; запис на "GLB по Уиш".
Пускане: python test_book_readers_layer.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_books_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, main, oi_snapshot, trade_sim
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))

FX = ROOT / "tests" / "fixtures"
BS = json.loads((FX / "buystop_book_2026-10-12.json").read_text(encoding="utf-8"))
QM = json.loads((FX / "qm_book_2026-10-12.json").read_text(encoding="utf-8"))["records"]
QM = QM if isinstance(QM, dict) else {f"q{i}": r for i, r in enumerate(QM)}
V1 = json.loads((FX / "backtest_tracker_v1_2026-10-02.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


def save(tr):
    backtest._save_tracker(tr)


print("── 1. book_records: книга, методология, статус (РЕАЛНИ записи) ──")
tr = {**V1, **{f"bs_{k}": v for k, v in BS["tracker_before"].items()}, **{f"qm_{k}": v for k, v in QM.items()}}
assert backtest.book_records(tracker=tr) == []                                                       # v1 архивът не е v2 Action
assert len(backtest.book_records(method=None, tracker=tr)) == len(V1)                                   # запис без category е Action
assert [r["ticker"] for r in backtest.book_records(backtest.CATEGORY_BUYSTOP, tracker=tr)] == [r["ticker"] for r in BS["tracker_before"].values()]
assert len(backtest.book_records(None, tracker=tr)) == len(BS["tracker_before"]) + len(QM)
assert all(r["status"] in backtest.LIVE for r in backtest.book_records(None, statuses=backtest.LIVE, method=None, tracker=tr))
assert backtest.LIVE == trade_sim.LIVE == ("pending", "open", "trailing") and backtest.POSITION == ("open", "trailing")
print(f"  ✓ v1 архивът ({len(V1)} записа) е извън v2 четците; buy-stop ({len(BS['tracker_before'])}) и qm_breakout ({len(QM)}) — всяка книга отделно")

print()
print("── 2. четците върху РЕАЛНАТА buy-stop книга от 12.10 ──")
save(BS["tracker_before"])
with q():
    pend, live, pos = backtest.pending_buystop_by_ticker(), backtest.live_buystop_by_ticker(), main._live_positions()
assert set(pend) == set(live) == {r["ticker"] for r in BS["tracker_before"].values()} and pos == {}
save(BS["tracker_after"])
with q():
    pend, live, pos = backtest.pending_buystop_by_ticker(), backtest.live_buystop_by_ticker(), main._live_positions()
assert pend == {} and {t: r["status"] for t, r in live.items()} == {r["ticker"]: "open" for r in BS["tracker_after"].values()} and pos == {}
print(f"  ✓ преди run-а: чакащи {sorted(set(r['ticker'] for r in BS['tracker_before'].values()))}; след него — задействани (open); buy-stop записът не е позиция")

print()
print("── 3. най-скорошният запис и равенството (СИНТЕТИЧНО: v1 записите като v2 Action) ──")
syn = {f"v2_{k}": {**v, "method": "v2"} for k, v in V1.items()}
save(syn)
with q():
    last, live_pos = main._last_resolved_positions(), main._live_positions()
resolved = [r for r in syn.values() if r.get("realized_r") is not None and r.get("resolution_date")]
for t, r in last.items():
    assert r["resolution_date"] == max(x["resolution_date"] for x in resolved if x["ticker"] == t)
assert set(live_pos) == {r["ticker"] for r in syn.values() if r["status"] in ("open", "trailing")}
a, b = {"ticker": "X", "entry_date": "2026-10-01", "k": 1}, {"ticker": "X", "entry_date": "2026-10-01", "k": 2}
assert backtest.latest_by_ticker([a, b])["X"]["k"] == 1                                              # при равенство — първият (както до 20.10)
print(f"  ✓ последната приключила позиция на тикър = най-късната дата на резолюция ({len(last)} тикъра); живите — open/trailing ({len(live_pos)})")

print()
print("── 4. интервалите за отметките и OI снимката ──")
mixed = {**syn, **{f"bs_{k}": v for k, v in BS["tracker_after"].items()}, "gw": {"method": "v2", "category": "glb_wish", "ticker": "GWX", "status": "open", "entry_date": "2026-10-13"}}
iv = backtest.book_intervals(backtest.CATEGORY_ACTION, mixed, trade_sim.NOT_A_POSITION)
bs_rec = next(iter(BS["tracker_after"].values()))
assert backtest.overlaps(bs_rec, iv) == any(s <= (bs_rec.get("resolution_date") or "9999-12-31") and bs_rec["entry_date"] <= e for s, e in iv.get(bs_rec["ticker"], []))
save(mixed)
config.UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS = 0
with q():
    oi = oi_snapshot.snapshot_tickers(0)
assert "GWX" not in oi and set(oi) == {r["ticker"] for r in mixed.values() if r.get("status") in backtest.LIVE and r.get("category") != "glb_wish"}
print("  ✓ 'и Action' = застъпване на интервалите; OI снимката — живите записи без книгата на Уиш")

print()
print("── 5. пазач: четците минават през слоя ──")
msrc = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
osrc = (ROOT / "src" / "oi_snapshot.py").read_text(encoding="utf-8")
assert "backtest._load_tracker()" not in msrc and "book_records(" in osrc
print("  ✓ main.py не чете tracker-а сам; oi_snapshot филтрира през backtest.book_records")
print("\n✅ test_book_readers_layer: всичко мина")
