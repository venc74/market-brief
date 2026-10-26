"""
19.10.2026 · етап 2, доп. т. 9 (WTI — проверка + етикет): кой договор дава Yahoo "CL=F" и кога е цената. CL=F е спойка: дневният ред за 16.10 е 101.41 = CLX26 (ноем.), а за 19.10 —
CLZ26 (дек.); в 07:30 Берлин брифът чете ЖИВАТА цена от нощната сесия (19.10: $97.45, декемврийският), а Reuters цитира затварянето на ноемврийския ($101.41 в петък). Сега до цената:
месецът на договора и часът ("WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET") — ред от кода под макро текста и на страницата, и в имейла.
Т. 4 (отговорите от 19.10): 5-дневната промяна е по СЪЩИЯ договор (CLZ26: +4.76%, а CL=F смесва дек. и ноем.: +3.78%); без серията на договора — изрично "по непрекъснатия символ".

26.10.2026 (етап 4б, т. 7): на 26.10 (06:20 UTC) .info на Yahoo нямаше underlyingSymbol за CL=F, GC=F и HG=F (regularMarketTime — имаше; следобед полето пак беше там: CLZ26.NYM) →
редът мълчеше, а промяната беше по непрекъснатия символ. Сега: "WTI $100.97, цена от 26.10 02:20 ET — договорът не е известен днес, промяната е по непрекъснатия символ: −2.6% за 5 дни"
и причината в данните (contract_reason).

РЕАЛНО: tests/fixtures/global_signals_2026-10-26.json — global_signals на брифа от 26.10; tests/fixtures/yahoo_futures_2026-10-19.json — .info и дневните Close на CL=F, GC=F, HG=F, CLX26.NYM, CLZ26.NYM (yfinance, 19.10.2026 следобед);
tests/fixtures/brief_2026-10-19.json — global_signals от брифа (Oil_WTI 97.45). СИНТЕТИЧНО (маркирано): подмененият yf.Ticker, часът на цената за брифа (01:30 ET).
Пускане: python test_futures_contract.py
"""
import sys, json, copy, pathlib, tempfile, re, io, contextlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fut_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import macro_layer as ml, render

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_futures_2026-10-19.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. договорът по underlyingSymbol (РЕАЛНО .info) ──")
assert ml.futures_contract(FX["info"]["CL=F"]) == {"contract": "CLZ26", "contract_month": "дек. 2026"} and FX["info"]["CL=F"]["shortName"] == "Crude Oil Dec 26"
assert ml.futures_contract(FX["info"]["GC=F"]) == {"contract": "GCZ26", "contract_month": "дек. 2026"} and ml.futures_contract(FX["info"]["HG=F"])["contract"] == "HGZ26"
assert ml.futures_contract({"underlyingSymbol": "CLX26.NYM"})["contract_month"] == "ноем. 2026" and ml.futures_contract({}) is None and ml.futures_contract({"underlyingSymbol": "SPY"}) is None
d = {s: dict(zip(v["dates"], v["close"])) for s, v in FX["daily"].items()}
assert round(d["CL=F"]["2026-10-16"], 2) == round(d["CLX26.NYM"]["2026-10-16"], 2) == 101.41 and round(d["CLZ26.NYM"]["2026-10-16"], 2) == 99.02     # петък: CL=F = ноем.
assert round(d["CL=F"]["2026-10-19"], 2) == round(d["CLZ26.NYM"]["2026-10-19"], 2) and FX["info"]["CL=F"]["previousClose"] == 99.02                   # понеделник: CL=F = дек.
print("  ✓ CL=F → CLZ26 'дек. 2026' (shortName 'Crude Oil Dec 26'); дневният ред за 16.10 = CLX26 101.41, за 19.10 = CLZ26; previousClose 99.02 е петъчното на декемврийския")

print()
print("── 2. global_market_signals носи договора и часа (подменен yf.Ticker върху РЕАЛНИТЕ серии) ──")
class Tk:
    def __init__(self, s): self.s = s
    @property
    def info(self): return FX["info"].get(self.s, {})
    def history(self, period=None, **k):
        v = FX["daily"].get(self.s)
        if not v:
            return pd.DataFrame()
        return pd.DataFrame({"Close": v["close"]}, index=pd.to_datetime(v["dates"]))
real_tk, real_stale = ml.yf.Ticker, ml._is_stale
ml.yf.Ticker, ml._is_stale = Tk, (lambda ts: False)                                    # СИНТЕТИЧНО: давността има свой тест
try:
    with contextlib.redirect_stdout(io.StringIO()):
        g = ml.global_market_signals()
finally:
    ml.yf.Ticker, ml._is_stale = real_tk, real_stale
assert g["Oil_WTI"]["contract"] == "CLZ26" and g["Oil_WTI"]["contract_month"] == "дек. 2026" and g["Oil_WTI"]["bar_date"] == "2026-10-19" and g["Oil_WTI"]["price_time_utc"].startswith("2026-10-19")
assert g["Gold"]["contract"] == "GCZ26" and "DXY" not in g                                                             # без данни за DXY в fixture-а — пропуснат, без срив
dz = dict(zip(FX["daily"]["CLZ26.NYM"]["dates"], FX["daily"]["CLZ26.NYM"]["close"])); dc = dict(zip(FX["daily"]["CL=F"]["dates"], FX["daily"]["CL=F"]["close"]))
assert g["Oil_WTI"]["chg_5d_basis"] == "contract" and g["Oil_WTI"]["chg_5d_pct"] == round((dz["2026-10-19"] / dz["2026-10-12"] - 1) * 100, 2) == 4.76      # т. 4: по CLZ26
assert round((dc["2026-10-19"] / dc["2026-10-12"] - 1) * 100, 2) == 3.78                                                # по CL=F (дек. срещу ноем.) — смесено
assert g["Gold"]["chg_5d_basis"] == "continuous"                                                                         # без серия на GCZ26 във fixture-а → изрично "непрекъснат"
print(f"  ✓ Oil_WTI: {g['Oil_WTI']['value']} — CLZ26 / дек. 2026, бар {g['Oil_WTI']['bar_date']}, цена {g['Oil_WTI']['price_time_utc']}; 5 дни по CLZ26 +4.76% (по CL=F смесено +3.78%)")

print()
print("── 3. редът под макро текста (РЕАЛНИЯТ бриф от 19.10 + договорът; часът 01:30 ET е СИНТЕТИЧЕН) ──")
b = copy.deepcopy(B19)
gs = b["macro"]["global_signals"]
assert gs["Oil_WTI"]["value"] == 97.45
gs["Oil_WTI"].update(contract="CLZ26", contract_month="дек. 2026", price_time_utc="2026-10-19T05:30+00:00")
gs["Gold"].update(contract="GCZ26", contract_month="дек. 2026")
line = ml.futures_quotes_line(gs)
assert line.startswith("Фючърси (Yahoo, договорът, който символът „=F“ дава днес): WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET, +4.0% за 5 дни по непрекъснатия символ "
                       "(може да смесва договори) · злато $4 197 — дек. 2026 (GCZ26)")                                  # брифът от 19.10 е без chg_5d_basis
gs["Oil_WTI"].update(chg_5d_pct=4.76, chg_5d_basis="contract")
assert "WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET, +4.8% за 5 дни по същия договор" in ml.futures_quotes_line(gs)
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
assert "WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET" in flat(render.render_dashboard(copy.deepcopy(b)))
assert "WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET" in flat(render.render_email(b))
assert ml.futures_quotes_line(B19["macro"]["global_signals"]) is None and "Фючърси (Yahoo" not in flat(render.render_dashboard(copy.deepcopy(B19)))   # стар бриф без договора — без ред
print("  ✓ 'WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET · злато …' на страницата и в имейла; стар бриф — без ред")

print()
print("── 4. договорът не е известен днес (РЕАЛНИЯТ бриф от 26.10) ──")
G26 = json.loads((ROOT / "tests" / "fixtures" / "global_signals_2026-10-26.json").read_text(encoding="utf-8"))["global_signals"]
assert G26["Oil_WTI"]["chg_5d_basis"] == "continuous" and "contract" not in G26["Oil_WTI"] and G26["Oil_WTI"]["value"] == 100.97
l26 = ml.futures_quotes_line(G26)
assert ("WTI $100.97, цена от 26.10 02:20 ET — договорът не е известен днес, промяната е по непрекъснатия символ: -2.6% за 5 дни · злато $4 019, цена от 26.10 02:20 ET — договорът "
        "не е известен днес") in l26
b26 = copy.deepcopy(B19); b26["macro"]["global_signals"] = G26
assert "WTI $100.97, цена от 26.10 02:20 ET — договорът не е известен днес" in flat(render.render_dashboard(copy.deepcopy(b26))) and "договорът не е известен днес" in flat(render.render_email(b26))
mixed = copy.deepcopy(G26); mixed["Gold"].update(contract="GCZ26", contract_month="дек. 2026", chg_5d_basis="contract")      # СИНТЕТИЧНО: единият с договор
assert "злато $4 019 — дек. 2026 (GCZ26), цена от 26.10 02:20 ET" in ml.futures_quotes_line(mixed) and "WTI $100.97, цена от 26.10 02:20 ET — договорът не е известен днес" in ml.futures_quotes_line(mixed)
print("  ✓", l26[:150], "…")
no_und = {k: v for k, v in FX["info"]["CL=F"].items() if k != "underlyingSymbol"}                                     # СИНТЕТИЧНО: РЕАЛНОТО .info от 19.10 без underlyingSymbol
no_name = {k: v for k, v in no_und.items() if k != "shortName"}                                                       # СИНТЕТИЧНО: и без името на договора


def signals_with(info_cl):
    class Tk2(Tk):
        @property
        def info(self): return info_cl if self.s == "CL=F" else FX["info"].get(self.s, {})
    ml.yf.Ticker, ml._is_stale = Tk2, (lambda ts: False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return ml.global_market_signals()
    finally:
        ml.yf.Ticker, ml._is_stale = real_tk, real_stale


# 26.10.2026 (решение по етап 4б, т. 3): резервът по името на договора ("Crude Oil Dec 26" + корена "CL")
assert ml.futures_contract(no_und, "CL=F") == {"contract": "CLZ26", "contract_month": "дек. 2026", "contract_source": "shortName"}
assert ml.futures_contract({"shortName": "Gold Feb 27"}, "GC=F")["contract"] == "GCG27" and ml.futures_contract({"shortName": "Crude Oil"}, "CL=F") is None
g2 = signals_with(no_und)
assert g2["Oil_WTI"]["contract"] == "CLZ26" and g2["Oil_WTI"]["contract_source"] == "shortName" and "contract_reason" not in g2["Oil_WTI"]
assert g2["Oil_WTI"]["chg_5d_basis"] == "contract" and g2["Oil_WTI"]["chg_5d_pct"] == 4.76                                # серията CLZ26.NYM от fixture-а
assert "WTI $97.45 — дек. 2026 (CLZ26, по името на договора)" in (ml.futures_quotes_line({**g2, "Oil_WTI": {**g2["Oil_WTI"], "value": 97.45}}) or "")
g3 = signals_with(no_name)
assert "contract" not in g3["Oil_WTI"] and g3["Oil_WTI"]["chg_5d_basis"] == "continuous" and g3["Oil_WTI"]["contract_reason"] == "Yahoo не върна underlyingSymbol"
assert g3["Oil_WTI"]["price_time_utc"].startswith("2026-10-19") and "contract_reason" not in g3["Gold"]
print("  ✓ без underlyingSymbol → договорът по името („Crude Oil Dec 26“ → CLZ26), 5 дни по CLZ26 (+4.76%), редът казва „по името на договора“; без име — непрекъснатият символ и причината")
print("\n✅ test_futures_contract: всичко мина")
