"""
06.11.2026 (пакет 05–06.11, т. 3): карта без известна дата на отчета (earnings_status "no_date") — видимо „Дата на отчета неизвестна — правилото 5 дни не може да се провери.“ на картата „Чака
пробив“, на картата Action, на реда „На радара“ и в имейла. Класът не се сменя (при "failed" картата вече е Watchlist).

РЕАЛНО: tests/fixtures/no_date_card_2026-11-06.json — картата на MNST от 06.11 (без recap и описание); tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): същата карта на радара (kind too_wide) и като Action в т. 2; картата с дата.
Пускане: python test_earnings_no_date.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_nodate_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render, enrich

CARD = json.loads((ROOT / "tests" / "fixtures" / "no_date_card_2026-11-06.json").read_text(encoding="utf-8"))["card"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
T = enrich.NO_DATE_TEXT
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))


def both(**over):
    b = copy.deepcopy(B19); b.update(action=[], watchlist=[]); b.update(over)
    with contextlib.redirect_stdout(io.StringIO()):
        return flat(render.render_dashboard(b, publish=False)), flat(render.render_email(b))


print("── 1. РЕАЛНАТА карта на MNST (06.11): „Чака пробив“ ──")
assert CARD["earnings"]["earnings_status"] == "no_date" and CARD["setup"]["kind"] == "below_pivot" and enrich.no_date(CARD)
assert T == "Дата на отчета неизвестна — правилото 5 дни не може да се провери."
p, m = both(watchlist=[CARD])
assert T in p and T in m and "Отчет снощи (05.11, след затварянето)" in p
print("  ✓ на картата и в имейла, до „Отчет снощи …“")

print("── 2. радарът и Action (СИНТЕТИЧНО: същата карта) ──")
r = copy.deepcopy(CARD); r["setup"] = {**r["setup"], "kind": "too_wide", "buy_stop": None, "struct_risk_pct": 12.0}
waiting, radar = render.split_canslim([r])
assert not waiting and radar[0]["earnings_unknown"] is True
p, m = both(watchlist=[r])
assert f"широк стоп · 12.0% · {T}" in p and T in m
ok = copy.deepcopy(CARD); ok["earnings"]["earnings_status"] = "ok"; ok["earnings"]["next_earnings"] = "2027-02-20"                     # СИНТЕТИЧНО: с дата
p, m = both(watchlist=[ok])
assert T not in p and T not in m and not enrich.no_date(ok) and not enrich.no_date({}) and not enrich.no_date(None)
src = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert src.count('st.earnings and st.earnings.earnings_status == "no_date"') == 2                                                     # и картата Action
print("  ✓ на реда „На радара“ и в имейла; картата Action — същият ред; с известна дата — нищо")
print("\n✅ test_earnings_no_date: всичко мина")
