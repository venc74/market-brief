"""
19.10.2026 · етап 2, т. 13 (трети преглед, С1/С2): повторен run в същия ден.

Реално: на 22.06.2026 брифът върви 5 пъти (05:36, 14:21, 14:41, 15:06, 19:02 UTC — четири по време на US сесията), Action списъкът е различен всеки път (ROK/CAT/ADI → ADI/AIZ/KEYS →
CAT/ADI → CAT/AIZ/ADI → AIZ/AMG) и излизат пет имейла. В хода на сесията Yahoo дава ЧАСТИЧЕН бар за днес (19.10 в 18:55 UTC: SPY с обем 22 млн при 64 млн на 16.10; във
fixture-а ohlc_EXEL.csv барът от 02.10 е с неокръглен обем 1 972 056 — свален по време на сесията).
  • С1: trade_sim.simulate / simulate_qm / simulate_glb_wish режат баровете с дата >= today (реплеят — без today — непроменен); GLB картите и наблюденията — също.
  • С2: ingest от диска пропуска snapshot-а с дата == днес (той е от по-ранния run; днешните карти идват in-memory).
  • Имейл: един на ден на брифа (data/email_state.json след УСПЕШНО изпращане; FORCE_EMAIL=1 праща отново).

РЕАЛНО: суровите барове на EXPD до 06.10 (ohlc_EXPD_SPY_raw_2026-10-06.json) и записът на книгата от 05.10 (buy-stop $194.59, стоп $181.53 — test_buystop_book_state); брифът от 16.10
(tests/fixtures/brief_2026-10-16.json: Action EXPD с v2 план). СИНТЕТИЧНО (означено): частичният бар на 07.10, записите на QM / Уиш върху реалните барове, подмененото изпращане,
временната data/.
Пускане: python test_same_day_rerun.py
"""
import sys, json, pathlib, tempfile, shutil, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_rerun_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.EMAIL_STATE_FILE = config.DATA_DIR / "email_state.json"
from src import trade_sim, glb_screener, backtest, emailer             # backtest._TRACKER_PATH — от временната data/ (импортът е след подмяната)
assert backtest._TRACKER_PATH.parent == config.DATA_DIR

FX = ROOT / "tests" / "fixtures"
B = json.loads((FX / "ohlc_EXPD_SPY_raw_2026-10-06.json").read_text(encoding="utf-8"))["bars"]["EXPD"]
real = pd.DataFrame({"Open": B["o"], "High": B["h"], "Low": B["l"], "Close": B["c"], "Volume": B["v"]}, index=pd.to_datetime(B["dates"]))
partial = pd.DataFrame({"Open": [191.5], "High": [192.0], "Low": [180.0], "Close": [190.0], "Volume": [300000]}, index=pd.to_datetime(["2026-10-07"]))   # СИНТЕТИЧНО
bars = pd.concat([real, partial])
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. С1: trade_sim без частичния днешен бар ──")
plan = {"buy_stop": 194.59, "max_chase": 204.32, "stop_loss": 181.53, "target_1": 220.71, "entry_date": "2026-10-05", "window_sessions": 5}
assert trade_sim.simulate(plan, bars, "2026-10-07")["status"] == "open"                          # run на 07.10: low 180 на частичния бар НЕ е стоп
assert trade_sim.simulate(plan, bars)["status"] == "stopped"                                     # без today (реплеят): барът се брои — както преди
assert len(trade_sim.complete_bars(bars, "2026-10-07")) == len(real) and trade_sim.complete_bars(bars, None) is bars
qm = {"entry_date": "2026-10-07", "buy_stop": 191.0, "adr": 2.0}                                   # СИНТЕТИЧЕН запис: входът е в сесията на брифа (07.10)
assert trade_sim.simulate_qm(qm, bars, "2026-10-07")["status"] == "pending" and trade_sim.simulate_qm(qm, bars)["status"] != "pending"
gw = {"signal_date": "2026-10-05", "line": 190.5, "signal_close": 194.12}                         # СИНТЕТИЧЕН запис върху реалните затваряния (05.10 194.12, 06.10 191.80)
assert trade_sim.simulate_glb_wish(gw, bars, "2026-10-07")["status"] == "open" and trade_sim.simulate_glb_wish(gw, bars)["status"] == "line_exit"
print("  ✓ buy-stop EXPD (реален запис): run на 07.10 — open (частичният low 180 не е стоп), реплеят — stopped; QM вход днес — pending; Уиш — open (частичното затваряне под линията не е изход)")

print()
print("── 2. С1: GLB картите режат днешния бар ──")
assert len(glb_screener._complete_bars(bars, "2026-10-07")) == len(real) and glb_screener._complete_bars(bars, "2026-10-08").index[-1] == pd.Timestamp("2026-10-07")
src = (ROOT / "src" / "glb_screener.py").read_text(encoding="utf-8")
assert src.index("df = _complete_bars(df, today)") < src.index("w = wish_signal(df, today)")
print("  ✓ _complete_bars(…, днес) маха днешния бар преди картите, наблюденията, seed-а и сигнала на Уиш")

print()
print("── 3. С2: ingest от диска пропуска днешния snapshot (РЕАЛНИЯТ бриф от 16.10) ──")
shutil.copy(FX / "brief_2026-10-16.json", config.DATA_DIR / "2026-10-16.json")
tr = {}
with q():
    backtest._ingest_new_positions(tr, today_action=[], today_date="2026-10-16")
assert not [k for k, r in tr.items() if r.get("entry_date") == "2026-10-16"], sorted(tr)
tr = {}
with q():
    backtest._ingest_new_positions(tr, today_action=[], today_date="2026-10-19")                    # следващ ден: пропуснатият run се възстановява от файла, както досега
assert "EXPD_2026-10-16" in tr and tr["EXPD_2026-10-16"]["method"] == "v2"
print("  ✓ повторен run на 16.10: файлът от сутринта не се ingest-ва; на 19.10 — да (EXPD 16.10 от файла)")

print()
print("── 4. имейл: един на ден (СИНТЕТИЧНО изпращане) ──")
sent = []
emailer.send_brief = lambda html, subject: sent.append(subject) or True
with q():
    r1 = emailer.send_once("<html>", "бриф 1", "2026-10-19")
    r2 = emailer.send_once("<html>", "бриф 2", "2026-10-19")
assert r1 == {"sent": True, "skipped": None} and r2["sent"] is False and "вече е изпратен" in r2["skipped"] and sent == ["бриф 1"]
config.FORCE_EMAIL = True
with q():
    assert emailer.send_once("<html>", "бриф 3", "2026-10-19")["sent"] is True
config.FORCE_EMAIL = False
with q():
    assert emailer.send_once("<html>", "бриф 4", "2026-10-20")["sent"] is True
assert sent == ["бриф 1", "бриф 3", "бриф 4"]
emailer.send_brief = lambda html, subject: False                                                  # провал → без запис → повторният run праща
config.EMAIL_STATE_FILE.unlink()
with q():
    assert emailer.send_once("<html>", "x", "2026-10-21")["sent"] is False
assert not config.EMAIL_STATE_FILE.exists()
config.EMAIL_STATE_FILE.write_text("{счупен", encoding="utf-8")
assert emailer.sent_on("2026-10-21") is None                                                       # нечетим файл → праща (по-добре втори, отколкото никакъв)
srcm = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "send_once(email_html, subject, today)" in srcm and "    send_brief(email_html, subject)" not in srcm
print("  ✓ втори run в същия ден — без имейл (ред в лога); FORCE_EMAIL=1 — праща; нов ден — праща; неуспешно изпращане не се записва")
print("\n✅ test_same_day_rerun: всичко мина")
