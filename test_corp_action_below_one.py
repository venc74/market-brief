"""
13.10.2026 · коефициент ПОД 1, който не е проста дроб (HON 0.9535 на 29.06.2026 — отделянето на Honeywell Aerospace, слято с обратен сплит 1:2), е съществен ПО ПОДРАЗБИРАНЕ: изключване +
ред "нужна проверка", докато не бъде потвърден в config.CORP_ACTIONS_KNOWN ("material": False го връща към маркера). Обратните сплитове като прости дроби (1:3, 1:5) са точни.
Измерено на 13.10 (универс 903, 2 години): 3 събития под 1 — DD 1:3 (24.06.2026), AMCR 1:5 (15.01.2026), HON 0.9535 (29.06.2026).

РЕАЛНО: Close и Stock Splits на HON от tests/fixtures/corp_actions_materiality_2026-10-13.json; коефициентите на DD и AMCR — реалните от Yahoo. СИНТЕТИЧНО (означено): таблицата без запис за HON
(непотвърденият случай), записът "material": False, сериите на DD и AMCR (само коефициентът е реален), редовете {ticker}.
Пускане: python test_corp_action_below_one.py
"""
import sys, json, pathlib, io, contextlib, tempfile, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_corpb1_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import corp_actions as ca

H = json.loads((ROOT / "tests" / "fixtures" / "corp_actions_materiality_2026-10-13.json").read_text(encoding="utf-8"))["tickers"]["HON"]
ALL = {"HON": {"dates": [d for d, r in zip(H["dates"], H["splits"]) if r], "ratios": [r for r in H["splits"] if r], "close": pd.Series(H["close"], index=pd.to_datetime(H["dates"]))},
       "DD": {"dates": ["2026-06-24"], "ratios": [1 / 3], "close": pd.Series([40.0], index=pd.to_datetime(["2026-06-24"]))},          # СИНТЕТИЧНА серия, реален коефициент
       "AMCR": {"dates": ["2026-01-15"], "ratios": [0.2], "close": pd.Series([45.0], index=pd.to_datetime(["2026-01-15"]))}}
assert ALL["HON"]["ratios"] == [0.9535] and ALL["HON"]["dates"] == ["2026-06-29"]
KNOWN = copy.deepcopy(config.CORP_ACTIONS_KNOWN)


def ex(tickers, known):
    config.CORP_ACTIONS_KNOWN = known
    ca.reset()
    with contextlib.redirect_stdout(io.StringIO()):
        return ca.exclude([{"ticker": t} for t in tickers], "screener", "2026-10-13", fetch=lambda ts: {t: ALL[t] for t in ts if t in ALL})


print("── 1. непотвърден (СИНТЕТИЧНА таблица без HON) — изключен с 'нужна проверка' ──")
kept, out = ex(["HON", "DD", "AMCR"], {k: v for k, v in KNOWN.items() if k != "HON"})
assert [e["ticker"] for e in out] == ["HON"] and sorted(r["ticker"] for r in kept) == ["AMCR", "DD"]
t = out[0]["text"]
assert t.startswith("HON — изключена: корпоративно действие на 29.06 (коефициент 0.9535 — под 1 и не е проста дроб: вероятно отделяне, слято с обратен сплит) — нужна проверка")
print("  ✓", t[:170], "…")
print("  ✓ DD 1:3 и AMCR 1:5 — точни обратни сплитове, остават")

print()
print("── 2. потвърден в таблицата (реалният запис за HON) — текстът от таблицата, без 'нужна проверка' ──")
_, out2 = ex(["HON"], KNOWN)
assert out2[0]["text"].startswith("HON — изключена: отделяне на Honeywell Aerospace") and "нужна проверка" not in out2[0]["text"]
print("  ✓", out2[0]["text"][:120], "…")

print()
print("── 3. 'material': False (СИНТЕТИЧНО) — връща към маркера ──")
k3 = copy.deepcopy(KNOWN); k3["HON"] = {**k3["HON"], "material": False}
kept3, out3 = ex(["HON"], k3)
assert out3 == [] and kept3 == [{"ticker": "HON"}]
config.CORP_ACTIONS_KNOWN = KNOWN
assert ca.is_material("XYZ", 0.9535, "2026-06-29") and ca.needs_check("XYZ", 0.9535, "2026-06-29") and not ca.needs_check("HON", 0.9535, "2026-06-29")
assert not ca.is_material("DD", 1 / 3, "2026-06-24") and not ca.is_material("AMCR", 0.2, "2026-01-15")
print("  ✓ потвърден като несъществен → не се изключва; is_material/needs_check — и за книгите (същата функция)")
print()
print("Всички тестове минаха.")
