"""
16.11.2026 (пакет 16.11, т. 10): плочката SOFR − IORB носеше „облигационният пазар беше затворен (11.11) — стойността е от 10.11“ — вярно, но объркващо: SOFR за работен ден D
излиза на следващия работен ден (по SIFMA) в 08:00 Ню Йорк, т.е. сутрин в 07:30 Берлин тя е винаги поне ден назад. Сега: „SOFR излиза на следващия работен ден в 08:00 Ню Йорк:
последна — 12.11; за 13.11 — днес ~14:00 Берлин“ (реално 16.11), а карето в 15:05 обновява SOFR от NY Fed (FRED я дава по-късно) и плочката на страницата.

РЕАЛНО: tests/fixtures/nyfed_sofr_last5_2026-11-16.json — markets.newyorkfed.org/api/rates/secured/sofr/last/5.json, изтеглено 16.11.2026 ~15:35 Берлин (последна — 13.11, 3.90%);
tests/fixtures/funding_sofr_iorb_2026-10-15.json — SOFR / IOER / IORB (до 14–15.10); брифът от 16.11 — SOFR към 12.11 (data/2026-11-16.json, цитирано тук); brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): т. 3 — двете реални серии са слепени (празнина 15.10–05.11) за опреснението в 15:05; подмененото теглене.
Пускане: python test_sofr_schedule.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_sofr_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, macro_layer as ml, preopen, render

FXD = ROOT / "tests" / "fixtures"
NY = json.loads((FXD / "nyfed_sofr_last5_2026-11-16.json").read_text(encoding="utf-8"))
F = json.loads((FXD / "funding_sofr_iorb_2026-10-15.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. графикът: последна, следваща и кога излиза ──")
assert th.sofr_schedule("2026-11-12", "2026-11-16") == "SOFR излиза на следващия работен ден в 08:00 Ню Йорк: последна — 12.11; за 13.11 — днес ~14:00 Берлин"
assert th.sofr_schedule("2026-11-09", "2026-11-12").endswith("последна — 09.11; за 10.11 — днес ~14:00 Берлин")             # 11.11 — Veterans Day (SIFMA): за 10.11 излиза на 12.11
assert th.sofr_schedule("2026-11-13", "2026-11-16", "15:05 Берлин").endswith("последна — 13.11 (обновена в 15:05 Берлин от NY Fed); за 16.11 — вторник 17.11 ~14:00 Берлин")
assert th.sofr_schedule("2026-10-28", "2026-10-30").endswith("за 29.10 — днес ~13:00 Берлин")                                 # седмицата с разминаване на часа (ЕС сменя на 25.10, САЩ — на 01.11)
assert th.sofr_schedule("2026-11-10", "2026-11-16").endswith("за 12.11 — излезе на 13.11 в 08:00 Ню Йорк — FRED още не я дава")
assert th.sofr_schedule(None, "2026-11-16") is None
print("  ✓ 16.11: „…последна — 12.11; за 13.11 — днес ~14:00 Берлин“; празникът 11.11 и смяната на часа")

print("── 2. плочката: без етикета за затворения пазар, с бележката ──")
assert "SOFR − IORB (финансиране)" not in th.BOND_TILES
inds = [{"name": "SOFR − IORB (финансиране)", "value": 0.0, "as_of": "2026-11-12"}, {"name": "VIX", "value": 19.3}]
th.mark_sofr_schedule(inds, "2026-11-16")
assert inds[0]["sofr_note"].endswith("за 13.11 — днес ~14:00 Берлин") and "sofr_note" not in inds[1]
assert th.mark_bond_closed(copy.deepcopy(inds), "2026-11-11") == []
print("  ✓ SOFR — само бележката за графика; етикетът „облигационният пазар беше затворен“ — не")

print("── 3. РЕАЛНО: NY Fed (последна — 13.11) и опреснението в 15:05 ──")
ny = ml.fetch_nyfed_sofr(get=lambda url: NY)
assert ny[-1] == ("2026-11-13", 3.9) and ny[0] == ("2026-11-06", 3.89) and len(ny) == 5
fred = [tuple(x) for x in F["sofr"]]
assert ml.merge_sofr(fred, ny)[-5:] == ny and ml.merge_sofr(fred, [("2026-10-14", 9.9)]) == fred                # само по-новите от FRED
fs_fn = lambda: ml.funding_spread(ml.merge_sofr(fred, ny), [tuple(x) for x in F["ioer"]], [tuple(x) for x in F["iorb"]], today=dt.date(2026, 11, 16))   # СИНТЕТИЧНО слепване
b = copy.deepcopy(B19)
b["macro"] = {**b.get("macro", {}), "funding_stress": {"as_of": "2026-11-12", "value": 0.0}}
b["thermometer"]["indicators"] = [i for i in b["thermometer"]["indicators"] if not str(i["name"]).startswith("SOFR")] + [{"name": "SOFR − IORB (финансиране)", "value": 0.0, "as_of": "2026-11-12", "informational": True, "status": "yellow", "label": "сутрин"}]
now = dt.datetime(2026, 11, 16, 14, 6, tzinfo=dt.timezone.utc)                                # 09:06 Ню Йорк = 15:06 Берлин
u = preopen.refresh_sofr(b, now, fs_fn)
assert u["from"] == "2026-11-12" and u["to"] == "2026-11-13" and u["value"] == 0.0
assert u["text"] == "SOFR − IORB обновена: +0.0 б.п. за 13.11 (SOFR 3.90%, NY Fed — 08:00 Ню Йорк)"
ind = next(i for i in b["thermometer"]["indicators"] if str(i["name"]).startswith("SOFR"))
assert ind["as_of"] == "2026-11-13" and ind["sofr_note"].endswith("последна — 13.11 (обновена в 15:06 Берлин от NY Fed); за 16.11 — вторник 17.11 ~14:00 Берлин")
assert preopen.refresh_sofr(b, now, fs_fn) is None                                            # вече е новата — нищо
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert 'res["sofr_update"] = refresh_sofr(brief, now)' in src
print(f"  ✓ {u['text']}; плочката — към 13.11; повторно — нищо")

print("── 4. страницата ──")
b["preopen"] = {"date": "2026-11-16", "time_ny": "09:06", "time_berlin": "15:06", "ok": True, "diag": {}, "gaps": [], "levels": [], "watch": [], "notes": [], "sofr_update": u}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "(обновена в 15:06 Берлин от NY Fed); за 16.11 — вторник 17.11 ~14:00 Берлин" in page and "SOFR − IORB обновена: +0.0 б.п. за 13.11" in page
print("  ✓ плочката с бележката и редът в карето")
print("\n✅ test_sofr_schedule: всичко мина")
