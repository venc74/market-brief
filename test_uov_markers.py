"""
Пакет 4б (06.10.2026) · т.б: списъкът "Unusual Options Yesterday" отпада; остава маркерът UOV✓ върху НАШИ кандидати (Action/Watchlist) и позиции (v2 отворени/чакащи и buy-stop
книгата), с числата при hover/клик. Следобедната OI снимка остава — вече за нашите тикъри (кандидати от последните брифове + позиции).

РЕАЛНО: брифът от 02.10.2026 (tests/fixtures/brief_2026-10-02.json) носи стария списък "unusual_options" (10 реда) — страницата вече не го показва; Watchlist/Action тикърите на
брифовете от 02.10 и 05.10 (snapshot_tickers); картата на EXPD от 05.10 за рендера. СИНТЕТИЧНО: веригите/снимките на тикърите (AAA…), позициите, tracker записите, подменените
yfinance/снимка, числата в маркерите.
Пускане: python test_uov_markers.py
"""
import sys, json, pathlib, tempfile, copy, ast, datetime as dt, html as htmllib, types, shutil
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import unusual_options as uo, oi_snapshot, enrich, render
from src import main as brief_main

FIX = ROOT / "tests" / "fixtures"
D = dt.date.fromisoformat
B02 = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
assert len(B02["unusual_options"]) == 10 and "unusual_options" in B02


class Chain:
    def __init__(self, c, p):
        self.calls, self.puts = c, p


class FakeTicker:
    def __init__(self, data):                                    # {падеж: (call_vol, call_oi, put_vol, put_oi)}
        self.data, self.options = data, tuple(sorted(data))

    def option_chain(self, exp):
        cv, co, pv, po = self.data[exp]
        mk = lambda v, o: pd.DataFrame({"volume": [v], "openInterest": [o]})
        return Chain(mk(cv, co), mk(pv, po))


CHAINS = {
    "AAA": FakeTicker({"2026-10-07": (3000, 0, 500, 0), "2026-10-09": (2500, 0, 500, 0)}),            # обем 6 500, OI 2 000 → 3.25×, calls 85%
    "BBB": FakeTicker({"2026-10-07": (400, 0, 400, 0)}),                                                # 800 / 1 000 = 0.8× — под прага
    "CCC": FakeTicker({"2026-10-07": (10, 0, 10, 0)}),                                                  # OI 20 → под 50
    "DDD": FakeTicker({}),                                                                              # без верига
    "EEE": FakeTicker({"2026-10-07": (900000, 0, 900000, 0)}),                                          # нереалистично съотношение
    "GGG": FakeTicker({"2026-10-07": (900, 0, 100, 0)}),                                                # не е в снимката
}
SNAP = {"horizon_days": 28, "fetched_at_utc": "2026-10-02 16:01",
        "tickers": {"AAA": {"2026-10-07": 1200, "2026-10-09": 800}, "BBB": {"2026-10-07": 1000}, "CCC": {"2026-10-07": 20}, "EEE": {"2026-10-07": 100}}}
config.UNUSUAL_OPTIONS_HISTORY_FILE = pathlib.Path(tempfile.mkdtemp(prefix="mb_uovhist_")) / "uov_ratio_history.json"           # 08.10: историята на съотношенията не се пише в data/
uo.yf = types.SimpleNamespace(Ticker=lambda sym: CHAINS[sym])
uo._snapshot_for_yesterday = lambda today: (SNAP, "2026-10-02", "")

print("── candidate_markers (СИНТЕТИЧНИ вериги, снимка в новия формат, бриф 05.10) ──")
mk, diag = uo.candidate_markers(["AAA", "BBB", "CCC", "DDD", "EEE", "GGG"], D("2026-10-05"))
assert list(mk) == ["AAA"] and mk["AAA"]["ratio"] == 3.25 and mk["AAA"]["call_put_bias"] == "calls" and mk["AAA"]["expiries"] == ["2026-10-07", "2026-10-09"]
note = mk["AAA"]["note"]
assert "≈ 3.25× OI — над абсолютния праг от 2× (силно ново позициониране)" in note and "върху 2 падежа до 09.10" in note and "Обем 6,500 / OI 2,000" in note and "calls 85%" in note and "сесията 02.10" in note, note
assert diag["with_ratio"] == 2 and diag["marked"] == 1 and diag["ratios"] == {"AAA": 3.25, "BBB": 0.8}
assert diag["missing"] == {"CCC": "OI в следобедната снимка е под 50 договора", "DDD": "няма опционна верига",
                           "EEE": "OI вероятно неактуален/непълен (нереалистично съотношение)", "GGG": "тикърът не е в следобедната снимка"}
assert diag["snapshot_session"] == "2026-10-02" and diag["min_ratio"] == 2.0 and diag["window_days"] == 21
print("  ✓ маркер само за AAA (3.25× ≥ 2.0; calls 85%; 2 падежа до 09.10); BBB (0.8×) без маркер, но съотношението е в diag (за калибриране); CCC/DDD/EEE/GGG — без съотношение, с причина")
print("    текст при hover/клик:", note)

print()
print("── маркерът върху картите (enrich) и на страницата ──")
row = {"ticker": "AAA"}
enrich._apply_markers(row, {"mf": set(), "uov": mk, "splits": {}, "si": {}, "si_new": {}})
assert row["markers"] == [{"tag": "UOV✓ (calls)", "title": note}]
assert enrich.uov_marker({"call_put_bias": "puts", "note": "x"}) == {"tag": "UOV✓ (puts)", "title": "x"} and enrich.uov_marker({"call_put_bias": "mixed", "note": "y"})["tag"] == "UOV✓"
tmp = tempfile.TemporaryDirectory(prefix="mb_uov_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
brief = copy.deepcopy(B05)
for c in brief["watchlist"]:
    if c["ticker"] == "EXPD":
        enrich._apply_markers(c, {"mf": set(), "uov": {"EXPD": {**mk["AAA"], "ticker": "EXPD"}}, "splits": {}, "si": {}, "si_new": {}})
page = htmllib.unescape(render.render_dashboard(brief))
assert page.count("UOV✓ (calls)") >= 1 and "Необичаен опционен обем вчера: ≈ 3.25× OI" in page
print("  ✓ РЕАЛНАТА карта на EXPD (05.10) получава маркер UOV✓ (calls) с текста за числата в страницата (маркерът е само показване)")

print()
print("── списъкът отпада от страницата и имейла ──")
page_old = htmllib.unescape(render.render_dashboard(copy.deepcopy(B02)))
assert "Unusual Options Yesterday" not in page_old
email = render.render_email(copy.deepcopy(B02))
assert "Необичаен опционен обем:" not in email
print("  ✓ РЕАЛНИЯТ бриф от 02.10 (с 10-редовия списък в данните) се рендира без секцията 'Unusual Options Yesterday' и без реда в имейла")

print()
print("── позициите ──")
calls = []
real_cm = uo.candidate_markers
uo.candidate_markers = lambda tk, today=None: (calls.append(list(tk)) or ({"AAA": mk["AAA"]}, {"requested": len(tk), "with_ratio": 1, "marked": 1, "missing": {}, "ratios": {"AAA": 3.25}}))
open_rows = [{"ticker": "AAA", "entry_date": "2026-09-22"}, {"ticker": "BBB"}]
pend_rows = [{"ticker": "AAA", "markers": [{"tag": "SI✓", "title": "x"}]}]
bs_rows = [{"ticker": "AAA", "also_action": True}, {"ticker": "CCC"}]
d = brief_main.attach_position_uov(open_rows + pend_rows + bs_rows)
assert calls == [["AAA", "BBB", "CCC"]] and d["marked"] == 1                              # ЕДНО извикване за всички позиции, без дубликати
assert [m["tag"] for m in open_rows[0]["markers"]] == ["UOV✓ (calls)"] and "markers" not in open_rows[1] and "markers" not in bs_rows[1]
assert [m["tag"] for m in pend_rows[0]["markers"]] == ["SI✓", "UOV✓ (calls)"] and [m["tag"] for m in bs_rows[0]["markers"]] == ["UOV✓ (calls)"]
assert brief_main.attach_position_uov([]) == {}
uo.candidate_markers = real_cm
print("  ✓ UOV✓ се добавя към отворените, чакащите и buy-stop позициите (след съществуващия SI✓), със ЕДНО извикване за всички тикъри")

print()
print("── свързването в main.run (структурно) ──")
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
called = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id for n in ast.walk(run)
          if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))}
assert "fetch_unusual_options" not in called and "attach_position_uov" in called
keys = [k.value for n in ast.walk(run) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
assert "uov_diag" in keys and "unusual_options" not in keys and "unusual_options_diag" not in keys
print("  ✓ run() вече не вика fetch_unusual_options (скенирането на топ-60 отпада); в брифа има uov_diag, няма unusual_options/unusual_options_diag")

print()
print("── следобедната снимка: НАШИТЕ тикъри ──")
for f in ("2026-10-02", "2026-10-05"):
    shutil.copy(FIX / f"brief_{f}.json", config.DATA_DIR / f"{f}.json")                  # РЕАЛНИТЕ брифове като "последни брифове"
want_05 = [c["ticker"] for c in B05["action"] + B05["watchlist"]]
want_02 = [c["ticker"] for c in B02["action"] + B02["watchlist"]]
tr = {"X1": {"ticker": "AAA", "status": "open"}, "X2": {"ticker": "ZZZ", "status": "pending", "category": "buystop"}, "X3": {"ticker": "BBB", "status": "stopped"}, "X4": {"ticker": "EXPD", "status": "open"}}
(config.DATA_DIR / "backtest_tracker.json").write_text(json.dumps(tr), encoding="utf-8")
got = oi_snapshot.snapshot_tickers()
exp = list(dict.fromkeys(want_05 + want_02 + ["AAA", "ZZZ"]))
assert got == exp, (got, exp)
assert "BBB" not in got                                                                   # затворена позиция не е за снимка
assert oi_snapshot.snapshot_tickers(max_briefs=1) == list(dict.fromkeys(want_05 + ["AAA", "ZZZ"]))
(config.DATA_DIR / "2026-10-06.json").write_text(json.dumps({"action": [], "watchlist": [], "qm_breakout": [{"ticker": "CORT"}, {"ticker": "CRL"}]}), encoding="utf-8")      # СИНТЕТИЧЕН бриф с РЕАЛНИТЕ QM тикъри от 02.10
assert oi_snapshot.snapshot_tickers(max_briefs=1)[:2] == ["CORT", "CRL"]                                                              # 08.10: и QM картите влизат в следобедната снимка (очаквано движение при отчет)
(config.DATA_DIR / "2026-10-06.json").unlink()
print(f"  ✓ РЕАЛНИ кандидати на 05.10 ({len(want_05)}) + на 02.10 + живи позиции от двете книги; затворена позиция не влиза; max_briefs=1 → само последния бриф")

# take_snapshot със заместители: снима точно тези тикъри, в нов формат
ny_today = dt.datetime.now(dt.timezone.utc).astimezone(oi_snapshot._NY).date()
oi_snapshot.uo.last_session_date = lambda: ny_today
oi_snapshot.uo.load_oi_snapshots = lambda: {}
oi_snapshot._skip_reason = lambda *a, **k: None
seen = []


def fake_ticker(sym):
    seen.append(sym)
    nxt = (ny_today + dt.timedelta(days=3)).isoformat()
    return FakeTicker({nxt: (1, 300, 1, 300)})


oi_snapshot.uo.yf = types.SimpleNamespace(Ticker=fake_ticker)
oi_snapshot.uo._top_by_volume = lambda *a, **k: (_ for _ in ()).throw(AssertionError("топ-N по ликвидност не се ползва при N=0"))
snap = oi_snapshot.take_snapshot()
assert config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS == 0 and seen[:len(exp)] == exp and sorted(snap["tickers"]) == sorted(exp)     # първата обиколка е за OI; след нея — straddle-ите за отчетите (т.д)
assert isinstance(snap["straddles"], dict)
assert snap["horizon_days"] == 28 and all(list(v.values()) == [600] for v in snap["tickers"].values())
(config.DATA_DIR / "backtest_tracker.json").unlink()
for f in config.DATA_DIR.glob("2026-*.json"):
    f.unlink()
assert oi_snapshot.take_snapshot() is None
print("  ✓ take_snapshot снима точно тези тикъри (без топ-80), в новия формат (horizon_days 28); без кандидати и позиции → нищо не се заснема")

print()
print("Всички тестове минаха.")
