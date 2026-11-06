"""
06.11.2026 (пакет 05–06.11, т. 8): макро разказът получава от кода дневната промяна на всичките 11 сектора, RSP, Russell, Nasdaq и SPY и спада от 52-седмичния връх. „Мечи пазар“, „корекция“, „рекорд“ — само с опора
в числата; „концентрирано / не системно“ — не при широка разпродажба. Без опора — цялото изречение пада, както при числата. Реално, 06.11: „Nikkei 225 влезе в мечи пазар“ (без число във входа, идваше от „why“ на
новина) и „разпродажбата е концентрирана в mega-cap tech, а не системна“ при 11 от 11 сектора надолу. Върху 103-те разказа (13.06–06.11) проверката маха 5 изречения: 06-29, 09-04, 10-19, двете от 06.11.

РЕАЛНО: tests/fixtures/market_day_2026-11-05.json (затварянията), tests/fixtures/macro_terms_2026-11-06.json (разказът, новините, числата от входа).
СИНТЕТИЧНО (означено): кратките изречения в т. 3, отговорът на модела в т. 4.
Пускане: python test_macro_terms.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_macroterms_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import sector_layer as sl, ai_brief as ab

MD = json.loads((ROOT / "tests" / "fixtures" / "market_day_2026-11-05.json").read_text(encoding="utf-8"))
DF = pd.DataFrame(MD["close"], index=pd.to_datetime(MD["index"]))
TX = json.loads((ROOT / "tests" / "fixtures" / "macro_terms_2026-11-06.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. денят на пазара от кода (РЕАЛНО, 05.11) ──")
board = sl.sector_board(download=lambda s: DF.tail(126), universe_sector={}, trend={}, ratings={}, earnings_fn=lambda s, t: {}, today=DF.index[-1].date())
day = sl.market_day(board, download=lambda s: DF[s])
ix = day["indexes"]
assert (ix["SPY"]["chg_1d_pct"], ix["RSP"]["chg_1d_pct"], ix["IWM"]["chg_1d_pct"], ix["QQQ"]["chg_1d_pct"]) == (-4.41, -2.89, -4.59, -6.49)
assert (ix["SPY"]["from_high_pct"], ix["QQQ"]["from_high_pct"], ix["IWM"]["from_high_pct"]) == (-5.92, -14.82, -10.95)
assert (day["down"], day["total"], day["selloff"], day["as_of"]) == (11, 11, True, "2026-11-05") and day["sectors"][0]["etf"] == "XLK"
assert sl.market_day({}, download=lambda s: (_ for _ in ()).throw(TimeoutError("x"))) == {}                     # провал и без карта → празно
only = sl.market_day(board, download=lambda s: (_ for _ in ()).throw(TimeoutError("x")))
assert only["indexes"] == {} and only["total"] == 11                                                            # провал на индексите → секторите остават
print(f"  ✓ SPY −4.41%, RSP −2.89%, IWM −4.59%, QQQ −6.49%; от върха QQQ −14.82%, IWM −10.95%; надолу 11 от 11")

print("── 2. промптът и проверката на числата ──")
block = ab.market_day_block(day)
assert "SPY -4.41%" in block and "RSP (равни тегла) -2.89%" in block and "Russell 2000 (IWM) -4.59%" in block and "надолу 11 от 11" in block and "QQQ -14.82%" in block and "XLK Технологии -8.00%" in block
assert ab.market_day_block({}) == "" and ab.market_day_block(None) == ""
assert block in ab.macro_user_prompt({}, [], {}, [], {}, day=day) and "ДЕНЯТ НА ПАЗАРА (от кода" not in ab.macro_user_prompt({}, [], {}, [], {})
vals = ab.narrative_sources({}, [], {}, [], {}, day=day)
assert ab.check_narrative_numbers("RSP падна с 2.89% за последната сесия, а Nasdaq е на 14.82% от върха.", vals)[1] == []        # числата от блока имат опора
print("  ✓ блокът е в промпта (11-те сектора, RSP, Russell, спадът от върха); числата му минават проверката")

print("── 3. думите (РЕАЛНИЯТ разказ от 06.11; СИНТЕТИЧНИ изречения за границите) ──")
new, fx = ab.check_market_terms(TX["macro_brief"], TX["vals"], day, TX["news"])
assert sorted(f["term"] for f in fx) == ["концентрирана", "мечи пазар"], fx
assert "Nikkei" not in new and "концентрирана" not in new and "Nasdaq влезе в корекция" in new                  # Nasdaq — опора: QQQ −14.82% от върха
assert len(new) < len(TX["macro_brief"]) and new.count("\n\n") == TX["macro_brief"].count("\n\n")               # абзаците остават
c = lambda s, d=day, v=(20.0, 1.92): ab.check_market_terms(s, list(v), d, [])[1]
assert c("Nikkei 225 влезе в мечи пазар.")                                                                       # без число
assert not c("CSI 300 е в мечи пазар (-20% от юнския връх).")                                                    # числото е в изречението и във входа
assert c("CSI 300 е в мечи пазар (-25% от върха).")                                                              # числото не е във входа
assert not c("Това не е нормална корекция, а координиран спад.") and not c("Рискът от кратка корекция расте.") and not c("Това прави следващата корекция по-рязка.")   # не твърдят състояние
assert c("Gold е в лека корекция (-1.92%).") and c("Пазарът е в корекция.", None)                                # под прага; без данни за деня — без опора
assert not c("Пазарът е в корекция.", {"indexes": {"SPY": {"from_high_pct": -10.0, "chg_1d_pct": -1}}})          # SPY на прага 10%
assert c("TSMC отчете рекордна печалба.") and not ab.check_market_terms("TSMC отчете рекордна печалба.", [], day, [{"headline": "TSMC posts record profit"}])[1]    # „рекорд“ — опора в дословното заглавие
assert not c("SPY затваря на 2.0 от историческия връх.", {"indexes": {"SPY": {"from_high_pct": -0.5, "chg_1d_pct": 1}}})
quiet = {**day, "selloff": False}
assert not c("Разпродажбата е концентрирана в мегакапите, а не системна.", quiet) and c("Разпродажбата е концентрирана в мегакапите, а не системна.")
print("  ✓ падат „Nikkei … мечи пазар“ и „концентрирана … а не системна“; „Nasdaq влезе в корекция“ остава; „не е корекция“, „риск от корекция“ — не твърдят; „рекорд“ — с число или заглавие")

print("── 4. веригата: от отговора на модела до брифа (СИНТЕТИЧЕН отговор) ──")
ab._macro_and_sector_brief_ai = lambda *a, **k: {"macro_brief": "Nikkei 225 влезе в мечи пазар. RSP падна с 2.89%.\n\nЗа нас: нищо ново."}
with q():
    out = ab.macro_and_sector_brief({}, [], {}, news=[], crypto={}, day=day)
assert out["macro_brief"] == "RSP падна с 2.89%.\n\nЗа нас: нищо ново." and out["terms_fixed"][0]["term"] == "мечи пазар" and "numbers_fixed" not in out
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "ai_brief.macro_and_sector_brief(macro, rotation, thermo, news=news, crypto=crypto, day=market_day)" in main_src and main_src.index('"market_day", lambda') < main_src.index("macro_and_sector_brief(macro")
print("  ✓ изречението пада, записът е в ai_macro[\"terms_fixed\"]; main подава деня на пазара")
print("── 5. същата проверка в „защо“ на значимите новини (РЕАЛНИТЕ новини от 06.11; СИНТЕТИЧНИ редове за границите) ──")
news = copy.deepcopy(TX["news"])
for n in news:
    assert n["why"]
fixed = ab.check_news_why_terms(news, day)
assert [f["term"] for f in fixed] == ["мечи пазар"] and "Nikkei" in fixed[0]["sentence"]
by = {n["headline"]: n["why"] for n in news}
assert by["South Korea stocks hit 9-month low as US midterm results spark AI selloff - Reuters"] == ""               # единственото изречение пада; заглавието стои
assert "Nasdaq влезе в корекция" in by["Global stocks tumble as Democratic midterm sweep sparks AI rout"]            # QQQ −14.82% от върха
assert any("концентрирана tech експозиция" in v for v in by.values())                                                # „концентрирано“ — само в разказа: тук думата е за портфолиата
rows = lambda why, h="H", **k: [{"headline": h, "why": why, **k}]
w = lambda r, d=day: (ab.check_news_why_terms(r, d), r[0]["why"])[1]
assert w(rows("Медта е на рекордни нива.", "Copper jumps to its highest level ever")) == "Медта е на рекордни нива."  # РЕАЛНОТО заглавие от 07.08 — рекорд
assert w(rows("Рекордният дефицит засилва натиска.", "U.S. budget deficit surged in July to highest level since March 2021")) == ""     # РЕАЛНОТО заглавие от 13.08 — не е рекорд
assert w(rows("Рекордни печалби.", source_text="Samsung posted a record profit")) == "Рекордни печалби."             # думата е в резюмето
r0 = rows("Рекордни печалби.", source_text="x"); ab.check_news_why_terms(r0, day); assert "source_text" not in r0[0]  # резюмето не влиза в брифа
assert w(rows("CSI 300 е в мечи пазар (-20% от върха).", "CSI 300 down 20% from its June high")) != ""               # процентът е в изречението
assert ab.check_news_why_terms(None, day) == [] and ab.check_news_why_terms([{"headline": "x"}], day) == []
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert main_src.index("ai_brief.check_news_why_terms(news, market_day)") < main_src.index("ai_brief.macro_and_sector_brief(macro, rotation") and '"news_terms_fixed": news_terms_fixed' in main_src
print("  ✓ „Nikkei … мечи пазар“ пада и от „защо“ (преди разказа); „Nasdaq влезе в корекция“ и „концентрирана tech експозиция“ остават; „рекорд“ — с дословен източник")

print("\n✅ test_macro_terms: всичко мина")
