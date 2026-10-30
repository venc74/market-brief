"""
30.10.2026 · разходката, т. 7: секторната карта — от кода, без AI.
  • 11-те секторни ETF-а в една таблица, подредени по сила (средното на RS 4 и 12 седм. спрямо SPY — RS линията ETF/SPY, както sector_rotation), думата от кода
    (води пазара / набира сила / отслабва / изостава — watch_monitor.rs_word), мястото спрямо преди config.SECTOR_BOARD_RANK_LAG сесии и RS на 6-месечен връх.
  • 2–3 лидери от нашия универс за всеки сектор: същият GICS сектор, над 50DMA и 200DMA, по RS рейтинг (1–99); кандидатите ни (Watchlist / QM / GLB) не са тук. Таблица под
    реда на сектора (като карето „Контекст“): Тикър · RS рейтинг · 1 месец · 50DMA · 200DMA · Отчет; разгъва се с клик, отворени — само секторите с „води пазара“.
  • Думите — с мъртвата зона ±1 пункт (config.RS_WORD_DEAD_ZONE): XLI +0.2 / −8.5 е „в крак с пазара“, не „набира сила“; числата в зоната — сиви, стрелката — →.
  • Едно изречение от кода над таблицата; подсекторите (18 ETF-а) — два реда: „Най-силни подсектори“ (5) и „Най-слаби“ (3).
  • Веригите на AI и „хоризонт (AI)“ отпаднаха; картите на тикърите получават секторите по кода (board_context).

РЕАЛНО: tests/fixtures/sector_board_2026-10-30.json — затварянията на 11-те ETF-а, 18-те подсектора и SPY (Yahoo, 6 месеца до 29.10, без днешния бар; свалени на 30.10),
GICS секторите на универса (Wikipedia S&P 500 + S&P 400, 903 тикъра), над/под 50/200DMA, 1 месец и RS рейтингът от скрийнинга, пуснат локално на 30.10, и следващите
отчети на 33-те лидера (tk.calendar / get_earnings_dates на 30.10);
tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подменените редове в раздел 4 (групите на изречението), провалът на тегленето в раздел 5, измисленият тикър в раздел 2; earnings_fn връща
записаните РЕАЛНИ дати (без мрежа).
Пускане: python test_sector_board.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_sboard_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import sector_layer, render

FX = json.loads((ROOT / "tests" / "fixtures" / "sector_board_2026-10-30.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
DF = pd.DataFrame({s: pd.Series({pd.Timestamp(d): v for d, v in c.items()}) for s, c in FX["closes"].items()}).sort_index()
U, T, R, E = FX["universe_sector"], FX["trend"], FX["ratings"], FX["earnings"]
TODAY = dt.date.fromisoformat(FX["today"])
efn = lambda sym, today: E.get(sym) or {}                                                       # записаните РЕАЛНИ отговори от 30.10 (без мрежа)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. таблицата върху РЕАЛНИТЕ затваряния до 29.10 ──")
with q():
    b = sector_layer.sector_board(download=lambda syms: DF[syms], universe_sector=U, trend=T, ratings=R, earnings_fn=efn, today=TODAY)
S = b["sectors"]
assert b["as_of"] == "2026-10-29" and len(S) == 11 and len(b["subsectors"]) == 18
assert [r["etf"] for r in S] == ["XLE", "XLV", "XLP", "XLB", "XLU", "XLF", "XLY", "XLRE", "XLK", "XLI", "XLC"]
assert [r["rank"] for r in S] == list(range(1, 12)) and [r["strength"] for r in S] == sorted((r["strength"] for r in S), reverse=True)
by = {r["etf"]: r for r in S}
assert (by["XLE"]["rs_4w"], by["XLE"]["rs_12w"], by["XLE"]["word"]) == (8.82, 15.5, "води пазара")
assert (by["XLU"]["rs_4w"], by["XLU"]["rs_12w"], by["XLU"]["word"]) == (7.96, -3.76, "набира сила")
assert (by["XLK"]["rs_4w"], by["XLK"]["rs_12w"], by["XLK"]["word"]) == (-5.25, 4.26, "отслабва")
assert (by["XLC"]["rs_4w"], by["XLC"]["rs_12w"], by["XLC"]["word"]) == (-8.58, -10.41, "изостава")
assert (by["XLI"]["rs_4w"], by["XLI"]["rs_12w"], by["XLI"]["word"]) == (0.18, -8.51, "в крак с пазара")                          # мъртвата зона: до нея — „набира сила“
assert all(abs(r["strength"] - (r["rs_4w"] + r["rs_12w"]) / 2) <= 0.01 for r in S)                                 # с точност до закръглянето на RS
assert [r["etf"] for r in S if r["rs_at_6m_high"]] == ["XLV"]
assert {r["etf"]: r["rank_change"] for r in S if r["rank_change"]} == {"XLB": 1, "XLU": 2, "XLY": -3, "XLRE": 1, "XLK": -1, "XLI": 1, "XLC": -1}
assert sum(r["rank_change"] for r in S) == 0
print("  ✓ XLE +8.8/+15.5 води пазара … XLI +0.2/−8.5 в крак с пазара … XLC −8.6/−10.4 изостава; RS на 6м връх — само XLV; място: XLU ↑2, XLY ↓3 (спрямо преди 5 сесии)")
rs = DF["XLE"] / DF["SPY"]
assert round((rs.iloc[-1] / rs.iloc[-21] - 1) * 100, 2) == 8.82 and round((rs.iloc[-1] / rs.iloc[-63] - 1) * 100, 2) == 15.5
print("  ✓ RS = промяната на отношението XLE / SPY за 20 и 62 сесии (същата сметка като sector_rotation)")

print()
print("── 2. лидерите от универса — същият сектор, над 50DMA и 200DMA, по RS рейтинг ──")
assert [(l["ticker"], l["rs_rating"]) for l in by["XLE"]["leaders"]] == [("APA", 98), ("MPC", 97), ("VAL", 97)]
assert [(l["ticker"], l["rs_rating"]) for l in by["XLV"]["leaders"]] == [("MRNA", 99), ("CRL", 99), ("ILMN", 99)]
assert [(l["ticker"], l["rs_rating"]) for l in by["XLC"]["leaders"]] == [("ROKU", 86), ("SIRI", 71), ("LYV", 57)]
apa = by["XLE"]["leaders"][0]
assert (apa["chg_1m_pct"], apa["above_50"], apa["above_200"], apa["next_earnings"], apa["days_to_earnings"], apa["earnings_soon"]) == (24.0, True, True, "2026-11-04", 5, True)
ilmn = by["XLV"]["leaders"][2]
assert (ilmn["ticker"], ilmn["next_earnings"], ilmn["earnings_soon"]) == ("ILMN", "2027-02-04", False)                         # календарът — минал отчет (29.10), резервът — следващият
assert all(l.get("next_earnings") for r in S for l in r["leaders"])
for r in S:
    assert len(r["leaders"]) == config.SECTOR_BOARD_LEADERS
    for l in r["leaders"]:
        t = l["ticker"]
        assert config.GICS_SECTOR_ETF[U[t]] == r["etf"] and T[t]["above_50"] and T[t]["above_200"] and l["rs_rating"] == min(99, R[t]) and l["chg_1m_pct"] == T[t]["chg_1m_pct"]
# по-високо оценен в същия сектор, но под 50DMA или 200DMA — не е лидер (РЕАЛНО: XLK — DELL, LITE, MU, SNDK с рейтинг 99, под 50DMA)
skipped = sorted(t for t, sec in U.items() if config.GICS_SECTOR_ETF.get(sec) == "XLK" and min(99, R.get(t, 0)) > 98 and not (T.get(t, {}).get("above_50") and T.get(t, {}).get("above_200")))
assert skipped == ["DELL", "LITE", "MU", "SNDK"] and all(T[t]["above_200"] and not T[t]["above_50"] for t in skipped)
assert [(l["ticker"], l["rs_rating"]) for l in by["XLK"]["leaders"]] == [("OKTA", 99), ("QLYS", 99), ("P", 98)]
syn = sector_layer.sector_leaders("XLE", {**U, "ZZZQ": "Energy"}, {**T, "ZZZQ": {"above_50": True, "above_200": False}}, {**R, "ZZZQ": 99})   # СИНТЕТИЧЕН тикър под 200DMA
assert "ZZZQ" not in [l["ticker"] for l in syn]
print("  ✓ XLE: APA 98 · MPC 97 · VAL 97; всеки лидер — същият GICS сектор, над 50 и 200DMA; под някоя от тях не влиза (РЕАЛНО: XLK без DELL, LITE, MU, SNDK; СИНТЕТИЧНО ZZZQ)")
print("  ✓ APA: 1 месец +24.0%, над / над, отчет 04.11 (5 дни, скоро); ILMN — 04.02.2027 (календарът на Yahoo връща миналия отчет, резервът — следващия); 33 от 33 с дата")
class _Tk:                                                                                     # отговорите на Yahoo за ILMN, наблюдавани на 30.10 (РЕАЛНИ стойности, подменен обект)
    def __init__(self, sym): self.calendar = {"Earnings Date": [dt.date(2026, 10, 29)]}
    def get_earnings_dates(self, limit=4):
        idx = pd.DatetimeIndex(["2027-02-04 16:00", "2026-10-29 16:00", "2026-07-30 16:00"]).tz_localize("America/New_York")
        return pd.DataFrame({"EPS Estimate": [None, 1.2, 1.1]}, index=idx)
_real_tk = sector_layer.yf.Ticker
sector_layer.yf.Ticker = _Tk
try:
    assert sector_layer.next_earnings("ILMN", TODAY) == {"next_earnings": "2027-02-04", "days_to_earnings": 97, "earnings_soon": False}
    sector_layer.yf.Ticker = lambda sym: (_ for _ in ()).throw(ConnectionError("СИНТЕТИЧНО"))
    with q():
        assert sector_layer.next_earnings("ILMN", TODAY) == {}
finally:
    sector_layer.yf.Ticker = _real_tk
print("  ✓ next_earnings: календарът с минал отчет → get_earnings_dates (ILMN 04.02.2027, 97 дни); провал → {} (graceful)")

print()
print("── 3. изречението, подсекторите и контекстът за картите ──")
assert b["summary"] == "Водят Енергетика, Здравеопазване и Потребителски (защитни); изостават Комуникации — отбранителна ротация — парите търсят сигурност."
assert [r["etf"] for r in b["top_sub"]] == ["XOP", "IBB", "OIH", "CIBR", "IGV"] and [r["etf"] for r in b["bottom_sub"]] == ["TAN", "URA", "JETS"]
assert [r["etf"] for r in b["subsectors"]][:5] == ["XOP", "IBB", "OIH", "CIBR", "IGV"] and [r["etf"] for r in b["subsectors"]][-3:] == ["JETS", "URA", "TAN"]
assert "leaders" not in b["subsectors"][0]
ctx = sector_layer.board_context(b)
assert [c["etf"] for c in ctx] == ["XLE", "XLV", "XLP", "XLB", "XLU", "XLF", "XLY", "XLRE"] and set(ctx[0]) == {"etf", "sector", "rs_4w", "rs_12w", "word"}   # XLI — в крак с пазара
assert sector_layer.board_context({}) == [] and sector_layer.board_context(None) == []
print("  ✓ „Водят Енергетика, Здравеопазване и Потребителски (защитни); изостават Комуникации — отбранителна ротация …“")
print("  ✓ най-силни подсектори XOP, IBB, OIH, CIBR, IGV; най-слаби TAN, URA, JETS; картите виждат само водещите и набиращите сила")

print()
print("── 4. изречението при други подредби (СИНТЕТИЧНИ редове) ──")
row = lambda e, w: {"etf": e, "sector": config.SECTOR_ETFS.get(e, e), "word": w}
assert sector_layer.board_summary([row("XLK", "води пазара"), row("XLY", "води пазара"), row("XLE", "набира сила"), row("XLU", "изостава")]) == \
    "Водят Технологии и Потребителски (циклични); изостават Комунални услуги — растежът води — апетит за риск."
assert sector_layer.board_summary([row("XLE", "набира сила"), row("XLK", "отслабва"), row("XLV", "отслабва")]) == \
    "Нито един сектор не води и на двата периода; нито един не изостава и на двата — смесена картина — няма ясна посока на ротацията."
assert sector_layer.board_summary([]) == ""
print("  ✓ XLK + XLY отгоре → „растежът води“; без група с 2 от първите 3 → „смесена картина“; празно → нищо")

print()
print("── 5. провал на тегленето → {} (graceful), без картата ──")
def boom(syms):
    raise ConnectionError("СИНТЕТИЧНО: Yahoo не отговаря")
with q() as log:
    assert sector_layer.sector_board(download=boom, universe_sector=U, trend=T, ratings=R, earnings_fn=efn, today=TODAY) == {}
assert "секторната карта не е изчислена" in log.getvalue()
print("  ✓ {} и ред в лога; main показва банера на стъпката „Секторната карта“")

print()
print("── 6. страницата ──")
bb = copy.deepcopy(B19); bb["sector_board"] = b
with q():
    page = render.render_dashboard(bb, publish=False)
txt = lambda h: re.sub(r"\s+\)", ")", re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h))))
sec = txt(page.split("Секторна карта · кои сектори водят", 1)[1].split("</section>", 1)[0])
assert "Водят Енергетика, Здравеопазване и Потребителски (защитни)" in sec and "хоризонт" not in sec.lower()
assert sec.index("XLE") < sec.index("XLV") < sec.index("XLC") and "APA · MPC · VAL" in sec and "RS на 6м връх" in sec
assert "Тикър RS рейтинг 1 месец 50DMA 200DMA Отчет APA 98 +24.0% над над 04.11 (5 дни) MPC 97 +9.4% над над 03.11 (4 дни)" in sec
assert "Най-силни подсектори: Добив на нефт и газ (XOP ↑)" in sec and "Киберсигурност (CIBR →) · Софтуер (IGV →)" in sec
assert "Най-слаби: Соларна (TAN ↓) · Уран/ядрена (URA ↓) · Авиокомпании (JETS ↓)" in sec
assert "↑ 2" in sec and "↓ 3" in sec and "Данни към 29.10." in sec and "между −1 и +1 е „в крак с пазара“" in sec
html_sec = page.split("Секторна карта · кои сектори водят", 1)[1].split("</section>", 1)[0]
opened = re.findall(r'<details class="wt-item"( open)?>\s*<summary class="wt-row sb-row">\s*<span class="wt-t">([A-Z]+)', html_sec)
assert [e for o, e in opened if o] == ["XLE", "XLV", "XLP", "XLB"] and len(opened) == 11                                        # отворени — само „води пазара“
assert '<span class="wt-mu">+0.2</span> / <span class="wt-dn">-8.5</span>' in html_sec                                            # XLI: +0.2 — сиво (в зоната)
print("  ✓ таблицата по сила; под всеки сектор — лидерите (Тикър · RS рейтинг · 1 месец · 50DMA · 200DMA · Отчет), отворени само XLE, XLV, XLP, XLB („води пазара“)")
print("  ✓ XLI +0.2 — сиво; CIBR +0.5 и IGV −0.9 → „→“; мястото (↑ 2 / ↓ 3), двата реда подсектори, без хоризонт (AI); данни към 29.10")
print("\n✅ test_sector_board: всичко мина")
