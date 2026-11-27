"""
27.11.2026 (уикенд пакет, т. 9): EPS изненадата — едно към едно или „основата е различна“; втори източник (Nasdaq), когато Yahoo няма отчетен EPS.
  • 25.11 в 07:30: „Нощта“ — DELL „EPS $2.35 срещу $6.55 очаквана (Nasdaq)“ при +1.2% след затварянето: различна основа (Nasdaq по-късно смени отчетения на $9.16, +39.85%).
  • 24.11: DKS и ANF в карето — „изненадата в EPS не е налична (Yahoo няма …)“; Nasdaq ги има (DKS $1.94 срещу $1.38, ANF $3.82 срещу $3.15).

РЕАЛНО: tests/fixtures/nasdaq_eps_2026-11-24.json — календарът на отчетите на Nasdaq за 24 и 25.11 (DKS, ANF, DELL, BBY), изтеглен на 27.11; DELL $2.35 / $6.55 — от брифа на 25.11.
СИНТЕТИЧНО (означено): празният отговор на Yahoo и отрицателният EPS.
Пускане: python run_tests.py test_eps_basis
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import qm_ep, overnight

FX = json.loads((ROOT / "tests" / "fixtures" / "nasdaq_eps_2026-11-24.json").read_text(encoding="utf-8"))
fetch = lambda d: FX["days"].get(d.isoformat(), {}).get("parsed", [])

print("── 1. различна основа ──")
assert qm_ep.eps_basis(2.35, 6.55) == "основата е различна (вероятно GAAP срещу коригирана) — изненадата не се смята"   # РЕАЛНО: DELL 25.11, 07:30
assert qm_ep.eps_basis(9.16, 6.55) is None and qm_ep.eps_basis(1.94, 1.38) is None                         # РЕАЛНО: Nasdaq по-късно; DKS
assert qm_ep.eps_basis(0.12, 0.05) is None                                                                 # СИНТЕТИЧНО: малки числа — без отношението
assert qm_ep.eps_basis(-0.10, 0.20) is not None                                                            # СИНТЕТИЧНО: противоположни знаци
row = overnight.company_row({"ticker": "DELL", "name": "Dell Technologies"}, {"eps": "$2.35", "eps_forecast": "$6.55"}, None, None, [], "2026-11-24")
assert row["lines"][0] == "EPS $2.35 срещу $6.55 очаквана (Nasdaq) — основата е различна (вероятно GAAP срещу коригирана) — изненадата не се смята" and row["eps"]["surprise"] is None
print(f"  ✓ «{row['lines'][0]}»")

print("── 2. РЕАЛНО: Nasdaq като втори източник (DKS, ANF — 24.11) ──")
dks = qm_ep.eps_surprise("DKS", "2026-11-23", rows=[], nasdaq_fn=fetch)                                    # СИНТЕТИЧНО: Yahoo — празно
assert dks == {"date": "2026-11-24", "reported": 1.94, "estimate": 1.38, "surprise_pct": 40.6, "source": "Nasdaq"}, dks
anf = qm_ep.eps_surprise("ANF", "2026-11-23", rows=[], nasdaq_fn=fetch)
assert (anf["reported"], anf["estimate"], anf["surprise_pct"]) == (3.82, 3.15, 21.3)
assert qm_ep.earnings_line(dks) == "отчет: EPS $1.94 срещу очаквани $1.38 (изненада +40.6%) (Nasdaq)"
none = qm_ep.eps_surprise("ZZZZ", "2026-11-23", rows=[], nasdaq_fn=fetch)
assert none["error"] == "Yahoo няма отчетен EPS за тази дата; Nasdaq няма отчетен EPS за тази дата"
assert qm_ep.eps_surprise("DKS", "2026-11-23", rows=[]).get("error") == "Yahoo няма отчетен EPS за тази дата"   # редове от теста без Nasdaq функция — без мрежа
assert qm_ep.eps_num("($0.12)") == -0.12
print(f"  ✓ «{qm_ep.earnings_line(dks)}»; ANF $3.82 срещу $3.15 (+21.3%)")
print("\n✅ test_eps_basis: всичко мина")
