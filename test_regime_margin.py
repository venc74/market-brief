"""
15.10.2026 · ред "Запас до смяна на режима" (src/regime_claims.py: margin) — в картата на термометъра и като факт в макро промпта. Смята го кодът: колко червени сменят режима по правилото,
distribution days спрямо прага (SPY и QQQ), IEI/HYG 10д RoC percentile спрямо прага за override (с посоката от roc_trend_text), близките прагове на VIX / MOVE / VIX term structure.

РЕАЛНО: tests/fixtures/brief_2026-10-15.json (Offensive 6/2/0; distribution days SPY 8 / QQQ 7 при праг 9; IEI/HYG RoC 87.7 при праг 90, спада) и brief_2026-10-09.json (override IEI/HYG
над прага, 1 червен). СИНТЕТИЧНО (маркирано): подменените термометри за близките прагове, Cash и недостатъчно потвърждение; подмененият _call_claude.
Пускане: python test_regime_margin.py
"""
import sys, json, pathlib, contextlib, io, copy, re, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_margin_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import regime_claims as rc, ai_brief, render

B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
B09 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-09.json").read_text(encoding="utf-8"))
f15 = rc.facts(B15["thermometer"])
rcm = B15["ai_macro"]["regime_comment"]
bad = "ако един зелен стане червен при 0 червени сега, системата пак остава Offensive; нужни са 2 червени за Defensive"
print("── 1. Запас до смяна на режима ──")
m15 = rc.margin(B15["thermometer"], B15["distribution_days"])
WANT15 = ["по броенето Offensive: 1 червен → Defensive (сега 0 червени; зелени 6, минимум 4; видими 8, минимум 6)",
          "distribution days SPY 8/9, QQQ 7/9 — при 9 Offensive се блокира (липсва 1)",
          "IEI/HYG 10д RoC 88. percentile при праг 90 (≥ 90 → червен и override Defensive); 10-дневната RoC е +0.56% срещу +0.79% преди 5 сесии — спада (забавя се)"]
assert m15["parts"] == WANT15, m15["parts"]
assert m15["text"] == "Запас до смяна на режима: " + " · ".join(WANT15)
print("  ✓ РЕАЛНО 15.10:", m15["text"])
m09 = rc.margin(B09["thermometer"], B09["distribution_days"])
assert m09["parts"][0] == "активен override (IEI/HYG) — режимът е Defensive независимо от броенето" and "IEI/HYG 10д RoC 94. percentile — над прага 90: override" in m09["parts"][-1]
assert "по броенето до Offensive: 0 червени (сега 1: IEI/HYG (Credit Spread)); до Cash: още 2 червени" in m09["parts"]
print("  ✓ РЕАЛНО 09.10:", m09["text"])
t = copy.deepcopy(B15["thermometer"])                                                                              # СИНТЕТИЧНО: близки прагове
by = {i["name"]: i for i in t["indicators"]}
by["VIX"]["value"], by["MOVE (Bond Vol)"]["value"], by["MOVE (Bond Vol)"]["delta_1w"], by["VIX Term Structure"]["value"] = 26.4, 131.0, 12.5, 0.97
mn = rc.margin(t, {"spy_count": 9, "qqq_count": 7})
assert "VIX 26.4 (override над 30)" in mn["parts"] and "MOVE 131 (override над 150)" in mn["parts"] and "MOVE +12.5 пункта за седмица (override при +15)" in mn["parts"]
assert "VIX term structure 0.97 (жълт от 1.00, червен от 1.10)" in mn["parts"] and "distribution days SPY 9/9, QQQ 7/9 — червени: Offensive е блокиран; блокът пада след 2 поредни дни под 9" in mn["parts"]
assert not any(p.startswith(("VIX ", "MOVE")) for p in m15["parts"])                                              # реално 15.10: VIX 16.9, MOVE 99, делта −3.5, ratio 0.78 — не са близо
assert rc.margin(None) == {"text": "", "parts": []} and rc.margin({"indicators": []}, None)["text"] == ""
cash = rc.margin({"indicators": [{"name": f"R{i}", "status": "red"} for i in range(3)] + [{"name": "G", "status": "green"}] * 3})            # СИНТЕТИЧНО
assert cash["parts"] == ["по броенето до Defensive: под 3 червени (сега 3: R0, R1, R2)"]
low = rc.margin({"indicators": [{"name": "G", "status": "green"}] * 3 + [{"name": "Y", "status": "yellow"}] * 2})                         # СИНТЕТИЧНО
assert low["parts"] == ["по броенето до Offensive: още 1 зелен и още 1 видим при 0 червени; до Cash: 3 червени"]
print("  ✓ СИНТЕТИЧНО: близките прагове (VIX ≥ 25, MOVE ≥ 120, делта ≥ +10, ratio ≥ 0.95) се показват само когато са близо; Cash / недостатъчно потвърждение; празен термометър → празно")

print()
print("── 2. промптът, страницата и main.run ──")
prompts = []
def fake_claude(system, user, **k):
    prompts.append(user)
    return json.dumps({"macro_brief": "Кратко.", "sector_logic": []}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
th = copy.deepcopy(B15["thermometer"]); th["regime_margin"] = m15
with contextlib.redirect_stdout(io.StringIO()):
    res = ai_brief.macro_and_sector_brief({}, [], th)
assert "ЗАПАС ДО СМЯНА НА РЕЖИМА" not in prompts[0] and m15["text"] not in prompts[0] and f15["rule_text"] not in prompts[0]        # 29.10.2026 (разходката, т. 5): за абзаца за режима
assert res == {"macro_brief": "Кратко.", "sector_logic": []}
print("  ✓ от 29.10 промптът е без запаса и правилото (абзацът за режима е махнат); редът „Запас до смяна на режима“ остава на страницата — от кода")
b = copy.deepcopy(B15); b["thermometer"]["regime_margin"] = m15
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Запас до смяна на режима: " + " · ".join(WANT15) in page
sec = page[page.index("Пазарен термометър"):]
assert sec.index("Запас до смяна на режима") < sec.index("Значими новини") if "Значими новини" in sec else True
assert "Запас до смяна" not in re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(copy.deepcopy(B15)))))      # стар бриф без ключа
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index('thermo = steps.step("distribution_cap", lambda: apply_distribution_cap(thermo, distribution_days') < src.index('thermo["regime_margin"] = regime_claims.margin(thermo, distribution_days') < src.index("ai_macro = ai_brief.macro_and_sector_brief(")
print("  ✓ страницата (РЕАЛНИЯТ бриф от 15.10): редът е в картата на термометъра; стар бриф без ключа — без реда; main: след distribution days, преди макро брифа")
print("\n✅ test_regime_margin: всичко мина")
