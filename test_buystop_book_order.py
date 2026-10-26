"""
12.10.2026 · картата в Watchlist чете buy-stop книгата СЛЕД резолюцията, а задействан запис има предимство пред всеки сетъп (освен confirmed).

Случаят (РЕАЛЕН, брифът от 12.10): setup_rules.annotate(..., backtest.live_buystop_by_ticker()) беше ПРЕДИ ранната резолюция (backtest.resolve_positions_only) → картата
четеше вчерашното състояние от диска. EXPD: книгата "open, вход 09.10 по $194.59" (High 195.73 на 09.10 > buy-stop), картата "чака buy-stop, валиден до 15.10, от 09.10".
ANET: вход 09.10 по $215.38 (отваряне над buy-stop $214.89), стоп $197.70, а на страницата — компактен ред "над pivot без обем, стоп 9.2%" (apply_book_window гледаше само below_pivot).
Дребно: plan_preview.valid_through на EXPD беше 16.10 (нов прозорец от днес), а setup — 15.10 (прозорецът на записа).

РЕАЛНО (tests/fixtures/buystop_book_2026-10-12.json): двата записа на книгата преди run-а на 12.10 (commit 5df8147) и след него (405ebaa), Watchlist картите на EXPD и ANET
от data/2026-10-12.json, дневните барове на EXPD/ANET/SPY от Yahoo до 09.10. СИНТЕТИЧНО (означено): временният tracker, подмененото yf.download, картата с confirmed сетъп.
Пускане: python test_buystop_book_order.py
"""
import sys, json, pathlib, tempfile, copy, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import setup_rules, backtest, sizing, render

# 20.10.2026 (етап 3, т. 1): реалните брифове до 20.10 носят старата формулировка ("Купува се само ако … обем ≥ 1.5× среден за потвърждение") — превежда се в новата
import re as _re
_OLD_TAIL = _re.compile(r"Купува се само ако High ≥ \$([\d.]+), до \$([\d.]+); обем ≥ ([\d.]+)× среден за потвърждение\.")
new_wording = lambda t: _OLD_TAIL.sub(lambda m: (f"Buy-stop поръчката се изпълнява при докосване (High ≥ ${m[1]}), до ${m[2]}; обемът се вижда едва при затварянето — "
                                                  f"книгата отбелязва дали денят на входа затвори с ≥ {m[3]}× среден обем."), t or "")

D = dt.date.fromisoformat
FX = json.loads((ROOT / "tests" / "fixtures" / "buystop_book_2026-10-12.json").read_text(encoding="utf-8"))
B12 = FX["cards"]

tmp = tempfile.TemporaryDirectory(prefix="mb_bsorder_")
config.DATA_DIR = pathlib.Path(tmp.name)
config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"
config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest._unapplied_splits = lambda rec: []


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):      # СИНТЕТИЧНО: подмяна на мрежата с РЕАЛНИТЕ барове от fixture-а
    fr = {t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["dates"]))
          for t, b in FX["bars"].items() if t in tickers}
    return pd.concat({f: pd.DataFrame({t: fr[t][f] for t in fr}) for f in ("Open", "High", "Low", "Close", "Volume")}, axis=1)


backtest.yf.download = fake_download


def fresh(t):
    c = copy.deepcopy(B12[t])
    for k in ("setup", "plan_preview", "levels"):
        c.pop(k, None)
    return c


print("── 1. КОНТРОЛ: старият ред (карта преди резолюцията) възпроизвежда брифа от 12.10 ──")
backtest._save_tracker(copy.deepcopy(FX["tracker_before"]))
old = {t: fresh(t) for t in ("EXPD", "ANET")}
setup_rules.annotate(list(old.values()), D("2026-10-12"), backtest.live_buystop_by_ticker())
assert old["EXPD"]["setup"]["book_status"] == "pending" and old["EXPD"]["setup"]["trigger_text"].startswith("Чака пробив: buy-stop $194.59 (валиден до 15.10, от 09.10")
assert old["EXPD"]["setup"]["trigger_text"] == new_wording(B12["EXPD"]["setup"]["trigger_text"])                          # дословно като в РЕАЛНИЯ бриф
assert old["ANET"]["setup"]["kind"] == "no_volume" and "triggered" not in old["ANET"]["setup"]
print("  ✓ с tracker-а от диска (преди run-а): EXPD 'Чака пробив … валиден до 15.10, от 09.10' — дословно като в брифа; ANET без дума за книгата")

print()
print("── 2. резолюцията върху РЕАЛНИТЕ барове дава записите от run-а на 12.10 ──")
tr = backtest._load_tracker()
backtest._resolve_open_positions(tr, D("2026-10-12"))
backtest._save_tracker(tr)
for k, want in FX["tracker_after"].items():
    got = backtest._load_tracker()[k]
    for f in ("status", "fill_date", "fill_price", "stop_loss", "target_1", "current_r"):
        assert got[f] == want[f], (k, f, got[f], want[f])
e = backtest._load_tracker()["EXPD_2026-10-09_buystop"]; a = backtest._load_tracker()["ANET_2026-10-09_buystop"]
assert (e["status"], e["fill_date"], e["fill_price"]) == ("open", "2026-10-09", 194.59) and (a["status"], a["fill_price"], a["stop_loss"]) == ("open", 215.38, 197.7)
bar = FX["bars"]["EXPD"]; i = bar["dates"].index("2026-10-09")
assert bar["h"][i] >= 194.59 > bar["o"][i]                                                                 # High 195.73 над buy-stop, Open 194.13 под него → вход по нивото
bar = FX["bars"]["ANET"]; i = bar["dates"].index("2026-10-09")
assert bar["o"][i] == 215.38 > 214.89                                                                      # отваряне над buy-stop → вход по отварянето
print("  ✓ EXPD: 09.10 O 194.13 / H 195.73 → вход $194.59; ANET: отваряне $215.38 > $214.89 → вход $215.38, стоп $197.70 — същите числа като в РЕАЛНИЯ tracker след 12.10")

print()
print("── 3. новият ред: картата чете книгата СЛЕД резолюцията ──")
new = {t: fresh(t) for t in ("EXPD", "ANET")}
setup_rules.annotate(list(new.values()), D("2026-10-12"), backtest.live_buystop_by_ticker())
se, sa = new["EXPD"]["setup"], new["ANET"]["setup"]
assert se["triggered"] is True and se["book_status"] == "open" and se["trigger_text"].startswith("✅ Задействан на 09.10 по $194.59 (buy-stop от 09.10) · стоп $181.53 · цел 2R $220.71")
assert sa["triggered"] is True and sa["kind"] == "no_volume" and sa["book"]["stop_loss"] == 197.7
assert sa["trigger_text"].startswith("✅ Задействан на 09.10 по $215.38 (buy-stop от 09.10) · стоп $197.70 · цел 2R $249.27")
print("  ✓ EXPD:", se["trigger_text"])
print("  ✓ ANET (сетъп no_volume):", sa["trigger_text"])

print()
print("── 4. confirmed: неутрален ред, без забрана (СИНТЕТИЧНА карта: ANET с обем 2.0× над прага; записът в книгата е РЕАЛНИЯТ) ──")
c = fresh("ANET"); c["volume_ratio"] = 2.0; c.pop("breakout_volume", None)
setup_rules.annotate([c], D("2026-10-12"), backtest.live_buystop_by_ticker())
assert c["setup"]["kind"] == "confirmed" and c["setup"]["eligible"] is True and "triggered" not in c["setup"] and c["setup"]["trigger_text"].startswith("Потвърден пробив")
assert c["setup"]["book_note"] == "в buy-stop книгата: отворена от 09.10 по $215.38" and "не нов вход" not in c["setup"]["trigger_text"]
tr_rec = backtest.live_buystop_by_ticker()["ANET"]
c_tr = fresh("ANET"); c_tr["volume_ratio"] = 2.0; c_tr.pop("breakout_volume", None)
setup_rules.annotate([c_tr], D("2026-10-12"), {"ANET": {**tr_rec, "status": "trailing"}})                    # СИНТЕТИЧНО: след частична продажба
assert c_tr["setup"]["book_note"] == "в buy-stop книгата: отворена от 09.10 по $215.38 (след частична продажба на 2R)"
seen = {}
from src import ai_brief
ai_brief._call_claude = lambda system, user, **k: seen.setdefault("user", user) and "[]"                       # СИНТЕТИЧНО: записва промпта
ai_brief.ticker_narratives([c], [], "Defensive")
assert "Потвърден пробив" in seen["user"] and "buy-stop книгата" not in seen["user"] and "не нов вход" not in seen["user"]
b0 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
c["ai"] = B12["ANET"].get("ai") or {}
c["plan"] = sizing.position_plan_v2(c, 0.5, D("2026-10-12"))                                                    # за Action картата
for where in ("watchlist", "action"):
    bb = copy.deepcopy(b0); bb["watchlist"], bb["action"] = ([c], []) if where == "watchlist" else ([], [c])
    pg = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(bb))))
    assert "в buy-stop книгата: отворена от 09.10 по $215.38" in pg and "не нов вход" not in pg, where
print("  ✓ confirmed остава 'Потвърден пробив' (може да стане Action); картата (Watchlist и Action) носи 'в buy-stop книгата: отворена от 09.10 по $215.38';")
print("    в промпта (setup + setup_reason) няма нито реда, нито 'не нов вход'")

print()
print("── 5. plan_preview.valid_through = прозорецът на картата ──")
backtest._save_tracker(copy.deepcopy(FX["tracker_before"]))                                                # чакащ запис (състоянието преди резолюцията)
p = fresh("EXPD"); setup_rules.annotate([p], D("2026-10-12"), backtest.live_buystop_by_ticker())
pp = sizing.buy_stop_preview(p, 0.5, D("2026-10-12"))
assert p["setup"]["valid_through"] == "2026-10-15" and pp["valid_through"] == "2026-10-15" and B12["EXPD"]["plan_preview"]["valid_through"] == "2026-10-16"
q = fresh("EXPD"); setup_rules.annotate([q], D("2026-10-12"))                                               # без книга — нов прозорец от днес, и двете еднакви
assert q["setup"]["valid_through"] == sizing.buy_stop_preview(q, 0.5, D("2026-10-12"))["valid_through"] == "2026-10-16"
print("  ✓ с чакащ запис от 09.10: setup и plan_preview — 15.10 (в брифа plan_preview беше 16.10); без запис — 16.10 и в двете")
backtest._save_tracker(tr)

print()
print("── 6. страницата: картата на EXPD и компактният ред на ANET ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))           # РЕАЛЕН бриф (05.10) като рамка; Watchlist = РЕАЛНИТЕ карти от 12.10 с новия setup
for t in ("EXPD", "ANET"):
    new[t]["ai"] = B12[t].get("ai") or {}
b["watchlist"] = [new["EXPD"], new["ANET"]]
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "EXPD — ✅ задействан в buy-stop книгата на 09.10 по $194.59" in page and "Чака пробив: buy-stop $194.59" not in page        # 26.10.2026 (етап 4б, т. 10): компактен ред
row = page[page.index("В скрийнъра, без сетъп за вход днес:"):][:400]
assert "ANET — ✅ задействан в buy-stop книгата на 09.10 по $215.38, стоп $197.70 (8.2% под входа), текущо +0.1R; днес: над pivot без обем ≥ 1.5×" in row and "стоп 9.2%" not in row
cards, compact = render.split_watchlist([new["ANET"]])
assert not cards and compact[0]["stop_pct"] is None and compact[0]["book"]["fill_price"] == 215.38
cards, compact = render.split_watchlist([old["ANET"]])
assert compact[0]["reason"] == "над pivot без обем ≥ 1.5×" and compact[0]["stop_pct"] == old["ANET"]["setup"]["struct_risk_pct"]   # без запис — както преди
print("  ✓", row[:row.index(", отчет")])

print()
print("── 7. редът в main.run(): резолюцията е преди setup_rules.annotate ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
call = "\n        backtest.resolve_positions_only()\n"                                                       # самото извикване (коментарите също споменават функцията)
assert src.count(call) == 1
assert src.index(call) < src.index("setup_rules.annotate(candidates") < src.index("cot_live = _live_positions()")
print("  ✓ ensure_v2_methodology + resolve_positions_only → setup_rules.annotate → _live_positions (веднъж)")
print()
print("Всички тестове минаха.")
