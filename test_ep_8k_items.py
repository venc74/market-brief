"""
28.10.2026 · EP (src/qm_ep.py) — точките на 8-K: заглавката на EDGAR може да е грешна. MANH 27.10, 16:02 ET (0001193125-26-434178): в заглавката — 2.01, 3.03, 5.02, 5.03, 7.01, 9.01,
а в документа — „Item 2.02 Results of Operations and Financial Condition“ (отчетът за Q3), не 2.01 (придобиване на активи); отделен 8-K с т. 2.02 няма. Брифът показа „т. 2.01 — придобиване
или продажба на активи“ и „т. 3.03 — т. 3.03“, „т. 5.03 — т. 5.03“ (липсваха в таблицата). Сега: пълната таблица на Form 8-K; точките се четат и от документа (document_items) и при
противоречие (точка в документа, която я няма в заглавката) се показват тези от документа, с бележка (reconcile_items). Измерено 28.10 върху 198 реални 8-K (60 случайни тикъра,
07–10.2026): 190 съвпадат, 8 — документът показва по-малко точки (не е противоречие), 0 — противоречие; MANH — единственият видян.

РЕАЛНО: tests/fixtures/edgar_8k_items_2026-10-28.json — submissions на MANH (от 01.10), текстът на 8-K-то от 27.10 и 8-K на ADM (04.08, 2.02 / 9.01) за сравнение; свалени от EDGAR 28.10.
СИНТЕТИЧНО (означено): подмененото теглене от EDGAR, падналото теглене на документа.
Пускане: python test_ep_8k_items.py
"""
import sys, json, pathlib, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import qm_ep

FX = json.loads((ROOT / "tests" / "fixtures" / "edgar_8k_items_2026-10-28.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. точките в документа (РЕАЛНИТЕ текстове) ──")
assert qm_ep.document_items(FX["manh_text"]) == ["2.02", "3.03", "5.02", "5.03", "7.01", "9.01"]
assert qm_ep.document_items(FX["ok_doc"]["text"]) == ["2.02", "9.01"] == FX["ok_doc"]["head"]
assert qm_ep.reconcile_items(["2.01", "3.03", "5.02", "5.03", "7.01", "9.01"], qm_ep.document_items(FX["manh_text"])) == (["2.02", "3.03", "5.02", "5.03", "7.01"], "по текста на документа; в заглавката на EDGAR: т. 2.01")
assert qm_ep.reconcile_items(FX["ok_doc"]["head"], qm_ep.document_items(FX["ok_doc"]["text"])) == (["2.02"], None)
assert qm_ep.reconcile_items(["1.01", "2.03", "9.01"], ["2.03", "9.01"]) == (["1.01", "2.03"], None)                         # по-малко разчетени точки — не е противоречие (VVV, 198-те)
assert qm_ep.ITEMS_8K["3.03"][1] == "промяна в правата на акционерите" and qm_ep.ITEMS_8K["5.03"][1] == "промяна в устава / финансовата година"
print("  ✓ MANH: документът — 2.02 (отчетът) и 3.03 / 5.02 / 5.03 / 7.01; заглавката — 2.01 → по документа, с бележка; ADM — съвпадат; 3.03 и 5.03 — с описание")

print()
print("── 2. company_filings върху РЕАЛНИТЕ submissions и документа (СИНТЕТИЧНО теглене) ──")
sub = {"cik": FX["cik"], "filings": {"recent": FX["manh_recent"]}}
calls = []
def get(url):
    calls.append(url)
    if "submissions" in url:
        return json.dumps(sub)
    if url.endswith("manh-20261027.htm"):
        return FX["manh_text"]
    raise ConnectionError(url)
config.QM_EP_EDGAR_8K = True
now = dt.datetime(2026, 10, 28, 5, 30, tzinfo=dt.timezone.utc)
with q():
    fs = qm_ep.company_filings("MANH", "2026-10-27", get=get, cik_map={"MANH": "1056696"}, now_utc=now)
assert len(fs) == 1 and fs[0]["acc"] == "0001193125-26-434178" and fs[0]["accepted_et"] == "2026-10-27 16:02"
assert [c for c, *_ in fs[0]["items"]] == ["2.02", "3.03", "5.02", "5.03", "7.01"] and fs[0]["items_header"] == ["2.01", "3.03", "5.02", "5.03", "7.01"]
h = qm_ep.filing_headline(fs[0])["title"]
assert h == ("8-K (SEC), 27.10 16:02 ET: т. 2.02 — резултати от дейността; т. 3.03 — промяна в правата на акционерите; т. 5.02 — смяна в ръководството; "
             "т. 5.03 — промяна в устава / финансовата година; т. 7.01 — оповестяване по Reg FD (по текста на документа; в заглавката на EDGAR: т. 2.01)"), h
prompt = qm_ep._build_prompt([{"ticker": "MANH", "headlines": [], "filings_8k": fs}])
assert "Item 2.02 Results of Operations and Financial Condition" in prompt and "Item 2.01" not in prompt
print(f"  ✓ «{h[:110]}…»; моделът получава Item 2.02")
def get_fail(url):                                                                              # СИНТЕТИЧНО: документът не се тегли
    if "submissions" in url:
        return json.dumps(sub)
    raise ConnectionError(url)
with q():
    fs2 = qm_ep.company_filings("MANH", "2026-10-27", get=get_fail, cik_map={"MANH": "1056696"}, now_utc=now)
assert [c for c, *_ in fs2[0]["items"]] == ["2.01", "3.03", "5.02", "5.03", "7.01"] and "items_note" not in fs2[0]
print("  ✓ документът не се изтегли → точките от заглавката (както до 28.10), без грешка")
print("\n✅ test_ep_8k_items: всичко мина")
