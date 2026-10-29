"""
29.10.2026 · regime_claims: грешен брой distribution days в макро текста — код "dd_count"; изречението се заменя с реда на кода („По кода: distribution days SPY 6/9, QQQ 7/9 —
при 9 Offensive се блокира (липсват 2).“), следващите такива се махат. Проверяват се броят („SPY 6/9“, „7/9 за QQQ“, „SPY под 9 (сега 7/9“) и колко липсват до прага („за SPY липсват 2“,
„липсват 2 при SPY, 3 при QQQ“, „за QQQ — само 2“; „липсват 2“ без тикър — вярно, ако е така за SPY или за QQQ); условното („ако SPY стигне 8/9 …“) не се проверява.

Случаят (РЕАЛЕН): 29.10 — „Distribution days са натрупани (SPY 6/9, QQQ 7/9) — при достигане на 9 Offensive се блокира и за SPY липсват само 2, за QQQ — само 2; …“ (за SPY липсват 3).
Измерено върху всичките брифове с реда „Запас до смяна на режима“ (15.10–29.10; 17 изречения с distribution days): 1 попадение — този, 0 фалшиви (верните 16.10 „липсват 2 при SPY,
3 при QQQ“, 21.10 „сега 7/9, липсват 2“, 22.10 „сега 6/9 — липсват 3“, 26.10 „липсват само 2 дни“ остават).

РЕАЛНО: tests/fixtures/dd_count_2026-10-29.json — термометърът и текстовете от 29.10; tests/fixtures/dd_claims_2026-10-28.json — 16.10–28.10.
СИНТЕТИЧНО (означено): изреченията в т. 3.
Пускане: python test_dd_count_claims.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import regime_claims as rc, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "dd_count_2026-10-29.json").read_text(encoding="utf-8"))
OLD = json.loads((ROOT / "tests" / "fixtures" / "dd_claims_2026-10-28.json").read_text(encoding="utf-8"))["briefs"]
LINE = "distribution days SPY 6/9, QQQ 7/9 — при 9 Offensive се блокира (липсват 2)"

print("── 1. РЕАЛНИЯТ текст от 29.10 ──")
f = rc.facts(FX["thermometer"])
assert f["dd"]["line"] == LINE and f["dd"]["counts"] == {"SPY": 6, "QQQ": 7} and f["dd"]["red"] == 9 and not f["dd"]["blocking"]
assert (FX["distribution_days"]["spy_count"], FX["distribution_days"]["qqq_count"]) == (6, 7)
bad = next(s for s in rc._sentences(FX["regime_comment"]) if "за SPY липсват само 2" in s)
probs = [p for p in rc.check_sentence(bad, f) if p["code"] == "dd_count"]
assert len(probs) == 1 and "за SPY липсват 2, а по кода 3 (SPY 6/9)" in probs[0]["why"]
new, problems = rc.clean(FX["regime_comment"], f)
assert bad not in new and f"По кода: {LINE}." in new and new.count("По кода:") == 1
assert "две distribution days или един нов червен индикатор" in new                                     # „две“ (QQQ 7/9) — без число до тикър, остава
print(f"  ✓ «…за SPY липсват само 2, за QQQ — само 2…» → «По кода: {LINE}.»")

print()
print("── 2. РЕАЛНИТЕ текстове 16.10–28.10: нито едно попадение ──")
for d, b in OLD.items():
    fd = rc.facts(b["thermometer"])
    for k in ("macro_brief", "regime_comment"):
        assert not [p for p in rc.check(b[k], fd) if p["code"] == "dd_count"], (d, k)
assert "(липсват 2 при SPY, 3 при QQQ)" in OLD["2026-10-16"]["regime_comment"] and "липсват само 2 дни" in OLD["2026-10-26"]["regime_comment"]
print(f"  ✓ {len(OLD)} брифа — верните („липсват 2 при SPY, 3 при QQQ“ на 16.10, „липсват само 2 дни“ на 26.10) не се пипат")

print()
print("── 3. формите (СИНТЕТИЧНИ изречения, броят от 29.10: SPY 6, QQQ 7) ──")
dd = f["dd"]
for s, n in (("Distribution days 7/9 за SPY и 7/9 за QQQ.", 1),
             ("Distribution days SPY под 9 (сега 7/9, липсват 2).", 1),
             ("Distribution days SPY 6/9, QQQ 7/9 (липсват 3 при SPY, 2 при QQQ).", 0),
             ("Distribution days SPY 6/9, QQQ 7/9 (липсват 3 при SPY, 3 при QQQ).", 1),
             ("Distribution days: до блокажа липсват само 2 дни.", 0),
             ("Distribution days: до блокажа липсват само 4 дни.", 1),
             ("Ако SPY стигне 8/9 distribution days, остава 1.", 0),
             ("SPY 5/9 сесии нагоре при обем над средния.", 0)):
    assert len(rc.dd_count_problems(s, dd)) == n, (s, rc.dd_count_problems(s, dd))
print("  ✓ брой до тикъра, „сега N/9“, „липсват N при …“, без тикър, условното, изречение без distribution days")

print()
print("── 4. от 29.10 не се прилага в main (29.10.2026 (разходката, т. 5): абзацът за режима и тази проверка в макро текста са махнати — macro_and_sector_brief вече не вика regime_claims.clean) ──")
assert not hasattr(ai_brief, "_apply_regime_claims") and "regime_claims.clean(" not in (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
print("  ✓ функцията остава в regime_claims (т. 1–3), макро текстът не минава през нея")
print("\n✅ test_dd_count_claims: всичко мина")
