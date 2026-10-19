"""
19.10.2026 · етап 2, т. 4: изходът от override-а казваше "(хистерезис — в момента 2/2)" при АКТИВЕН скок — четеше се като "2 дни в скока". Сега "дни под прага: X/2",
а скок ДНЕС нулира брояча винаги (дедупликират се само спокойните дни). Причината за "2/2" на 19.10: от етап 1 броячът върви по датата на данните, а състоянието от 16.10
пазеше ДАТАТА НА БРИФА (16.10); данните на 19.10 са от петък 16.10 → "същият ден" → streak_below остана 5 (от спокойните дни до 16.10). Същото за блока от distribution days:
червен ден блокира веднага и при "същата" дата. Плюс "Регимът" → "Режимът".

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — индикаторите и макрото от брифа на 19.10 (IEI/HYG +1.0% за 10д, 95. percentile — активен; в брифа "в момента 2/2");
tests/fixtures/regime_override_state_2026-10-16.json — data/regime_override_state.json от бот commit-а на 16.10 (9cf198d): credit_spike streak_below 5, last_date 2026-10-16.
СИНТЕТИЧНО (маркирано): червеният ден за блока (статусът е подменен), спокойният повторен ден.
Пускане: python test_override_days_below.py
"""
import sys, json, pathlib, tempfile, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import thermometer as th

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
STATE16 = json.loads((ROOT / "tests" / "fixtures" / "regime_override_state_2026-10-16.json").read_text(encoding="utf-8"))
IND = {i["name"]: i for i in B19["thermometer"]["indicators"]}
quiet = lambda: contextlib.redirect_stdout(io.StringIO())
assert STATE16["credit_spike"] == {"streak_below": 5, "last_date": "2026-10-16"}
assert "в момента 2/2" in B19["thermometer"]["exit_rule"] and B19["thermometer"]["overrides"][0]["state"] == "active"       # какво казваше брифът


def run(prior):
    saved = {n: getattr(th, n) for n in ("spy_trend", "vix_level", "market_put_call", "move_index", "vix_term_structure", "credit_spread_proxy", "market_breadth", "_breadth_divergence")}
    th.spy_trend = lambda: dict(IND["SPY тренд"]); th.vix_level = lambda: dict(IND["VIX"]); th.market_put_call = lambda: dict(IND["Put/Call (SPY)"])
    th.move_index = lambda: dict(IND["MOVE (Bond Vol)"]); th.vix_term_structure = lambda: dict(IND["VIX Term Structure"])
    th.credit_spread_proxy = lambda: dict(IND["IEI/HYG (Credit Spread)"]); th.market_breadth = lambda: dict(IND["Market Breadth (% над 40dMA)"])
    th._breadth_divergence = lambda _i: None
    orig = th._OVERRIDE_STATE_FILE
    with tempfile.TemporaryDirectory() as tmp:
        th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "state.json"
        th._OVERRIDE_STATE_FILE.write_text(json.dumps(prior))
        try:
            with quiet():
                t = th.build_thermometer(B19["macro"], today=dt.date(2026, 10, 19))
            return t, json.loads(th._OVERRIDE_STATE_FILE.read_text())
        finally:
            th._OVERRIDE_STATE_FILE = orig
            for n, f in saved.items():
                setattr(th, n, f)


print("── 1. 19.10: активен IEI/HYG при състояние от 16.10 (РЕАЛНИ) ──")
t, st = run(STATE16)
ov = {o["trigger"]: o for o in t["overrides"]}
assert ov["IEI/HYG"]["state"] == "active" and t["regime"] == "Defensive"
assert "дни под прага: 0/2" in ov["IEI/HYG"]["exit_condition"] and "в момента" not in ov["IEI/HYG"]["exit_condition"] and "дни под прага: 0/2" in t["exit_rule"]
assert st["credit_spike"]["streak_below"] == 0
print("  ✓ 'хистерезис — дни под прага: 0/2' (в брифа: 'в момента 2/2'); броячът е нулиран от скока, режимът — същият Defensive")

print()
print("── 2. спокоен ден със същата дата не се брои втори път (СИНТЕТИЧНО) ──")
th_file = pathlib.Path(tempfile.mkdtemp()) / "s.json"
orig = th._OVERRIDE_STATE_FILE; th._OVERRIDE_STATE_FILE = th_file
try:
    th_file.write_text(json.dumps({"credit_spike": {"streak_below": 1, "last_date": "2026-10-16"}}))
    with quiet():
        assert th._hysteresis_effective("credit_spike", False, "2026-10-16") == (True, 1)       # същата дата, спокоен → не се брои
        assert th._hysteresis_effective("credit_spike", False, "2026-10-19") == (False, 2)      # нова дата → +1 → освободен
        assert th._hysteresis_effective("credit_spike", True, "2026-10-19") == (True, 0)        # скок при същата дата → нулира
    th_file.write_text(json.dumps({"distribution_block": {"blocked": False, "streak_nonred": 0, "last_date": "2026-10-16", "seed": {"version": 99}}}))
    with quiet():
        b = th._distribution_block({"status": "red", "as_of": "2026-10-16"}, "2026-10-16")
    assert b["blocked"] and b["kind"] == "red"                                                   # червен ден при "същата" дата → блокира веднага (СИНТЕТИЧНО)
finally:
    th._OVERRIDE_STATE_FILE = orig
print("  ✓ спокоен ден при същата дата — 1 (не 2); нова дата — освободен; скок при същата дата — 0; червен ден при същата дата — блок веднага")

src = (ROOT / "src" / "thermometer.py").read_text(encoding="utf-8")
assert "Регимът" not in src and "Режимът в момента се определя от броенето" in src
print("  ✓ 'Режимът в момента се определя от броенето' (беше 'Регимът')")
print("\n✅ test_override_days_below: всичко мина")
