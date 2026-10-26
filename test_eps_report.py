"""
26.10.2026 · решение по етап 4б, т. 2: EPS на картата — основното число е „EPS ръст (от отчета)“: последното отчетено тримесечие срещу същото година по-рано (enrich.eps_report_yoy, от
get_earnings_dates — тегли се за всяка карта); earningsQuarterlyGrowth на Yahoo (полето eps_growth_yoy) е ръстът на НЕТНАТА ПЕЧАЛБА — показва се само с изричен етикет. Моделът получава
двете под честни имена; текстът за изключен по CANSLIM казва „нетна печалба г/г … (Yahoo)“.

Случаят (РЕАЛЕН): AMG — „EPS +120.5%“ на картата беше нетната печалба (Q2 2026 $185.9 млн / Q2 2025 $84.3 млн); EPS от отчета е $8.29 / $5.39 = +53.8%. RS — +120.3% = EPS $8.02 / $3.64.
В историята: от 85 (тикър, отчет) EPS от отчета имаше само при 9 (прегледът на отчетите се смята само при скорошен отчет) — сега се смята винаги.

РЕАЛНО: tests/fixtures/eps_report_amg_rs_2026-10-26.json — get_earnings_dates и earningsQuarterlyGrowth на AMG и RS (Yahoo, 26.10) и картата на AMG от 26.10;
tests/fixtures/brief_2026-10-16.json — реалният бриф за рендера (с една Action карта). СИНТЕТИЧНО (означено): тикърът, EPS и отчетите на AMG върху Action картата на брифа от 16.10, подмененото извикване на модела.
Пускане: python test_eps_report.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_eps_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import enrich, render, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "eps_report_amg_rs_2026-10-26.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


def past(sym):
    rows = FX["rows"][sym]
    df = pd.DataFrame([{k: r[k] for k in ("EPS Estimate", "Reported EPS", "Surprise(%)")} for r in rows], index=pd.to_datetime([r["ts"] for r in rows], utc=True))
    return df[df.index <= pd.Timestamp("2026-10-26", tz="UTC")]


print("── 1. EPS от отчета г/г (РЕАЛНИТЕ отчети) ──")
amg, rs = enrich.eps_report_yoy(past("AMG")), enrich.eps_report_yoy(past("RS"))
assert amg == {"pct": 53.8, "current": 8.29, "yoy": 5.39, "date": "2026-07-30", "yoy_date": "2025-07-31"}
assert rs == {"pct": 120.3, "current": 8.02, "yoy": 3.64, "date": "2026-10-21", "yoy_date": "2025-10-22"}
assert round(FX["eqg"]["AMG"] * 100, 1) == 120.5 and round(FX["eqg"]["RS"] * 100, 1) == 112.6                         # нетната печалба (Yahoo) — друго число
assert enrich.eps_report_yoy(past("AMG").iloc[:2]) is None and enrich.eps_report_yoy(None) is None                   # без тримесечие година по-рано
print(f"  ✓ AMG: EPS {amg['current']} / {amg['yoy']} = {amg['pct']:+.1f}% (нетна печалба по Yahoo +120.5%); RS: {rs['pct']:+.1f}% (Yahoo +112.6%)")

print()
print("── 2. картата (полетата на РЕАЛНАТА карта на AMG върху Action картата от 16.10 — СИНТЕТИЧНО) ──")
card = copy.deepcopy(FX["card_amg_2026_10_26"])
card["earnings"] = {**(card.get("earnings") or {}), "eps_report_yoy": amg}
assert card["eps_growth_yoy"] == 120.5
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
a0 = copy.deepcopy(b["action"][0]); a0.update({k: card[k] for k in ("ticker", "company", "eps_growth_yoy", "earnings")})
b["action"] = [a0] + b["action"][1:]
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "EPS ръст (от отчета) +53.8% (EPS $8.29 срещу $5.39, 30.07 г/г)" in page and "Ръст на нетната печалба (Yahoo, тримесечие г/г) +120.5%" in page
assert "EPS ръст YoY" not in page
old = copy.deepcopy(b); old["action"][0]["earnings"] = {k: v for k, v in a0["earnings"].items() if k != "eps_report_yoy"}; old["action"][0]["earnings"]["recap"] = None
with q():
    page_old = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(old, publish=False))))
assert "EPS ръст (от отчета) —" in page_old and "Ръст на нетната печалба (Yahoo, тримесечие г/г) +120.5%" in page_old
print("  ✓ „EPS ръст (от отчета) +53.8% (EPS $8.29 срещу $5.39, 30.07 г/г)“ и „Ръст на нетната печалба (Yahoo, тримесечие г/г) +120.5%“; стар бриф без полето — „—“ и етикетираният ред")

print()
print("── 3. моделът — честните имена ──")
sent = []
real = ai_brief._call_claude
ai_brief._call_claude = lambda system, user, **k: (sent.append(user), '{"tickers": []}')[1]                         # СИНТЕТИЧНО
try:
    c = copy.deepcopy(card); c["setup"] = {"kind": "below_pivot", "trigger_text": "…"}
    with q():
        ai_brief.ticker_narratives([c], [], "Defensive")
finally:
    ai_brief._call_claude = real
assert sent and '"eps_growth_report_pct": 53.8' in sent[0] and '"net_income_growth_yoy_yahoo_pct": 120.5' in sent[0] and '"eps_growth_yoy"' not in sent[0]
print("  ✓ промптът: eps_growth_report_pct 53.8 и net_income_growth_yoy_yahoo_pct 120.5 (без eps_growth_yoy)")
print("\n✅ test_eps_report: всичко мина")
