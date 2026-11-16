"""
16.11.2026 (пакет 16.11, т. 3): сурови имена на полета в AI текста на публичната страница — „sells_25pct_of_stake“ (13.11, ACN), „Съгласно setup_reason кодът определя“ (13.11, NDAQ),
„rs_status: near_high“ (16.11, NDAQ), „laggard persistence от 85%“ (16.11, разказът). Проверката (ai_brief._FIELD_RE в _fix_translit — всеки AI отговор минава оттам) маха
изречението цяло; записът — brief["ai_field_drops"]; на всяко извикване системата получава правилото FIELD_NAMES_RULE. Стойностите-кодове без кирилица („existing_position“)
не се пипат. Измерено върху 109 брифа: 2 070 български низа с име на поле, 56 различни имена — всичките полета от входа.

РЕАЛНО: tests/fixtures/ai_field_names_2026-11-16.json — AI полетата на ACN (наблюдаван, 13.11), NDAQ (картата, 13.11 и 16.11) и разказът от 16.11 (data/, изрязано 16.11.2026).
СИНТЕТИЧНО (означено): т. 3 — границите (URL, тикър с точка, код без кирилица, елемент от списък).
Пускане: python test_ai_field_names.py
"""
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_field_names_2026-11-16.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНО: ACN 13.11 (наблюдаван), NDAQ 13.11 и 16.11 (картата) ──")
ai_brief.FIELD_DROPS.clear()
with q():
    acn = ai_brief._fix_text(copy.deepcopy(FX["watch_13"]["ai"]), "наблюдаваните")
    nd13 = ai_brief._fix_text(copy.deepcopy(FX["card_13"]["ai"]), "картите")
    nd16 = ai_brief._fix_text(copy.deepcopy(FX["card_16"]["ai"]), "картите")
assert "sells_25pct_of_stake" not in json.dumps(acn) and "И двамата са в" not in acn["insider_read"] and acn["insider_read"].startswith("Налице е клъстер от продажби")
assert "Насреща: председателят" in acn["insider_read"]                                         # останалите изречения — непокътнати
w = nd13["why_now"]
assert "setup_reason" not in w and "rs_4w" not in w and "near_high" not in w and w.startswith("Setup-ът е чисто технически.")
assert "Финансовите борси и инфраструктурата за данни са относително защитен поджанр в слаба среда." in w
assert "rs_status" not in json.dumps(nd16, ensure_ascii=False) and "near_high" not in json.dumps(nd16, ensure_ascii=False)
fields = sorted({f for d in ai_brief.FIELD_DROPS for f in d["fields"]})
assert {"sells_25pct_of_stake", "setup_reason", "rs_4w", "near_high", "rs_status"} <= set(fields), fields
assert {d["section"] for d in ai_brief.FIELD_DROPS} == {"наблюдаваните", "картите"}
print(f"  ✓ махнати {len(ai_brief.FIELD_DROPS)} изречения; имена: {', '.join(fields)}")

print("── 2. РЕАЛНО: разказът от 16.11 — „laggard persistence от 85%“ ──")
ai_brief.FIELD_DROPS.clear()
with q():
    m = ai_brief._fix_text({"macro_brief": FX["macro_16"]}, "макро")
assert "laggard persistence" in FX["macro_16"] and "laggard persistence" not in m["macro_brief"]
assert "Секторната ротация за 4-те седмици е ясна" not in m["macro_brief"] and "За нас: водещите сектори" in m["macro_brief"]
assert len(m["macro_brief"].split("\n\n")) == len(FX["macro_16"].split("\n\n"))                  # абзаците остават
print(f"  ✓ махнато: «{ai_brief.FIELD_DROPS[0]['sentence'][:90]}…»")

print("── 3. СИНТЕТИЧНО: границите ──")
ai_brief.FIELD_DROPS.clear()
with q():
    r = ai_brief._fix_text({"watchlist_reason_type": "existing_position", "x": "Линк https://example.com/a_b_c към статията остава тук.",
                            "risks": ["Само rs_12w расте.", "Обемът е нисък при BRK.B и BF.B днес."], "y": "insider_cluster = true е сигнал. Второ изречение остава."}, "x")
assert r["watchlist_reason_type"] == "existing_position" and r["x"].startswith("Линк https://example.com/a_b_c")
assert r["risks"] == ["Обемът е нисък при BRK.B и BF.B днес."] and r["y"] == "Второ изречение остава."
print("  ✓ код без кирилица, URL, тикър с точка — остават; елемент само от такова изречение — пада; „x = true“ — пада")

print("── 4. правилото към модела и записът в брифа ──")
assert "Не пиши имена на полета" in ai_brief.FIELD_NAMES_RULE
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert '"system": system + FIELD_NAMES_RULE' in src
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"ai_field_drops": list(ai_brief.FIELD_DROPS)' in main and "ai_brief.FIELD_DROPS.clear()" in main
print("  ✓ системата на всяко извикване; brief[\"ai_field_drops\"]")
print("\n✅ test_ai_field_names: всичко мина")
