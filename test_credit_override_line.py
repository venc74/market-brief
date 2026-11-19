"""
19.11.2026 (пакет 19.11, т. 3): кредитният override на плочката — правилото „скок IEI/HYG (≥ 90-и перц.) И кредитен натиск (HYG 10д ≤ −1% ИЛИ HY OAS 20д ≥ 75-и перц.)“ с ✓ / ✗
за всяка част (thermometer.credit_override_status → rule["credit_override"]); редът „Запас до смяна на режима“ — по едното правило (regime_claims._rule_margin), без „по броенето
до Offensive“ (старото правило). В кода: override-ът на IEI/HYG пада без кредитен натиск (credit_gate); режимът е от apply_market_rule.

РЕАЛНО: tests/fixtures/thermo_2026-11-19.json — термометърът и distribution days от брифа на 19.11 (скок 84-и, HYG −1.12%, HY OAS 73-и; SPY 730 под 50DMA 762).
СИНТЕТИЧНО (означено): т. 3 — скокът, натискът и хистерезисът.
Пускане: python test_credit_override_line.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_credit_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, regime_claims as rc, render

FX = json.loads((ROOT / "tests" / "fixtures" / "thermo_2026-11-19.json").read_text(encoding="utf-8"))
T = FX["thermometer"]

print("── 1. РЕАЛНО: 19.11 — натиск има, скок няма ──")
co = th.credit_override_status(T)
assert co["text"] == ("Кредитен override: скок IEI/HYG (10д RoC ≥ 90-и перц.) — 84-и ✗ И кредитен натиск (HYG 10д ≤ -1% — -1.1% ✓ ИЛИ HY OAS 20д ≥ 75-и перц. — 73-и ✗) "
                      "→ няма override (натиск без скок)"), co["text"]
assert co["spike"]["ok"] is False and co["hyg"]["ok"] is True and co["oas"]["ok"] is False and co["pressure"] is True and not co["active"]
print(f"  ✓ «{co['text']}»")

print("── 2. РЕАЛНО: „Запас“ — по правилото, без броенето за Offensive ──")
t = copy.deepcopy(T); t["rule"]["credit_override"] = co
m = rc.margin(t, FX["distribution_days"])
assert m["parts"][0] == ("до Offensive: SPY 730 под 50DMA (762) — нужни +4.4% и 50DMA да расте; distribution days червени (SPY 8, QQQ 8; праг 9) — по хистерезис — "
                         "после 2 поредни дни с изпълнени условия"), m["parts"][0]
assert m["parts"][1] == "до Cash: още 2 червени броени уреда (сега 1: VIX)"
assert not any("по броенето до Offensive" in p or "≥ 90 → червен и override Defensive" in p for p in m["parts"])
assert "distribution days SPY 8/9, QQQ 8/9 — под прага, но блокът на Offensive се държи по хистерезис" in m["parts"]
assert any(p.startswith("IEI/HYG: скок IEI/HYG (10д RoC ≥ 90-и перц.) — 84-и ✗; override само при кредитен натиск — сега има") for p in m["parts"])
old = copy.deepcopy(T); old.pop("rule")
assert any("по броенето до Offensive" in p for p in rc.margin(old, FX["distribution_days"])["parts"])          # стар бриф без правилото — както преди
print("  ✓ " + " · ".join(m["parts"][:2]))

print("── 3. СИНТЕТИЧНО: скок с натиск, скок без натиск, хистерезис ──")
def with_(p_roc, hyg, oas, overrides=()):
    x = copy.deepcopy(T)
    next(i for i in x["indicators"] if i["name"].startswith("IEI/HYG"))["roc_percentile"] = p_roc
    x["credit_pressure"] = dict(x["credit_pressure"], hyg_10d_pct=hyg, oas_chg_pct=oas, active=(hyg <= -1 or oas >= 75))
    x["overrides"] = list(overrides)
    return th.credit_override_status(x)
ov = [{"trigger": "IEI/HYG", "text": "…"}]
a = with_(93, -1.4, 40, ov)
assert a["active"] and a["verdict"] == "→ override: Defensive" and a["spike"]["text"].endswith("93-и ✓")
b = with_(95, -0.3, 50)
assert not b["active"] and b["verdict"] == "→ няма override (скок без натиск)"
c = with_(86, -1.5, 60, ov)
assert c["active"] and "override-ът се държи по хистерезис" in c["spike"]["text"]
src = (ROOT / "src" / "thermometer.py").read_text(encoding="utf-8")
assert 'if any(o["trigger"] == "IEI/HYG" for o in overrides) and cp["active"] is False:' in src                   # без натиск — override-ът пада
print("  ✓ скок + натиск → Defensive; скок без натиск → няма; под прага по хистерезис — казано")

print("── 4. плочката ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
bb = copy.deepcopy(B); bb["thermometer"] = t
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "Кредитен override: скок IEI/HYG (10д RoC ≥ 90-и перц.) — 84-и ✗ И кредитен натиск ( HYG 10д ≤ -1% — -1.1% ✓ ИЛИ HY OAS 20д ≥ 75-и перц. — 73-и ✗ ) → няма override" in txt, txt[txt.find("Кредитен override"):][:300]
print("  ✓ редът на плочката с ✓ / ✗")
print("\n✅ test_credit_override_line: всичко мина")
