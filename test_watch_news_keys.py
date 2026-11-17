"""
17.11.2026 (пакет 1, т. 4): новините на HONA (Honeywell Aerospace, отделена от Honeywell) се търсят по „Honeywell Aerospace“, не по „Honeywell“ — първата дума хващаше и
заглавията за HON. Правилото (watch_monitor.company_keys): първата дума на името е ключ САМО ако не е първа дума и на друга компания (универсът и другите наблюдавани).

РЕАЛНО: tests/fixtures/watch_news_keys_2026-11-17.json — имената на 6-те наблюдавани и на универса от 17.11 (HON = „Honeywell Technologies“ по Wikipedia).
СИНТЕТИЧНО (означено): т. 2 — заглавията.
Пускане: python test_watch_news_keys.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import watch_monitor as wm

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_news_keys_2026-11-17.json").read_text(encoding="utf-8"))
U, W = FX["universe_names"], FX["watch_names"]
others = lambda t: [v for k, v in {**U, **W}.items() if k != t]

print("── 1. РЕАЛНО: ключовете на 6-те наблюдавани ──")
keys = {t: wm.company_keys(n, others(t)) for t, n in W.items()}
assert keys["HONA"] == {"Honeywell Aerospace"} and U["HON"] == "Honeywell Technologies"
assert keys["ACN"] == {"Accenture"} and keys["SIRI"] == {"Sirius XM", "Sirius"} and keys["AI"] == {"C3.ai"}
assert [t for t in W if len(keys[t]) == 1 and " " in next(iter(keys[t]))] == ["HONA"]                     # само HONA губи първата дума
assert wm.company_keys("Honeywell Aerospace Inc.") == {"Honeywell", "Honeywell Aerospace"}                     # без другите имена — както до 17.11
print(f"  ✓ HONA → {sorted(keys['HONA'])}; останалите — както досега")

print("── 2. СИНТЕТИЧНО: заглавие за Honeywell (HON) не е за HONA; за Honeywell Aerospace — е ──")
assert wm.about_company("HONA", keys["HONA"], "Honeywell raises full-year outlook on building automation demand") is None
assert wm.about_company("HONA", keys["HONA"], "Honeywell Aerospace wins engine contract") == "name"
assert wm.about_company("HONA", keys["HONA"], "Spin-off watch: HONA shares debut") == "ticker"
print("  ✓ „Honeywell raises…“ — не; „Honeywell Aerospace wins…“ — да; тикърът — да")
src = (ROOT / "src" / "watch_monitor.py").read_text(encoding="utf-8")
assert 'company_keys(f.get("name"), _other_names(tk, _watch_names))' in src
print("\n✅ test_watch_news_keys: всичко мина")
