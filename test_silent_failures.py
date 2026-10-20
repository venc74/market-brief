"""
19.10.2026 · етап 2, т. 12 (трети преглед): тихи частични провали → ред / банер. Пълните провали вече имаха банер; тук е "част от данните липсва днес".

  • сектори (n от 17), скрийнър (тикъри без история без паднала партида; от 20.10 — тикъри БЕЗ бар ≥ 1% от универса, спрямо фона 0 от 903),
    OI снимка (неуспешни тикъри), 13F (n от 15 мениджъра), GLB (тикъри без история без паднала партида — праг 99%; 19.10: 903 от 903), INS✓ за позициите,
    празни новини, канарче без проверка, липсващ FRED_API_KEY — data_warnings._partial_warnings;
  • spinoff_watch: тикър без CIK → "непроверен" (до 19.10 — тихо прескачане, checked < requested без банер);
  • паднал здравен монитор → ред "мониторът не се изпълни" (до 19.10 — health = [], т.е. "всичко наред");
  • неуспешен имейл → банер на днешната страница и в JSON-а (страницата се рендерира наново след изпращането).
Измерено в 89 реални брифа: секторите винаги 17 от 17, 13F — 15 от 15, GLB — 903 от 903, канарчето — проверено, новините — никога празни, OI снимката — 0 неуспешни;
новите банери върху тях — 0 (без фалшиви). Пътищата в кода бяха тихи.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json (статусите на деня: superinvestor_status, glb_status, uov_diag, insider_buying_positions_status, data_canary).
СИНТЕТИЧНО (означено): частичните варианти на същите статуси, подмененото теглене от EDGAR, празният пул на новините.
Пускане: python test_silent_failures.py
"""
import sys, json, pathlib, tempfile, io, contextlib, copy, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_silent_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
from src import data_warnings as dw, spinoff_watch, news_aggregator as na

B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
SECT = {"ok": True, "etfs_total": 17, "etfs_ok": len(B["rotation"]), "missing": []}
REAL = dict(sector_status=SECT, screener_status=None, superinvestor_status=B["superinvestor_status"], glb_status=B["glb_status"], uov_diag=B["uov_diag"],
            ins_pos_status=B["insider_buying_positions_status"], news_status={"ok": True, "count": 8}, canary=B["data_canary"], fred_key_missing=False)
pw = lambda **kw: dw._partial_warnings(**{**REAL, **kw})
src_of = lambda ws: [w["source"] for w in ws]

print("── 1. РЕАЛНИЯТ ден 19.10 → нито един частичен банер ──")
assert len(B["rotation"]) == 17 and B["glb_status"]["with_history"] == 903 and B["superinvestor_status"]["managers_with_data"] == 15
assert pw() == []
print("  ✓ 17 от 17 сектора, 15 от 15 мениджъра, GLB 903 от 903, канарчето проверено, INS✓ за позициите — легитимна нула → 0 банера")

print()
print("── 2. частичните провали (СИНТЕТИЧНИ варианти на реалните статуси) ──")
w = pw(sector_status={**SECT, "etfs_ok": 15, "missing": ["TAN", "URA"]})
assert src_of(w) == ["sector_rotation"] and "15 от 17 секторни ETF-а — без данни днес: TAN, URA" in w[0]["message"]
# 20.10.2026 (етап 3б): прагът е спрямо нормалния фон — тикъри БЕЗ НИТО ЕДИН бар ≥ 1% от универса. РЕАЛНИ броеве: пробното пускане при ограничение на 20.10 (12:54) —
# 903 / 869 с бар / 865 с история (старият праг 90% мълчеше); чист run (16.10, 19.10, 20.10) — 903 с бар, 898 с история (5 нови листинга). Имената са СИНТЕТИЧНИ (не са записвани).
w = pw(screener_status={"kind": "ok", "universe": 903, "with_history": 865, "with_bars": 869, "no_bars_n": 34, "no_bars": ["T1", "T2", "T3"], "batches_failed": 0})
assert src_of(w) == ["screener"] and "за 34 от 903 тикъра Yahoo не върна нито един бар" in w[0]["message"] and "върху 865 тикъра" in w[0]["message"]
assert pw(screener_status={"kind": "ok", "universe": 903, "with_history": 898, "with_bars": 903, "no_bars_n": 0, "no_bars": [], "batches_failed": 0}) == []    # нормата
assert pw(screener_status={"kind": "ok", "universe": 903, "with_history": 890, "with_bars": 895, "no_bars_n": 8, "no_bars": [], "batches_failed": 0}) == []    # под 1% (9)
w = pw(superinvestor_status={**B["superinvestor_status"], "managers_with_data": 14})
assert src_of(w) == ["13f"] and "14 от 15 мениджъра" in w[0]["message"]
w = pw(glb_status={**B["glb_status"], "with_history": 880})
assert src_of(w) == ["glb"] and "23 от 903 тикъра без история" in w[0]["message"]
w = pw(uov_diag={**B["uov_diag"], "snapshot_failed": ["AAPL", "LLY"]})
assert src_of(w) == ["unusual_options"] and "не взе 2 тикъра (AAPL, LLY)" in w[0]["message"]
w = pw(ins_pos_status={"kind": "failed", "note": "проверката не се изпълни (HTTPError)"})
assert src_of(w) == ["insider"] and "позициите в книгите" in w[0]["message"]
w = pw(news_status={"ok": False, "reason": "нито един RSS източник не върна заглавия", "count": 0})
assert src_of(w) == ["news"] and "нито един RSS източник" in w[0]["message"]
w = pw(canary={**B["data_canary"], "ok": None, "error": "няма бар за 2024-06-07"})
assert src_of(w) == ["data_canary"] and "не провери днес" in w[0]["message"]
w = pw(fred_key_missing=True)
assert src_of(w) == ["fred"] and "FRED_API_KEY" in w[0]["message"]
assert "news" in src_of(dw.collect({}, {}, news_status={"ok": False, "reason": "x"}))                                  # през collect
print("  ✓ сектори 15/17, скрийнър 700/903, 13F 14/15, GLB 880/903, OI 2 неуспешни, INS✓ позиции, празни новини, канарче без проверка, без FRED ключ — по един ред")

print()
print("── 3. spinoff_watch: тикър без CIK е непроверен (СИНТЕТИЧНО теглене) ──")
empty_sub = json.dumps({"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": [], "items": []}}})
with contextlib.redirect_stdout(io.StringIO()):
    spinoff_watch.check(["AAPL", "NOCIK"], today=dt.date(2026, 10, 19), get=lambda url: empty_sub, cik_map={"AAPL": 320193})
d = dict(spinoff_watch.LAST_DIAG)
assert d["requested"] == 2 and d["checked"] == 1 and d["unchecked"] == ["NOCIK"]
assert any("NOCIK" in x["message"] for x in dw._spinoff_warning(d))
print("  ✓ NOCIK: checked 1 от 2, 'unchecked' = ['NOCIK'] → банерът 'не са проверени днес'")

print()
print("── 4. новините: статус при празен пул (СИНТЕТИЧНО) ──")
na._RAW_MEMO = (24, [])
with contextlib.redirect_stdout(io.StringIO()):
    assert na.significant_news() == []
assert na.LAST_STATUS == {"ok": False, "reason": "нито един RSS източник не върна заглавия", "count": 0}
print("  ✓ празен пул → LAST_STATUS с причината → банер")

print()
print("── 5. main: монитор, имейл, INS✓, нормата на скрийнъра ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"check": "health_monitor", "message": f"мониторът не се изпълни' in src
i = src.index('sent = send_once(email_html, subject, today)')
tail = src[i:i + 1200]
assert 'if not sent["sent"] and not sent["skipped"]:' in tail and '"source": "email"' in tail and "render_dashboard(brief)" in tail
assert 'ins_pos_status = {"kind": "failed"' in src and '"screener_status": dict(screener.LAST_STATUS)' in src
assert "news_status=dict(news_aggregator.LAST_STATUS)" in src and "fred_key_missing=not config.FRED_API_KEY" in src
print("  ✓ паднал монитор → ред; неизпратен имейл (не повторен run) → банер + страницата наново; паднал INS✓ за позициите → 'failed'; screener_status в брифа")
print("\n✅ test_silent_failures: всичко мина")
