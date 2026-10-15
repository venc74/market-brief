"""
16.10.2026 · предпазител за ЗАСТОЯЛ дневен бар (src/bar_freshness.py): изчакване и нов опит преди run-а, дял на универса със стар бар след скрийнъра, един банер през здравната проверка.

РЕАЛНО: tests/fixtures/stale_bars_cards_2026-07-29_09-24.json — цените на картите от брифовете на 6-те дни със застоял бар (29.07, 04.08, 18.08, 19.08, 04.09, 23.09) и 2 контролни (30.07, 24.09)
и затварянията на Yahoo за d1/d2 (свалени 15.10); tests/fixtures/yf_download_bars_2026-09-14_09-25.csv — реален резултат на yf.download (SPY, QQQ, AAPL, MSFT; group_by="ticker").
СИНТЕТИЧНО (маркирано): "сутрешното" състояние на Yahoo (махнат ред за 22.09 / NaN Close — като инцидента от 23.09), кошницата от 3 тикъра, подменените sleep/часовник/теглене,
"универсът" в т. 1 = картите на деня (истинският универс не е записан в брифа).
Пускане: python test_bar_freshness.py
"""
import sys, json, pathlib, io, contextlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bars_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import bar_freshness as bf, health_monitor, data_warnings, screener

FX = json.loads((ROOT / "tests" / "fixtures" / "stale_bars_cards_2026-07-29_09-24.json").read_text(encoding="utf-8"))["days"]
BARS = pd.read_csv(ROOT / "tests" / "fixtures" / "yf_download_bars_2026-09-14_09-25.csv", header=[0, 1], index_col=0, parse_dates=True)
D = dt.date.fromisoformat
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНИТЕ 6 дни: картите са с бара от предишната сесия ──")
def last_dates(day):
    v = FX[day]; out = {}
    for c in v["cards"]:
        m1, m2 = abs(c["price"] / c["close_d1"] - 1) < 0.002, abs(c["price"] / c["close_d2"] - 1) < 0.002
        if m1 != m2:
            out[c["ticker"]] = v["d1"] if m1 else v["d2"]
    return out
got = {}
for day in ("2026-07-29", "2026-08-04", "2026-08-18", "2026-08-19", "2026-09-04", "2026-09-23", "2026-07-30", "2026-09-24"):
    bf.LAST_DIAG.clear()
    ld = last_dates(day)
    u = bf.universe(ld, list(ld), D(day))
    assert u["expected"] == FX[day]["d1"]
    got[day] = (u["stale"], u["n"], bf.message(bf.LAST_DIAG))
assert {d: g[:2] for d, g in got.items()} == {"2026-07-29": (10, 10), "2026-08-04": (5, 5), "2026-08-18": (9, 9), "2026-08-19": (4, 10), "2026-09-04": (4, 4), "2026-09-23": (3, 3),
                                               "2026-07-30": (0, 12), "2026-09-24": (0, 3)}, {d: g[:2] for d, g in got.items()}
assert got["2026-07-29"][2].startswith("дневните данни за 10 от 10 тикъра в универса са от 27.07 (Yahoo не е обновил сесията 28.07)")
assert "Засегнати карти: " in got["2026-08-19"][2] and got["2026-08-19"][2].startswith("дневните данни за 4 от 10 тикъра")
assert got["2026-07-30"][2] is None and got["2026-09-24"][2] is None
print("  ✓ 29.07 10/10, 04.08 5/5, 18.08 9/9, 19.08 4/10 (частично), 04.09 4/4, 23.09 3/3 — банер; контролните 30.07 и 24.09 — без банер")
print("   ", got["2026-08-19"][2])

print()
print("── 2. предварителната проверка върху РЕАЛНИЯ yf.download (кошницата е СИНТЕТИЧНА: 3 тикъра) ──")
config.BAR_FRESHNESS_PROBE = ("QQQ", "AAPL", "MSFT")
dates = bf.last_bar_dates(["SPY", "QQQ", "AAPL", "MSFT"], fetch=lambda t: BARS)
assert dates == {t: "2026-09-25" for t in ("SPY", "QQQ", "AAPL", "MSFT")}
cut = lambda last: (lambda t: BARS[BARS.index <= pd.Timestamp(last)])                                   # СИНТЕТИЧНО: Yahoo "до" дадена дата
assert bf.probe(D("2026-09-23"), cut("2026-09-22"))["ok"] is True
p = bf.probe(D("2026-09-23"), cut("2026-09-21"))                                                       # СИНТЕТИЧНО: в 07:30 на 23.09 бара за 22.09 го няма
assert (p["ok"], p["expected"], p["spy_last"], p["data_from"], p["basket_fresh"]) == (False, "2026-09-22", "2026-09-21", "2026-09-21", 0)
nan = BARS[BARS.index <= pd.Timestamp("2026-09-22")].copy()
nan.loc[pd.Timestamp("2026-09-22"), [(t, "Close") for t in ("SPY", "QQQ", "AAPL", "MSFT")]] = np.nan          # СИНТЕТИЧНО: частичен бар — High/Low, без Close (инцидентът от 23.09)
assert bf.probe(D("2026-09-23"), lambda t: nan)["ok"] is False
print("  ✓ реалният формат се чете (последен бар 25.09 за четирите); без бара за 22.09 или с NaN Close → застоял, 'данните са от 21.09'")

print()
print("── 3. изчакване и нов опит (подменени sleep и часовник) ──")
class Clock:
    t = 0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s
c = Clock(); seq = [cut("2026-09-21"), cut("2026-09-21"), cut("2026-09-22")]
with quiet():
    r = bf.wait_for_fresh(D("2026-09-23"), fetch=lambda t: seq.pop(0)(t), sleep=c.sleep, clock=c)
assert (r["ok"], r["attempts"], r["waited_sec"]) == (True, 3, 600) and bf.message(bf.LAST_DIAG) is None
print("  ✓ два застояли опита и пресен на третия: ok след 10 мин, без банер")
c = Clock()
with quiet():
    r = bf.wait_for_fresh(D("2026-09-23"), fetch=cut("2026-09-21"), sleep=c.sleep, clock=c)
assert (r["ok"], r["attempts"], r["waited_sec"]) == (False, 6, 1500) and config.BAR_FRESHNESS_MAX_WAIT_SEC == 1500 and config.BAR_FRESHNESS_RETRY_SEC == 300
msg = bf.message(bf.LAST_DIAG)
assert msg.startswith("дневните данни са от 21.09 (Yahoo не е обновил сесията 22.09; изчакано 25 мин) — скрийнърът, картите и термометърът са с данните от предишната сесия.")
print("  ✓ застоял и след 25 мин (6 опита на 5 мин): брифът тръгва;", msg)
c = Clock()
with quiet():
    r = bf.wait_for_fresh(D("2026-09-23"), fetch=lambda t: (_ for _ in ()).throw(RuntimeError("Yahoo down (СИНТЕТИЧНО)")), sleep=c.sleep, clock=c)
assert (r["ok"], r["attempts"], r["waited_sec"]) == (None, 3, 600) and bf.message(bf.LAST_DIAG) is None
print("  ✓ изключения от Yahoo: 3 опита (10 мин), после продължава без банер от този модул (паднал Yahoo има свои банери)")

print()
print("── 4. банерът — през здравната проверка, веднъж ──")
c = Clock()
with quiet():
    bf.wait_for_fresh(D("2026-09-23"), fetch=cut("2026-09-21"), sleep=c.sleep, clock=c)
h = health_monitor.check("2026-09-23", config.DATA_DIR, freshness=dict(bf.LAST_DIAG))
hit = [x for x in h if x["check"] == "daily_bars"]
assert len(hit) == 1 and hit[0]["message"] == msg
w = data_warnings.collect(None, None, health=h)
assert sum("дневните данни са от 21.09" in x["message"] for x in w) == 1 and any(x["message"] == "Здравна проверка: " + msg for x in w)
assert not [x for x in health_monitor.check("2026-09-23", config.DATA_DIR, freshness={"ok": True, "expected": "2026-09-22"}) if x["check"] == "daily_bars"]
print("  ✓ 'Здравна проверка: дневните данни са от 21.09 …' — един ред; пресни данни → нищо")

print()
print("── 5. скрийнърът записва последната дата на всеки тикър (РЕАЛНИЯТ yf.download) ──")
real_dl = screener.yf.download
screener.yf.download = lambda t, **k: BARS["SPY"] if t == "SPY" else BARS[[c for c in BARS.columns if c[0] in t]]
try:
    with quiet():
        screener.technical_screen(["QQQ", "AAPL", "MSFT"])
finally:
    screener.yf.download = real_dl
assert screener.LAST_BAR_DATES == {"QQQ": "2026-09-25", "AAPL": "2026-09-25", "MSFT": "2026-09-25"}
print("  ✓ LAST_BAR_DATES = 25.09 за трите")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index("bar_freshness.wait_for_fresh(dt.date.fromisoformat(today))") < src.index("macro = collect_macro_layer()")
assert src.index("bar_freshness.universe(screener.LAST_BAR_DATES") < src.index("health = health_monitor.check(") and '"bar_freshness": dict(bar_freshness.LAST_DIAG)' in src
print("  ✓ main: изчакването е преди първото теглене (макро), делът на универса — преди здравната проверка; brief['bar_freshness']")
print("\n✅ test_bar_freshness: всичко мина")
