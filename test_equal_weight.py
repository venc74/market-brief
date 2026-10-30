"""
30.10.2026 · поправки от брифа, т. 7: нов информативен уред — RSP (S&P 500 с равни тегла) спрямо SPY за 5 и 10 сесии, разликата в ръста в пунктове: „средната акция бие
гигантите“ (и двете +) / „гигантите дърпат индекса“ (и двете −) / смесено — с двете думи. В блока „Информативни — не влизат в режима“ (не се брои), подава се и на разказа.
РЕАЛНО към 29.10: 5 сесии RSP +0.83% срещу SPY +0.71% (+0.1 п.), 10 сесии +2.34% срещу −0.31% (+2.7 п.) → средната акция бие гигантите.

РЕАЛНО: tests/fixtures/rsp_spy_closes_2026-10-30.json — дневните затваряния на RSP и SPY (Yahoo, 3 месеца до 29.10, свалени на 30.10.2026);
tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): обърнатите редици в т. 3 и късата история.
Пускане: python test_equal_weight.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_rsp_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, render, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "rsp_spy_closes_2026-10-30.json").read_text(encoding="utf-8"))["closes"]
S = {t: pd.Series(list(v.values()), index=pd.to_datetime(list(v.keys()))) for t, v in FX.items()}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНИТЕ затваряния до 29.10 ──")
ind = th.equal_weight_signal(S["RSP"], S["SPY"])
assert (ind["as_of"], ind["diff_5"], ind["diff_10"], ind["rsp_5"], ind["spy_5"], ind["rsp_10"], ind["spy_10"]) == ("2026-10-29", 0.1, 2.7, 0.83, 0.71, 2.34, -0.31)
assert ind["informational"] and ind["status"] == "green"
assert ind["label"] == "5 сесии: RSP +0.8% срещу SPY +0.7% (+0.1 п.) · 10 сесии: +2.7 п. — средната акция бие гигантите · само информативен, не влиза в режима"
print(f"  ✓ «{ind['label'][:100]}…»")

print()
print("── 2. в „Информативни“, не се брои; разказът го вижда ──")
t = copy.deepcopy(B19["thermometer"]); t["indicators"] = t["indicators"] + [ind]
regime, _, counts = th._count_regime(t["indicators"])
assert "RSP спрямо SPY (широчина)" in counts.split("не се броят:")[1] and th._count_regime(B19["thermometer"]["indicators"])[0] == regime
b = copy.deepcopy(B19); b["thermometer"] = t
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
info = page[page.index('<div class="thermo-info">'):]
assert "RSP спрямо SPY (широчина)" in info
top = page[page.index("<h2>Пазарен термометър</h2>"):page.index('<div class="thermo-info">')]
assert "RSP спрямо SPY" not in top
assert '"name": "RSP спрямо SPY (широчина)"' in ai_brief.macro_user_prompt({}, [], t, [], {})
print("  ✓ картата е в блока „Информативни“, не горе; броенето не се променя; в промпта на разказа")

print()
print("── 3. гигантите дърпат индекса / смесено / къса история (СИНТЕТИЧНО) ──")
g = th.equal_weight_signal(S["SPY"], S["RSP"])                                                  # обърнато: „RSP“ е SPY → отрицателни разлики
assert g["status"] == "red" and "гигантите дърпат индекса" in g["label"] and "средната" not in g["label"]
mix_rsp = S["RSP"].copy(); mix_rsp.iloc[-1] = mix_rsp.iloc[-6] * (1 + (S["SPY"].iloc[-1] / S["SPY"].iloc[-6] - 1) - 0.01)
m = th.equal_weight_signal(mix_rsp, S["SPY"])
assert m["status"] == "yellow" and "за 5 сесии гигантите дърпат индекса, за 10 — средната акция бие гигантите" in m["label"]
h = th.equal_weight_signal(S["RSP"].iloc[-5:], S["SPY"].iloc[-5:])
assert h["hide"] and h["informational"] and h["hide_reason"] == "под 11 общи сесии"
print("  ✓ червено при „гигантите дърпат индекса“, жълто при смесено, скрит при къса история")
print("\n✅ test_equal_weight: всичко мина")
