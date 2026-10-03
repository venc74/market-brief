"""
Пакет 1, т.7 (2026-10-03): чист старт на Track Record-а — архив на v1, "v1_closed", v2-only
OPEN✓/RE-ENTRY/COT, обратимост, устойчивост при срив. Без мрежа и БЕЗ реални data/*.json:
tracker/архив/състояние са във временна директория.

РЕАЛНИ данни: tests/fixtures/backtest_tracker_v1_2026-10-02.json — копие на РЕАЛНИЯ v1 tracker към
02.10.2026 (51 записа: 25 отворени, 25 stopped, 1 trailing_stop_exit; 26 резолвирани, 1 win).
СИНТЕТИЧНИ: цените, по които се затварят отворените позиции (+10% / -5% / липсваща), и v2 плановете.
Пускане: python test_tracker_switch.py
"""
import sys, pathlib, json, tempfile, copy, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest, tracker_switch, thermometer, render
from src import main as brief_main

FIXTURE = ROOT / "tests/fixtures/backtest_tracker_v1_2026-10-02.json"
REAL = json.loads(FIXTURE.read_text(encoding="utf-8"))
TODAY = dt.date(2026, 10, 5)

_tmp = tempfile.TemporaryDirectory(prefix="market_brief_sw_")
DATA = pathlib.Path(_tmp.name)
config.DATA_DIR = DATA
backtest._TRACKER_PATH = DATA / "backtest_tracker.json"
assert not str(DATA.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
backtest._resolve_open_positions = lambda tracker, today=None: None          # резолюцията е тествана другаде
backtest._fetch_current_prices = lambda tickers: {}
backtest.enrich.earnings_recap = lambda t: None


def reset(tracker=None):
    for f in DATA.glob("*"):
        f.unlink()
    (DATA / "backtest_tracker.json").write_text(json.dumps(tracker if tracker is not None else REAL), encoding="utf-8")


def read(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


LIVE = [(k, r) for k, r in REAL.items() if r["status"] in ("open", "trailing")]
assert len(REAL) == 51 and len(LIVE) == 25


def synth_prices(tickers):
    """СИНТЕТИЧНИ цени: четните +10% над entry, нечетните -5%, а последният тикър липсва."""
    out = {}
    entries = {r["ticker"]: r["entry_price"] for _, r in LIVE}
    for i, t in enumerate(sorted(tickers)[:-1]):
        out[t] = round(entries[t] * (1.10 if i % 2 == 0 else 0.95), 2)
    return out


print("── РЕАЛНАТА v1 статистика преди превключването ──")
st0 = tracker_switch.v1_stats(REAL)
assert (st0["n"], st0["wins"], st0["win_rate_pct"], st0["avg_r"]) == (26, 1, 3.8, -0.9), st0
assert st0["by_status"] == {"open": 25, "stopped": 25, "trailing_stop_exit": 1}
print("  ✓ 51 записа: 26 резолвирани, 1 win → win rate 3.8%, среден R -0.90 (25 stopped, 1 trailing exit, 25 още отворени)")
print()

print("── превключване: архив, v1_closed, чист tracker, състояние ──")
reset()
prices_seen = {}
def fetch(tickers):
    prices_seen.update(synth_prices(tickers)); return synth_prices(tickers)
res = tracker_switch.switch_to_v2(TODAY, fetch_prices=fetch)
assert res["status"] == "switched" and res["archived"] == 51 and res["closed"] == 25, res
arch = read("backtest_archive_v1.json")
assert arch["pre_switch_tracker"] == REAL                                   # точното оригинално състояние
assert len(arch["records"]) == 51 and len(arch["closed_on_switch"]) == 25 and arch["archived_on"] == "2026-10-05"
unpriced = [k for k in arch["closed_on_switch"] if arch["records"][k].get("mtm_unavailable")]
assert len(unpriced) == 1, unpriced
for k in arch["closed_on_switch"]:
    r, orig = arch["records"][k], REAL[k]
    assert r["status"] == "v1_closed" and r["closed_from"] == "open" and r["resolution_date"] == "2026-10-05"
    if k in unpriced:
        assert r["realized_r"] is None and "close_price" not in r
    else:
        cur = prices_seen[r["ticker"]]
        assert r["close_price"] == cur and r["realized_r"] == round((cur - orig["entry_price"]) / (orig["entry_price"] - orig["stop_loss"]), 2)
for k, orig in REAL.items():                                                # резолвираните не се пипат
    if orig["status"] not in ("open", "trailing"):
        assert arch["records"][k] == orig
assert read("backtest_tracker.json") == {}                                  # Track Record v2 започва от нула
state = read("track_record_state.json")
assert state["methodology"] == "v2" and state["switched_on"] == "2026-10-05" and backtest.methodology() == "v2"
priced_r = [arch["records"][k]["realized_r"] for k in arch["closed_on_switch"] if k not in unpriced]
all_r = [r["realized_r"] for r in REAL.values() if r.get("realized_r") is not None] + priced_r
exp_wins = sum(1 for x in all_r if x > 0)
sv = state["v1_stats"]
assert sv["n"] == len(all_r) == 50 and sv["wins"] == exp_wins and sv["unpriced"] == 1 and sv["v1_closed"] == 25
assert sv["expired_no_r"] == 0                                              # в реалния tracker няма изтекли без R
assert sv["win_rate_pct"] == round(exp_wins / 50 * 100, 1) and sv["avg_r"] == round(sum(all_r) / 50, 2)
print(f"  ✓ 51 записа в архива (с точно копие на оригиналния tracker), 25 затворени като v1_closed ({24} с R, 1 без цена →")
print(f"    извън статистиката), tracker започва от нула; v1 ред: n={sv['n']}, win rate {sv['win_rate_pct']}%, среден R {sv['avg_r']}")
print("    (цените за затварянето са СИНТЕТИЧНИ; реалните 26 резолвирани не са пипани)")
before = {n: (DATA / n).read_bytes() for n in ("backtest_archive_v1.json", "backtest_tracker.json", "track_record_state.json")}
assert tracker_switch.ensure_v2_methodology(TODAY, fetch_prices=fetch)["status"] == "already"
assert before == {n: (DATA / n).read_bytes() for n in before}
print("  ✓ повторно извикване е идемпотентно — нито един файл не се променя")
print()

print("── след превключването: v2-only, v1 не се връща от snapshot-ите ──")
old_plan = {"entry_range": [10.0, 10.4], "target_1": 12.0, "stop_loss": 9.0}                 # v1 план от стар snapshot
tr = backtest._load_tracker()
backtest._ingest_action_list(tr, "2026-06-13", [{"ticker": "AIZ", "plan": old_plan}])
assert tr == {}                                                              # НЕ се ingest-ва втори път
v2plan = {"method": "v2", "buy_stop": 50.0, "max_chase": 52.5, "stop_loss": 46.0, "target_1": 58.0,
          "entry_mid": 51.0, "window_sessions": 5, "valid_through": "2026-10-09", "entry_range": [50.0, 52.5]}
backtest._ingest_action_list(tr, "2026-10-05", [{"ticker": "AIZ", "plan": v2plan}])
assert list(tr) == ["AIZ_2026-10-05"] and tr["AIZ_2026-10-05"]["status"] == "pending"
backtest._save_tracker(tr)
sm = backtest.get_backtest_summary()
assert sm["total_resolved"] == 0 and sm["pending"] == 1 and sm["methodology"] == {"version": "v2", "switched_on": "2026-10-05"}
assert sm["v1_archive"]["n"] == 50 and sm["v1_archive"]["win_rate_pct"] == sv["win_rate_pct"]
# OPEN✓ / RE-ENTRY / COT позиции: v1 записите (дори оставени в tracker-а) не се броят
mixed = copy.deepcopy(REAL); mixed.update(tr)
backtest._save_tracker(mixed)
assert brief_main._live_positions() == {} and brief_main._last_resolved_positions() == {}
print("  ✓ v1 план от архивните snapshot-и не се ingest-ва втори път; v2 планът влиза като pending; summary: 0 резолвирани,")
print("    v1 архивният ред от състоянието; OPEN✓/RE-ENTRY/COT позициите игнорират v1 записите (дори и да са в tracker-а)")

brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": [], "watchlist": [], "backtest": sm,
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as docs:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(docs)
    try:
        html = render.render_dashboard(brief)
    finally:
        config.DOCS_DIR = orig_docs
line = f"v1 методология: n={sv['n']}, win rate {sv['win_rate_pct']}%,"
assert " ".join(line.split()) in " ".join(html.split()) and "Track Record v2 започва от нула" in html
assert f"({sv['unpriced']} без цена)" in " ".join(html.split())
print(f"  ✓ dashboard: 'v1 методология: n={sv['n']}, win rate {sv['win_rate_pct']}%, среден R {sv['avg_r']} (1 без цена)'")
print()

print("── v1 изтекли без R се броят, не се крият ──")
exp_tr = copy.deepcopy(REAL)
k0 = LIVE[0][0]
exp_tr[k0].update(status="expired", resolution_date="2026-10-03", realized_r=None)          # СИНТЕТИЧНО: един запис изтича (v1 фаза 1)
reset(exp_tr)
rs_ = tracker_switch.switch_to_v2(TODAY, fetch_prices=fetch)
sx = rs_["stats"]
assert sx["expired_no_r"] == 1 and sx["n"] == 49 and rs_["closed"] == 24, sx            # 24 живи затворени + 1 изтекъл без R (извън n)
brief_x = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
           "action": [], "watchlist": [], "backtest": backtest.get_backtest_summary(),
           "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as docs:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(docs)
    try:
        html_x = render.render_dashboard(brief_x)
    finally:
        config.DOCS_DIR = orig_docs
assert "(1 изтекли без R, извън n)" in " ".join(html_x.split())
print("  ✓ изтекъл v1 запис (фаза 1, без R) не влиза в n, но редът казва '(1 изтекли без R, извън n)'")
print()

print("── обратимост ──")
reset(); tracker_switch.switch_to_v2(TODAY, fetch_prices=fetch)
tr = backtest._load_tracker()
backtest._ingest_action_list(tr, "2026-10-06", [{"ticker": "AIZ", "plan": v2plan}]); backtest._save_tracker(tr)
rv = tracker_switch.revert_to_v1(dt.date(2026, 10, 7))
assert rv["status"] == "reverted" and rv["records"] == 51
assert read("backtest_tracker.json") == REAL                                # оригиналният v1 tracker, байт по байт като данни
bk = read("backtest_tracker_v2_backup_2026-10-07.json")
assert list(bk) == ["AIZ_2026-10-06"] and bk["AIZ_2026-10-06"]["method"] == "v2"      # v2 записите не се губят
assert backtest.methodology() == "v1" and read("track_record_state.json")["reverted_on"] == "2026-10-07"
assert tracker_switch.revert_to_v1()["status"] == "reverted"                # повторно връщане от архива е безопасно
print("  ✓ revert_to_v1: tracker == оригиналните 51 v1 записа; v2 записите са във backup файл; методология v1")
print()

print("── устойчивост при срив и гранични случаи ──")
# а) срив при записа на tracker-а СЛЕД архива: tracker-ът е непокътнат, състоянието не е v2; повторният опит успява
reset()
orig_save = backtest._save_tracker
def boom(tracker): raise OSError("диск пълен (СИНТЕТИЧЕН срив)")
backtest._save_tracker = boom
r1 = tracker_switch.ensure_v2_methodology(TODAY, fetch_prices=fetch)
backtest._save_tracker = orig_save
assert r1["status"] == "failed" and read("backtest_tracker.json") == REAL and backtest.methodology() == "v1"
assert (DATA / "backtest_archive_v1.json").exists() and not (DATA / "track_record_state.json").exists()
r2 = tracker_switch.ensure_v2_methodology(TODAY, fetch_prices=fetch)
assert r2["status"] == "switched" and read("backtest_archive_v1.json")["pre_switch_tracker"] == REAL
# б) срив СЛЕД записа на tracker-а, преди състоянието: повторният run осиновява архива, не го презаписва
reset(); tracker_switch.switch_to_v2(TODAY, fetch_prices=fetch)
arch_bytes = (DATA / "backtest_archive_v1.json").read_bytes()
(DATA / "track_record_state.json").unlink()
assert backtest.methodology() == "v1"
r3 = tracker_switch.ensure_v2_methodology(dt.date(2026, 10, 6), fetch_prices=fetch)
assert r3["status"] == "adopted" and (DATA / "backtest_archive_v1.json").read_bytes() == arch_bytes
assert read("track_record_state.json")["v1_stats"]["n"] == 50 and backtest.methodology() == "v2"
# в) няма цени за отворените позиции → отлагане, нищо не се пише
reset()
r4 = tracker_switch.ensure_v2_methodology(TODAY, fetch_prices=lambda t: {})
assert r4["status"] == "deferred" and read("backtest_tracker.json") == REAL
assert not (DATA / "backtest_archive_v1.json").exists() and not (DATA / "track_record_state.json").exists()
# г) пропуснат стоп се резолвира ПРЕДИ затварянето (не става v1_closed)
reset()
first_key = LIVE[0][0]
def fake_resolve(tracker, today=None):
    tracker[first_key].update(status="stopped", resolution_date="2026-10-02", realized_r=-1.0)
orig_resolve = backtest._resolve_open_positions
backtest._resolve_open_positions = fake_resolve
res = tracker_switch.switch_to_v2(TODAY, fetch_prices=fetch)
backtest._resolve_open_positions = orig_resolve
arch = read("backtest_archive_v1.json")
assert res["closed"] == 24 and first_key not in arch["closed_on_switch"] and arch["records"][first_key]["status"] == "stopped"
assert arch["pre_switch_tracker"] == REAL and arch["records"][first_key]["realized_r"] == -1.0
# д) чист старт без v1 записи; изключен превключвател; split флаг → без R
reset({})
assert tracker_switch.ensure_v2_methodology(TODAY)["status"] == "fresh_start" and backtest.methodology() == "v2"
assert read("track_record_state.json")["v1_stats"] is None and not (DATA / "backtest_archive_v1.json").exists()
reset(); config.TRACK_RECORD_V2 = False
assert tracker_switch.ensure_v2_methodology(TODAY)["status"] == "disabled" and backtest.methodology() == "v1"
config.TRACK_RECORD_V2 = True
flagged = copy.deepcopy(REAL); flagged[first_key]["needs_manual_review"] = {"reason": "split_sanity_failed"}
reset(flagged)
tracker_switch.switch_to_v2(TODAY, fetch_prices=lambda t: {x: 1.0 for x in t})
fr = read("backtest_archive_v1.json")["records"][first_key]
assert fr["status"] == "v1_closed" and fr["realized_r"] is None and fr["mtm_unavailable"] is True
print("  ✓ срив при записа на tracker-а → tracker и архив непокътнати, повторният run успява; срив преди състоянието →")
print("    архивът се осиновява, не се презаписва; без цени → отлагане без запис; пропуснат стоп се резолвира преди затварянето;")
print("    чист старт, изключен превключвател, split флаг → затворена без R")

# редът в main.py: превключването е ПРЕДИ резолюцията и преди четенето на живите позиции
src = (ROOT / "src/main.py").read_text(encoding="utf-8")
pair = "tracker_switch.ensure_v2_methodology()\n        backtest.resolve_positions_only()\n"     # последователни извиквания в run()
assert src.count(pair) == 1 and src.index(pair) < src.index("cot_live = _live_positions() if config.ENABLE_BACKTEST")
print("  ✓ main.run(): ensure_v2_methodology() е преди resolve_positions_only() и преди четенето на живите позиции")

_tmp.cleanup()
print()
print("Всички тестове минаха.")
