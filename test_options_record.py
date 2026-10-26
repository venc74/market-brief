"""
22.10.2026 · етап 4 (решение от 22.10): САМО ЗАПИС на опционните данни (src/options_record.py) — топ 200 по оборот + кандидатите от (а) (ход ≥ ±5% при обем ≥ 2× средния),
най-близките 2 падежа (обем и OI на call / put, последната сделка). Нищо в брифа; доклад след ~20 сесии. Включва се (ENABLE_OPTIONS_RECORD) след проверката кога Yahoo дава пълния обем.

РЕАЛНО: tests/fixtures/options_stock_side_2026-10-20.json — дневните барове на HAS, EFX, GM (кандидати от (а) на 20.10) и AAPL, MSFT, NVDA (Yahoo, 21.10);
tests/fixtures/yf_chain_roku_2026-10-22.json — веригата на ROKU (2 падежа) от yfinance на 22.10 (15:37 Берлин = 09:37 ET, сесията в ход). СИНТЕТИЧНО (означено): по-малкият топ N,
грешката на една верига, часът на снимката в т. 3.

26.10.2026 (етап 4б, т. 9): включено в сутрешния run със самопроверка — денят влиза в историята само ако последната сделка във веригите е от затварянето на сесията (16:00 ET) и
снимката е преди отварянето на следващата; иначе "incomplete" (без данните). РЕАЛНО: tests/fixtures/options_preopen_2026-10-22.json — снимката на 60 вериги от 22.10 09:12 ET
(последната сделка 21.10 16:00 ET — пълен ден).
Пускане: python test_options_record.py
"""
import sys, json, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_optrec_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import options_record as orc

SS = json.loads((ROOT / "tests" / "fixtures" / "options_stock_side_2026-10-20.json").read_text(encoding="utf-8"))["tickers"]
FR = {t: pd.DataFrame({"Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in SS.items()}
CH = json.loads((ROOT / "tests" / "fixtures" / "yf_chain_roku_2026-10-22.json").read_text(encoding="utf-8"))
assert config.ENABLE_OPTIONS_RECORD is True                                                    # 26.10.2026: включено със самопроверка

print("── 1. страната на акциите (РЕАЛНИ барове до 20.10) ──")
config.OPTIONS_RECORD_TOP_N = 3                                                                # СИНТЕТИЧНО: топ 3 от 6-те тикъра
top, cand = orc.stock_side(FR)
assert top == ["NVDA", "AAPL", "MSFT"], top
assert [(c["ticker"], c["date"]) for c in cand] == [("EFX", "2026-10-20"), ("HAS", "2026-10-20"), ("GM", "2026-10-20")], cand
assert [c["ret_pct"] for c in cand] == [11.3, 11.2, -6.8] or all(abs(c["ret_pct"]) >= 5 for c in cand)
print(f"  ✓ топ по оборот: {', '.join(top)}; кандидати от (а): " + ", ".join(f"{c['ticker']} {c['ret_pct']:+.1f}% ({c['vol_x']}×)" for c in cand))


class Tk:
    """РЕАЛНАТА верига на ROKU (2 падежа) като обект на yfinance: .options и .option_chain(e) с .calls / .puts."""
    def __init__(self, data): self.d = data
    @property
    def options(self): return tuple(self.d["options"])
    def option_chain(self, e):
        mk = lambda rows: pd.DataFrame(rows).assign(lastTradeDate=lambda x: pd.to_datetime(x["lastTradeDate"]))
        return type("C", (), {"calls": mk(self.d["chains"][e]["calls"]), "puts": mk(self.d["chains"][e]["puts"])})()


print()
print("── 2. веригата (РЕАЛНАТА на ROKU) ──")
row = orc.chain_row(Tk(CH))
exp = list(CH["chains"])
cv = sum((r["volume"] or 0) for e in exp for r in CH["chains"][e]["calls"]); poi = sum((r["openInterest"] or 0) for e in exp for r in CH["chains"][e]["puts"])
assert list(row["exp"]) == exp and row["cv"] == cv and row["poi"] == poi and row["last_trade"]
print(f"  ✓ 2 падежа ({', '.join(exp)}): call обем {row['cv']:.0f}, put OI {row['poi']:.0f}, последна сделка {row['last_trade'][:16]}")

print()
print("── 3. самопроверката: последната сделка и часът на снимката ──")
PRE = json.loads((ROOT / "tests" / "fixtures" / "options_preopen_2026-10-22.json").read_text(encoding="utf-8"))
pre = {t: {"last_trade": r["last"]} for t, r in PRE["rows"].items()}
c = orc.completeness(pre, "2026-10-21", PRE["taken_utc"])
assert c == {"complete": True, "last_trade_et": "2026-10-21T16:00:00-04:00", "reason": None}                     # РЕАЛНО: 22.10 09:12 ET — пълният 21.10
assert sum(r["last"] >= "2026-10-21 19:59" for r in PRE["rows"].values()) == 58 and len(pre) == 60
c20 = orc.completeness(pre, "2026-10-20", PRE["taken_utc"])
assert not c20["complete"] and "след сесията 20.10" in c20["reason"]                                              # веригите носят по-нова сесия
roku = {"ROKU": row}
assert row["last_trade"].startswith("2026-10-21 19:59:34")                                                        # РЕАЛНО: ROKU, 22.10 09:37 ET — още вчерашната последна сделка
c_r = orc.completeness(roku, "2026-10-21", "2026-10-22 13:37")
assert not c_r["complete"] and "след отварянето на следващата сесия" in c_r["reason"]                             # …но сесията вече тече — обемът е на новия ден
assert orc.completeness(roku, "2026-10-21", "2026-10-22 06:20")["complete"]                                     # СИНТЕТИЧЕН час: същата верига в 02:20 ET — пълна
early = orc.completeness({"X": {"last_trade": "2026-11-27 17:59:50+00:00"}}, "2026-11-27", "2026-11-30 06:20")      # СИНТЕТИЧНО: ранно затваряне 13:00 ET
assert early["complete"] and not orc.completeness({"X": {"last_trade": "2026-10-21 18:30:00+00:00"}}, "2026-10-21")["complete"]   # 14:30 ET — преди затварянето
assert orc.completeness({}, "2026-10-21")["reason"] == "веригите нямат време на последната сделка"
print(f"  ✓ 22.10 09:12 ET: последната сделка 21.10 16:00 ET → пълен (58 от 60 вериги ≥ 15:59 ET); като 20.10 → непълен; ROKU в 09:37 ET → непълен (сесията тече); "
      f"ранно затваряне 13:00 ET; 14:30 ET → непълен")

print()
print("── 4. записът: файлът, сесията, грешките, пазенето, непълният ден ──")
path = config.DATA_DIR / "options_daily.json"
def ticker(s):
    if s == "GM":
        raise ConnectionError("Yahoo")                                                         # СИНТЕТИЧНО: една верига пада
    return Tk(CH)
_real_completeness = orc.completeness
orc.completeness = lambda rows, session, taken=None: _real_completeness(rows, session, "2026-10-22 06:20")         # СИНТЕТИЧЕН час на снимката: сутринта на 22.10
try:
    st = orc.record(list(FR), "2026-10-22", download=lambda ts: FR, ticker=ticker, path=path, sleep=lambda s: None)
    data = json.loads(path.read_text(encoding="utf-8"))
    day = data["sessions"]["2026-10-21"]
    assert st["ok"] and st["complete"] and st["session"] == "2026-10-21" and st["tickers"] == 5 and st["candidates"] == 3 and st["errors"] == 1
    assert set(day["tickers"]) == {"NVDA", "AAPL", "MSFT", "EFX", "HAS"} and "GM" in day["errors"] and day["top_n"] == 3 and day["last_trade_et"] == "2026-10-21T15:59:34-04:00"
    st2 = orc.record(list(FR), "2026-10-21", download=lambda ts: FR, ticker=ticker, path=path, sleep=lambda s: None)   # сесия 20.10, а веригите са от 21.10 → непълен
finally:
    orc.completeness = _real_completeness
data = json.loads(path.read_text(encoding="utf-8"))
assert st2["ok"] and st2["complete"] is False and "след сесията 20.10" in st2["reason"] and "2026-10-20" not in data["sessions"]
assert data["incomplete"]["2026-10-20"]["tickers"] == 5 and "tickers" in data["incomplete"]["2026-10-20"] and isinstance(data["incomplete"]["2026-10-20"]["tickers"], int)
assert "2026-10-21" in data["sessions"]                                                                           # пълният ден остава
print("  ✓ сесия 21.10 (сутринта на 22.10): 5 вериги, 3 кандидата, 1 грешка (GM) → в историята; сесия 20.10 с веригите на 21.10 → 'incomplete' (без данните), историята непокътната")
from src import steps
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'partial=lambda v: (f"денят е непълен — {v.get(\'reason\')}"' in src
steps.reset()
steps.step("options_record", lambda: st2, enabled=True, label="Записът на опционните данни", consequence="…",
           failed_if=lambda v: (v.get("reason") or "не се изпълни") if not v.get("ok") else None,
           partial=lambda v: (f"денят е непълен — {v.get('reason')}", {"last_trade_et": v.get("last_trade_et")}) if v.get("ok") and v.get("complete") is False else None)
assert steps.summary()[-1]["status"] == "partial" and "денят е непълен" in steps.summary()[-1]["reason"]
print("  ✓ стъпката в main: непълен ден → 'partial' с причината")
for k in range(40):                                                                          # пазят се последните OPTIONS_RECORD_KEEP сесии
    data = orc.merge(data, f"2026-09-{k % 28 + 1:02d}" if k < 28 else f"2026-08-{k - 27:02d}", {"tickers": {}})
assert len(data["sessions"]) == config.OPTIONS_RECORD_KEEP and "2026-10-21" in data["sessions"] and "2026-10-20" in data["incomplete"]
bad = orc.record(list(FR), "2026-10-21", download=lambda ts: (_ for _ in ()).throw(RuntimeError("Yahoo down")), ticker=ticker, path=path)
assert bad["ok"] is False and "Yahoo down" in bad["reason"]
print("  ✓ пазят се последните 30 сесии (и непълните отделно); провал на тегленето → причина, без грешка")
print("\n✅ test_options_record: всичко мина")
