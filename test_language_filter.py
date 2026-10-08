"""
Пакет 2 (2026-10-05) · езиков филтър: soft hyphen (U+00AD) се маха от AI текстовете; "marginalen" и "expозиция" (видени на 05.10) се логват поименно, без замяна.

РЕАЛНО: трите реални фрагмента от cross тезите на брифа от 05.10.2026 (tests/fixtures/brief_2026-10-05.json): "ви­соки разходи" (soft hyphen насред думата),
"…marginalen P&L ефект…", "…тикъри без материална … expозиция." и "…точно типа expозиция, концентрирана…"; броят им в историята (1 / 1 / 19 — измерено на 05.10,
не се проверява тук). СИНТЕТИЧНО: границите (дума в друга дума, главни букви, soft hyphen в чисто латински низ, вложени структури).
Пускане: python test_language_filter.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import ai_brief

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
TEXTS = [c["cross_sector_thesis"]["reasoning"] for c in B05["cot"] if c.get("cross_sector_thesis")]
shy = next(t for t in TEXTS if "­" in t)
marg = next(t for t in TEXTS if "marginalen" in t)
expo = [t for t in TEXTS if "expозиция" in t]
assert len(expo) == 2


def run(obj):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai_brief._parse_json(json.dumps(obj, ensure_ascii=False))
    return out, buf.getvalue()


print("── soft hyphen ──")
out, log = run({"t": shy})
assert "­" not in out["t"] and "високи разходи за рефинансиране" in out["t"] and out["t"] == shy.replace("­", "")
assert "премахнат soft hyphen (U+00AD) ×1" in log and "ви·соки" in log
print("  ✓ РЕАЛНО: 'ви­соки разходи за рефинансиране' → 'високи разходи…'; един ред в лога с контекста")
out, log = run({"a": ["x­­y", {"b": "само латиница­"}], "n": 5, "e": ""})
assert out == {"a": ["xy", {"b": "само латиница"}], "n": 5, "e": ""} and "×2" in log
out, log = run({"t": "чист текст без нищо"})
assert "soft hyphen" not in log
print("  ✓ СИНТЕТИЧНО: вложени списъци/речници, два символа, низ без кирилица; чист текст не дава лог")

print()
print("── известни дефекти: само лог ──")
out, log = run({"t": marg})
assert out["t"] == marg                                                                  # текстът не се пипа
assert "известен езиков дефект 'marginalen' (трябва 'маргинален')" in log and "USD/GBP движението би имало marginalen P&L ефект" in log
_orig_vocab = ai_brief._bg_vocab
ai_brief._bg_vocab = lambda: ({}, {})                                                    # без речник от историята (изключен/липсва) — старото поведение: само лог
out, log = run({"t": expo[0], "u": expo[1]})
ai_brief._bg_vocab = _orig_vocab
assert out["t"] == expo[0] and out["u"] == expo[1]
assert log.count("известен езиков дефект 'expозиция' (трябва 'експозиция')") == 2 and "смесена дума 'expозиция'" in log      # и общият лог за хибриди остава
print("  ✓ РЕАЛНО: 'marginalen' (USD/GBP тезата) и двете 'expозиция' от 05.10 → ред 'известен езиков дефект … (трябва …)' с контекст; текстът остава непроменен;")
print("    общият лог за смесени думи на 'expозиция' също е там")
out, log = run({"t": "Marginalen и MARGINALEN, но не remarginalenx и не marginalenки"})
assert log.count("известен езиков дефект") == 2 and out["t"].startswith("Marginalen и MARGINALEN")
out, log = run({"t": "нормален текст с експозиция и маргинален ефект"})
assert "известен езиков дефект" not in log
print("  ✓ СИНТЕТИЧНО: регистърът не пречи (Marginalen, MARGINALEN), думи, в които е вградено, не се броят; правилните 'експозиция', 'маргинален' не се логват")
print()
print("Всички тестове минаха.")
