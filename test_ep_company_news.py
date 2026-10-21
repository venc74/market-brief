"""
21.10.2026 · етап 4 (решение от 21.10): EP предпочита новината за самата компания. Реално на 21.10 и трите заглавия на Yahoo за SMCI бяха прегледи на пазара
(„Dow Jones Futures: SpaceX, Supermicro Revive AI Stocks…“), а катализаторът — 8-K на SMCI с т. 2.02 (резултати), приет на 20.10 в 20:44 ET. Сега: 8-K-тата на компанията,
приети след затварянето (EDGAR submissions), са първият ред на картата и отделно поле за AI; заглавията за самата компания — преди общите прегледи на пазара.

РЕАЛНО: tests/fixtures/ep_8k_2026-10-21.json — 8-K записите на SMCI и HUM от EDGAR (свалени 21.10.2026) и qm_ep от брифовете на 09.10 (HUM) и 21.10 (SMCI);
tests/fixtures/brief_2026-10-19.json — реалният бриф за страницата. СИНТЕТИЧНО (означено): отговорът на AI, CIK картата, провалът на заявката, заглавието „за компанията“ в т. 2.
Пускане: python test_ep_company_news.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_ep8k_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, render

FX = json.loads((ROOT / "tests" / "fixtures" / "ep_8k_2026-10-21.json").read_text(encoding="utf-8"))
UTC = dt.timezone.utc
brief_time = lambda d: dt.datetime.fromisoformat(d).replace(hour=5, minute=30, tzinfo=UTC)          # 07:30 Берлин (лятно време) = 05:30 UTC

print("── 1. 8-K след затварянето (РЕАЛНИТЕ записи на EDGAR) ──")
smci = qm_ep.filings_after_close(FX["submissions"]["SMCI"], "2026-10-20", brief_time("2026-10-21"))
assert len(smci) == 1 and smci[0]["accepted_et"] == "2026-10-20 20:44" and [c for c, _, _ in smci[0]["items"]] == ["2.02"]      # 9.01 (приложения) не се показва
assert qm_ep.filing_headline(smci[0]) == {"title": "8-K (SEC), 20.10 20:44 ET: т. 2.02 — резултати от дейността", "published": "2026-10-20 20:44", "source": "SEC"}
assert qm_ep.filings_after_close(FX["submissions"]["HUM"], "2026-10-08", brief_time("2026-10-09")) == []          # 8-K на HUM е приет на 09.10 в 10:01 ET — след брифа
late = qm_ep.filings_after_close(FX["submissions"]["HUM"], "2026-10-08", dt.datetime(2026, 10, 9, 15, 0, tzinfo=UTC))
assert [c for c, _, _ in late[0]["items"]] == ["7.01"] and late[0]["accepted_et"] == "2026-10-09 10:01"
assert qm_ep.filings_after_close(FX["submissions"]["SMCI"], "2026-10-15", brief_time("2026-10-16")) == []         # 8-K от 15.10 (5.02) е приет в 13:08 ET — преди затварянето
print("  ✓ SMCI: 8-K т. 2.02, приет 20.10 в 20:44 ET → „8-K (SEC), 20.10 20:44 ET: т. 2.02 — резултати от дейността“; HUM: 8-K т. 7.01 е от 09.10 10:01 ET — след брифа, не влиза")

print()
print("── 2. заглавията: самата компания преди общите прегледи ──")
smci_h = FX["qm_ep"]["SMCI"]["rows"][0]["headlines"]
assert all(qm_ep.OVERVIEW_RE.search(h["title"]) for h in smci_h)                                       # и трите реални — прегледи на пазара
assert [h["title"] for h in qm_ep.rank_headlines(smci_h, "SMCI", "Super Micro Computer, Inc.")] == [h["title"] for h in smci_h]
hum_h = FX["qm_ep"]["HUM"]["rows"][0]["headlines"]
assert qm_ep.rank_headlines(hum_h, "HUM", "Humana Inc.")[0]["title"].startswith("Humana Stock Surges")
mix = [{"title": smci_h[0]["title"]}, {"title": "Super Micro Computer raises its outlook on AI demand"}]          # СИНТЕТИЧНО второто
assert qm_ep.rank_headlines(mix, "SMCI", "Super Micro Computer, Inc.")[0]["title"].startswith("Super Micro Computer raises")
print("  ✓ SMCI — и трите реални заглавия са прегледи (редът остава, 8-K-то е отгоре); HUM — „Humana Stock Surges …“ остава първо; заглавие за компанията изпреварва прегледа")

print()
print("── 3. заявката към EDGAR и AI ──")
calls = []
got = qm_ep.company_filings("SMCI", "2026-10-20", get=lambda u: (calls.append(u), json.dumps(FX["submissions"]["SMCI"]))[1], cik_map={"SMCI": "1375365"}, now_utc=brief_time("2026-10-21"))
assert got == smci and calls == ["https://data.sec.gov/submissions/CIK0001375365.json"]
with contextlib.redirect_stdout(io.StringIO()):
    assert qm_ep.company_filings("SMCI", "2026-10-20", get=lambda u: (_ for _ in ()).throw(TimeoutError("SEC")), cik_map={"SMCI": "1375365"}) == []
assert qm_ep.company_filings("ZZZZ", "2026-10-20", get=lambda u: "{}", cik_map={}) == []
config.QM_EP_EDGAR_8K = False
assert qm_ep.company_filings("SMCI", "2026-10-20", get=lambda u: json.dumps(FX["submissions"]["SMCI"]), cik_map={"SMCI": "1375365"}) == []
config.QM_EP_EDGAR_8K = True
row = {"ticker": "SMCI", "filings_8k": smci, "headlines": [qm_ep.filing_headline(smci[0])] + smci_h}
prompt = qm_ep._build_prompt([row])
payload = json.loads(prompt[prompt.index("["):prompt.index("]\n\nКАТАЛИЗАТОРИ") + 1])
assert payload[0]["sec_8k_after_close"] == ["2026-10-20 20:44 ET — Item 2.02 Results of Operations and Financial Condition"]
assert len(payload[0]["headlines"]) == 3 and "8-K (SEC)" not in " ".join(payload[0]["headlines"]) and "най-прякото доказателство" in prompt
ai = lambda system, user: json.dumps({"items": [{"ticker": "SMCI", "catalyst": "earnings_guidance", "summary_bg": "Super Micro подаде 8-K с резултатите си след затварянето.", "surprise": "yes"}]})
cls, notes = qm_ep.classify_catalysts([row], ai)
assert cls["SMCI"]["catalyst"] == "earnings_guidance" and cls["SMCI"]["summary_bg"] and not notes
print("  ✓ една заявка към submissions на SEC; провал / без CIK / изключено → нищо; AI получава 8-K-то отделно (Item 2.02 …), а заглавията — без реда на SEC")

print()
print("── 4. страницата (РЕАЛНИЯТ ред на SMCI от 21.10 в брифа от 19.10) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
ep = copy.deepcopy(FX["qm_ep"]["SMCI"]); ep.pop("brief")
ep["rows"][0]["headlines"] = [qm_ep.filing_headline(smci[0])] + smci_h[:2]
b["qm_ep"] = ep
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b)
assert "8-K (SEC), 20.10 20:44 ET: т. 2.02 — резултати от дейността" in page
print("  ✓ първият ред на EP картата е 8-K-то на компанията")
print("\n✅ test_ep_company_news: всичко мина")
