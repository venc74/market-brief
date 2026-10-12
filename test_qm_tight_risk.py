"""
12.10.2026 · книга qm_breakout: R = печалба ÷ max(вход − low на входния ден, 0.25×ADR) (решение на Венци), колона "Вход", доходност в % до R, флаг за записите с риск под пода.

Случаят (РЕАЛЕН, книгата след run-а на 12.10): ELF от 09.10 — нивото $106.97, отваряне $107.36 (вход при гап), low на входния ден $107.00 (стопът), ADR 3.86% → риск $0.36 = 0.09×ADR;
затваряне $109.23 → "+5.2R" при +1.7%. С пода 0.25×ADR знаменателят е $1.036 → +1.8R. Стопът и изходът не се променят. Старите записи се преизчисляват еднократно
(backtest._migrate_qm_r_floor) с бележка в записа. Реплей 02.01.2024–01.10.2026 (244 сделки): 30 сделки с риск под 0.25×ADR носеха 69% от ΣR; среден R +1.51 → +1.00.

РЕАЛНО: tests/fixtures/qm_book_2026-10-12.json (8-те записа на книгата), tests/fixtures/brief_2026-10-05.json (рамка на страницата). СИНТЕТИЧНО (означено): временният tracker,
затвореният запис, сделката в т.5 (барове).
Пускане: python test_qm_tight_risk.py
"""
import sys, json, pathlib, tempfile, copy, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import backtest, render, trade_sim

FX = json.loads((ROOT / "tests" / "fixtures" / "qm_book_2026-10-12.json").read_text(encoding="utf-8"))["records"]
tmp = tempfile.TemporaryDirectory(prefix="mb_qmtight_")
config.DATA_DIR = pathlib.Path(tmp.name); config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"; config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
TODAY = dt.date(2026, 10, 12)

print("── 1. числата на реалния ELF (по старата формула) ──")
e = FX["ELF_2026-10-09_qm"]
assert (e["buy_stop"], e["fill_price"], e["stop_loss"], e["risk_per_share"], e["adr"], e["current_r"], e["last_close"], e["return_pct"]) == (106.97, 107.36, 107.0, 0.36, 3.86, 5.19, 109.23, 1.74)
assert round((e["fill_price"] - e["stop_loss"]) / e["fill_price"] * 100 / e["adr"], 2) == 0.09
print("  ✓ ниво $106.97, вход $107.36 (гап), стоп $107.00 (над нивото), риск $0.36 = 0.09×ADR, +5.19R при +1.74%")

print()
print("── 2. еднократното преизчисляване на старите записи ──")
tr = copy.deepcopy(FX)
assert backtest._migrate_qm_r_floor(tr, TODAY) == 1                                                  # само ELF е под пода
el, sn = tr["ELF_2026-10-09_qm"], tr["SN_2026-10-09_qm"]
assert el["current_r"] == round(5.19 * 0.36 / (0.25 * 3.86 / 100 * 107.36), 2) == 1.8 and el["r_floored"] is True and el["r_method"] == "floor_adr"
assert el["stop_loss"] == 107.0 and el["return_pct"] == 1.74 and el["r_before_floor"]["current_r"] == 5.19
assert el["r_note"] == "R преизчислен на 2026-10-12: печалба ÷ max(вход − low на входния ден, 0.25×ADR); стопът и изходът не са променени (беше 5.19R)"
assert (sn["current_r"], sn["r_floored"], sn["r_method"]) == (-0.45, False, "floor_adr")                # 2.97 > 0.25×3.57%×186.33 = 1.66 → без промяна
assert sn["r_note"].endswith("— без промяна: рискът на входа е над пода")
assert all(r["r_method"] == "floor_adr" for r in tr.values())
before = json.dumps(tr, sort_keys=True)
assert backtest._migrate_qm_r_floor(tr, TODAY) == 0 and json.dumps(tr, sort_keys=True) == before   # идемпотентно
print(f"  ✓ ELF: +5.19R → +{el['current_r']}R (стопът $107.00 и доходността +1.74% — същите); SN (0.45×ADR) — без промяна; втори път — нищо; бележка: '{el['r_note']}'")

print()
print("── 3. обобщението и страницата ──")
backtest._save_tracker(tr)
s = backtest.get_qm_summary()
rows = {r["ticker"]: r for r in s["live"]}
assert rows["ELF"]["risk_adr"] == 0.09 and rows["ELF"]["tight_risk"] is True and rows["ELF"]["current_r"] == 1.8 and rows["ELF"]["return_pct"] == 1.74
assert rows["SN"]["tight_risk"] is False and rows["CORT"]["risk_adr"] is None and s["tight_risk"] == 1 and s["tight_risk_adr"] == 0.25
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b.setdefault("backtest", {})["qm_breakout"] = s
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Ниво Вход Стоп (low на входния ден)" in page and "R = печалба ÷ max(вход − low на входния ден, 0.25×ADR)" in page
elf = page[page.index("ELF 2026-10-09"):][:400]
assert "+1.8R (+1.7%)" in elf and "⚠ риск на входа 0.09×ADR — R от пода 0.25×ADR" in elf and "$106.97 $107.36 (гап) $107.0" in elf and "+5.2R" not in elf
assert "с риск на входа под 0.25×ADR: 1 (R от пода)" in page
sn_txt = page[page.index("SN 2026-10-09"):][:300]
assert "R от пода" not in sn_txt and "(гап)" not in sn_txt and "-0.5R (-0.7%)" in sn_txt
print("  ✓", elf[:elf.index("Defensive") + 9] if "Defensive" in elf else elf[:200])

print()
print("── 4. затворен запис (СИНТЕТИЧЕН: ELF, стопиран на 14.10 по $107.00) ──")
tr2 = copy.deepcopy(tr)
el2 = tr2["ELF_2026-10-09_qm"]
el2.update(status="stopped", resolution_date="2026-10-14", realized_r=round((107.0 - 107.36) / 1.036, 2), realized_r_pess=round((107.0 - 107.36) / 1.036, 2),
           exit_price=107.0, return_pct=-0.34, return_pct_pess=-0.34)
backtest._save_tracker(tr2)
s2 = backtest.get_qm_summary()
assert s2["recent"][0]["ticker"] == "ELF" and s2["recent"][0]["tight_risk"] is True and s2["avg_return_pct"] == -0.34
b["backtest"]["qm_breakout"] = s2
page2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "R=-0.35 opt / -0.35 pess (-0.3% / -0.3%) · Defensive ⚠ риск на входа 0.09×ADR — R от пода 0.25×ADR" in page2
assert "средна доходност на сделка -0.34% / -0.34%" in page2
print("  ✓ стоп на дъното на деня = −0.35R (не −1R): загубата е $0.36 при знаменател $1.036; доходност −0.3%")

print()
print("── 5. simulate_qm (СИНТЕТИЧНИ барове: гап над нивото, дъното на деня на 0.1×ADR под входа) ──")
idx = pd.bdate_range("2026-09-01", periods=40)
c = [100.0] * 30 + [101.0, 102.0, 103.0, 103.5, 104.0, 104.5, 105.0, 105.5, 106.0, 106.5]
bars = pd.DataFrame({"Open": c, "High": [x + 0.5 for x in c], "Low": [x - 0.5 for x in c], "Close": c}, index=idx)
bars.iloc[30] = [101.0, 101.5, 100.6, 101.2]                                                       # вход: отваряне 101.0 над нивото 100.8, low 100.6 → риск 0.4 = 0.1×ADR (ADR 4%)
res = trade_sim.simulate_qm({"entry_date": idx[30].date().isoformat(), "buy_stop": 100.8, "adr": 4.0}, bars, None)
assert res["fill_price"] == 101.0 and res["stop_loss"] == 100.6 and res["risk_per_share"] == 0.4 and res["r_floored"] is True and res["r_risk"] == round(0.25 * 4.0 / 100 * 101.0, 4)
old_floor = config.QM_R_RISK_FLOOR_ADR
config.QM_R_RISK_FLOOR_ADR = 0.0                                                                   # без пода — старото поведение
res0 = trade_sim.simulate_qm({"entry_date": idx[30].date().isoformat(), "buy_stop": 100.8, "adr": 4.0}, bars, None)
config.QM_R_RISK_FLOOR_ADR = old_floor
assert res0["r_floored"] is False and res0["stop_loss"] == res["stop_loss"] and res0["exit_date"] == res["exit_date"] and res0["return_pct"] == res["return_pct"]
assert abs(res0["current_r"] / res["current_r"] - res["r_risk"] / 0.4) < 0.01
print(f"  ✓ риск 0.4 (0.10×ADR) → знаменател {res['r_risk']} (0.25×ADR): {res['current_r']:+.2f}R вместо {res0['current_r']:+.2f}R; стоп, изход и доходност в % — същите")
print()
print("Всички тестове минаха.")
