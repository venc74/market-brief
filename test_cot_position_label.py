"""
26.10.2026 · етап 4б, т. 8 · етикетът на COT екстремума — по ЗНАКА на нетната позиция, не само по перцентила (src/cot.py: position_label; render: филтър cot_label).

Реален дефект (брифът от 26.10): Bitcoin Futures (CME) — нетно −4 942 на 100-и перцентил за 156 седмици, а картата казваше "екстремно дълги"; managed money са НЕТНО КЪСИ, само
най-малко къси от 3 години. В историята: 79 от 336 екстремума с такова разминаване. Посоката на contrarian сигнала (extreme_long → цена надолу) не се мени.

РЕАЛНО: tests/fixtures/cot_labels_2026-10-26.json — COT редовете и crypto.cot_btc на брифа от 26.10; tests/fixtures/brief_2026-10-19.json — целият бриф от 19.10 (страницата).
СИНТЕТИЧНО (означено): граничните стойности в т. 2.
Пускане: python test_cot_position_label.py
"""
import sys, json, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cotlbl_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import cot, render

FX = json.loads((ROOT / "tests" / "fixtures" / "cot_labels_2026-10-26.json").read_text(encoding="utf-8"))

print("── 1. брифът от 26.10 (РЕАЛНИТЕ редове) ──")
lab = {c["market"]: render.cot_label(c) for c in FX["cot"]}
btc = next(c for c in FX["cot"] if c["market"] == "Bitcoin Futures (CME)")
assert (btc["net_position"], btc["percentile"], btc["direction"], btc["weeks_of_history"]) == (-4942, 100.0, "extreme_long", 156)
assert lab["Bitcoin Futures (CME)"] == "най-малко къси от 3 години"
assert lab["30-Year Treasury Bond"] == lab["2-Year Treasury Note"] == "нетно къси, близо до най-малко късите за 3 години"
assert lab["Silver"] == "нетно дълги, близо до най-малко дългите за 3 години"
assert lab["Sugar No. 11"] == "екстремно дълги" and lab["Euro FX"] == lab["Natural Gas"] == "екстремно къси" and lab["XRP"] == "екстремно дълги"   # XRP: нетно +273
wrong = [m for m, c in ((c["market"], c) for c in FX["cot"]) if (c["direction"] == "extreme_long") != (c["net_position"] > 0)]
assert sorted(wrong) == ["2-Year Treasury Note", "30-Year Treasury Bond", "Bitcoin Futures (CME)", "Silver"]
assert all(not lab[m].startswith("екстремно") for m in wrong) and all(lab[m].startswith("екстремно") for m in lab if m not in wrong)
assert render.cot_label(FX["cot_btc"]) == "най-малко къси от 3 години"                                  # крипто секцията (net / percentile / weeks)
print(f"  ✓ Bitcoin −4 942 (100.) → „{lab['Bitcoin Futures (CME)']}“; 30Y/2Y → „{lab['30-Year Treasury Bond']}“; Silver +3 505 (3.2) → „{lab['Silver']}“; "
      f"останалите {len(lab) - len(wrong)} — непроменени")

print()
print("── 2. гранични стойности (СИНТЕТИЧНИ) ──")
assert cot.position_label("extreme_short", 5, 0.0, 156) == "най-малко дълги от 3 години"
assert cot.position_label("extreme_long", -5, 100.0, 52) == "най-малко къси от година"
assert cot.position_label("extreme_long", 100, 95, 62) == "екстремно дълги"
assert cot.position_label("extreme_long", -1, 97, 62) == "нетно къси, близо до най-малко късите за 62 седмици"
assert cot.position_label(None, -4942, 100.0, 156) == "най-малко къси от 3 години" and cot.position_label(None, 10, 50, 156) == ""
assert cot.position_label("extreme_long", None, None, None) == "екстремно дълги"                          # без числа — старият етикет, без грешка
print("  ✓ 0-и перцентил при нетно дълги, прозорец 52 / 62 седмици, без посока (по прага), без числа")

print()
print("── 3. новият ред носи полето; страницата (РЕАЛНИЯТ бриф от 19.10, без полето) ──")
pts = [{"date": f"2026-{(i // 4) + 1:02d}-{(i % 4) * 7 + 1:02d}", "net": -9000 + i * 10} for i in range(40)]  # СИНТЕТИЧНА серия: къси, всяка седмица по-малко
ex = cot._market_extreme("X", pts, "financial", config.COT_PERCENTILE_LOW, config.COT_PERCENTILE_HIGH)
assert ex["direction"] == "extreme_long" and ex["position_label"] == "най-малко къси от 40 седмици"
b19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
assert all("position_label" not in c for c in b19["cot"])
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b19)
sec = page[page.index("COT Екстремуми"):]; sec = htmllib.unescape(sec[:sec.index("</section>")])
heads = dict(re.findall(r'class="thesis-name">([^<]+)</span>\s*<span class="cot-percentile">[^(]*\(([^)]+)\)', sec))
assert heads["Bitcoin Futures (CME)"] == "нетно къси, близо до най-малко късите за 3 години"                 # −5 844 на 99.4
assert heads["30-Year Treasury Bond"] == "най-малко къси от 3 години" and heads["XRP"] == "най-малко къси от 62 седмици"  # −154 020 на 100; XRP −45 на 100 (62 седмици)
assert heads["Coffee C"] == "нетно дълги, близо до най-малко дългите за 3 години" and heads["Euro FX"] == "екстремно къси"
print(f"  ✓ 19.10: Bitcoin → „{heads['Bitcoin Futures (CME)']}“, 30Y → „{heads['30-Year Treasury Bond']}“, XRP → „{heads['XRP']}“, Coffee → „{heads['Coffee C']}“")
print("\n✅ test_cot_position_label: всичко мина")
