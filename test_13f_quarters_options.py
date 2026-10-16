"""
16.10.2026 · т. 7 (трети преглед): 13F — В4 предишното тримесечие по reportDate (ПОРЕДНОТО, от всеки CIK на мениджъра; тримесечие от няколко CIK-а = сборът им), В3 "без сравнение"
(няма филинг / непоредни / не се изтегли — без нова/увеличена, SI✓ и изходи), В5 putCall извън дългите позиции и знаменателя на %, срокът за подаване с почивните дни.

РЕАЛНО (свалени от sec.gov на 16.10.2026 през вградения браузър; infotable файловете — байт по байт, SHA-256 сверен с файла на SEC):
  • tests/fixtures/sec_submissions_13f_2026-10-16.json — 13F редовете (form, accession, filingDate, reportDate) от data.sec.gov/submissions за 15-те мениджъра и PERSHING SQUARE INC.;
  • sec_13f_infotable_949509_0000949509-26-000005.xml / -000002.xml — Oaktree Q2 / Q1 2026 (Q2: 4 PUT, вкл. "STATE STREET CORP" с CUSIP 78462F103 = SPDR S&P 500 ETF, $1.01 млрд; 3 CALL);
  • sec_13f_infotable_1656456_0001656456-26-000003.xml / -000002.xml — Appaloosa Q2 / Q1 2026 (Q2: PUT на AAPL $241.6 млн и на BRK-B);
  • sec_13f_infotable_2026053_0001172661-26-002339.xml — Q1 2026 на PERSHING SQUARE INC. (само HHH 9 000 000); Q2 на родителя и Q1 на стария CIK — fixture-ите от 08.10;
  • tests/fixtures/brief_2026-10-16.json — реалният бриф: SI✓ "STT 14.0% · Oaktree" и "AAPL 3.1% · Appaloosa" (и двете са PUT), "STT нова позиция $1.01 млрд" в Moves.
СИНТЕТИЧНО (маркирано): Q3 2026 филингите на Pershing (ноември — още ги няма; съдържанието е реалното Q2), мениджър с махнат реален ред (пропуснато тримесечие), малката таблица за
мениджърите без свален infotable (само за избора на тримесечие), "днес".
Пускане: python test_13f_quarters_options.py
"""
import sys, json, copy, pathlib, tempfile, types, contextlib, io, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_13fq_")
config.DATA_DIR = pathlib.Path(_tmp.name)
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DOCS_DIR.mkdir()
from src import dataroma, data_warnings, render

FX = ROOT / "tests" / "fixtures"
SUB = json.loads((FX / "sec_submissions_13f_2026-10-16.json").read_text(encoding="utf-8"))
NT_XML = (FX / "sec_13f_nt_1336528_0001172661-26-003777.xml").read_text(encoding="utf-8")
FILES = {"0000949509-26-000005": "sec_13f_infotable_949509_0000949509-26-000005.xml", "0000949509-26-000002": "sec_13f_infotable_949509_0000949509-26-000002.xml",
         "0001656456-26-000003": "sec_13f_infotable_1656456_0001656456-26-000003.xml", "0001656456-26-000002": "sec_13f_infotable_1656456_0001656456-26-000002.xml",
         "0001172661-26-003790": "sec_13f_infotable_2026053_0001172661-26-003790.xml", "0001172661-26-002339": "sec_13f_infotable_2026053_0001172661-26-002339.xml",
         "0001172661-26-002336": "sec_13f_infotable_1336528_0001172661-26-002336.xml"}
TABLES = {acc: dataroma._parse_info_table((FX / f).read_text(encoding="utf-8")) for acc, f in FILES.items()}
B16 = json.loads((FX / "brief_2026-10-16.json").read_text(encoding="utf-8"))
OLD, NEW, OAK, APP = "0001336528", "0002026053", "0000949509", "0001656456"
D = dt.date.fromisoformat
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

dataroma._CACHE = config.DATA_DIR / "dataroma_cache.json"
dataroma._TMAP_CACHE = config.DATA_DIR / "sec_tickers.json"
dataroma._ticker_map = lambda: {}
SYN_ROW = [{"issuer": "X", "value": 1e9, "cusip": "SYN000000", "shares": 1e7, "stype": "SH", "putcall": ""}]                       # СИНТЕТИЧНО: за мениджърите без свален infotable


class Resp:
    def __init__(self, text="", js=None):
        self.text, self._js = text, js

    def json(self):
        return self._js

    def raise_for_status(self):
        return None


SUBS = {c: copy.deepcopy(v) for c, v in SUB["submissions"].items()}
NT_EXTRA: dict[str, str] = {}


def fake_get(url, **kw):
    m = re.fullmatch(r"https://data\.sec\.gov/submissions/CIK(\d{10})\.json", url)
    if m:
        return Resp(js=SUBS[m.group(1)])
    m = re.search(r"/Archives/edgar/data/1336528/(\d{18})/primary_doc\.xml$", url)
    if m and (m.group(1) == "000117266126003777" or m.group(1) in NT_EXTRA):
        return Resp(NT_XML)                                                                                                     # СИНТЕТИЧНОТО известие за Q3 — със съдържанието на реалното
    raise AssertionError(f"неочакван URL: {url}")


dataroma.requests = types.SimpleNamespace(get=fake_get)
dataroma._info_table = lambda cik, acc: copy.deepcopy(TABLES.get(acc, SYN_ROW))


def snap(cik, name="М"):
    with quiet():
        return dataroma._manager_snapshot(cik, name)


print("── 1. В4: тримесечията по reportDate — РЕАЛНИТЕ подавания на 15-те мениджъра (16.10) ──")
got = {}
for cik, name in config.DATAROMA_CIK.items():
    s = snap(cik, name)
    got[cik] = s
    assert (s["quarter"], s["prev_quarter"], s["comparison"]) == ("2026-06-30", "2026-03-31", None), (name, s.get("quarter"), s.get("comparison"))
prev_acc = {c: [acc for _, (acc, _) in s["sources"]["2026-03-31"]] for c, s in got.items()}
assert prev_acc[OAK] == ["0000949509-26-000002"]                                                                                # 13F-HR, не двете 13F-HR/A от 19–20.05
assert prev_acc[OLD] == ["0001172661-26-002336", "0001172661-26-002339"]                                                        # Pershing: Q1 = стария CIK + родителя
assert all(len(v) == 1 for c, v in prev_acc.items() if c != OLD)
print("  ✓ всичките 15: текущо Q2 2026, предишно Q1 2026, сравнение има; Oaktree — 13F-HR (не 13F-HR/A); Pershing — Q1 от двата CIK-а (1336528 и 2026053)")

print()
print("── 2. Pershing: HHH +9 000 000 е обхват, не покупка (РЕАЛНИ файлове) ──")
p = got[OLD]
hhh = "44267T102"
assert p["current_agg"][hhh]["shares"] == p["prev_agg"][hhh]["shares"] == 18_852_064 + 9_000_000
assert dataroma._aggregate_by_cusip(TABLES["0001172661-26-002336"])[hhh]["shares"] == 18_852_064                                 # само стария CIK (до 16.10): +48% → "увеличена"
moves = {r["company"]: r["action"] for r in dataroma._moves_from_snapshot(p, 10_000_000, {})}
assert "HOWARD HUGHES HOLDINGS INC" not in moves and moves["MICROSOFT CORP"] == "увеличена" and moves["VISA INC"] == "нова позиция"
print("  ✓ Q1 = 18 852 064 (Pershing Square Capital Management) + 9 000 000 (PERSHING SQUARE INC.) = Q2 27 852 064 → HHH не е 'увеличена'; Visa 'нова', Microsoft 'увеличена'")

print()
print("── 3. ноември (СИНТЕТИЧНО: Q3 на родителя и 13F-NT на стария CIK, 16.11.2026): предишното = Q2 на родителя, не Q1 на стария CIK ──")
def add(cik, form, acc, filed, rep):
    r = SUBS[cik]["filings"]["recent"]
    for k, v in (("form", form), ("accessionNumber", acc), ("filingDate", filed), ("reportDate", rep)):
        r[k].insert(0, v)
add(NEW, "13F-HR", "0001172661-26-009990", "2026-11-16", "2026-09-30")
add(OLD, "13F-NT", "0001172661-26-009991", "2026-11-16", "2026-09-30")
NT_EXTRA["000117266126009991"] = "nt"
TABLES["0001172661-26-009990"] = copy.deepcopy(TABLES["0001172661-26-003790"])                                                  # СИНТЕТИЧНО: Q3 = реалното Q2 (без промени)
n = snap(OLD)
assert (n["quarter"], n["prev_quarter"], n["comparison"]) == ("2026-09-30", "2026-06-30", None)
assert [acc for _, (acc, _) in n["sources"]["2026-06-30"]] == ["0001172661-26-003790"]
old_pairing = dataroma._recent_13f_filings(OLD, n=2)[0]                                                                        # старият код: [родителят] + последният 13F-HR на стария CIK
assert old_pairing[0] == "0001172661-26-002336" and old_pairing[2] == "2026-03-31"
assert dataroma._moves_from_snapshot(n, 10_000_000, {}) == []                                                                   # непроменен портфейл → нищо ново (със стария Q1 — Visa, Mastercard … пак "нови")
print("  ✓ Q3 (родителя) срещу Q2 (родителя); старото сдвояване беше Q3 срещу Q1 (0001172661-26-002336) — непоредни; при непроменен портфейл — нито един ред")
for c in (NEW, OLD):
    SUBS[c] = copy.deepcopy(SUB["submissions"][c])

print()
print("── 4. В3: без сравнение (реалните подавания на Appaloosa, СИНТЕТИЧНО махнат ред / провал) ──")
def drop(cik, accs):
    r = SUBS[cik]["filings"]["recent"]
    keep = [i for i, a in enumerate(r["accessionNumber"]) if a not in accs]
    for k in ("form", "accessionNumber", "filingDate", "reportDate"):
        r[k] = [r[k][i] for i in keep]
def silent(s):
    return dataroma._moves_from_snapshot(s, 1, {}) == [] and dataroma._new_position_highlights_from_snapshot(s, {}) == [] and dataroma._major_exits_from_snapshot(s, {}) == []
drop(APP, {"0001656456-26-000002"})
s1 = snap(APP)
assert s1["comparison"] == {"reason": "not_consecutive", "text": "предишният 13F е за Q4 2025, а не за Q1 2026"} and silent(s1)
SUBS[APP] = copy.deepcopy(SUB["submissions"][APP]); drop(APP, set(SUB["submissions"][APP]["filings"]["recent"]["accessionNumber"][1:]))
s2 = snap(APP)
assert s2["comparison"] == {"reason": "no_prev_filing", "text": "няма 13F за Q1 2026"} and silent(s2)
SUBS[APP] = copy.deepcopy(SUB["submissions"][APP])
saved = TABLES.pop("0001656456-26-000002")
dataroma._info_table = lambda cik, acc: copy.deepcopy(TABLES.get(acc, SYN_ROW)) if acc != "0001656456-26-000002" else []
s3 = snap(APP)
assert s3["comparison"] == {"reason": "prev_fetch_failed", "text": "13F за Q1 2026 не се изтегли днес"} and silent(s3) and s3["current_agg"]
TABLES["0001656456-26-000002"] = saved
dataroma._info_table = lambda cik, acc: copy.deepcopy(TABLES.get(acc, SYN_ROW))
s4 = snap(APP)
assert s4["comparison"] is None and not silent(s4)
print("  ✓ пропуснато тримесечие → 'предишният 13F е за Q4 2025, а не за Q1 2026'; само един филинг → 'няма 13F за Q1 2026'; неизтеглен → 'не се изтегли днес' — и в трите: без нова/увеличена, SI✓ и изходи")

print()
print("── 5. В5: PUT / CALL извън дългите позиции (РЕАЛНИТЕ Oaktree и Appaloosa) ──")
oak, app = got[OAK], got[APP]
assert len(TABLES["0000949509-26-000005"]) == 145 and len(oak["current_agg"]) == 138 and oak["current_total"] == 5_310_831_670.0                  # отчетено $7 206 070 520 — опциите са 26%
assert "78462F103" not in oak["current_agg"] and oak["current_options"][("78462F103", "PUT")]["value"] == 1_011_873_350.0
hl = {r["company"]: r["pct_of_portfolio"] for r in dataroma._new_position_highlights_from_snapshot(oak, {})}
assert hl == {"INDIVIOR PHARMACEUTICALS INC": 4.7}
real_si = {(r["ticker"], r["pct_of_portfolio"], r["value"]) for r in B16["superinvestor_new_positions"] if r["manager"].endswith(("Oaktree Capital Management", "Appaloosa Management"))}
assert real_si == {("STT", 14.0, 1_011_873_350.0), ("INDV", 3.5, 251_399_508.0), ("AAPL", 3.1, 241_615_600.0), ("BA", 2.2, 173_176_000.0)}          # РЕАЛНИЯТ бриф от 16.10
assert {(c, t): o["value"] for (c, t), o in app["current_options"].items()} == {("037833100", "PUT"): 241_615_600.0, ("084670702", "PUT"): 12_509_750.0}
assert {r["company"]: r["pct_of_portfolio"] for r in dataroma._new_position_highlights_from_snapshot(app, {})} == {"BOEING CO": 2.3}
stt = next(r for r in B16["superinvestor_moves"] if r["ticker"] == "STT")
assert stt["action"] == "нова позиция" and stt["value"] == 1_011_873_350.0 and "STATE STREET CORP" not in {r["company"] for r in dataroma._moves_from_snapshot(oak, 10_000_000, {})}
print("  ✓ брифът от 16.10: SI✓ STT 14.0% и AAPL 3.1% са PUT ($1 011 873 350 и $241 615 600 в 13F); след поправката: Oaktree — само INDV 4.7% (знаменател $5.31 млрд, не $7.21 млрд), "
      "Appaloosa — само BA 2.3%; 'STT нова позиция' го няма в Moves")
summ = dataroma._options_summary("Хауърд Маркс · Oaktree Capital Management", oak)
assert (summ["put"]["count"], summ["put"]["value"], summ["call"]["count"], summ["call"]["value"]) == (4, 1_750_656_350.0, 3, 144_582_500.0)
assert summ["put"]["top"][0] == {"company": "STATE STREET CORP", "cusip": "78462F103", "value": 1_011_873_350.0}                 # CUSIP 78462F103 = SPDR S&P 500 ETF — името е както е в 13F, без тикър по име
print("  ✓ опциите отделно: Oaktree PUT 4 ($1.75 млрд), CALL 3 ($144.6 млн); 'STATE STREET CORP' е с CUSIP 78462F103 (SPY) — без тикър по име")

print()
print("── 6. страницата: ред за опциите (РЕАЛНИЯТ бриф от 16.10 като рамка) ──")
b = copy.deepcopy(B16)
b["superinvestor_status"] = {**(b.get("superinvestor_status") or {}), "options": [summ], "no_comparison": []}
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Опции в 13F — не са дълги позиции и не влизат в % от портфейла" in page
assert "Хауърд Маркс · Oaktree Capital Management — PUT 4 ($1.8 млрд): STATE STREET CORP $1.0 млрд," in page and "; CALL 3 ($144.6 млн): CORE SCIENTIFIC" in page
print("  ✓ 'Хауърд Маркс · Oaktree Capital Management — PUT 4 ($1.8 млрд): STATE STREET CORP $1.0 млрд, … ; CALL 3 ($144.6 млн): CORE SCIENTIFIC …'")

print()
print("── 7. срокът за подаване — почивни дни и празници ──")
assert [dataroma.filing_deadline(D(q)) for q in ("2026-03-31", "2026-06-30", "2026-09-30", "2025-12-31", "2026-12-31")] == \
       [D("2026-05-15"), D("2026-08-14"), D("2026-11-16"), D("2026-02-17"), D("2027-02-16")]                                   # 14.11.2026 събота; 14.02.2026 събота → 16.02 Presidents' Day; 14.02.2027 неделя → 15.02 празник
q4 = {c: [s["filings"]["recent"]["filingDate"][i] for i, (f, r) in enumerate(zip(s["filings"]["recent"]["form"], s["filings"]["recent"]["reportDate"])) if f == "13F-HR" and r == "2025-12-31"]
      for c, s in SUB["submissions"].items() if c in config.DATAROMA_CIK}
on_deadline = sorted(c for c, d in q4.items() if d == ["2026-02-17"])
assert len(on_deadline) == 11                                                                                                     # РЕАЛНО: 11 от 15 подадоха Q4 2025 точно на 17.02.2026
def last_before(c, day):
    r = SUB["submissions"][c]["filings"]["recent"]
    return max(d for f, d in zip(r["form"], r["filingDate"]) if f == "13F-HR" and d < day)
def late_old(last, today):                                                                                                       # старото правило: край + 45 дни, без почивните дни
    ends = [D(f"{y}-{md}") for y in (today.year - 1, today.year) for md in ("03-31", "06-30", "09-30", "12-31")]
    q = max(e for e in ends if e + dt.timedelta(days=45) < today)
    return D(last) <= q
day = D("2026-02-17")                                                                                                           # брифът в 07:30 Берлин — преди подаванията от деня
assert sum(late_old(last_before(c, "2026-02-17"), day) for c in config.DATAROMA_CIK) == 11
assert sum(bool(dataroma.late_filer(last_before(c, "2026-02-17"), day)) for c in config.DATAROMA_CIK) == 0
assert sum(bool(dataroma.late_filer(last_before(c, "2026-02-18"), D("2026-02-18"))) for c in config.DATAROMA_CIK) == 0
assert dataroma.last_quarter_deadline(D("2026-11-16")) == (D("2026-06-30"), D("2026-08-14")) and dataroma.last_quarter_deadline(D("2026-11-17")) == (D("2026-09-30"), D("2026-11-16"))
print("  ✓ Q3 2026 → 16.11; Q4 2025 → 17.02.2026 (събота + Presidents' Day): 11 от 15 подадоха точно тогава — старото правило ги бележеше 'закъснява' сутринта на 17.02, новото — никого")

print("\n✅ test_13f_quarters_options: всичко мина")
