"""
19.10.2026 · етап 2, доп. т. 8 + т. 17а: тикърът на 13F реда е по CUSIP (src/cusip_map.py → OpenFIGI), после по име; неразпознат → "без тикър" (не името на емитента като тикър).
Опциите се показват с тикъра по CUSIP: PUT-ът на Oaktree "STATE STREET CORP" е CUSIP 78462F103 = SPY.

РЕАЛНО:
  • tests/fixtures/openfigi_mapping_2026-10-19.json — дословните отговори на OpenFIGI v3 /mapping (19.10.2026, exchCode=US, ID_CINS за кодовете с буква) за 20 CUSIP-а от реалните 13F + 000000000;
  • tests/fixtures/sec_13f_infotable_1061165_0000919574-26-005485.xml (Lone Pine Q2 2026), _1569205_0001569205-26-000012.xml (Fundsmith), _1581811_0001581811-26-000007.xml (Egerton),
    _949509_0000949509-26-000005.xml (Oaktree) — свалени от sec.gov на 19.10/16.10, SHA-256 сверен с файла на SEC;
  • tests/fixtures/brief_2026-10-19.json — 8 от 36 нови позиции без тикър (Seagate, Mastercard ×2, Applied Materials ×2, TSMC, On Holding, TJX), "AMPHENOL CORP" и "SEAGATE TECHNOLOGY" в Moves.
СИНТЕТИЧНО (маркирано): подмененото извикване (post) и часовникът, датите за давността на кеша, грешката на мрежата, минималната карта по име.
Пускане: python test_cusip_tickers.py
"""
import sys, json, copy, pathlib, tempfile, re, io, contextlib, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cusip_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import cusip_map, dataroma, render

FX = ROOT / "tests" / "fixtures"
OF = json.loads((FX / "openfigi_mapping_2026-10-19.json").read_text(encoding="utf-8"))
RESP = {}
for b in OF["batches"]:
    for j, item in zip(b["request"], json.loads(b["response_text"])):
        RESP[j["idValue"]] = (j, item)
B19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
quiet = lambda: contextlib.redirect_stdout(io.StringIO())
D = dt.date.fromisoformat

print("── 1. парсерът върху РЕАЛНИЯ отговор на OpenFIGI ──")
cus = sorted(RESP)
assert cusip_map.jobs(["78462F103", "G7997R103"]) == [{"idType": "ID_CUSIP", "idValue": "78462F103", "exchCode": "US"}, {"idType": "ID_CINS", "idValue": "G7997R103", "exchCode": "US"}]
assert all(RESP[c][0] == cusip_map.jobs([c])[0] for c in cus)                                            # задачите в fixture-а са точно тези на кода
parsed = {}
for b in OF["batches"]:
    parsed.update(cusip_map.parse([j["idValue"] for j in b["request"]], json.loads(b["response_text"])))
tick = {c: (v or {}).get("ticker") for c, v in parsed.items()}
assert tick["78462F103"] == "SPY" and tick["46090E103"] == "QQQ" and tick["084670702"] == "BRK-B" and tick["G7997R103"] == "STX" and tick["H5919C104"] == "ONON"
assert tick["57636Q104"] == "MA" and tick["038222105"] == "AMAT" and tick["874039100"] == "TSM" and tick["872540109"] == "TJX" and tick["032095101"] == "APH"
assert parsed["000000000"] is None and sum(1 for v in parsed.values() if v) == 20
assert parsed["78462F103"]["name"] == "SS SPDR S&P 500 ETF TRUST-US" and parsed["78462F103"]["type"] == "ETP"
print("  ✓ 20 от 20 реални CUSIP-а: 78462F103 → SPY (ETP), QQQ (не 'NDQ'), BRK/B → BRK-B, CINS G7997R103 → STX, H5919C104 → ONON; 000000000 → няма")

print()
print("── 2. resolve: кеш, давност, бюджет, провал (СИНТЕТИЧНИ post/часовник) ──")
calls = []
def post(jobs):
    calls.append([j["idValue"] for j in jobs])
    return [RESP[j["idValue"]][1] if j["idValue"] in RESP else RESP["000000000"][1] for j in jobs]       # непознат → реалният формат "No identifier found."
r1 = cusip_map.resolve(cus, post=post, today=D("2026-10-19"), sleep=lambda s: None)
assert len(calls) == 3 and {c: v["ticker"] for c, v in r1.items()} == {c: t for c, t in tick.items() if t} and cusip_map.LAST_STATUS["fetched"] == 20 and cusip_map.LAST_STATUS["not_found"] == 1
cache = json.loads(cusip_map.cache_path().read_text())
assert cache["78462F103"] == {"ticker": "SPY", "name": "SS SPDR S&P 500 ETF TRUST-US", "type": "ETP", "date": "2026-10-19"} and cache["000000000"] == {"date": "2026-10-19"}
calls.clear()
r2 = cusip_map.resolve(cus, post=post, today=D("2026-11-18"), sleep=lambda s: None)                       # СИНТЕТИЧНО: след 30 дни — от кеша, без заявка
assert calls == [] and r2 == r1 and cusip_map.LAST_STATUS["from_cache"] == 21
r3 = cusip_map.resolve(cus, post=post, today=D("2026-11-19"), sleep=lambda s: None)                       # 31 дни: ненамереното се пита пак, намереното — от кеша
assert calls == [["000000000"]] and r3 == r1
calls.clear()
cusip_map.resolve(cus, post=post, today=D("2027-01-18"), sleep=lambda s: None)                             # 91 дни: всичко се опреснява
assert sum(map(len, calls)) == 21
cusip_map.cache_path().unlink()
t = iter(range(0, 1000, 59))                                                                              # СИНТЕТИЧНО: часовник — бюджетът (60 s) стига за 1 заявка
calls.clear()
r4 = cusip_map.resolve(cus, post=post, today=D("2026-10-19"), sleep=lambda s: None, clock=lambda: next(t))
assert len(calls) == 1 and cusip_map.LAST_STATUS["skipped"] == 11 and len(r4) == 9          # първата партида съдържа 000000000
def boom(jobs):
    raise ConnectionError("OpenFIGI недостъпен (СИНТЕТИЧНО)")
cusip_map.cache_path().unlink()
with quiet():
    r5 = cusip_map.resolve(cus, post=boom, today=D("2026-10-19"), sleep=lambda s: None)
assert r5 == {} and "ConnectionError" in cusip_map.LAST_STATUS["error"] and not cusip_map.cache_path().exists()
print("  ✓ първи run: 3 заявки, кеш; след 30 дни — нито една; след 31 — само ненамереното; след 91 — всичко; бюджетът спира с 'skipped'; мрежов провал → {} без запис")

print()
print("── 3. неразпознатите от брифа на 19.10 — с CUSIP от РЕАЛНИЯ 13F на мениджъра ──")
files = {"Стивън Мандел · Lone Pine Capital": "sec_13f_infotable_1061165_0000919574-26-005485.xml", "Тери Смит · Fundsmith": "sec_13f_infotable_1569205_0001569205-26-000012.xml",
         "Джон Армитидж · Egerton Capital": "sec_13f_infotable_1581811_0001581811-26-000007.xml", "Бил Акман · Pershing Square": "sec_13f_infotable_2026053_0001172661-26-003790.xml"}
by_mgr = {m: {r["issuer"]: r["cusip"] for r in dataroma._parse_info_table((FX / f).read_text(encoding="utf-8")) if not r["putcall"]} for m, f in files.items()}
un = [dict(r) for r in B19["superinvestor_new_positions"] + B19["superinvestor_moves"] if r.get("_resolved") is False]
assert sorted({r["company"] for r in un}) == ["AMPHENOL CORP", "APPLIED MATLS INC", "MASTERCARD INCORPORATED", "ON HLDG AG", "SEAGATE TECHNOLOGY HLDNGS PL", "TAIWAN SEMICONDUCTOR MANUFAC", "TJX COS INC NEW"]
for r in un:
    mgr = r.get("manager") or r["managers"][0]
    r["cusip"] = by_mgr[mgr][r["company"]]
cusip_map.cache_path().unlink(missing_ok=True)
orig = cusip_map._post
cusip_map._post = post
try:
    with quiet():
        dataroma._apply_cusip_tickers(un)
finally:
    cusip_map._post = orig
got_t = {r["company"]: r["ticker"] for r in un}
assert got_t == {"SEAGATE TECHNOLOGY HLDNGS PL": "STX", "MASTERCARD INCORPORATED": "MA", "APPLIED MATLS INC": "AMAT", "TAIWAN SEMICONDUCTOR MANUFAC": "TSM", "ON HLDG AG": "ONON",
                 "TJX COS INC NEW": "TJX", "AMPHENOL CORP": "APH"}
assert all(r["_resolved"] and r["ticker_source"] == "cusip" for r in un)
print("  ✓ 'SEAGATE TECHNOLOGY' → STX, 'MASTERCARD INCORPORATED' → MA, 'APPLIED MATLS INC' → AMAT, TSMC → TSM, 'ON HLDG AG' → ONON, TJX → TJX, Amphenol → APH")

print()
print("── 4. CUSIP пред името; неразпознат → без тикър; опциите (РЕАЛНИЯТ Oaktree) ──")
rows = [{"ticker": "STT", "_resolved": True, "cusip": "78462F103", "company": "STATE STREET CORP", "manager": "M", "value": 1.0},              # СИНТЕТИЧНО: картата по име даваше STT
        {"ticker": "NO NAME CO", "_resolved": False, "cusip": "000000000", "company": "NO NAME CO", "manager": "M", "value": 2.0},
        {"ticker": "OTHER CO", "_resolved": False, "cusip": "999999999", "company": "OTHER CO", "manager": "N", "value": 3.0}]
oak = dataroma._aggregate_by_cusip(dataroma._parse_info_table((FX / "sec_13f_infotable_949509_0000949509-26-000005.xml").read_text(encoding="utf-8")))
oak_opts = dataroma._options_by_cusip(dataroma._parse_info_table((FX / "sec_13f_infotable_949509_0000949509-26-000005.xml").read_text(encoding="utf-8")))
summ = dataroma._options_summary("Хауърд Маркс · Oaktree Capital Management", {"period": "13F · 2026-08-14", "current_options": oak_opts})
cusip_map._post = post
try:
    with quiet():
        dataroma._apply_cusip_tickers(rows, [summ])
finally:
    cusip_map._post = orig
assert rows[0]["ticker"] == "SPY" and rows[0]["ticker_by_name"] == "STT" and rows[1]["ticker"] is None and rows[2]["ticker"] is None
assert [r["ticker"] for r in dataroma._dedupe_by_ticker(rows)] == ["SPY", None, None]                                                    # двата без тикър НЕ се сливат
assert set(dataroma.superinvestor_map(rows)) == {"SPY"}
assert summ["put"]["top"][0]["ticker"] == "SPY" and summ["put"]["top"][0]["figi_name"] == "SS SPDR S&P 500 ETF TRUST-US" and summ["put"]["top"][1]["ticker"] == "QQQ"
assert [t["ticker"] for t in summ["call"]["top"]] == ["CORZ", "BTDR", "MX"]
print("  ✓ STT по име → SPY по CUSIP; без тикър — два отделни реда (не се сливат), не са маркер; опциите на Oaktree: PUT SPY, QQQ …; CALL CORZ, BTDR, MX")

print()
print("── 5. страницата (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
b = copy.deepcopy(B19)
b["superinvestor_moves"] = [{**b["superinvestor_moves"][0]}, {"ticker": None, "_resolved": False, "cusip": "999999999", "company": "OTHER CO", "manager": "N", "action": "нова позиция", "value": 3e7, "period": "13F · 2026-08-14"}]
b["superinvestor_status"] = {**b["superinvestor_status"], "options": [summ]}
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "без тикър" in page and "Хауърд Маркс · Oaktree Capital Management — PUT 4 ($1.8 млрд): SPY $1.0 млрд, QQQ $651.7 млн" in page and "STATE STREET CORP $1.0 млрд" not in page
mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_email(b))))
assert "без тикър (OTHER)" in mail                                                                                     # display_name маха правното окончание "CO"
print("  ✓ 'без тикър' на картата; 'PUT 4 ($1.8 млрд): SPY $1.0 млрд, QQQ $651.7 млн …' (беше 'STATE STREET CORP $1.0 млрд'); в имейла 'без тикър (OTHER)'")
print("\n✅ test_cusip_tickers: всичко мина")
