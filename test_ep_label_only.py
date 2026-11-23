"""
23.11.2026 (пакет 23.11, т. 3): EP — AI остава, но само слага етикета (ключ от CATALYSTS) върху фактите от кода: EPS при отчета срещу очаквания (eps_surprise — Yahoo, при
8-K т. 2.02) и точките на 8-K след затварянето; без AI резюме и без AI „изненада“ (config.EP_AI_LABEL_ONLY = 1).

РЕАЛНО: tests/fixtures/ep_facts_2026-11-23.json — EP редовете ABNB (06.11) и AAON (10.11) от брифовете и EPS редовете от Yahoo (get_earnings_dates), изтеглени на 23.11.
СИНТЕТИЧНО (означено): отговорът на модела.
Пускане: python test_ep_label_only.py
"""
import sys, json, pathlib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import qm_ep

FX = json.loads((ROOT / "tests" / "fixtures" / "ep_facts_2026-11-23.json").read_text(encoding="utf-8"))
assert config.EP_AI_LABEL_ONLY == 1

print("── 1. РЕАЛНО: фактите от кода — EPS при отчета и точките на 8-K ──")
rows = []
for t, v in FX["rows"].items():
    r = copy.deepcopy(v["row"])
    r["eps"] = qm_ep.eps_surprise(t, v["session"], rows=FX["yahoo_earnings"][t])
    r["filings_8k"] = [{**f, "items": [tuple(i) for i in f["items"]]} for f in r.get("filings_8k") or []]
    rows.append(r)
abnb, aaon = rows
assert abnb["eps"] == {"date": "2026-11-05", "reported": 3.16, "estimate": 2.85, "surprise_pct": 11.0}
assert aaon["eps"]["surprise_pct"] == 43.5
f = qm_ep.code_facts(aaon)
assert f["eps_from_code"] == {"reported": 0.83, "estimate": 0.58, "surprise_pct": 43.5}
assert any("Item 4.02" in x for x in f["sec_8k_after_close"]) and any("Item 2.02" in x for x in f["sec_8k_after_close"])
assert qm_ep.code_facts({"eps": {"error": "Yahoo няма отчетен EPS за тази дата"}}) == {"eps_from_code": "не е наличен (Yahoo няма отчетен EPS за тази дата)"}
assert qm_ep.code_facts({"filings_error": "EDGAR: TimeoutError"})["sec_8k_after_close"].startswith("не се провери")
print(f"  ✓ ABNB: EPS $3.16 срещу $2.85 (+11.0%); AAON: $0.83 срещу $0.58 (+43.5%), 8-K: {', '.join(c for c, _, _ in aaon['filings_8k'][0]['items'])}")

print("── 2. промптът — факти → само етикет ──")
p = qm_ep._build_prompt(rows)
assert '"eps_from_code": {"reported": 3.16, "estimate": 2.85, "surprise_pct": 11.0}' in p and "САМО етикета" in p
assert "summary_bg" not in p and '"surprise"' not in p
print("  ✓ без резюме и без „изненада“ в заявката")

print("── 3. отговорът (СИНТЕТИЧЕН): резюмето и „изненадата“ на AI не минават ──")
ans = {"items": [{"ticker": "ABNB", "catalyst": "earnings_guidance", "summary_bg": "Airbnb отчете Q3 над очакванията", "surprise": "yes"},
                 {"ticker": "AAON", "catalyst": "измислен_ключ"}]}
cls, notes = qm_ep.classify_catalysts(rows, ai_call=lambda system, user: json.dumps(ans, ensure_ascii=False))
assert cls["ABNB"] == {"ticker": "ABNB", "catalyst": "earnings_guidance", "catalyst_label": "Отчет / guidance", "summary_bg": None, "surprise": "unclear"}
assert cls["AAON"]["catalyst"] == "unknown" and cls["AAON"]["summary_bg"] is None
print("  ✓ ABNB → „Отчет / guidance“ без резюме; ключ извън списъка → „Неясен катализатор“")
print(f"  (за сравнение — AI резюмето от 06.11, вече го няма: «{FX['rows']['ABNB']['row'].get('summary_bg', '')[:80]}…»)")

print("── 4. EP_AI_LABEL_ONLY = 0 връща старото ──")
config.EP_AI_LABEL_ONLY = 0
try:
    assert "summary_bg" in qm_ep._build_prompt(rows)
    v, _ = qm_ep.verify_ai_item(ans["items"][0], abnb["headlines"], {"ABNB"})
    assert v["summary_bg"] and v["surprise"] == "yes"
finally:
    config.EP_AI_LABEL_ONLY = 1
print("  ✓")
print("\n✅ test_ep_label_only: всичко мина")
