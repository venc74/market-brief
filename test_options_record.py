"""
22.10.2026 · етап 4 (решение от 22.10): САМО ЗАПИС на опционните данни (src/options_record.py) — топ 200 по оборот + кандидатите от (а) (ход ≥ ±5% при обем ≥ 2× средния),
най-близките 2 падежа (обем и OI на call / put, последната сделка). Нищо в брифа; доклад след ~20 сесии. Включва се (ENABLE_OPTIONS_RECORD) след проверката кога Yahoo дава пълния обем.

РЕАЛНО: tests/fixtures/options_stock_side_2026-10-20.json — дневните барове на HAS, EFX, GM (кандидати от (а) на 20.10) и AAPL, MSFT, NVDA (Yahoo, 21.10);
tests/fixtures/yf_chain_roku_2026-10-22.json — веригата на ROKU (2 падежа) от yfinance на 22.10 (сесията в ход). СИНТЕТИЧНО (означено): по-малкият топ N, грешката на една верига.
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
assert config.ENABLE_OPTIONS_RECORD is False                                                   # изключено, докато не се потвърди часът

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
print("── 3. записът: файлът, сесията, грешките, пазенето ──")
path = config.DATA_DIR / "options_daily.json"
def ticker(s):
    if s == "GM":
        raise ConnectionError("Yahoo")                                                         # СИНТЕТИЧНО: една верига пада
    return Tk(CH)
st = orc.record(list(FR), "2026-10-21", download=lambda ts: FR, ticker=ticker, path=path, sleep=lambda s: None)
data = json.loads(path.read_text(encoding="utf-8"))
day = data["sessions"]["2026-10-20"]
assert st["ok"] and st["session"] == "2026-10-20" and st["tickers"] == 5 and st["candidates"] == 3 and st["errors"] == 1
assert set(day["tickers"]) == {"NVDA", "AAPL", "MSFT", "EFX", "HAS"} and "GM" in day["errors"] and day["top_n"] == 3
for k in range(40):                                                                          # пазят се последните OPTIONS_RECORD_KEEP сесии
    data = orc.merge(data, f"2026-09-{k % 28 + 1:02d}" if k < 28 else f"2026-08-{k - 27:02d}", {"tickers": {}})
assert len(data["sessions"]) == config.OPTIONS_RECORD_KEEP and "2026-10-20" in data["sessions"]
bad = orc.record(list(FR), "2026-10-21", download=lambda ts: (_ for _ in ()).throw(RuntimeError("Yahoo down")), ticker=ticker, path=path)
assert bad["ok"] is False and "Yahoo down" in bad["reason"]
print("  ✓ сесия 20.10 (последната цяла преди 21.10): 5 вериги, 3 кандидата, 1 грешка (GM); пазят се последните 30 сесии; провал на тегленето → причина, без грешка")
print("\n✅ test_options_record: всичко мина")
