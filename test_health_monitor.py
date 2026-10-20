"""
Здравен монитор (втори преглед, 10.10.2026, подобрение №1) · src/health_monitor.py + backtest.LAST_RESOLUTION + data_warnings.

Цел: К1 (OI снимката не се записва от 09.10) да не може да мине незабелязано пак. Проверки в края на run-а: OI снимка за предишната NYSE сесия, брифът за предишната
сесия, резолюцията на книгите, записаното GLB състояние, дневните кешове.
РЕАЛНО (data/ към 10.10, вградено тук — тестовете не четат data/): сесиите в OI снимката 30.09…08.10 (09.10 липсва — К1), glb_state.updated = 09.10, датата на
news/splits/dataroma/magic_formula кешовете = 09.10. Измерено върху историята: 28 брифа от 01.09 — кешовете/GLB никога не изостават (0 фалшиви); OI проверката от 29.09 —
сигнал само на 29.09 (job-ът още не съществуваше — верен). СИНТЕТИЧНО: състоянията на резолюцията, подмененото yf.download в т.3, датите 12.10 / 13.10.
Пускане: python test_health_monitor.py
"""
import sys, json, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import health_monitor as hm, data_warnings, backtest

REAL_SESSIONS = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]


def world(sessions=REAL_SESSIONS, cache_date="2026-10-09", glb_updated="2026-10-09", briefs=("2026-10-08", "2026-10-09")):
    d = pathlib.Path(tempfile.mkdtemp(prefix="mb_health_"))
    (d / "unusual_options_oi_snapshot.json").write_text(json.dumps({"snapshots": {s: {"session_date": s} for s in sessions}}))
    (d / "glb_state.json").write_text(json.dumps({"updated": glb_updated, "events": {}}))
    for f in hm.DAILY_CACHES:
        (d / f).write_text(json.dumps({"date": cache_date}))
    for b in briefs:
        (d / f"{b}.json").write_text("{}")
    return d


OK_RES = {"ok": True, "live": 9, "priced": 9, "missing": [], "data_through": "2026-10-08"}

print("── 1. РЕАЛНОТО състояние в края на run-а от 09.10: нищо за докладване ──")
assert hm.prev_session("2026-10-09").isoformat() == "2026-10-08" and hm.prev_session("2026-10-12").isoformat() == "2026-10-09"
assert hm.prev_session("2026-09-08").isoformat() == "2026-09-04"                     # празник 07.09
assert hm.check("2026-10-09", world(), resolution=OK_RES, glb_status={"ok": True}) == []
print("  ✓ 0 проблема (предишната сесия 08.10 е в снимката, брифът за 08.10 го има, GLB и кешовете са от 09.10)")

print()
print("── 2. понеделник 12.10 с РЕАЛНАТА снимка (09.10 липсва — К1), всичко друго обновено ──")
w = world(cache_date="2026-10-12", glb_updated="2026-10-12", briefs=("2026-10-09",))
iss = hm.check("2026-10-12", w, resolution=dict(OK_RES, data_through="2026-10-09"), glb_status={"ok": True})
assert [i["check"] for i in iss] == ["oi_snapshot"] and "OI снимката за сесията 09.10 липсва (последна: 08.10)" in iss[0]["message"]
banner = data_warnings.collect(None, None, health=iss)
assert banner == [{"source": "health:oi_snapshot", "level": "warn", "message": "Здравна проверка: " + iss[0]["message"]}]
print("  ✓ само «OI снимката за сесията 09.10 липсва (последна: 08.10) … провери job-а» → банер «Здравна проверка: …»")

print()
print("── 3. книгите: backtest.LAST_RESOLUTION от реалната функция с подменено теглене ──")
tr = {"AAA_2026-10-09_buystop": {"ticker": "AAA", "status": "pending", "entry_date": "2026-10-09", "method": "v2", "category": "buystop"},
      "BBB_2026-10-09_buystop": {"ticker": "BBB", "status": "pending", "entry_date": "2026-10-09", "method": "v2", "category": "buystop"}}


def boom(*a, **k):
    raise RuntimeError("YFRateLimitError (СИНТЕТИЧНО)")


backtest.yf.download = boom
backtest._unapplied_splits = lambda rec: []                                          # СИНТЕТИЧНО: проверката за сплит след входа е мрежа (yf.Ticker(...).splits)
backtest._resolve_open_positions(dict(tr), today=pd.Timestamp("2026-10-12").date())
assert backtest.LAST_RESOLUTION["ok"] is False and backtest.LAST_RESOLUTION["live"] == 2
i3 = hm.check("2026-10-12", world(sessions=REAL_SESSIONS + ["2026-10-09"], cache_date="2026-10-12", glb_updated="2026-10-12", briefs=("2026-10-09",)),
              resolution=backtest.LAST_RESOLUTION, glb_status={"ok": True})
assert [i["check"] for i in i3] == ["books"] and "цените за 2 живи записа не се изтеглиха" in i3[0]["message"]
idx = pd.to_datetime(["2026-10-07", "2026-10-08"])
backtest.yf.download = lambda *a, **k: pd.DataFrame({(c, "AAA"): [10.0, 10.5] for c in ("Open", "High", "Low", "Close")}, index=idx)
backtest._resolve_open_positions(dict(tr), today=pd.Timestamp("2026-10-12").date())
r = backtest.LAST_RESOLUTION
assert r["ok"] is True and r["missing"] == ["BBB"] and r["data_through"] == "2026-10-08"
i4 = hm.check("2026-10-12", world(sessions=REAL_SESSIONS + ["2026-10-09"], cache_date="2026-10-12", glb_updated="2026-10-12", briefs=("2026-10-09",)),
              resolution=r, glb_status={"ok": True})
msgs = " | ".join(i["message"] for i in i4)
assert [i["check"] for i in i4] == ["books", "books"] and "до 08.10, очаквано 09.10" in msgs and "без цени днес (резолюцията им е отложена): BBB" in msgs
print("  ✓ паднало теглене → «книгите не са обновени днес»; цени до 08.10 при очаквано 09.10 и тикър без цени → два реда")

print()
print("── 4. GLB състояние, предишен бриф, кешове ──")
i5 = hm.check("2026-10-12", world(sessions=REAL_SESSIONS + ["2026-10-09"], cache_date="2026-10-09", glb_updated="2026-10-09", briefs=()),
              resolution={"ok": True, "live": 0}, glb_status={"ok": True})
assert sorted({i["check"] for i in i5}) == ["cache", "glb_state", "prior_brief"] and sum(i["check"] == "cache" for i in i5) == 4
assert hm.check("2026-10-12", world(sessions=REAL_SESSIONS + ["2026-10-09"], cache_date="2026-10-12", glb_updated="2026-10-09", briefs=("2026-10-09",)),
                resolution={"ok": True, "live": 0}, glb_status={"ok": False}) == []                    # GLB падна → банерът е от С3, не от монитора
print("  ✓ липсващ предишен бриф, стари кешове (4) и незаписано GLB състояние → редове; при паднал GLB мониторът не дублира банера на С3")

print()
print("── 4б. таблицата NYSE_HOLIDAYS (РЕАЛНАТА — покрива до 2028 от 16.10.2026) ──")
assert max(int(h[:4]) for h in config.NYSE_HOLIDAYS) == 2028
w_ok = world(cache_date="2028-10-02", glb_updated="2028-10-02", briefs=("2028-09-29",), sessions=["2028-09-29"])
assert "holidays" not in {i["check"] for i in hm.check("2028-10-02", w_ok, resolution={"ok": True, "live": 0}, glb_status={"ok": True})}
w_late = world(cache_date="2028-11-15", glb_updated="2028-11-15", briefs=("2028-11-14",), sessions=["2028-11-14"])
hol = [i for i in hm.check("2028-11-15", w_late, resolution={"ok": True, "live": 0}, glb_status={"ok": True}) if i["check"] == "holidays"]
assert len(hol) == 1 and "покрива до 2028 г. (остават 46 дни)" in hol[0]["message"] and "празниците за 2029" in hol[0]["message"]
print("  ✓ СИНТЕТИЧНА 'днес' 02.10.2028 (90 дни до края) → нищо; 15.11.2028 (46 дни) → «покрива до 2028 г. (остават 46 дни) — добави празниците за 2029»")

print()
print("── 5. main ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "health_monitor.check(today, resolution=backtest.LAST_RESOLUTION" in src and "canary=canary, health=health," in src and '"health": health,' in src   # 19.10: + още аргументи след health (т. 12)
assert '"check": "health_monitor"' in src                                     # 19.10 (т. 12): паднал монитор → ред в банера, не тихо []
print("  ✓ main пуска монитора в края, подава го на data_warnings и го записва в брифа (health)")
print()
print("Всички тестове минаха.")
