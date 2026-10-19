"""
19.10.2026 · етап 2, т. 16 (трети преглед, Н4): събитията за GLB и "GLB по Уиш" се теглят от месеца на най-старата линия, ако е преди CORP_ACTION_FETCH_PERIOD (5 г.).

Прозорецът на GLB е "събитие след месеца на линията", а линията може да е години назад. До 19.10 тегленето беше винаги "5y": PR беше GLB карта на 25.08–01.09.2026 с линия от
09.2018 — 5 години назад стигаха до 08.2021, събитие от 10.2018 до 08.2021 не се виждаше; TMO (линия 12.2021, в GLB 25.09–01.10 и в glb_state.json) щеше да излезе от прозореца
около 20.12.2026. Сега: начало = по-старото от (днес − 5 г.) и първия ден на месеца на най-старата линия; кешът на run-а помни от коя дата е изтеглен всеки тикър и тегли наново,
ако GLB иска по-стара дата от скрийнъра.

РЕАЛНО: tests/fixtures/glb_old_lines_2026-08-25_09-25.json — GLB картите на PR (25.08) и TMO (25.09) от data/. СИНТЕТИЧНО (означено): подмененото теглене / yf.download (записват
аргументите, събития няма), датата 21.12.2026, редът на скрийнъра {ticker}.
Пускане: python test_corp_action_old_lines.py
"""
import sys, json, pathlib, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import corp_actions as ca

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_old_lines_2026-08-25_09-25.json").read_text(encoding="utf-8"))
PR, TMO = FX["PR_2026-08-25"], FX["TMO_2026-09-25"]
D = dt.date.fromisoformat
assert (PR["prior_high_month"], TMO["prior_high_month"]) == ("2018-09", "2021-12")
assert config.CORP_ACTION_FETCH_PERIOD == "5y"

print("── 1. началото на тегленето ──")
assert ca.fetch_start([PR], "glb", D("2026-08-25")) == D("2018-09-01")
assert ca.fetch_start([TMO], "glb", D("2026-09-25")) == D("2021-09-25")                    # линията е в петте години → петте години
assert ca.fetch_start([TMO], "glb", D("2026-12-21")) == D("2021-12-01")                    # СИНТЕТИЧНА дата: 5 г. назад = 21.12.2021, след месеца на линията
assert ca.fetch_start([PR, TMO], "glb_wish", D("2026-10-19")) == D("2018-09-01")
assert ca.fetch_start([PR], "screener", D("2026-08-25")) == D("2021-08-25")                 # скрийнърът и QM — както досега
print("  ✓ PR 25.08 → от 01.09.2018 (линия 09.2018); TMO 25.09 → петте години (21.09.2021 е преди 12.2021); TMO на 21.12.2026 → от 01.12.2021; скрийнърът — 5 г.")

print()
print("── 2. кешът на run-а тегли наново за по-стара линия (СИНТЕТИЧНО теглене) ──")
calls = []


def fetch(tickers, start=None):
    calls.append((list(tickers), start))
    return {t: {"dates": [], "ratios": [], "close": pd.Series(dtype=float), "from": start.isoformat()} for t in tickers}


ca.reset()
with contextlib.redirect_stdout(io.StringIO()):
    ca.exclude([{"ticker": "PR"}], "screener", "2026-08-25", fetch=fetch)                   # СИНТЕТИЧЕН ред на скрийнъра
    ca.exclude([PR], "glb", "2026-08-25", fetch=fetch)
    ca.exclude([PR], "glb_wish", "2026-08-25", fetch=fetch)
assert calls == [(["PR"], D("2021-08-25")), (["PR"], D("2018-09-01"))], calls             # Уиш не тегли трети път — кешът стига
assert ca.LAST_DIAG["fetch_from"] == "2018-09-01"
print("  ✓ скрийнърът тегли от 25.08.2021, GLB — наново от 01.09.2018, Уиш — от кеша")

print()
print("── 3. fetch_actions подава start на yf.download (СИНТЕТИЧЕН yf.download) ──")
seen = {}
idx = pd.to_datetime(["2018-09-04", "2026-08-24"])
frame = pd.DataFrame({"Close": [20.0, 14.0], "Stock Splits": [0.0, 0.0]}, index=idx)


class _YF:
    @staticmethod
    def download(tickers, **kw):
        seen.update(kw)
        return frame


real_yf, ca.yf = ca.yf, _YF
try:
    out = ca.fetch_actions(["PR"], start=D("2018-09-01"))
    assert seen["start"] == "2018-09-01" and "period" not in seen and out["PR"]["from"] == "2018-09-01"
    seen.clear()
    out = ca.fetch_actions(["PR"])
    assert seen["period"] == "5y" and "start" not in seen and out["PR"]["from"] is None
finally:
    ca.yf = real_yf
print("  ✓ start → yf.download(start=…), записът носи 'from'; без start — периодът, както преди")

print()
print("── 4. старото подменено теглене (без start) работи както преди ──")
ca.reset()
with contextlib.redirect_stdout(io.StringIO()):
    kept, out = ca.exclude([PR], "glb", "2026-08-25", fetch=lambda ts: {t: {"dates": [], "ratios": [], "close": pd.Series(dtype=float)} for t in ts})
assert [r["ticker"] for r in kept] == ["PR"] and out == []
print("  ✓ fetch(tickers) без start — извиква се с тикърите, записът без 'from' се смята за покрит")
print("\n✅ test_corp_action_old_lines: всичко мина")
