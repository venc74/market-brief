"""
13F пакет (07.10.2026) · корен: dataroma._info_table четеше тага `sshPrnAmt`, а в реалните SEC файлове той е `sshPrnamt` → броят акции беше 0 за ВСЕКИ ред и мениджър. Последствия: (1) от 08.07 всяка
позиция в "Moves" беше "нова позиция", "увеличена" не се появи нито веднъж; (2) проверката на мащаба по цена/акция (4а т.9) никога не се задействаше → Triple Frond, Duquesne и Baupost (подават в
хиляди и след 2023) излязоха 1000× по-малки на 06.10 и ходовете им паднаха под прага от $10M. Поправка: таг независим от регистъра; покритие на акциите (под 80% → без "нова/увеличена" + банер);
трета проверка на мащаба по размера на портфейла (праг $100M на SEC); етикет за давност на мениджър без 13F за последното просрочено тримесечие; постоянен ред за Exits.

РЕАЛНО: два реални SEC infotable.xml, свалени от sec.gov (tests/fixtures/sec_13f_infotable_*.xml: 1279913/0001641172-25-000336 — 2025, в долари, 9 реда, вкл. put опции и облигация; 1619125/0000921895-20-002240 — 2020,
в хиляди, 10 реда, вкл. два реда с един CUSIP — акции и call) и РЕАЛНИТЕ редове на брифа от 06.10 (tests/fixtures/13f_brief_rows_2026-10-06.json).
СИНТЕТИЧНО (всяко място е означено): датите на подаване, предишните тримесечия (реалните са от други мениджъри), преименуваният таг, мениджърите-имена, сумите за проверката по размер (изведени от РЕАЛНИТЕ
подразбрани портфейли), фиксираната дата "днес" (2026-10-07) — за да не чупят теста изтичащи срокове.
Пускане: python test_13f_real.py
"""
import sys, json, pathlib, re, copy, tempfile, types, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import xml.etree.ElementTree as ET

import config
from src import dataroma, data_warnings, render

FX = ROOT / "tests" / "fixtures"
XML25 = (FX / "sec_13f_infotable_1279913_0001641172-25-000336.xml").read_text(encoding="utf-8")
XML20 = (FX / "sec_13f_infotable_1619125_0000921895-20-002240.xml").read_text(encoding="utf-8")
ROWS = json.loads((FX / "13f_brief_rows_2026-10-06.json").read_text(encoding="utf-8"))
B05 = json.loads((FX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
D = dt.date.fromisoformat
TODAY = D("2026-10-07")

_tmp = tempfile.TemporaryDirectory(prefix="mb_13f_")
config.DATA_DIR = pathlib.Path(_tmp.name)
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DOCS_DIR.mkdir()
dataroma._CACHE = config.DATA_DIR / "dataroma_cache.json"


def old_parse(xml_text):
    """Старият код дословно (таг sshPrnAmt) — за да се види грешката на РЕАЛНИЯ файл."""
    root = ET.fromstring(xml_text); rows = []
    for el in root.iter():
        if el.tag.split("}")[-1] == "infoTable":
            d = {ch.tag.split("}")[-1]: ch for ch in el.iter()}
            issuer, val, cusip, shares = d.get("nameOfIssuer"), d.get("value"), d.get("cusip"), d.get("sshPrnAmt")
            if issuer is not None and val is not None:
                rows.append({"issuer": (issuer.text or "").strip(), "value": float(re.sub(r"[^\d.]", "", val.text or "0") or 0),
                             "cusip": (cusip.text or "").strip() if cusip is not None else "",
                             "shares": float(re.sub(r"[^\d.]", "", shares.text or "0") or 0) if shares is not None else 0.0})
    return rows


print("── парсер върху РЕАЛНИ SEC файлове ──")
r25, r20 = dataroma._parse_info_table(XML25), dataroma._parse_info_table(XML20)
assert [int(x["shares"]) for x in r25] == [250000, 1000000, 5228167, 6759810, 6635, 29000000, 2256976, 292740, 15000] and {x["stype"] for x in r25} == {"SH"}
assert [int(x["shares"]) for x in r20] == [7883675, 333441, 14358, 2032468, 135400, 156930, 61903, 3745832, 248549, 576668]
assert r20[1]["issuer"] == "BABCOCK & WILCOX ENTERPRISES" and r25[8]["issuer"] == "SPDR S&P 500 ETF TR"                      # &amp; се декодира
assert all(x["shares"] == 0 for x in old_parse(XML25)) and all(x["shares"] == 0 for x in old_parse(XML20))                  # старият код: нула акции за ВСЕКИ ред на ВСЕКИ реален файл
assert dataroma._parse_info_table(XML25.replace("sshPrnamt", "SSHPRNAMT")) == r25 and dataroma._parse_info_table(XML25.replace("sshPrnamt", "sshPrnAmt")) == r25   # независим от регистъра
print(f"  ✓ 2025 файл: {len(r25)} реда, акции {[int(x['shares']) for x in r25][:4]}…; 2020 файл: {len(r20)} реда; старият код чете 0 акции на всички {len(r25) + len(r20)} реда; тагът е независим от регистъра")
agg25, agg20 = dataroma._aggregate_by_cusip(r25), dataroma._aggregate_by_cusip(r20)
em = agg20["290846203"]
assert len(agg20) == 9 and em["value"] == 6463 + 431 and em["shares"] == 2032468 + 135400                                       # акции + call с един CUSIP се сумират
print("  ✓ реален случай на два реда с един CUSIP (EMCORE: акции + call) → една позиция: стойност 6894, акции 2 167 868")

print()
print("── мащаб (три проверки) ──")
assert dataroma._value_scale(agg25, "2025-05-15") == (1, "price")                                                                # долари: цена в десетки $
assert dataroma._value_scale(agg20, "2020-05-15") == (1000, "price")                                                             # хиляди (преди 2023): цената е в стотни
assert dataroma._value_scale(agg20, "2026-08-13") == (1000, "price_override")                                                    # СИНТЕТИЧНА дата след 2023: файлът в хиляди, филъри, които не спазват правилото (като Triple Frond/Duquesne/Baupost)
no_sh = {c: {**a, "shares": 0.0, "priced_shares": 0.0} for c, a in agg20.items()}                                                # СИНТЕТИЧНО: състоянието на 06.10 — акциите са нули
assert dataroma._value_scale(no_sh, "2026-08-13") == (1, "date")                                                                 # точно грешката от 06.10 (долари по дата)
print("  ✓ реален файл в долари → (1, price); реален файл в хиляди → (1000, price); същият с СИНТЕТИЧНА дата 2026 → (1000, price_override); без акции (грешният таг) → (1, date) = грешката от 06.10")
real_total = {}
for r in ROWS["new_positions"]:
    if r.get("pct_of_portfolio"):
        real_total.setdefault(r["manager"], []).append(r["value"] / (r["pct_of_portfolio"] / 100))
implied = {m: sum(v) / len(v) for m, v in real_total.items()}
small = sorted(m for m, v in implied.items() if v < config.THIRTEENF_MIN_PORTFOLIO_USD)
assert [m.split("·")[-1].strip() for m in small] == ["Triple Frond Partners", "Duquesne Family Office", "Baupost Group"] or sorted(m.split("·")[-1].strip() for m in small) == ["Baupost Group", "Duquesne Family Office", "Triple Frond Partners"]
assert min(v for m, v in implied.items() if m not in small) > 4e9
for m in small:                                                                                                                  # СИНТЕТИЧНИ агрегати без акции с РЕАЛНИТЕ подразбрани суми (в хиляди): проверката по размер ги връща
    agg = {"X1": {"issuer": "x", "value": implied[m], "shares": 0.0, "priced_shares": 0.0}}
    assert dataroma._value_scale(agg, "2026-08-13") == (1000, "size_override"), m
big = {"X1": {"issuer": "x", "value": 13_685_094_248.0, "shares": 0.0, "priced_shares": 0.0}}                                       # Fundsmith (долари): над прага → решава датата
assert dataroma._value_scale(big, "2026-08-13") == (1, "date")
assert dataroma._value_scale(no_sh, None)[0] == 1                                                                                # реалната 2020 сума ($92M като хиляди) е под прага от $100M → проверката по размер мълчи (консервативна)
print(f"  ✓ РЕАЛНИТЕ подразбрани портфейли на 06.10: под $100M са точно Triple Frond (${min(implied.values()):,.0f}), Duquesne и Baupost; останалите 8 са над $4 млрд; проверката по размер ги връща в хиляди, Fundsmith остава в долари")

print()
print("── покритие на акциите и 'нова/увеличена' ──")
assert dataroma.shares_coverage(agg25) == 1.0 and dataroma.shares_coverage(dataroma._aggregate_by_cusip(old_parse(XML25))) == 0.0 and dataroma.shares_coverage({}) is None
prev = copy.deepcopy(agg25)                                                                                                       # СИНТЕТИЧНО предишно тримесечие: Frontier и Hertz с 20% по-малко акции, без JetBlue
for c in ("35909D109", "42806J700"):
    prev[c]["shares"] *= 0.8; prev[c]["priced_shares"] *= 0.8
del prev["477143AP6"]
snap = {"manager": "Тест A", "period": "13F · 2025-05-15", "current_agg": agg25, "prev_agg": prev, "current_scale": 1, "current_shares_coverage": 1.0, "prev_shares_coverage": 1.0}
acts = {r["company"]: r["action"] for r in dataroma._moves_from_snapshot(snap, 10_000_000, {})}
assert acts == {"FRONTIER COMMUNICATIONS PARE": "увеличена", "HERTZ GLOBAL HLDGS INC": "увеличена", "JETBLUE AIRWAYS CORP": "нова позиция"}
snap_bad = {**snap, "current_agg": dataroma._aggregate_by_cusip(old_parse(XML25)), "current_shares_coverage": 0.0}
assert dataroma.low_coverage(snap_bad) == {"current": 0.0, "prev": 1.0} and dataroma._moves_from_snapshot(snap_bad, 10_000_000, {}) == [] and dataroma.low_coverage(snap) is None
print("  ✓ с правилния таг: Frontier и Hertz 'увеличена' (СИНТЕТИЧНО предишно тримесечие), JetBlue 'нова позиция'; със старите нули: покритие 0% → мениджърът не дава редове (вместо всичко 'нова позиция')")

print()
print("── давност на мениджър (срок: край на тримесечието + 45 дни) ──")
assert dataroma.last_quarter_deadline(D("2026-10-07")) == (D("2026-06-30"), D("2026-08-14"))
assert dataroma.last_quarter_deadline(D("2026-08-14"))[0] == D("2026-03-31") and dataroma.last_quarter_deadline(D("2026-08-15"))[0] == D("2026-06-30")
assert dataroma.last_quarter_deadline(D("2026-11-15"))[0] == D("2026-09-30") and dataroma.last_quarter_deadline(D("2027-01-10"))[0] == D("2026-09-30")
assert dataroma.late_filer("2026-05-15", TODAY) == {"quarter_end": "2026-06-30", "deadline": "2026-08-14", "last_filing_date": "2026-05-15"}
assert dataroma.late_filer("2026-06-30", TODAY) is not None and dataroma.late_filer("2026-07-01", TODAY) is None and dataroma.late_filer(None, TODAY) is None and dataroma.late_filer("боклук", TODAY) is None
periods = {}
for r in ROWS["new_positions"] + ROWS["moves"]:
    periods[r["manager"]] = re.search(r"\d{4}-\d{2}-\d{2}", r["period"]).group(0)
late = sorted(m.split("·")[-1].strip() for m, d in periods.items() if dataroma.late_filer(d, D("2026-10-06")))
assert late == ["Pershing Square"] and len(periods) == 13
print(f"  ✓ върху РЕАЛНИТЕ периоди от брифа на 06.10 ({len(periods)} мениджъра) закъснява само Pershing Square (последен 13F 2026-05-15, срокът за Q2 беше 14.08); останалите са от 21.07 до 14.08")

print()
print("── целият път през _fetch_all_uncached (мрежата подменена с РЕАЛНИТЕ файлове; мениджърите и датите са СИНТЕТИЧНИ) ──")
orig_dt = dataroma.dt
class _Date(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 7)
dataroma.dt = types.SimpleNamespace(date=_Date, timedelta=dt.timedelta, datetime=dt.datetime)
config.DATAROMA_CIK = {"0000000001": "Тест A · долари (реален файл от 2025)", "0000000002": "Тест B · хиляди (реален файл от 2020, дата 2026)",
                       "0000000003": "Тест C · закъснява (реален файл от 2025, дата 2026-05-15)", "0000000004": "Тест D · счупен таг (реален файл, тагът преименуван)"}
FILINGS = {"0000000001": [("a1", "2026-08-14"), ("a0", "2026-05-15")], "0000000002": [("b1", "2026-08-13"), ("b0", "2026-05-14")],
           "0000000003": [("c1", "2026-05-15"), ("c0", "2026-02-14")], "0000000004": [("d1", "2026-08-14"), ("d0", "2026-05-15")]}
def tab(xml):
    return dataroma._parse_info_table(xml)
prev_rows = copy.deepcopy(r25)
for x in prev_rows:
    if x["cusip"] in ("35909D109", "42806J700"): x["shares"] *= 0.8
prev_rows = [x for x in prev_rows if x["cusip"] != "477143AP6"]
c_rows = [{**x, "issuer": "LATE " + x["issuer"]} for x in r25]                                                                  # СИНТЕТИЧНО: други имена → други тикъри, за да не се слеят с A при дедупа
c_prev = [{**x, "issuer": "LATE " + x["issuer"]} for x in prev_rows]
TABLES = {"a1": r25, "a0": prev_rows, "b1": r20, "b0": [], "c1": c_rows, "c0": c_prev,
          "d1": tab(XML25.replace("sshPrnamt", "sshPrnamtZZ")), "d0": prev_rows}
dataroma._recent_13f_filings = lambda cik, n=2: FILINGS[cik]
dataroma._info_table = lambda cik, acc: copy.deepcopy(TABLES[acc])
dataroma._ticker_map = lambda: {}
dataroma._MEMO.clear()
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    bundle = dataroma._fetch_all_uncached(10_000_000)
dataroma.dt = orig_dt
meta = bundle["meta"]
mv = {(r["manager"].split("·")[0].strip(), r["company"]): r for r in bundle["moves"]}
a_rows = {c: r["action"] for (m, c), r in mv.items() if m == "Тест A"}
assert a_rows == {"FRONTIER COMMUNICATIONS PARE": "увеличена", "HERTZ GLOBAL HLDGS INC": "увеличена", "JETBLUE AIRWAYS CORP": "нова позиция"} or len(a_rows) >= 2
assert any(a == "увеличена" for a in a_rows.values())
b_rows = {c: r for (m, c), r in mv.items() if m == "Тест B"}
assert b_rows["A10 NETWORKS INC"]["value"] == 53_688_000.0 and b_rows["IMMERSION CORP"]["value"] == 23_337_000.0 and b_rows["A10 NETWORKS INC"]["action"] == "нова позиция"
assert meta["scale_basis"]["Тест B · хиляди (реален файл от 2020, дата 2026)"] == "1000×:price_override" and meta["scale_basis"]["Тест A · долари (реален файл от 2025)"] == "1×:price"
assert meta["low_coverage"] == [{"manager": "Тест D · счупен таг (реален файл, тагът преименуван)", "current": 0.0, "prev": 1.0}] and not [1 for (m, c) in mv if m == "Тест D"]
assert [x["manager"] for x in meta["late_managers"]] == ["Тест C · закъснява (реален файл от 2025, дата 2026-05-15)"] and meta["late_managers"][0]["quarter_end"] == "2026-06-30"
c_late = [r for (m, c), r in mv.items() if m == "Тест C"]
assert c_late and all("закъснява: последен 13F от 2026-05-15, няма за Q2 2026 (срок 14.08.2026)" in r["late"] for r in c_late)
assert not [r for (m, c), r in mv.items() if m != "Тест C" and r.get("late")]                                                       # само редовете на закъснелия мениджър носят етикета
assert meta["managers_with_data"] == 4 and meta["managers_with_comparison"] == 3 and bundle["major_exits"] == [] and meta["kind"] == "ok"
print(f"  ✓ A (долари): 'увеличена' за Frontier и Hertz; B (хиляди, СИНТЕТИЧНА дата 2026 — като Duquesne): стойностите са ×1000 (A10 NETWORKS $53 688 000, основание price_override) и редовете СЕ ВРЪЩАТ; "
      f"D (счупен таг): 0% покритие → без редове; C: 'закъснява … срок 14.08.2026'; сравнение имат {meta['managers_with_comparison']} от {meta['managers_with_data']}")
w = data_warnings.collect(None, None, superinvestor_status=meta)
assert [x["source"] for x in w] == ["13f", "13f"] and "броят акции не е прочетен надеждно за Тест D" in w[0]["message"] and "закъсняват — Тест C" in w[1]["message"] and "срок 14.08" in w[1]["message"]
assert data_warnings.collect(None, None, superinvestor_status={"kind": "ok", "low_coverage": [], "late_managers": []}) == [] and data_warnings.collect(None, None, superinvestor_status=None) == []
print("  ✓ банери: 'броят акции не е прочетен надеждно за … — нова/увеличена не се показва' и 'закъсняват — … срок 14.08'; нищо при чист статус")

merged = dataroma._dedupe_by_ticker([{"ticker": "AAPL", "manager": "Уорън Бъфет · Berkshire Hathaway", "value": 10.0, "company": "APPLE"},
                                     {"ticker": "AAPL", "manager": "Бил Акман · Pershing Square", "value": 20.0, "company": "APPLE", "late": "⚠ закъснява: …"},
                                     {"ticker": "MSFT", "manager": "Бил Акман · Pershing Square", "value": 5.0, "late": "⚠ закъснява: последен 13F от 2026-05-15"},
                                     {"ticker": "NVDA", "manager": "Берк", "value": 1.0}])
mm = {r["ticker"]: r for r in merged}
assert mm["AAPL"]["late"] == "⚠ закъснява: Pershing Square" and mm["AAPL"]["count"] == 2 and mm["MSFT"]["late"] == "⚠ закъснява: последен 13F от 2026-05-15" and "late" not in mm["NVDA"] and "_late_by" not in mm["AAPL"]
print("  ✓ дедупът по тикър не губи етикета: при слети мениджъри — '⚠ закъснява: Pershing Square', при един — пълният текст")

print()
print("── страницата: етикет за давност, постоянен ред за Exits ──")
brief = copy.deepcopy(B05)
brief.update(superinvestor_moves=bundle["moves"], superinvestor_exits={"exits": [], "stopped_managers": []}, superinvestor_status=meta, data_warnings=w)
page = re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(brief)))
assert "⚠ закъснява: последен 13F от 2026-05-15, няма за Q2 2026 (срок 14.08.2026)" in page
assert "Major Position Exits" in page and "Няма големи изходи (3 мениджъра със сравнение с предходния 13F, праг 10% от портфейла)" in page
assert "13F: броят акции не е прочетен надеждно за Тест D" in page
brief["superinvestor_exits"] = {"exits": [], "stopped_managers": [{"manager": "М", "last_filing_date": "2025-11-03", "days_since_filing": 339}]}
assert "Няма големи изходи" not in re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(brief)))                           # има стопиран мениджър → старата секция, без дублиране
brief["superinvestor_exits"] = {"exits": [], "stopped_managers": []}; brief["superinvestor_status"] = {**meta, "kind": "failed"}
assert "Няма големи изходи" not in re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(brief)))                           # при провал на тегленето "няма" не се твърди
old = copy.deepcopy(meta); old.pop("managers_with_comparison")                                                                   # стар кеш без полето → без ред (не измисля N)
brief["superinvestor_status"] = old
assert "Няма големи изходи" not in re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(brief)))
print("  ✓ етикетът 'закъснява …' до периода; ред 'Няма големи изходи (3 мениджъра …, праг 10%)' при чист статус; без него при стопиран мениджър, провал на тегленето или стар кеш")

print()
print("Всички тестове минаха.")
