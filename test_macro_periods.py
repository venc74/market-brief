"""
03.11.2026 · поправки след брифа, т. 4: числата в макро разказа — с изричен период. На 03.11 текстът каза „петролът (CLZ26) всъщност завърши петицата с -2.34%“ — 5-дневната
промяна — и пропусна −7.36% от понеделник: входът на макро повикването имаше само Oil_WTI {value 97.56, chg_5d_pct −2.34} (периодът — само в името на полето). Сега
macro_layer.last_session_change добавя промяната за ПОСЛЕДНАТА ЗАВЪРШЕНА сесия (chg_1d_pct / chg_1d_bp + датата; без днешния частичен бар на фючърсите), а промптът получава блок
от кода с периода на всяко число (ai_brief.signal_periods_block) и правило: всяко число — с периода си; ход ≥ ±3% за последната сесия — споменат.

РЕАЛНО: tests/fixtures/macro_signals_2026-11-03.json — global_signals от брифа на 03.11 (06:20 UTC), дневните затваряния на символите / договорите (свалени на 03.11.2026) и изречението
за петрола от макро текста на 03.11. СИНТЕТИЧНО (означено): частичният бар, NaN, празната серия.
Пускане: python test_macro_periods.py
"""
import sys, json, copy, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_macro_periods_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import macro_layer as ml, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "macro_signals_2026-11-03.json").read_text(encoding="utf-8"))
ser = lambda k: pd.Series(list(FX["closes"][k].values()), index=pd.to_datetime(list(FX["closes"][k].keys())))
TODAY = dt.date(2026, 11, 3)

print("── 1. last_session_change — РЕАЛНИТЕ затваряния (03.11: последната завършена сесия е 02.11) ──")
oil = ml.last_session_change(ser("Oil_WTI"), TODAY)
assert oil == {"chg_1d_pct": -7.36, "chg_1d_date": "2026-11-02"}, oil                                     # CLZ26: 104.12 (30.10) → 96.46 (02.11)
assert FX["closes"]["Oil_WTI"]["2026-10-30"] == 104.12 and FX["closes"]["Oil_WTI"]["2026-11-02"] == 96.46 and "2026-11-03" in FX["closes"]["Oil_WTI"]   # днешният (нощен) бар — изрязан
assert ml.last_session_change(ser("US10Y"), TODAY, bp=True) == {"chg_1d_bp": -3.5, "chg_1d_date": "2026-11-02"}
assert ml.last_session_change(ser("VIX"), TODAY)["chg_1d_pct"] == 8.91
assert ml.last_session_change(pd.Series([1.0]), TODAY) == {} and ml.last_session_change(pd.Series([1.0, float("nan")], index=pd.to_datetime(["2026-10-30", "2026-11-02"])), TODAY) == {}
print("  ✓ петрол WTI (CLZ26) −7.36% на 02.11 (днешният нощен бар — изрязан); 10-год. доходност −3.5 б.п.; VIX +8.91%; кратко / NaN → {}")

print()
print("── 2. блокът с периодите в промпта (РЕАЛНИТЕ сигнали на 03.11 + дневната промяна) ──")
macro = {"global_signals": copy.deepcopy(FX["global_signals"])}
for k, g in macro["global_signals"].items():
    g.update(ml.last_session_change(ser(k), TODAY, bp=(k == "US10Y")))
block = ai_brief.signal_periods_block(macro)
assert "Петрол WTI (CLZ26): 97.56 сега · последната сесия (понеделник): -7.36% · 5 сесии: -2.34%" in block
assert "10-годишна доходност: 4.89 · последната сесия (понеделник): -3.50 б.п. · 5 сесии: -9.20 б.п." in block
assert "НЕ пиши „петицата“, „седмицата“, „завърши“ без периода" in block and "Ход за последната сесия от ±3% или повече — спомени го" in block
u = ai_brief.macro_user_prompt(macro, [], {"indicators": []})
assert u.index("МАКРО (FRED + пазарни сигнали)") < u.index("ПАЗАРНИ СИГНАЛИ С ПЕРИОДА") and '"chg_1d_pct": -7.36' in u
assert ai_brief.signal_periods_block({}) == "" and ai_brief.signal_periods_block({"global_signals": {"VIX": {"value": None}}}) == ""
print("  ✓ „Петрол WTI (CLZ26): 97.56 сега · последната сесия (понеделник): -7.36% · 5 сесии: -2.34%“ и правилото — в промпта след МАКРО")

print()
print("── 3. текстът от 03.11 и проверката на числата ──")
old_text = FX["macro_text_oil"]
assert "завърши петицата с -2.34%" in old_text and "7.36" not in old_text                                  # РЕАЛНО: периодът липсва, понеделник — също
src = ai_brief.narrative_sources(macro, [], {"indicators": []})
new, fixed = ai_brief.check_narrative_numbers("Петролът (CLZ26) падна с 7.36% за последната сесия (понеделник), а за 5 сесии е -2.34%.", src)
assert not fixed, fixed                                                                                     # новото число е в източниците, периодът — без число
assert ai_brief.check_narrative_numbers("Последната сесия (02.11) беше слаба.", src)[1]                       # с дата „02.11“ проверката би махнала изречението — затова денят от седмицата
print("  ✓ на 03.11 текстът каза „завърши петицата с -2.34%“ без −7.36%; новото число минава проверката на числата (в източниците е)")
print("\n✅ test_macro_periods: всичко мина")
