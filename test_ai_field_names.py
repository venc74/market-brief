"""
16.11.2026 (пакет 16.11, т. 3): сурови имена на полета в AI текста на публичната страница — „sells_25pct_of_stake“ (13.11, ACN), „Съгласно setup_reason кодът определя“ (13.11, NDAQ),
„rs_status: near_high“ (16.11, NDAQ), „laggard persistence от 85%“ (16.11, разказът). Проверката (ai_brief._FIELD_RE в _fix_translit — всеки AI отговор минава оттам) маха
изречението цяло (от 17.11.2026, пакет 1, т. 3: само при НЕПОЗНАТО име; познатите — подменени с български термин, brief["ai_field_subs"]); записът — brief["ai_field_drops"]; на всяко извикване системата получава правилото FIELD_NAMES_RULE. Стойностите-кодове без кирилица („existing_position“)
не се пипат. Измерено върху 109 брифа: 2 070 български низа с име на поле, 56 различни имена — всичките полета от входа.

РЕАЛНО: tests/fixtures/ai_field_names_2026-11-16.json — AI полетата на ACN (наблюдаван, 13.11), NDAQ (картата, 13.11 и 16.11) и разказът от 16.11 (data/, изрязано 16.11.2026).
СИНТЕТИЧНО (означено): т. 3 — границите (URL, тикър с точка, код без кирилица, елемент от списък).
Пускане: python test_ai_field_names.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_field_names_2026-11-16.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНО: ACN 13.11 (наблюдаван), NDAQ 13.11 и 16.11 (картата) — от 17.11 познатите имена се подменят ──")
ai_brief.FIELD_DROPS.clear(); ai_brief.FIELD_SUBS.clear()
with q():
    acn = ai_brief._fix_text(copy.deepcopy(FX["watch_13"]["ai"]), "наблюдаваните")
    nd13 = ai_brief._fix_text(copy.deepcopy(FX["card_13"]["ai"]), "картите")
    nd16 = ai_brief._fix_text(copy.deepcopy(FX["card_16"]["ai"]), "картите")
assert "И двамата са в групата „продава ≥25% от дела си“." in acn["insider_read"] and "Насреща: председателят" in acn["insider_read"]
w = nd13["why_now"]
assert "води пазара с RS за 4 седмици 7.36 — силна секторна подкрепа" in w and "Съгласно причината за сетъпа кодът определя" in w
assert "rs_status" not in json.dumps(nd16, ensure_ascii=False) and "RS линията е близо до нов връх при RS рейтинг 73, а EPS ръст от 18.2%" in nd16["why_now"]   # EPS остава (16.11 падаше)
assert ai_brief.FIELD_DROPS == [] and {d["field"].strip() for d in ai_brief.FIELD_SUBS} >= {"sells_25pct_of_stake", "setup_reason", "rs_4w", "(rs_status: near_high)"}
print(f"  ✓ подменени {len(ai_brief.FIELD_SUBS)}, махнати 0 изречения; NDAQ 16.11 пази „EPS ръст от 18.2%“")

print("── 2. РЕАЛНО: разказът от 16.11 — „laggard persistence от 85%“ → „устойчивото изоставане от 85%“ ──")
ai_brief.FIELD_DROPS.clear()
with q():
    m = ai_brief._fix_text({"macro_brief": FX["macro_16"]}, "макро")
assert "laggard persistence" in FX["macro_16"] and "laggard persistence" not in m["macro_brief"] and "устойчивото изоставане от 85% и 100%" in m["macro_brief"]
assert "Секторната ротация за 4-те седмици е ясна" in m["macro_brief"] and ai_brief.FIELD_DROPS == []
assert len(m["macro_brief"].split("\n\n")) == len(FX["macro_16"].split("\n\n"))
print("  ✓ изречението остава, полето е на български")

print("── 3. СИНТЕТИЧНО: границите; непознато име — изречението пада ──")
ai_brief.FIELD_DROPS.clear()
with q():
    r = ai_brief._fix_text({"watchlist_reason_type": "existing_position", "x": "Линк https://example.com/a_b_c към статията остава тук.",
                            "risks": ["Само foo_bar_baz расте.", "Обемът е нисък при BRK.B и BF.B днес."], "y": "insider_cluster = true е сигнал. Второ изречение остава.",
                            "z": "Освен това volume_ratio 0.81× е под изисквания 1.5× праг."}, "x")
assert r["watchlist_reason_type"] == "existing_position" and r["x"].startswith("Линк https://example.com/a_b_c")
assert r["risks"] == ["Обемът е нисък при BRK.B и BF.B днес."] and r["y"] == "Второ изречение остава."
assert r["z"] == "Освен това обем 0.81× от средния е под изисквания 1.5× праг."                          # РЕАЛНОТО изречение от 09.10 (пример на Венци)
assert {f for d in ai_brief.FIELD_DROPS for f in d["fields"]} == {"foo_bar_baz", "insider_cluster"}
print("  ✓ код без кирилица, URL, тикър с точка — остават; „volume_ratio 0.81×“ → „обем 0.81× от средния“; непознато име / „x = true“ — изречението пада")

print("── 4. правилото към модела и записът в брифа ──")
assert "Не пиши имена на полета" in ai_brief.FIELD_NAMES_RULE
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert '"system": system + FIELD_NAMES_RULE' in src
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"ai_field_drops": list(ai_brief.FIELD_DROPS)' in main and "ai_brief.FIELD_DROPS.clear()" in main
assert '"ai_field_subs": list(ai_brief.FIELD_SUBS)' in main and "ai_brief.FIELD_SUBS.clear()" in main and "обем 0.81× от средния" in ai_brief.FIELD_NAMES_RULE
print("  ✓ системата на всяко извикване; brief[\"ai_field_drops\"]")
print("\n✅ test_ai_field_names: всичко мина")
