"""
21.10.2026 · етап 3б (решение на Венци): ЦЕЛ НА ПРИДОБИВАНЕ — САМО МАРКЕР върху картата („цел на придобиване (купувач, дата на обявяване)“), картата остава. Откриването е в модула за
отделяния (spinoff_watch), който вече чете submissions на нашите тикъри: 8-K с т. 1.01, в който ПОДАТЕЛЯТ е целта — в 8-K на купувача "the Company" е целта по дефиницията на
договора (FOX за Roku), затова се проверява кой е "the Company". В продукция — config.EDGAR_UA от secrets (същият като за 13F / Form 4 / отделянията).

Измерено на 21.10 върху ВСИЧКИ 8-K с т. 1.01 на 903-те тикъра от универса (1 192 документа, 10.2025–10.2026): 19 засичания — 15 цели + страните в 3 сливания на равни, всичките
истински; 0 в 8-K на купувачите; купувачът — вярното име и при 19-те. Докладът: 18 цели висяха в прозореца на брифовете, 3 са били карти докато сделката виси (ROKU 27 дни, NWE и CRBG по 2).

РЕАЛНО: tests/fixtures/edgar_8k_merger_2026-10-21.json (текстовете на 17 реални 8-K и редовете от submissions на ROKU), tests/fixtures/card_roku_2026-10-20.json (реалната карта на ROKU
от Watchlist на 20.10), tests/fixtures/brief_2026-10-19.json (реалният бриф за рендера). СИНТЕТИЧНО (означено): подмененото теглене от EDGAR, по-късните 8-K с т. 5.01 / 1.02,
вмъкването на картата на ROKU в брифа от 19.10.
Пускане: python test_merger_marker.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_merger_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import spinoff_watch as sw, render

FX = json.loads((ROOT / "tests" / "fixtures" / "edgar_8k_merger_2026-10-21.json").read_text(encoding="utf-8"))
CARD = json.loads((ROOT / "tests" / "fixtures" / "card_roku_2026-10-20.json").read_text(encoding="utf-8"))["card"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. детекторът върху 17 РЕАЛНИ 8-K ──")
WANT = {"ROKU": ("Fox Corporation", "2026-06-14"), "SLAB": ("Texas Instruments Incorporated", "2026-02-04"), "VAL": ("Transocean Ltd.", "2026-02-09"),
        "AES": ("Horizon Parent, L.P.", "2026-03-01"), "TECH": ("Merck KGaA, Darmstadt, Germany", "2026-06-25"), "PTC": ("Schneider Electric SE", "2026-10-04"),
        "OPCH": ("Onyx Bidco LLC", "2026-10-05"), "TXNM": ("Troy ParentCo LLC", "2025-05-18"), "AXTA": ("AkzoNobel", "2025-11-18")}
for d in FX["docs"]:
    h = sw.detect_merger(d["text"], d["filer"], d["filed"])
    if d["kind"] == "target":
        assert h and (h["buyer"], h["announced"]) == WANT[d["ticker"]], (d["ticker"], h)
    else:
        assert h is None, (d["kind"], d["ticker"], h)
print("  ✓ 9 цели — купувач и дата на обявяване (ROKU: Fox Corporation, 14.06.2026; TXNM: изменение, договорът е от 18.05.2025); 6 купувачи (FOX, VRTX, JAZZ, CRH, CPRT, VRT) — нищо;"
      " AES 19.03 (кредит) и NWE (облигации) — нищо")
assert sw.same_company("TXNM", "TXNM ENERGY INC") and sw.same_company("Roku, Inc.", "ROKU, INC") and not sw.same_company("Arcosa", "CRH PUBLIC LTD CO")

print()
print("── 2. висяща ли е сделката (РЕАЛНИТЕ подавания на ROKU) ──")
SUB = FX["roku_submissions"]
assert sw.merger_state(SUB, "2026-06-15") is None
closed = copy.deepcopy(SUB); r = closed["filings"]["recent"]
for k, v in (("form", "8-K"), ("filingDate", "2026-10-16"), ("items", "2.01,3.01,5.01"), ("accessionNumber", "0000000000-26-999999"), ("primaryDocument", "close.htm")):
    r[k].append(v)                                                                                        # СИНТЕТИЧНО: приключване
assert sw.merger_state(closed, "2026-06-15") == "closed"
print("  ✓ до 20.10 — без 8-K т. 5.01 / Form 25 → виси; с 8-K т. 5.01 след обявяването (СИНТЕТИЧНО) → приключила")

print()
print("── 3. check(): засичане, кеш, приключване, прекратяване (СИНТЕТИЧНО теглене от EDGAR) ──")
ROKU_DOC = next(d for d in FX["docs"] if d["ticker"] == "ROKU")
TERM = "Item 1.02 Termination of a Material Definitive Agreement. On October 15, 2026, the Merger Agreement was terminated by mutual consent."     # СИНТЕТИЧНО
calls = []


def make_get(sub, term=False):
    def get(url):
        calls.append(url)
        if "submissions" in url:
            return json.dumps(sub)
        if url.endswith("index.json"):
            return json.dumps({"directory": {"item": []}})
        if ROKU_DOC["accession"].replace("-", "") in url:
            return ROKU_DOC["text"]
        if "term.htm" in url:
            return TERM if term else ""
        return ""
    return get


def run(sub, term=False):
    calls.clear()
    with q():
        sw.check(["ROKU"], today=dt.date(2026, 10, 20), get=make_get(sub, term), cik_map={"ROKU": SUB["cik"]}, merger_tickers=["ROKU"])
    return dict(sw.LAST_MERGERS)


m = run(SUB)
assert m["ROKU"]["buyer"] == "Fox Corporation" and m["ROKU"]["announced"] == "2026-06-14" and m["ROKU"]["filing_date"] == "2026-06-15"
assert sw.LAST_DIAG["mergers"] == [{"ticker": "ROKU", "buyer": "Fox Corporation", "announced": "2026-06-14", "filing_date": "2026-06-15"}] and sw.LAST_DIAG["merger_fetched"] >= 1
cache = json.loads((config.DATA_DIR / config.SPINOFF_CACHE_NAME).read_text(encoding="utf-8"))
assert cache["merger_docs"][ROKU_DOC["accession"]]["hit"]["buyer"] == "Fox Corporation"
m2 = run(SUB)
assert m2 == m and not any(ROKU_DOC["accession"].replace("-", "") in u for u in calls)                       # вторият run — от кеша, документът не се тегли пак
assert run(closed) == {}
term = copy.deepcopy(SUB); r = term["filings"]["recent"]
for k, v in (("form", "8-K"), ("filingDate", "2026-10-15"), ("items", "1.02"), ("accessionNumber", "0000000000-26-888888"), ("primaryDocument", "term.htm")):
    r[k].append(v)                                                                                        # СИНТЕТИЧНО: прекратяване
assert run(term, term=True) == {}
other = copy.deepcopy(SUB); r = other["filings"]["recent"]
for k, v in (("form", "8-K"), ("filingDate", "2026-10-15"), ("items", "1.02"), ("accessionNumber", "0000000000-26-777777"), ("primaryDocument", "term.htm")):
    r[k].append(v)                                                                                        # СИНТЕТИЧНО: т. 1.02 за друг договор (напр. кредит) — сделката виси
assert run(other, term=False)["ROKU"]["buyer"] == "Fox Corporation"
with q():
    sw.check(["ROKU"], today=dt.date(2026, 10, 20), get=make_get(SUB), cik_map={"ROKU": SUB["cik"]}, merger_tickers=[])
assert sw.LAST_MERGERS == {}                                                                              # само тикърите на картите
print("  ✓ ROKU → Fox Corporation, обявено 14.06.2026; вторият run — от кеша; приключила / прекратена (договорът за сливане) → без маркер; тикър извън картите — не се търси")

print()
print("── 4. маркерът върху РЕАЛНАТА карта на ROKU (20.10) — страницата и имейлът ──")
card = copy.deepcopy(CARD)
assert sw.annotate_mergers([[card]], m) == 1
text = "⚠ Цел на придобиване (Fox Corporation, обявено 14.06.2026) — цената следва условията на сделката"
assert card["merger_target"]["text"] == text and card["ticker"] == "ROKU"
b = copy.deepcopy(B19); b["watchlist"] = [card] + b["watchlist"]                                           # СИНТЕТИЧНО: картата от 20.10 в брифа от 19.10
page = re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(b, publish=False)))
mail = re.sub(r"\s+", " ", htmllib.unescape(render.render_email(b)))
assert text in page and text in mail and len(b["watchlist"]) == len(B19["watchlist"]) + 1          # картата остава (само маркер)
print(f"  ✓ «{text}» — на картата в страницата и в имейла; картата не е махната")

src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "merger_tickers=card_tickers" in src and "spinoff_watch.annotate_mergers([action, watchlist, qm_cards, glb_candidates])" in src
assert config.ENABLE_MERGER_MARKER and config.MERGER_LOOKBACK_DAYS == 540
print("  ✓ main: търсенето е само за тикърите на картите, маркерът — върху Action / Watchlist / Kullamägi / GLB")
print("\n✅ test_merger_marker: всичко мина")
