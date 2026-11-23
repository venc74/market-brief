"""
16.11.2026 (пакет 16.11, т. 5): покритието в премаркета падна до 58% (534 от 924, 13.11), без да се казва кои липсват. Сега карето (и имейлът) казва броя, причините и поименно
важните (картите, книгите, наблюдаваните, сутрешните EP); целият списък — сгънат. Изтеглено наново на 16.11 за 13.11, 09:07 Ню Йорк: 566 от 926 с премаркет (в пускането — 534:
Yahoo дава част от баровете със закъснение); от 360-те без цена — 359 „няма премаркет бари днес до 09:07“ (без сделка; Yahoo дава бар само при сделка), 1 — TCBI, „Yahoo не върна
5-минутни бари“ („possibly delisted“).

РЕАЛНО: tests/fixtures/preopen_missing_5m_2026-11-13.csv — 5-минутните бари с премаркет от Yahoo (yf.download, period 5d, prepost), изтеглени 16.11.2026 в ~15:40 Берлин,
по вида: AAPL, NVDA, CRWV (с премаркет в 09:07 на 13.11) и ACGL, ACM, ADC (без премаркет бар до 09:07), изрязани 12.11 00:00 → 13.11 09:45 Ню Йорк; TCBI — без бари (Yahoo не
върна нищо). brief_2026-10-19.json и ep_aaon_sanm_2026-11-10.json — рамката и карето. СИНТЕТИЧНО (означено): кои тикъри са „важни“ (наблюдавани / карти).
Пускане: python test_preopen_missing.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_pmmiss_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import preopen, render

FXD = ROOT / "tests" / "fixtures"
_df = pd.read_csv(FXD / "preopen_missing_5m_2026-11-13.csv")
FR = {s: g.set_index(pd.DatetimeIndex(pd.to_datetime(g["time_utc"], utc=True)))[["Open", "High", "Low", "Close", "Volume"]] for s, g in _df.groupby("symbol")}
FX = json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 13, 14, 7, tzinfo=dt.timezone.utc)                       # 09:07 Ню Йорк — часът на карето от 13.11
REQ = ["AAPL", "NVDA", "CRWV", "ACGL", "ACM", "ADC", "TCBI"]

print("── 1. РЕАЛНО: 13.11, 09:07 Ню Йорк — кои са без цена и защо ──")
pts = {t: p for t, df in FR.items() if (p := preopen.premarket_point(df, NOW))}
assert sorted(pts) == ["AAPL", "CRWV", "NVDA"]
m = preopen.missing_block(REQ, FR, pts, NOW, important=["ACM", "TCBI"])                  # СИНТЕТИЧНО: ACM и TCBI като „важни“
assert m["n"] == 4 and m["requested"] == 7 and m["tickers"] == ["ACGL", "ACM", "ADC", "TCBI"]
assert m["by_reason"] == [{"reason": "няма премаркет бари днес до 09:07 Ню Йорк", "n": 3, "tickers": ["ACGL", "ACM", "ADC"]},
                          {"reason": "Yahoo не върна 5-минутни бари", "n": 1, "tickers": ["TCBI"]}], m["by_reason"]
assert m["important"] == [{"ticker": "ACM", "reason": "няма премаркет бари днес до 09:07 Ню Йорк"}, {"ticker": "TCBI", "reason": "Yahoo не върна 5-минутни бари"}]
T = preopen.missing_text(m)
assert T == ("Без премаркет цена: 4 от 7 (57%) — няма премаркет бари днес до 09:07 Ню Йорк (Yahoo дава бар само при сделка): 3 (ACGL, ACM, ADC); "
             "Yahoo не върна 5-минутни бари: 1 (TCBI). От картите, книгите и наблюдаваните: ACM, TCBI."), T
print(f"  ✓ {T}")

print("── 2. мащабът (РЕАЛНО 13.11: 360 от 926) — над 5 в група без имената в реда ──")
big = {"n": 360, "requested": 926, "by_reason": [{"reason": "няма премаркет бари днес до 09:07 Ню Йорк", "n": 359, "tickers": ["X"] * 359},
                                                 {"reason": "Yahoo не върна 5-минутни бари", "n": 1, "tickers": ["TCBI"]}], "important": [], "tickers": []}
assert preopen.missing_text(big) == ("Без премаркет цена: 360 от 926 (39%) — няма премаркет бари днес до 09:07 Ню Йорк (Yahoo дава бар само при сделка): 359; "
                                     "Yahoo не върна 5-минутни бари: 1 (TCBI).")
assert preopen.missing_text({"n": 0}) is None and preopen.missing_text(None) is None
print("  ✓ 360 от 926 — групите с броя; всички с цена — без ред")

print("── 3. run(), карето и имейлът ──")
brief = {"watchlist": [], "qm_breakout": [], "qm_ep": {"rows": []}}
with contextlib.redirect_stdout(io.StringIO()):
    res = preopen.run(NOW, frames5=FR, brief=brief, records=[], watched=["ACM"], universe=REQ)
assert res["missing"]["n"] == 4 and [x["ticker"] for x in res["missing"]["important"]] == ["ACM"]
assert res["missing"]["text"].startswith("Без премаркет цена: 4 от 7 (57%)")
day = {**FX["preopen"], "missing": res["missing"]}
mail = preopen.email_html(day)
assert "Без премаркет цена: 4 от 7 (57%)" in mail and "От картите, книгите и наблюдаваните: ACM." in mail
bb = copy.deepcopy(B19); bb["preopen"] = day
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert "Без премаркет цена: 4 от 7 (57%)" in page and "▸ всички 4</summary>" in page and "ACGL, ACM, ADC, TCBI" in page
print("  ✓ run() с наблюдаван без цена (ACM); карето — редът и сгънатият списък; имейлът")
print("\n✅ test_preopen_missing: всичко мина")
