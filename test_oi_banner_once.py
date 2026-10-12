"""
12.10.2026 · един банер за липсваща OI снимка, не два.

Случаят (РЕАЛЕН, брифът от 12.10): "Unusual options: за нито един кандидат няма съотношение обем/OI (следобедната OI снимка за сесията 09.10 липсва) …" (source unusual_options)
и "Здравна проверка: OI снимката за сесията 09.10 липсва (последна: 08.10) …" (source health:oi_snapshot) — едно и също два пъти. Остава здравната проверка (по-конкретна:
последната снимка и кой job да се провери), с добавеното "липсващ UOV✓ НЕ значи нормален обем" от другия банер.

РЕАЛНО: tests/fixtures/oi_banner_2026-10-12.json (uov_diag, health и data_warnings от брифа на 12.10). СИНТЕТИЧНО (означено): uov_diag без липсваща снимка (с налична снимка,
но без съотношения), временната директория за здравната проверка.
Пускане: python test_oi_banner_once.py
"""
import sys, json, pathlib, tempfile, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import data_warnings, health_monitor

FX = json.loads((ROOT / "tests" / "fixtures" / "oi_banner_2026-10-12.json").read_text(encoding="utf-8"))
U, H = FX["uov_diag"], FX["health"]

print("── 1. брифът от 12.10 имаше два банера за една причина ──")
src = [w["source"] for w in FX["data_warnings"]]
assert src == ["unusual_options", "health:oi_snapshot"] and "09.10 липсва" in FX["data_warnings"][0]["message"] and "09.10 липсва" in FX["data_warnings"][1]["message"]
print("  ✓ РЕАЛНО:", " | ".join(w["message"][:60] + "…" for w in FX["data_warnings"]))

print()
print("── 2. сега — един ──")
w = data_warnings.collect(None, None, uov_diag=U, health=H)
assert [x["source"] for x in w] == ["health:oi_snapshot"]
print("  ✓ същите РЕАЛНИ uov_diag и health → само", w[0]["source"])
w_no_health = data_warnings.collect(None, None, uov_diag=U)
assert [x["source"] for x in w_no_health] == ["unusual_options"]                                    # без здравна проверка (напр. изключена) UOV банерът остава
u2 = copy.deepcopy(U); u2["snapshot_missing_reason"] = ""; u2["missing"] = {"A": "снимката е в стария формат"}   # СИНТЕТИЧНО: снимката е налице, съотношения няма по друга причина
assert [x["source"] for x in data_warnings.collect(None, None, uov_diag=u2, health=H)] == ["unusual_options", "health:oi_snapshot"]
print("  ✓ без здравната проверка — UOV банерът остава; съотношения няма по ДРУГА причина (СИНТЕТИЧНО) — и двата, защото казват различни неща")

print()
print("── 3. текстът на здравната проверка носи и предупреждението на UOV ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_oiban_")
d = pathlib.Path(tmp.name)
(d / "unusual_options_oi_snapshot.json").write_text(json.dumps({"snapshots": {"2026-10-08": {"session_date": "2026-10-08"}}}))   # СИНТЕТИЧНО: последна снимка 08.10, както на 12.10
iss = [i for i in health_monitor.check("2026-10-12", d) if i["check"] == "oi_snapshot"]
assert iss and iss[0]["message"].startswith("OI снимката за сесията 09.10 липсва (последна: 08.10)") and "липсващ UOV✓ НЕ значи нормален обем" in iss[0]["message"]
print("  ✓", iss[0]["message"])
print()
print("Всички тестове минаха.")
