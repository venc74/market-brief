"""
С4 (втори преглед, 10.10.2026) · Track Record v2 (Action): win rate, win/loss и сравнението със SPY чак при ≥ config.TRACK_RECORD_MIN_CLOSED_FOR_WINRATE (20) затворени,
както другите книги (buy-stop, QM, GLB по Уиш). До 10.10 се показваха от първата резолюция → "Win rate: 100% (1 win / 0 loss)". РЕАЛНО: в tracker-а на 10.10 няма
нито един Action запис (първата резолюция предстои). РЕАЛНО: страницата от 05.10 (tests/fixtures/brief_2026-10-05.json). СИНТЕТИЧНО: обобщенията на книгата.
Пускане: python test_track_record_threshold.py
"""
import sys, re, json, pathlib, tempfile, copy, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_trt_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import render

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
assert config.TRACK_RECORD_MIN_CLOSED_FOR_WINRATE == 20
BASE = {"total_resolved": 1, "action_signals": 3, "min_closed": 20, "stats_visible": False, "win_rate_pct": None, "wins": None, "losses": None,
        "stopped": 0, "trailing_stop_exit": 1, "expired_in_trail": 0, "expired": 0, "still_open": 1, "trailing": 0, "partial_taken": 1, "stopped_after_partial": 0,
        "pending": 1, "methodology": {"version": "v2", "switched_on": "2026-10-05"}, "spy_compare": None, "v1_archive": None, "not_triggered": 0,
        "skipped_extended": 0, "pending_positions": [], "avg_realized_r": 1.5, "recent": [], "open_positions": []}


def page(bt):
    b = copy.deepcopy(B05); b["backtest"] = bt
    return " ".join(re.sub(r"<[^>]+>", " ", htmllib.unescape(render.render_dashboard(b))).split()).replace(" — ", " — ")


h = page(dict(BASE))
assert "Затворени: 1 — win rate и сравнението със SPY се показват при ≥ 20 затворени" in h and "Win rate:" not in h and "Среден реализиран R: 1.5" in h
print("  ✓ СИНТЕТИЧНО 1 затворена (печалба): «Затворени: 1 — win rate и сравнението със SPY … при ≥ 20», средният R остава; няма «Win rate: 100%»")
vis = dict(BASE, total_resolved=20, stats_visible=True, win_rate_pct=40.0, wins=8, losses=12)
assert "Win rate: 40.0% (8 win / 12 loss)" in page(vis)
old = {k: v for k, v in BASE.items() if k not in ("stats_visible", "min_closed")} | {"win_rate_pct": 100.0, "wins": 1, "losses": 0}
assert "Win rate: 100.0% (1 win / 0 loss)" in page(old)
print("  ✓ при 20 затворени — win rate както преди; стар бриф без полето stats_visible — рендерира се както е записан")
print()
print("Всички тестове минаха.")
