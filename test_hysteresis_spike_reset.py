"""
19.10.2026 · поправка на етап 1 (хистерезис по датата на данните): скок ДНЕС нулира брояча винаги, червен distribution day блокира веднага — и при "същата" дата. При прехода
състоянието от 16.10 пазеше ДАТАТА НА БРИФА (16.10); run-ът на 19.10 чете данни от 16.10 → "същият ден" → скокът на IEI/HYG (94.6. percentile) не нулира streak_below (остана 5).
Без поправката един спокоен ден (данните от 19.10, ако затворят под 90.) би освободил override-а веднага (5 + 1 = 6 ≥ 2) вместо на втория. Еднократно data/regime_override_state.json:
credit_spike → streak_below 0 (каквото трябваше да запише run-ът от 19.10).

РЕАЛНО: tests/fixtures/regime_override_state_2026-10-16.json (бот commit 9cf198d), tests/fixtures/brief_2026-10-19.json (IEI/HYG: +1.01%, 94.6. percentile, active; "в момента 2/2").
СИНТЕТИЧНО (маркирано): спокойният ден на 19.10 (данните за затварянето още ги няма), временният файл със състоянието, червеният ден за блока.
Пускане: python test_hysteresis_spike_reset.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import thermometer as th

ST16 = json.loads((ROOT / "tests" / "fixtures" / "regime_override_state_2026-10-16.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
cr = next(i for i in B19["thermometer"]["indicators"] if i["name"].startswith("IEI/HYG"))
assert ST16["credit_spike"] == {"streak_below": 5, "last_date": "2026-10-16"} and cr["spike"] and cr["as_of"] == "2026-10-16" and "в момента 2/2" in B19["thermometer"]["exit_rule"]
quiet = lambda: contextlib.redirect_stdout(io.StringIO())
f = pathlib.Path(tempfile.mkdtemp()) / "state.json"
orig = th._OVERRIDE_STATE_FILE; th._OVERRIDE_STATE_FILE = f
try:
    f.write_text(json.dumps(ST16))
    with quiet():
        assert th._hysteresis_effective("credit_spike", True, "2026-10-16") == (True, 0)                     # run-ът на 19.10 с поправката: скокът нулира
        assert th._hysteresis_effective("credit_spike", False, "2026-10-19") == (True, 1)                    # СИНТЕТИЧНО: спокоен 19.10 → още държи (1/2)
    f.write_text(json.dumps(ST16))
    with quiet():
        assert th._hysteresis_effective("credit_spike", False, "2026-10-19") == (False, 6)                   # без корекцията на състоянието: освободен още на първия спокоен ден
    f.write_text(json.dumps({"distribution_block": {"blocked": False, "streak_nonred": 0, "last_date": "2026-10-16", "seed": {"version": 99}}}))
    with quiet():
        b = th._distribution_block({"status": "red", "as_of": "2026-10-16"}, "2026-10-16")
    assert b["blocked"] and b["kind"] == "red"                                                                # СИНТЕТИЧНО: червен ден при "същата" дата → блок веднага
finally:
    th._OVERRIDE_STATE_FILE = orig
print("  ✓ скок при 'същата' дата нулира (5 → 0); след корекцията спокоен 19.10 държи override-а (1/2), без нея — освобождава (6); червен distribution day — блок веднага")
print("\n✅ test_hysteresis_spike_reset: всичко мина")
