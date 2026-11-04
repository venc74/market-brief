"""
03.11.2026 · разходката, т. 18–19: 13F — една секция, компактна таблица Мениджър · Тикър · Действие (нова / увеличена / изход) · Стойност · Промяна · % от портфейла · в нашия скрийнър ✓.
Изходите са редове „изход“ (без отделната „Major Position Exits“ и без реда „Няма големи изходи“). Проверено: „промяна“ и „% от портфейла“ СЕ попълват от двата поредни 13F — колоните остават.
Ритъмът е дневен (цялата при ново подаване, иначе ред + сгънато); маркерът SI✓ остава.

РЕАЛНО: tests/fixtures/sec_13f_infotable_1656456_0001656456-26-00000{2,3}.xml (Appaloosa, две поредни подавания); tests/fixtures/brief_2026-10-19.json — рамката и стар бриф без новите полета.
СИНТЕТИЧНО (означено): по-ниският праг за изход (10% → 0.5%, за да има реални редове „изход“ от файловете), тикърите (OpenFIGI не се вика), нашият скрийнър, спрелият мениджър.
Пускане: python test_13f_table.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import xml.etree.ElementTree as ET
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_13ftable_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import dataroma, render

FX = ROOT / "tests" / "fixtures"
PREV, CUR = (FX / "sec_13f_infotable_1656456_0001656456-26-000002.xml").read_text(encoding="utf-8"), (FX / "sec_13f_infotable_1656456_0001656456-26-000003.xml").read_text(encoding="utf-8")
B19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
M = "Дейвид Тепър · Appaloosa Management"

print("── 1. „% от портфейла“ и „промяна“ се попълват от двата поредни 13F (РЕАЛНО, Appaloosa) ──")
pa, ca = dataroma._aggregate_by_cusip(dataroma._parse_info_table(PREV)), dataroma._aggregate_by_cusip(dataroma._parse_info_table(CUR))
snap = {"manager": M, "period": "13F · 2026-08-14", "current_agg": ca, "prev_agg": pa, "current_scale": 1, "prev_scale": 1, "current_total": sum(a["value"] for a in ca.values()),
        "prev_total": sum(a["value"] for a in pa.values()), "current_shares_coverage": 1.0, "prev_shares_coverage": 1.0, "quarter": "2026-06-30"}
mv = dataroma._moves_from_snapshot(snap, 10e6, {})
assert len(mv) == 12 and all(r["pct_of_portfolio"] is not None for r in mv)
assert all((r["change_pct"] is None) == (r["action"] == "нова позиция") for r in mv)


def indep(xml):                                                                          # независимо от парсера: дълги редове по CUSIP (без putCall)
    out = {}
    for el in ET.fromstring(xml).iter():
        if el.tag.split("}")[-1] == "infoTable":
            d = {ch.tag.split("}")[-1]: (ch.text or "").strip() for ch in el.iter()}
            if not d.get("putCall"):
                x = out.setdefault(d["cusip"], [0.0, 0.0, d["nameOfIssuer"]])
                x[0] += float(d["value"]); x[1] += float(d["sshPrnamt"])
    return out


ic, ip = indep(CUR), indep(PREV)
tot = sum(v[0] for v in ic.values())
for r in mv:
    c = ic[r["cusip"]]
    assert r["pct_of_portfolio"] == round(c[0] / tot * 100, 1), r
    if r["change_pct"] is not None:
        assert r["change_pct"] == round((c[1] / ip[r["cusip"]][1] - 1) * 100, 1), r
top = max(mv, key=lambda r: r["value"])
assert top["company"].startswith("AMAZON") and (top["action"], top["pct_of_portfolio"], top["change_pct"]) == ("увеличена", 16.0, 15.7)
print(f"  ✓ {len(mv)} реда; AMAZON — увеличена с +15.7% акции, 16.0% от портфейла; всички сверени независимо с XML файла; нова позиция — без промяна")

print()
print("── 2. дедупът пази реда на всеки мениджър ──")
rows = [{**r, "ticker": {"AMAZON COM INC": "AMZN"}.get(r["company"], r["ticker"])} for r in mv]                      # СИНТЕТИЧНО: тикърът
other = {**[r for r in rows if r["ticker"] == "AMZN"][0], "manager": "Друг мениджър", "value": 5e9, "action": "нова позиция", "pct_of_portfolio": 30.0, "change_pct": None}    # СИНТЕТИЧНО
dd = {r["ticker"]: r for r in dataroma._dedupe_by_ticker(rows + [other])}
bm = dd["AMZN"]["by_manager"]
assert dd["AMZN"]["count"] == 2 and [m["manager"] for m in bm] == ["Друг мениджър", M] and bm[1]["pct_of_portfolio"] == 16.0 and bm[1]["action"] == "увеличена" and bm[0]["action"] == "нова позиция"
print("  ✓ AMZN при двама мениджъри — ред за всеки, със собствените действие, стойност и дял")

print()
print("── 3. thirteenf_rows: покупките по стойност, после изходите; стар бриф ──")
_t, config.DATAROMA_MAJOR_EXIT_PCT = config.DATAROMA_MAJOR_EXIT_PCT, 0.5                   # СИНТЕТИЧНО: прагът, за да има реални изходи от файловете
ex = dataroma._major_exits_from_snapshot(snap, {})
config.DATAROMA_MAJOR_EXIT_PCT = _t
assert ex and all(r["cusip"] not in ic for r in ex)
tr = render.thirteenf_rows(list(dd.values()), {"exits": ex, "stopped_managers": []}, ["AMZN"])
buys = [r for r in tr if r["action"] != "изход"]
gone = [r for r in tr if r["action"] == "изход"]
assert tr[:len(buys)] == buys and len(gone) == len(ex) and [r["value"] for r in buys] == sorted((r["value"] for r in buys), reverse=True)
assert all(r["change_pct"] == -100.0 and r["pct_of_portfolio"] is not None for r in gone) and {r["action"] for r in buys} <= {"нова", "увеличена"}
assert [r["in_screener"] for r in tr if r["ticker"] == "AMZN"] == [True, True] and sum(r["in_screener"] for r in tr) == 2
old = render.thirteenf_rows([{"ticker": "X", "company": "X Co", "manager": "Бъфет", "action": "нова позиция", "value": 1e8, "count": 3}], None, [])              # стар бриф: ред на тикър
assert old[0]["manager"] == "Бъфет +2" and old[0]["action"] == "нова" and old[0]["pct_of_portfolio"] is None
assert render.thirteenf_rows(None, None, None) == []
print(f"  ✓ {len(buys)} покупки по стойност, {len(gone)} изхода (−100%, дял в предходния 13F); ✓ при нашия скрийнър; стар бриф без „by_manager“ — „Бъфет +2“")

print()
print("── 4. страницата: една секция; без „Major Position Exits“ и „Няма големи изходи“ ──")


def page_of(**over):
    b = copy.deepcopy(B19); b["thirteenf_rhythm"] = {}
    b.update(over)
    with contextlib.redirect_stdout(io.StringIO()):
        return render.render_dashboard(b, publish=False)


st = {"kind": "ok", "note": "1 от 1", "managers_with_comparison": 1, "managers_with_data": 1, "managers_total": 1}
p = page_of(superinvestor_moves=list(dd.values()), superinvestor_exits={"exits": ex, "stopped_managers": [{"manager": "Спрял", "last_filing_date": "2025-11-03", "days_since_filing": 339}]}, superinvestor_status=st,
            action=[{**B19["action"][0], "ticker": "AMZN"}] if B19.get("action") else [], watchlist=B19.get("watchlist") or [])
s = p[p.index("Superinvestor Positions — Last 13F"):]; s = s[:s.index("</section>")]
fs = flat(s)
assert p.count("Superinvestor Positions — Last 13F") == 1 and "Major Position Exits" not in p and "Няма големи изходи" not in p and 'class="si-card' not in p
assert "Мениджър Тикър Действие Стойност Промяна % от портфейла Скрийнър" in fs
assert f"{M} AMZN AMAZON COM INC увеличена $1.2 млрд +16% 16.0%" in fs, fs[:900]
assert s.count('class="si-exit"') == len(ex) and " изход " in fs and "-100%" in fs and "Мениджъри, спрели да подават 13F" in fs and "Спрял" in fs
p0 = page_of(superinvestor_moves=[], superinvestor_exits={"exits": [], "stopped_managers": []}, superinvestor_status={**st, "kind": "legit_zero", "note": "нито една нова позиция"})
assert "Няма големи изходи" not in p0 and "Major Position Exits" not in p0 and "нито една нова позиция" in flat(p0)
p1 = page_of(superinvestor_moves=list(dd.values()), superinvestor_exits={"exits": ex, "stopped_managers": []}, superinvestor_status=st,
             thirteenf_rhythm={"compact": True, "text": "13F: последни 13F от 20.10 — следваща вълна около 16.11"})
s1 = p1[p1.index("Superinvestor Positions — Last 13F"):]; s1 = s1[:s1.index("</section>")]
assert s1.index("следваща вълна около 16.11") < s1.index('<details class="si-full">') < s1.index('class="ctx-table si-table"') and f"<summary>Таблицата от последните 13F ({len(tr)})</summary>" in s1
print("  ✓ една таблица с колоните; изходите — редове „изход“; спрелите мениджъри — бележка; без нови подавания — ред + ▸ Таблицата от последните 13F (N)")
print("\n✅ test_13f_table: всичко мина")
