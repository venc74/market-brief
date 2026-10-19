"""
19.10.2026 · етап 2, т. 17б: "Moves" брои МЕНИДЖЪРИ, не редове. Мениджър с два реда за един тикър (два класа акции с едно име — Alphabet) се броеше два пъти: GOOGL "5 мениджъра" при 4.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — редът GOOGL в superinvestor_moves (count 5, мениджъри 4: Berkshire, Baupost, TCI, Third Point); в историята 356 такива реда.
СИНТЕТИЧНО (маркирано): редовете за дедупа (стойности), понеже брифът пази само слетия ред.
Пускане: python test_moves_manager_count.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import dataroma

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
g = next(r for r in B19["superinvestor_moves"] if r["ticker"] == "GOOGL")
assert g["count"] == 5 and len(g["managers"]) == 4                                                       # какво казваше брифът
rows = [{"ticker": "GOOGL", "manager": m, "value": v, "company": "ALPHABET INC"} for m, v in zip(g["managers"] + [g["managers"][0]], (10.0, 9.0, 8.0, 7.0, 6.0))]   # СИНТЕТИЧНО: 5 реда, 4 мениджъра
m = dataroma._dedupe_by_ticker(rows)
assert len(m) == 1 and m[0]["count"] == 4 and m[0]["managers"] == g["managers"]
one = dataroma._dedupe_by_ticker([{"ticker": "X", "manager": "M", "value": 1.0, "late": "⚠ закъснява: последен 13F …"}, {"ticker": "X", "manager": "M", "value": 2.0, "late": "⚠ закъснява: последен 13F …"}])
assert one[0]["count"] == 1 and one[0]["late"] == "⚠ закъснява: последен 13F …"                         # един мениджър с два реда — пълният етикет, не "закъснява: M"
print("  ✓ GOOGL: 4 мениджъра (в брифа на 19.10: 5); един мениджър с два реда — count 1 и пълният етикет за давност")
print("\n✅ test_moves_manager_count: всичко мина")
