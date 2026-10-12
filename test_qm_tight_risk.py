"""
12.10.2026 · книга qm_breakout: колона "Вход" и флаг "риск < 0.25×ADR — R е раздут" (само показване; изчислението на R не е променено).

Случаят (РЕАЛЕН, книгата след run-а на 12.10): ELF от 09.10 — нивото $106.97, отваряне $107.36 (вход при гап), low на входния ден $107.00 (стопът), ADR 3.86% → риск $0.36 = 0.09×ADR;
затваряне $109.23 → "+5.2R" при +1.7%. В таблицата стопът ($107.00) стоеше над нивото ($106.97), а входът не се виждаше.
Реплей 02.01.2024–01.10.2026 (производственият check_candidate + simulate_qm, 244 сделки): риск < 0.25×ADR имат 30 сделки (12%), те носят 69% от ΣR.

РЕАЛНО: tests/fixtures/qm_book_2026-10-12.json (8-те записа на книгата), tests/fixtures/brief_2026-10-05.json (рамка на страницата). СИНТЕТИЧНО (означено): временният tracker, затвореният запис с малък риск.
Пускане: python test_qm_tight_risk.py
"""
import sys, json, pathlib, tempfile, copy, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "qm_book_2026-10-12.json").read_text(encoding="utf-8"))["records"]
tmp = tempfile.TemporaryDirectory(prefix="mb_qmtight_")
config.DATA_DIR = pathlib.Path(tmp.name); config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"; config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest._save_tracker(copy.deepcopy(FX))

print("── 1. числата на реалния ELF ──")
e = FX["ELF_2026-10-09_qm"]
assert (e["buy_stop"], e["fill_price"], e["stop_loss"], e["risk_per_share"], e["adr"], e["current_r"], e["last_close"]) == (106.97, 107.36, 107.0, 0.36, 3.86, 5.19, 109.23)
assert round((e["fill_price"] - e["stop_loss"]) / e["fill_price"] * 100 / e["adr"], 2) == 0.09
print("  ✓ ниво $106.97, вход $107.36 (гап), стоп $107.00 (над нивото), риск $0.36 = 0.09×ADR, +5.19R при затваряне $109.23 (+1.7%)")

print()
print("── 2. обобщението ──")
s = backtest.get_qm_summary()
rows = {r["ticker"]: r for r in s["live"]}
assert rows["ELF"]["risk_adr"] == 0.09 and rows["ELF"]["tight_risk"] is True and rows["ELF"]["fill_price"] == 107.36 and rows["ELF"]["current_r"] == 5.19   # R непроменен
assert rows["SN"]["risk_adr"] == round((186.325 - 183.355) / 186.325 * 100 / 3.57, 2) and rows["SN"]["tight_risk"] is False
assert rows["CORT"]["risk_adr"] is None and rows["CORT"]["tight_risk"] is False                                     # чакащ — без вход
assert s["tight_risk"] == 1 and s["tight_risk_adr"] == 0.25
print(f"  ✓ ELF: risk_adr 0.09 → флаг; SN: {rows['SN']['risk_adr']}×ADR → без флаг; CORT (чака) → без; общо 1 запис с флаг; R непроменен (+5.19)")

print()
print("── 3. страницата ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b.setdefault("backtest", {})["qm_breakout"] = s
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Ниво Вход Стоп (low на входния ден)" in page
elf = page[page.index("ELF 2026-10-09"):][:400]
assert "+5.2R" in elf and "⚠ риск 0.09×ADR < 0.25×ADR — R е раздут" in elf and "$106.97 $107.36 (гап) $107.0" in elf
assert "с риск на входа под 0.25×ADR: 1 (R е раздут)" in page
sn = page[page.index("SN 2026-10-09"):][:300]
assert "R е раздут" not in sn and "(гап)" not in sn
print("  ✓", elf[:elf.index("Defensive") + 9] if "Defensive" in elf else elf[:200])

print()
print("── 4. затворен запис (СИНТЕТИЧЕН: ELF, стопиран на 14.10) ──")
tr = backtest._load_tracker()
tr["ELF_2026-10-09_qm"].update(status="stopped", resolution_date="2026-10-14", realized_r=-1.0, realized_r_pess=-1.0, exit_price=107.0)
backtest._save_tracker(tr)
s2 = backtest.get_qm_summary()
assert s2["recent"][0]["ticker"] == "ELF" and s2["recent"][0]["tight_risk"] is True
b["backtest"]["qm_breakout"] = s2
page2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "R=-1.0 opt / -1.0 pess · Defensive ⚠ риск 0.09×ADR < 0.25×ADR — R е раздут" in page2
print("  ✓ флагът е и на картата на затворения запис")
print()
print("Всички тестове минаха.")
