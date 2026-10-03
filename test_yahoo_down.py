"""
Пакет 2 · т.6 (2026-10-03): паднал/празен Yahoo не сваля run-а. sector_layer.sector_rotation() и screener.technical_screen()
връщат [] с причина в LAST_STATUS; main.py слага src/data_warnings.collect() в brief["data_warnings"]; dashboard и имейл го
показват като банер най-горе, а празният Action не се представя като "няма сетъпи"; макро промптът казва, че ротацията липсва.

РЕАЛНО: цените на SPY, AMD, TWLO, LNTH, EXEL (tests/fixtures/ohlc_*.csv, 01.04.2025 → 01.10.2026) и целият бриф от 02.10.2026
(tests/fixtures/brief_2026-10-02.json) за рендера. СИНТЕТИЧНО: подменените yf.download (празна таблица / изключение), секторните ETF-и
(цена на SPY × синтетичен фактор), предупрежденията в рендера (брифът от 02.10 е бил без предупреждения).
Пускане: python test_yahoo_down.py
"""
import sys, pathlib, json, tempfile, io, contextlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import sector_layer, screener, data_warnings, render, ai_brief

FIX = ROOT / "tests" / "fixtures"


def ohlc(sym):
    return pd.read_csv(FIX / f"ohlc_{sym}.csv", index_col="Date", parse_dates=True)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def raises(msg):
    def f(*a, **k):
        raise ConnectionError(msg)
    return f


SPY = ohlc("SPY")
ETFS = [k for k in config.SECTOR_ETFS if "PROXY" not in k]
print("── sector_rotation(): паднал Yahoo ──")
ok_frame = pd.DataFrame({e: SPY["Close"] * (1 + 0.0004 * i * np.arange(len(SPY)) / 100) for i, e in enumerate(ETFS)} | {"SPY": SPY["Close"]})
for label, dl, why in (
        ("yf.download хвърля", raises("Yahoo Finance недостъпен"), "Yahoo Finance недостъпен"),
        ("празна таблица", lambda *a, **k: pd.DataFrame(), "KeyError"),            # празна таблица → няма колона "Close"
        ("без колона SPY", lambda *a, **k: pd.concat({"Close": ok_frame.drop(columns="SPY")}, axis=1), "KeyError"),
        ("SPY с твърде къса история", lambda *a, **k: pd.concat({"Close": ok_frame.iloc[:30]}, axis=1), "ValueError")):
    sector_layer.yf.download = dl
    res, log = quiet(sector_layer.sector_rotation)
    st = sector_layer.LAST_STATUS
    assert res == [] and st["ok"] is False and why in st["reason"], (label, res, st)
    assert "секторната ротация не е изчислена" in log
print("  ✓ СИНТЕТИЧНО: изключение / празна таблица / липсва SPY / SPY с 30 реда → [] (без изключение) и LAST_STATUS.ok=False с причина")

sector_layer.yf.download = lambda *a, **k: pd.concat({"Close": ok_frame}, axis=1)
res, _ = quiet(sector_layer.sector_rotation)
assert len(res) == len(ETFS) and sector_layer.LAST_STATUS["ok"] is True and sector_layer.LAST_STATUS["etfs_ok"] == len(ETFS)
assert [r["etf"] for r in res] == sorted(ETFS, key=lambda e: -next(r["rs_chg_4w_pct"] for r in res if r["etf"] == e))        # сортиране по 4-седмична RS
assert sector_layer.leading_sectors([]) == [] and sector_layer.laggard_sectors([]) == []
print(f"  ✓ здравият случай (РЕАЛЕН SPY + {len(ETFS)} СИНТЕТИЧНИ ETF-а) дава {len(res)} реда, status ok; leading_sectors([]) и laggard_sectors([]) са []")

bad = ok_frame.copy(); bad[ETFS[0]] = np.nan; bad.loc[bad.index[:350], ETFS[1]] = np.nan          # един ETF без данни, един с къса история
sector_layer.yf.download = lambda *a, **k: pd.concat({"Close": bad}, axis=1)
res, _ = quiet(sector_layer.sector_rotation)
assert len(res) == len(ETFS) - 2 and {r["etf"] for r in res}.isdisjoint({ETFS[0], ETFS[1]}) and sector_layer.LAST_STATUS["ok"] is True
print(f"  ✓ СИНТЕТИЧНО: два лоши ETF-а ({ETFS[0]} само NaN, {ETFS[1]} къса история) отпадат поотделно, останалите {len(res)} остават")
print()

print("── technical_screen(): паднал Yahoo ──")
uni = ["AMD", "TWLO", "LNTH", "EXEL"]
screener.time.sleep = lambda s: None
screener.yf.download = lambda *a, **k: pd.DataFrame()
res, log = quiet(screener.technical_screen, uni, 2)
st = screener.LAST_STATUS
assert res == [] and st["ok"] is False and st["kind"] == "spy_failed" and st["with_history"] == 0 and "няма SPY история" in log
screener.yf.download = raises("Yahoo Finance недостъпен")
res, _ = quiet(screener.technical_screen, uni, 2)
assert res == [] and screener.LAST_STATUS["kind"] == "spy_failed" and "Yahoo Finance недостъпен" in screener.LAST_STATUS["reason"]
print("  ✓ СИНТЕТИЧНО: празен или хвърлящ SPY download → [] и kind=spy_failed (преди: KeyError още на първия ред)")


def make_download(fail_batches=()):
    state = {"n": 0}
    def dl(tickers, *a, **k):
        if tickers == "SPY":
            return pd.concat({"Close": SPY["Close"]}, axis=1)
        i = state["n"]; state["n"] += 1
        if i in fail_batches:
            raise ConnectionError("batch down")
        return pd.concat({t: ohlc(t) for t in tickers}, axis=1)
    return dl


screener.yf.download = make_download(fail_batches=(0, 1))
res, log = quiet(screener.technical_screen, uni, 2)
st = screener.LAST_STATUS
assert res == [] and st["ok"] is False and st["kind"] == "no_history" and st["batches"] == 2 and st["batches_failed"] == 2
print("  ✓ СИНТЕТИЧНО: SPY идва, но и двете партиди падат → [] и kind=no_history (2 от 2 партиди с грешка)")

def empty_batches(tickers, *a, **k):
    return pd.concat({"Close": SPY["Close"]}, axis=1) if tickers == "SPY" else pd.DataFrame()
screener.yf.download = empty_batches
res, _ = quiet(screener.technical_screen, uni, 2)
assert res == [] and screener.LAST_STATUS["kind"] == "no_history" and screener.LAST_STATUS["batches_failed"] == 0
print("  ✓ СИНТЕТИЧНО: партидите връщат празни таблици без изключение (Yahoo логва грешка и мълчи) → пак kind=no_history")

screener.yf.download = make_download(fail_batches=(1,))
res, _ = quiet(screener.technical_screen, uni, 2)
st = screener.LAST_STATUS
assert st["ok"] is True and st["kind"] == "partial" and st["batches"] == 2 and st["batches_failed"] == 1 and st["with_history"] == 2
print("  ✓ РЕАЛНИ цени (AMD, TWLO в първата партида) + СИНТЕТИЧНА грешка във втората: kind=partial, 1 от 2 партиди, 2 тикъра с история")

screener.yf.download = make_download()
res, _ = quiet(screener.technical_screen, uni, 2)
assert screener.LAST_STATUS["ok"] is True and screener.LAST_STATUS["kind"] == "ok" and screener.LAST_STATUS["with_history"] == 4
print("  ✓ РЕАЛНИ цени, без грешки: kind=ok, 4 тикъра с история")

# цялата верига run_screen при празен Yahoo
screener.build_universe = lambda: uni
screener.yf.download = lambda *a, **k: pd.DataFrame()
res, _ = quiet(screener.run_screen, ["Технологии"], leaders=[])
assert res == []
print("  ✓ run_screen() през целия път при паднал Yahoo → [] (без изключение)")
print()

print("── data_warnings.collect() ──")
assert data_warnings.collect({"ok": True}, {"ok": True, "kind": "ok"}) == [] and data_warnings.collect(None, None) == []
w = data_warnings.collect({"ok": False, "reason": "ConnectionError: x"}, {"ok": False, "kind": "spy_failed", "reason": "y"})
assert [x["source"] for x in w] == ["sector_rotation", "screener"] and all(x["level"] == "error" for x in w)
assert "НЕ е изчислена" in w[0]["message"] and "НЕ защото няма сетъпи" in w[1]["message"]
w2 = data_warnings.collect({"ok": True}, {"ok": True, "kind": "partial", "batches": 10, "batches_failed": 2, "with_history": 700, "universe": 900})
assert len(w2) == 1 and w2[0]["level"] == "warn" and "2 от 10 партиди" in w2[0]["message"] and "700 от 900" in w2[0]["message"]
assert data_warnings.collect(None, {"kind": "universe_empty", "reason": "z"})[0]["level"] == "error"
assert data_warnings.collect(None, {"kind": "crashed", "reason": "KeyError"})[0]["level"] == "error"
print("  ✓ здрави състояния → []; провал на ротацията и скрийнъра → 2 error; частичен провал → 1 warn с броя; празен универс/срив → error")
print()

print("── макро промптът ──")
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
ai_brief.macro_and_sector_brief({}, [], {"regime": "Defensive", "indicators": []})
assert "СЕКТОРНИТЕ ДАННИ НЕ СА НАЛИЧНИ" in seen["u"] and 'НЕ измисляй водещи сектори' in seen["u"] and '"sector_logic": []' in seen["u"]
seen.clear()
ai_brief.macro_and_sector_brief({}, [{"etf": "XLK", "sector": "Технологии", "rs_chg_4w_pct": 3.1}], {"regime": "Defensive", "indicators": []})
assert "СЕКТОРНИТЕ ДАННИ НЕ СА НАЛИЧНИ" not in seen["u"]
print("  ✓ празна ротация → промптът забранява измислени сектори (sector_logic []); непразна → бележката я няма")
print()

print("── рендер: dashboard и имейл (РЕАЛЕН бриф от 02.10 + СИНТЕТИЧНИ предупреждения) ──")
brief = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
assert not brief.get("data_warnings")


def render_both(b):
    with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
        o1, o2 = config.DOCS_DIR, config.DATA_DIR
        config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
        try:
            return htmllib.unescape(render.render_dashboard(b)), htmllib.unescape(render.render_email(b))
        finally:
            config.DOCS_DIR, config.DATA_DIR = o1, o2


dash0, mail0 = render_both(brief)
assert "Проблем с данните днес" not in dash0 and "Проблем с данните днес" not in mail0
b2 = dict(brief); b2["action"] = []; b2["watchlist"] = []
b2["data_warnings"] = data_warnings.collect({"ok": False, "reason": "ConnectionError: Yahoo down"}, {"ok": False, "kind": "spy_failed", "reason": "ValueError: празна история"})
dash1, mail1 = render_both(b2)
for page in (dash1, mail1):
    assert "Проблем с данните днес" in page and "Секторна ротация: Yahoo Finance не върна данни" in page
    assert "НЕ значи, че няма сетъпи" in page
    assert "Кешът също е позиция" not in page and "кешът също е позиция" not in page and "Кешът е позиция" not in page
print("  ✓ без предупреждения: банер няма (същото като досега); с предупреждения: банер в dashboard-а и в имейла, празният Action казва 'липсват данни', не 'кешът е позиция'")
b3 = dict(brief); b3["action"] = []; b3["watchlist"] = []                                  # празен Action БЕЗ провал на данните
dash2, mail2 = render_both(b3)
assert ("кешът също е позиция" in dash2) and ("Кешът е позиция" in mail2) and "Проблем с данните днес" not in dash2
print("  ✓ празен Action без провал на данните → старият текст 'кешът е позиция' остава")
print()

print("── main.py ──")
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i = main_src.index("rotation = sector_rotation()")
assert "try:" in main_src[i - 120:i] and "except Exception" in main_src[i:i + 200]
j = main_src.index("candidates = run_screen(")
assert "try:" in main_src[j - 120:j] and "except Exception" in main_src[j:j + 260] and "candidates = []" in main_src[j:j + 400]
assert '"data_warnings": data_warnings.collect(' in main_src
print("  ✓ sector_rotation() и run_screen() са в try/except (при срив: [] + LAST_STATUS), а брифът носи data_warnings")
print()
print("Всички тестове минаха.")
