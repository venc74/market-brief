"""
04.11.2026 · прегледът, т. 5: SN 12.10 в книгата qm_breakout стоеше „pending“ при ниво $186.75 и цена ~$213, а обновяването в 15:05 го показа „над нивото“.
Причината (РЕАЛНАТА история на записа): записът не е заседнал — роден е сутринта на 04.11. Първото попълване с 5-минутни бари смени SN_2026-10-09 от „стоп на 16.10“ на „стоп в деня на входа, 09.10“;
интервалът на позицията се скъси, _is_continuation за картата от 12.10 вече е False и ingest-ът (след резолюцията в същия run) създаде SN_2026-10-12_qm от стария snapshot.
Срокът му е една сесия (valid_through 12.10); следващата резолюция го решава от баровете на САМИЯ 12.10 (днешната цена не участва), 5-минутните бари се теглят за същия ден.
Поправката: чакащ запис с изтекъл срок не влиза в нивата на карето.

РЕАЛНО: tests/fixtures/preopen_pending_2026-11-04.json (бележката — вътре). СИНТЕТИЧНО (означено): точките на премаркета са построени от реалните цени в нивата на 04.11; записът без срок.
Пускане: python test_preopen_pending.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_prepend_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen, backtest, trade_sim

FX = json.loads((ROOT / "tests" / "fixtures" / "preopen_pending_2026-11-04.json").read_text(encoding="utf-8"))
B = FX["bars"]
bars = pd.DataFrame({"Open": B["o"], "High": B["h"], "Low": B["l"], "Close": B["c"]}, index=pd.to_datetime(B["d"]))

print("── 1. защо се роди: 5-минутните бари скъсиха предишния запис ──")
before, after, rec = FX["sn_0910_before"], FX["sn_0910_after"], FX["sn_1012"]
assert (before["exit_date"], before["how"], before["realized_r"]) == ("2026-10-16", "stop", 0.99) and (after["exit_date"], after["how"], after["realized_r"]) == ("2026-10-09", "stop_intraday", -0.76)
k = "SN_2026-10-09_qm"
assert backtest._is_continuation({k: before}, "SN", "2026-10-12", backtest.CATEGORY_QM) is True
assert backtest._is_continuation({k: after}, "SN", "2026-10-12", backtest.CATEGORY_QM) is False
print("  ✓ SN 09.10: стоп на 16.10 (+0.99 R) → стоп в деня на входа (−0.76 R); картата от 12.10 вече не е продължение — записът е нов, от стария snapshot")

print()
print("── 2. не е заседнал: следващата резолюция го решава от баровете на 12.10 ──")
assert (rec["status"], rec["valid_through"], rec["buy_stop"], rec["fill_date"]) == ("pending", "2026-10-12", 186.75, None)
res = trade_sim.simulate_qm(rec, bars, dt.date(2026, 11, 5))
assert (res["fill_date"], res["fill_price"], res["status"], res["exit_date"]) == ("2026-10-12", 186.75, "stopped", "2026-10-14")
assert bars.loc["2026-10-12", "High"] >= 186.75 and bars["Close"].iloc[-1] > 200                    # денят на пробива е 12.10, не днес; цената отдавна е над нивото
print(f"  ✓ по дневни бари: вход на 12.10 по $186.75, стоп на 14.10 ({res['realized_r']:+.2f} R); 5-минутните бари се теглят за 12.10 (днешната цена не участва)")

print()
print("── 3. карето: изтекъл чакащ запис не е ниво за днес ──")
live = {x["ticker"]: x for x in FX["levels_live"]}
assert set(live) == {"WST", "SN"}                                                                    # какво показа живото обновяване на 04.11
pts = {t: {"pm_price": x["pm_price"], "pm_volume": None} for t, x in live.items()}                    # СИНТЕТИЧНО: точките — от реалните цени
wst = {**FX["wst"], "category": FX["wst"].get("category") or "action"}
lv = preopen.level_checks(pts, [], [], [FX["sn_1012"], wst], "2026-11-04")
assert [x["ticker"] for x in lv] == ["WST"] and lv[0]["level"] == 398.67 and wst["valid_through"] == "2026-11-10"
assert {x["ticker"] for x in preopen.level_checks(pts, [], [], [FX["sn_1012"], wst])} == {"WST", "SN"}    # без дата — както досега
today_card = {**FX["sn_1012"], "valid_through": "2026-11-04"}                                         # СИНТЕТИЧНО: срокът изтича днес — още важи
assert [x["ticker"] for x in preopen.level_checks(pts, [], [], [today_card], "2026-11-04")] == ["SN"]
no_date = {k: v for k, v in FX["sn_1012"].items() if k != "valid_through"}                            # СИНТЕТИЧНО: стар запис без срок — не се крие
assert [x["ticker"] for x in preopen.level_checks(pts, [], [], [no_date], "2026-11-04")] == ["SN"]
print("  ✓ 04.11: WST (срок 10.11) остава; SN (срок 12.10) — не; срок днес и запис без срок — остават")
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert 'level_checks(pts, waiting, qm_cards, records or [], res["date"])' in src
print("\n✅ test_preopen_pending: всичко мина")
