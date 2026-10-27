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
import datetime as _dt
assert config.OPTIONS_RECORD_KEEP == 90                                                      # 26.10.2026: плъзгащ се прозорец от 90 сесии
for k in range(120):                                                                         # СИНТЕТИЧНО: 120 по-стари сесии → остават последните 90, по-старите са изтрити
    data = orc.merge(data, (_dt.date(2026, 5, 1) + _dt.timedelta(days=k)).isoformat(), {"tickers": {}})
assert len(data["sessions"]) == config.OPTIONS_RECORD_KEEP and "2026-10-21" in data["sessions"] and "2026-10-20" in data["incomplete"]
assert min(data["sessions"]) > "2026-05-31" and "2026-05-01" not in data["sessions"]
bad = orc.record(list(FR), "2026-10-21", download=lambda ts: (_ for _ in ()).throw(RuntimeError("Yahoo down")), ticker=ticker, path=path)
assert bad["ok"] is False and "Yahoo down" in bad["reason"]
print("  ✓ пазят се последните 90 сесии, по-старите се трият (и непълните отделно); провал на тегленето → причина, без грешка")

print()
print("── 5. отделният job преди отварянето (27.10.2026): кога пропуска; сутрешният бриф не записва ──")
assert config.OPTIONS_RECORD_IN_MORNING_RUN is False
assert "config.OPTIONS_RECORD_IN_MORNING_RUN" in src[src.index('steps.step("options_record"'):][:300]
H = {"sessions": {"2026-10-21": {}}}
assert orc.skip_reason("2026-10-22 13:12", {}) is None                                                     # РЕАЛНИЯТ час от 22.10: 09:12 EDT — пълна верига
assert orc.skip_reason("2026-10-22 13:12", H).startswith("сесия 2026-10-21 вече е записана пълна")          # повторен dispatch
assert orc.skip_reason("2026-10-30 13:05", {}) is None                                                     # 09:05 EDT (лятно време до 01.11)
assert "след отварянето" in orc.skip_reason("2026-10-30 14:05", {})                                        # 14:05 UTC = 10:05 EDT — веригата вече е на новия ден
assert orc.skip_reason("2026-11-02 14:05", {}) is None                                                     # 02.11 (след 01.11): 14:05 UTC = 09:05 EST — тригерът по Ню Йорк
assert orc.skip_reason("2026-11-02 14:31", {}).startswith("09:31 EST — след отварянето")
assert "не е сесия" in orc.skip_reason("2026-10-31 13:05", {}) and "не е сесия" in orc.skip_reason("2026-11-26 14:05", {})   # събота; Thanksgiving
# 27.10.2026: задачата в cron-job.org е по Берлин — "5 14,15 * * 1-5" (часовата зона не се сменя там); 02.11 в 14:05 Берлин = 13:05 UTC = 08:05 EST → преди прозореца
assert orc.skip_reason("2026-11-02 13:05", {}).startswith("08:05 EST — преди прозореца (09:00–09:30 Ню Йорк)")
from zoneinfo import ZoneInfo
import pandas as _pd
from src import sessions as _ses
_d, _odd = _dt.date(2026, 10, 28), []
while _d <= _dt.date(2027, 12, 31):                                                        # година напред: и двете смени на часа (САЩ и Европа), с разминаванията им
    if _ses.is_session(_d):
        runs = [_pd.Timestamp(_dt.datetime(_d.year, _d.month, _d.day, h, 5, tzinfo=ZoneInfo("Europe/Berlin"))).tz_convert("UTC") for h in (14, 15)]
        ok = [r for r in runs if orc.skip_reason(r, {}) is None]
        if len(ok) != 1 or ok[0].tz_convert("America/New_York").strftime("%H:%M") != "09:05":
            _odd.append((_d, [r.tz_convert("America/New_York").strftime("%H:%M") for r in runs]))
    _d += _dt.timedelta(days=1)
assert _odd == [], _odd[:5]
print("  ✓ графикът по Берлин „5 14,15 * * 1-5“ до края на 2027: всяка сесия — точно едно пускане записва и то е в 09:05 Ню Йорк; другото (08:05 или 10:05) пропуска")
import re as _re
YML = (ROOT / ".github" / "workflows" / "options_record.yml").read_text(encoding="utf-8")
live = "\n".join(l for l in YML.splitlines() if not l.lstrip().startswith("#"))
assert not _re.search(r"^\s*schedule:", live, _re.M) and "workflow_dispatch" in live and "group: options-record" in live
assert "python src/options_record.py" in live and "git add data/options_daily.json" in live and "git add data/\n" not in live and "git stash push --include-untracked" in live
print("  ✓ 09:05 EDT (30.10) и 09:05 EST (02.11) → запис; 10:05 EDT / 09:31 EST → пропуска; събота, Thanksgiving, вече пълна сесия → пропуска; брифът не записва; "
      "options_record.yml — само workflow_dispatch, собствена група, качва само options_daily.json")
print("\n✅ test_options_record: всичко мина")
