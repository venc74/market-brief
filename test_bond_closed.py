"""
12.11.2026 (т. 3, Veterans Day 11.11): в ден без търговия на облигации (SIFMA — пълно затваряне), в който NYSE търгува, облигационните плочки на термометъра (MOVE, 2Y/10Y,
SOFR − IORB, HY / IG OAS) са със стойност от предишен ден, а изглеждат свежи → етикет „облигационният пазар беше затворен (11.11) — стойността е от 10.11“. Брифът от 12.11:
MOVE и 2Y/10Y — към 10.11, SOFR − IORB и HY / IG OAS — към 09.11 (обичайното им закъснение от ден + празника).

РЕАЛНО: tests/fixtures/thermo_macro_2026-11-12.json — термометърът и макрото на брифа от 12.11 (data/2026-11-12.json, изрязано 12.11.2026);
tests/fixtures/bond_tiles_asof_2026-10-16_11-12.json — датите на SPY и на облигационните плочки във всичките 19 брифа с дата на данните (16.10–12.11, събрано 12.11.2026);
tests/fixtures/brief_2026-10-19.json — рамката на страницата. Списъкът config.SIFMA_US_FULL_CLOSES — от sifma.org (holiday schedule, 2026 и 2027), проверен 12.11.2026.
СИНТЕТИЧНО (означено): т. 3 — Columbus Day 12.10 (датите — по реалния случай от коментара в thermometer.py: ^MOVE без бар за 12.10, брифът от 13.10 чете 09.10; в брифа от 13.10
плочките още нямат дата); подменените функции на индикаторите за build_thermometer; скрита плочка; временният файл със състоянието.
Пускане: python test_bond_closed.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bond_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, render, ai_brief

FXD = ROOT / "tests" / "fixtures"
R = json.loads((FXD / "thermo_macro_2026-11-12.json").read_text(encoding="utf-8"))
HIST = json.loads((FXD / "bond_tiles_asof_2026-10-16_11-12.json").read_text(encoding="utf-8"))["briefs"]
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. списъкът на SIFMA: дните без облигации, в които NYSE търгува ──")
from src import sessions
bond_only = sorted(d for d in config.SIFMA_US_FULL_CLOSES if sessions.is_session(d))
assert bond_only == ["2026-10-12", "2026-11-11", "2027-10-11", "2027-11-11"], bond_only
assert "2026-04-03" not in config.SIFMA_US_FULL_CLOSES                                   # Добрият петък 2026 — само ранно затваряне (12:00 ET)
print("  ✓ Columbus Day и Veterans Day 2026–2027; останалите празници на SIFMA са и на NYSE")

print("── 2. РЕАЛНО: брифът от 12.11 — четирите плочки ──")
assert th.bond_closed_note("2026-11-10", "2026-11-11")["text"] == "облигационният пазар беше затворен (11.11) — стойността е от 10.11"
assert th.bond_closed_note("2026-11-09", "2026-11-11")["text"] == "облигационният пазар беше затворен (11.11) — стойността е от 09.11"
assert th.bond_closed_note("2026-11-11", "2026-11-11") is None and th.bond_closed_note(None, "2026-11-11") is None
inds = copy.deepcopy(R["thermometer"]["indicators"])
next(i for i in inds if i["name"] == "2Y/10Y спред")["as_of"] = R["macro"]["spread_2s10s"]["as_of"]       # до 12.11 плочката беше без дата (тя е в макрото)
marked = th.mark_bond_closed(inds, "2026-11-11")
assert marked == ["2Y/10Y спред", "SOFR − IORB (финансиране)", "MOVE (Bond Vol)", "HY / IG OAS (кредитни спредове)"], marked
by = {i["name"]: i for i in inds}
assert by["MOVE (Bond Vol)"]["bond_closed"]["text"].endswith("стойността е от 10.11") and by["HY / IG OAS (кредитни спредове)"]["bond_closed"]["value_from"] == "2026-11-09"
assert not any("bond_closed" in by[n] for n in ("IEI/HYG (Credit Spread)", "Fed Net Liquidity", "SPY тренд"))   # IEI/HYG са ETF-и — търгуваха на 11.11; Net Liquidity — седмична
print("  ✓ " + "\n  ✓ ".join(f"{n}: {by[n]['bond_closed']['text']}" for n in marked))

print("── 3. СИНТЕТИЧНО (по реалния случай): Columbus Day 12.10, скрита плочка ──")
assert th.bond_closed_note("2026-10-09", "2026-10-12")["text"] == "облигационният пазар беше затворен (12.10) — стойността е от 09.10"      # брифът от 13.10
assert th.bond_closed_note("2026-10-09", "2026-10-09") is None                            # брифът от 12.10 — денят на пазара е петък 09.10
assert th.bond_closed_note("2026-11-25", "2026-11-27") is None                            # Thanksgiving 26.11 — затворени и двата пазара
hid = [{"name": "MOVE (Bond Vol)", "as_of": "2026-11-10", "hide": True}]
assert th.mark_bond_closed(hid, "2026-11-11") == [] and "bond_closed" not in hid[0]
print("  ✓ 13.10: „(12.10) — стойността е от 09.10“; 12.10 и Thanksgiving — без етикет; скрита плочка — без етикет")

print("── 4. РЕАЛНО: цялата история с дати (19 брифа, 16.10–12.11) — само 12.11 ──")
fired = {}
for b in HIST:
    tiles = [{"name": n, **v} for n, v in b["tiles"].items()]
    m = th.mark_bond_closed(tiles, b["spy_as_of"])
    if m:
        fired[b["brief"]] = m
assert list(fired) == ["2026-11-12"] and len(fired["2026-11-12"]) == 4, fired
lagged = sum(1 for b in HIST for v in b["tiles"].values() if v["as_of"] and v["as_of"] < b["spy_as_of"])
assert lagged > 20                                                                        # обичайното закъснение на SOFR / OAS — без етикет
print(f"  ✓ 19 брифа: етикет само на 12.11 (4 плочки); {lagged} плочки с обичайното закъснение — без етикет")

print("── 5. build_thermometer: 2Y/10Y получава датата, етикетът е в индикаторите ──")
IND = {i["name"]: dict(i) for i in R["thermometer"]["indicators"]}
names = ("spy_trend", "vix_level", "market_put_call", "move_index", "vix_term_structure", "credit_spread_proxy", "market_breadth", "_breadth_divergence", "equal_weight_vs_cap")
saved = {n: getattr(th, n) for n in names}
th.spy_trend = lambda: dict(IND["SPY тренд"]); th.vix_level = lambda: dict(IND["VIX"]); th.market_put_call = lambda: dict(IND["Put/Call (SPY)"])
th.move_index = lambda: dict(IND["MOVE (Bond Vol)"]); th.vix_term_structure = lambda: dict(IND["VIX Term Structure"])
th.credit_spread_proxy = lambda: dict(IND["IEI/HYG (Credit Spread)"]); th.market_breadth = lambda: dict(IND["Market Breadth (% над 40dMA)"]); th._breadth_divergence = lambda _i: None
th.equal_weight_vs_cap = lambda: dict(IND["RSP спрямо SPY (широчина)"])
orig = th._OVERRIDE_STATE_FILE
try:
    th._OVERRIDE_STATE_FILE = pathlib.Path(_tmp.name) / "s.json"
    with contextlib.redirect_stdout(io.StringIO()) as log:
        t = th.build_thermometer(R["macro"], today=dt.date(2026, 11, 12))
finally:
    th._OVERRIDE_STATE_FILE = orig
    for n, f in saved.items():
        setattr(th, n, f)
tb = {i["name"]: i for i in t["indicators"]}
assert tb["2Y/10Y спред"]["as_of"] == "2026-11-10" and tb["2Y/10Y спред"]["bond_closed"]["text"] == "облигационният пазар беше затворен (11.11) — стойността е от 10.11"
assert sorted(n for n, i in tb.items() if i.get("bond_closed")) == sorted(marked)
assert t["regime"] == R["thermometer"]["regime"] and t["counts"] == R["thermometer"]["counts"]      # режимът и броенето — същите
assert "[thermo] облигационният пазар беше затворен — етикет върху:" in log.getvalue()
ctx = {r["name"]: r for r in ai_brief._thermo_context(t)}
assert ctx["MOVE (Bond Vol)"]["note"] == "облигационният пазар беше затворен (11.11) — стойността е от 10.11" and "note" not in ctx["VIX"]
print("  ✓ четирите плочки с етикет; режимът и броенето — без промяна; контекстът за AI носи бележката")

print("── 6. страницата ──")
bb = copy.deepcopy(B19); bb["thermometer"] = t
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert page.count("⚠ облигационният пазар беше затворен (11.11) — стойността е от 10.11") == 2 and page.count("⚠ облигационният пазар беше затворен (11.11) — стойността е от 09.11") == 2
i_move, i_vix = page.index('<div class="t-name">MOVE (Bond Vol)</div>'), page.index('<div class="t-name">VIX Term Structure</div>')
assert i_move < page.index("стойността е от 10.11", i_move) < i_vix                   # етикетът е в плочката на MOVE
bb["thermometer"] = R["thermometer"]
with contextlib.redirect_stdout(io.StringIO()):
    old = render.render_dashboard(bb, publish=False)
assert "облигационният пазар беше затворен" not in old                                    # записан бриф без полето — без етикет
print("  ✓ етикетът е в плочките (2 × „от 10.11“, 2 × „от 09.11“); стар бриф — без него")
print("── 7. здравната проверка: списъкът на SIFMA свършва ──")
from src import health_monitor as hm
src_hm = (ROOT / "src" / "health_monitor.py").read_text(encoding="utf-8")
assert '"check": "bond_holidays"' in src_hm and "max(int(h[:4]) for h in config.SIFMA_US_FULL_CLOSES)" in src_hm
with contextlib.redirect_stdout(io.StringIO()):
    now = hm.check("2026-11-12", resolution={"ok": True, "live": 0}, glb_status={"ok": True})
    late = hm.check("2027-11-15", resolution={"ok": True, "live": 0}, glb_status={"ok": True})
assert "bond_holidays" not in {i["check"] for i in now}
bh = [i for i in late if i["check"] == "bond_holidays"]
assert len(bh) == 1 and "покрива до 2027 г. (остават 46 дни)" in bh[0]["message"] and "за 2028" in bh[0]["message"], bh
print("  ✓ 12.11.2026 — нищо; СИНТЕТИЧНА „днес“ 15.11.2027 → „SIFMA_US_FULL_CLOSES … покрива до 2027 г. (остават 46 дни)“")
print("\n✅ test_bond_closed: всичко мина")
